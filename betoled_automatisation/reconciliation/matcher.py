# Copyright (c) 2024, BETOWARE and contributors
# For license information, please see license.txt

"""
Payment matching logic for reconciling bank transactions with Sales Invoices.

The matching is primarily based on the Belgian structured reference
(gestructureerde mededeling) which is stored on Sales Invoices.
"""

import frappe
from frappe.utils import flt


class MatchResult:
	"""Result of a payment matching attempt"""
	
	EXACT_MATCH = "Exact Match"
	PARTIAL_PAYMENT = "Partial Payment"
	OVERPAYMENT = "Overpayment"
	NO_MATCH = "No Match"
	MULTIPLE_MATCHES = "Multiple Matches"
	AMOUNT_MISMATCH = "Amount Mismatch"
	
	def __init__(self, match_type, invoice=None, confidence=0, notes=None):
		self.match_type = match_type
		self.invoice = invoice
		self.confidence = confidence
		self.notes = notes or []
	
	def is_exact(self):
		return self.match_type == self.EXACT_MATCH
	
	def needs_review(self):
		return self.match_type not in [self.EXACT_MATCH, self.NO_MATCH]


class PaymentMatcher:
	"""
	Matches bank transactions to Sales Invoices based on structured references
	and amounts.
	"""
	
	def __init__(self, company):
		"""
		Initialize the matcher for a specific company.
		
		Args:
			company: Company name
		"""
		self.company = company
	
	def match_transaction(self, transaction):
		"""
		Try to match a Ponto Transaction to a Sales Invoice.
		
		Args:
			transaction: Ponto Transaction document or dict
			
		Returns:
			MatchResult: Result of the matching attempt
		"""
		# Only process credit transactions (incoming payments)
		if transaction.get("credit_debit") != "Credit":
			return MatchResult(
				MatchResult.NO_MATCH,
				notes=["Not a credit transaction (incoming payment)"]
			)
		
		structured_ref = transaction.get("structured_reference")
		amount = flt(transaction.get("amount"))
		
		if not structured_ref:
			# Try to find by remittance information
			return self._match_by_remittance(transaction)
		
		# First, try exact match by structured reference
		return self._match_by_structured_reference(structured_ref, amount)
	
	def _match_by_structured_reference(self, structured_ref, amount):
		"""
		Match transaction by structured reference (gestructureerde mededeling).
		
		Args:
			structured_ref: 12-digit structured reference
			amount: Transaction amount
			
		Returns:
			MatchResult
		"""
		# Find invoices with this structured reference
		invoices = frappe.get_all(
			"Sales Invoice",
			filters={
				"company": self.company,
				"docstatus": 1,  # Only submitted invoices
				"gestructureerde_mededeling": structured_ref,
			},
			fields=[
				"name", "grand_total", "outstanding_amount", 
				"customer", "gestructureerde_mededeling", "status"
			]
		)
		
		if not invoices:
			return MatchResult(
				MatchResult.NO_MATCH,
				notes=[f"No invoice found with structured reference: {structured_ref}"]
			)
		
		if len(invoices) > 1:
			return MatchResult(
				MatchResult.MULTIPLE_MATCHES,
				notes=[
					f"Multiple invoices found with reference {structured_ref}: "
					f"{', '.join([i.name for i in invoices])}"
				],
				confidence=50
			)
		
		invoice = invoices[0]
		
		# Check if invoice is already paid
		if invoice.status == "Paid":
			return MatchResult(
				MatchResult.NO_MATCH,
				invoice=invoice,
				notes=[f"Invoice {invoice.name} is already fully paid"],
				confidence=90
			)
		
		outstanding = flt(invoice.outstanding_amount)
		
		# Compare amounts
		if abs(amount - outstanding) < 0.01:  # Exact match (within 1 cent)
			return MatchResult(
				MatchResult.EXACT_MATCH,
				invoice=invoice,
				confidence=100,
				notes=[f"Exact match: payment {amount} matches outstanding {outstanding}"]
			)
		
		elif amount < outstanding:
			# Partial payment
			return MatchResult(
				MatchResult.PARTIAL_PAYMENT,
				invoice=invoice,
				confidence=85,
				notes=[
					f"Partial payment: received {amount}, outstanding is {outstanding}",
					f"Remaining after payment: {outstanding - amount}"
				]
			)
		
		else:
			# Overpayment
			return MatchResult(
				MatchResult.OVERPAYMENT,
				invoice=invoice,
				confidence=70,
				notes=[
					f"Overpayment: received {amount}, outstanding is only {outstanding}",
					f"Excess amount: {amount - outstanding}"
				]
			)
	
	def _match_by_remittance(self, transaction):
		"""
		Try to match by analyzing remittance information for invoice references.
		
		Args:
			transaction: Ponto Transaction
			
		Returns:
			MatchResult
		"""
		remittance = transaction.get("remittance_information", "")
		
		if not remittance:
			return MatchResult(
				MatchResult.NO_MATCH,
				notes=["No structured reference or remittance information"]
			)
		
		# Try to extract invoice number patterns
		# Common patterns: "Factuur XXX-YYYY-ZZZZ", "Invoice XXX-YYYY-ZZZZ"
		import re
		
		# Pattern for invoice numbers like BIN-2024-0001 or LIN-2024-0001
		invoice_patterns = [
			r'([A-Z]{2,3}-\d{4}-\d{4})',  # XXX-YYYY-ZZZZ
			r'Factuur[:\s]+([A-Z0-9-]+)',
			r'Invoice[:\s]+([A-Z0-9-]+)',
			r'Ref[:\s]+([A-Z0-9-]+)',
		]
		
		for pattern in invoice_patterns:
			matches = re.findall(pattern, remittance, re.IGNORECASE)
			
			for potential_invoice in matches:
				# Check if this invoice exists
				if frappe.db.exists("Sales Invoice", {
					"name": potential_invoice.upper(),
					"company": self.company,
					"docstatus": 1
				}):
					invoice = frappe.get_doc("Sales Invoice", potential_invoice.upper())
					amount = flt(transaction.get("amount"))
					outstanding = flt(invoice.outstanding_amount)
					
					if invoice.status == "Paid":
						continue
					
					if abs(amount - outstanding) < 0.01:
						return MatchResult(
							MatchResult.EXACT_MATCH,
							invoice=invoice,
							confidence=80,  # Lower confidence due to text matching
							notes=[
								f"Matched by invoice reference in remittance: {potential_invoice}",
								"Note: Match based on text analysis, not structured reference"
							]
						)
					elif amount < outstanding:
						return MatchResult(
							MatchResult.PARTIAL_PAYMENT,
							invoice=invoice,
							confidence=70,
							notes=[
								f"Partial payment matched by text: {potential_invoice}",
								f"Payment {amount}, outstanding {outstanding}"
							]
						)
					else:
						return MatchResult(
							MatchResult.OVERPAYMENT,
							invoice=invoice,
							confidence=60,
							notes=[
								f"Overpayment matched by text: {potential_invoice}",
								f"Payment {amount}, outstanding {outstanding}"
							]
						)
		
		return MatchResult(
			MatchResult.NO_MATCH,
			notes=[
				"Could not extract valid invoice reference from remittance",
				f"Remittance: {remittance[:100]}..."
			]
		)
	
	def find_potential_matches(self, transaction, max_results=5):
		"""
		Find potential invoice matches for manual review.
		
		This is useful when automatic matching fails but we want to
		suggest possible matches to the user.
		
		Args:
			transaction: Ponto Transaction
			max_results: Maximum number of suggestions
			
		Returns:
			list: List of potential matches with confidence scores
		"""
		amount = flt(transaction.get("amount"))
		counterpart = transaction.get("counterpart_name", "")
		
		# Find unpaid invoices with similar amounts
		invoices = frappe.get_all(
			"Sales Invoice",
			filters={
				"company": self.company,
				"docstatus": 1,
				"status": ["in", ["Unpaid", "Partly Paid", "Overdue"]],
			},
			fields=[
				"name", "customer", "customer_name", "grand_total",
				"outstanding_amount", "posting_date", "gestructureerde_mededeling"
			],
			order_by="posting_date desc",
			limit=50
		)
		
		potential_matches = []
		
		for inv in invoices:
			score = 0
			notes = []
			
			# Amount matching
			outstanding = flt(inv.outstanding_amount)
			amount_diff = abs(amount - outstanding)
			amount_diff_pct = (amount_diff / outstanding * 100) if outstanding else 100
			
			if amount_diff < 0.01:
				score += 50
				notes.append("Exact amount match")
			elif amount_diff_pct <= 5:
				score += 30
				notes.append(f"Amount close (within 5%): diff = {amount_diff}")
			elif amount_diff_pct <= 10:
				score += 15
				notes.append(f"Amount roughly close (within 10%)")
			
			# Customer name matching (fuzzy)
			if counterpart and inv.customer_name:
				counterpart_lower = counterpart.lower()
				customer_lower = inv.customer_name.lower()
				
				# Simple substring matching
				if counterpart_lower in customer_lower or customer_lower in counterpart_lower:
					score += 30
					notes.append("Customer name match")
				else:
					# Check for partial word matches
					counterpart_words = set(counterpart_lower.split())
					customer_words = set(customer_lower.split())
					common_words = counterpart_words.intersection(customer_words)
					
					if common_words:
						score += 15
						notes.append(f"Partial name match: {', '.join(common_words)}")
			
			if score > 0:
				potential_matches.append({
					"invoice": inv,
					"score": score,
					"notes": notes
				})
		
		# Sort by score and return top matches
		potential_matches.sort(key=lambda x: x["score"], reverse=True)
		return potential_matches[:max_results]

