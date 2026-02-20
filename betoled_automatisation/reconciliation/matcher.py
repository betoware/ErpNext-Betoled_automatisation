# Copyright (c) 2024, BETOWARE and contributors
# For license information, please see license.txt

"""
Payment matching logic for reconciling bank transactions with Sales Invoices.

Two-phase matching:
Phase 1: Match by Belgian structured reference (gestructureerde mededeling)
Phase 2: Match by amount (within tolerance) + fuzzy name matching
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
	FUZZY_MATCH = "Fuzzy Match"
	
	def __init__(self, match_type, invoice=None, purchase_order=None, confidence=0, notes=None, phase=1):
		self.match_type = match_type
		self.invoice = invoice
		self.purchase_order = purchase_order
		self.confidence = confidence
		self.notes = notes or []
		self.phase = phase  # 1 = structured ref, 2 = fuzzy
	
	def is_exact(self):
		return self.match_type == self.EXACT_MATCH
	
	def needs_review(self):
		return self.match_type not in [self.EXACT_MATCH, self.NO_MATCH]


def fuzzy_match_score(s1, s2):
	"""
	Calculate fuzzy match score between two strings.
	Returns a score between 0 and 100.
	
	Uses a simple but effective approach:
	1. Normalize strings (lowercase, remove extra spaces)
	2. Check for exact match
	3. Check if one contains the other
	4. Calculate Levenshtein-based similarity
	"""
	if not s1 or not s2:
		return 0
	
	# Normalize
	s1 = ' '.join(s1.lower().split())
	s2 = ' '.join(s2.lower().split())
	
	# Exact match
	if s1 == s2:
		return 100
	
	# One contains the other
	if s1 in s2 or s2 in s1:
		shorter = min(len(s1), len(s2))
		longer = max(len(s1), len(s2))
		return int((shorter / longer) * 100)
	
	# Word overlap
	words1 = set(s1.split())
	words2 = set(s2.split())
	
	if words1 and words2:
		common = words1.intersection(words2)
		total = words1.union(words2)
		word_score = (len(common) / len(total)) * 100
		
		# Boost score if significant words match
		significant_common = [w for w in common if len(w) > 3]
		if significant_common:
			word_score = min(100, word_score * 1.3)
		
		return int(word_score)
	
	# Fallback: character-based similarity (simplified Levenshtein ratio)
	return _levenshtein_ratio(s1, s2)


def _levenshtein_ratio(s1, s2):
	"""Calculate similarity ratio based on Levenshtein distance"""
	if not s1 or not s2:
		return 0
	
	# Simple implementation for shorter strings
	if len(s1) > 100 or len(s2) > 100:
		# For very long strings, just use word overlap
		return 0
	
	len1, len2 = len(s1), len(s2)
	
	# Create distance matrix
	distances = [[0] * (len2 + 1) for _ in range(len1 + 1)]
	
	for i in range(len1 + 1):
		distances[i][0] = i
	for j in range(len2 + 1):
		distances[0][j] = j
	
	for i in range(1, len1 + 1):
		for j in range(1, len2 + 1):
			cost = 0 if s1[i-1] == s2[j-1] else 1
			distances[i][j] = min(
				distances[i-1][j] + 1,      # deletion
				distances[i][j-1] + 1,      # insertion
				distances[i-1][j-1] + cost  # substitution
			)
	
	distance = distances[len1][len2]
	max_len = max(len1, len2)
	
	return int(((max_len - distance) / max_len) * 100)


class PaymentMatcher:
	"""
	Matches bank transactions to Sales Invoices.
	
	Phase 1: Match by structured reference (gestructureerde mededeling)
	Phase 2: Match by amount + fuzzy customer name matching
	"""
	
	def __init__(self, company, settings=None):
		"""
		Initialize the matcher for a specific company.
		
		Args:
			company: Company name
			settings: Optional PontoSettings document
		"""
		self.company = company
		self.settings = settings
		self._load_settings()
	
	def _load_settings(self):
		"""Load matching settings from Ponto Settings"""
		if not self.settings:
			try:
				self.settings = frappe.get_doc("Ponto Settings", {"company": self.company})
			except:
				self.settings = None
		
		# Default settings: 10% amount tolerance and 70% name threshold so ~90% matches are accepted
		self.amount_tolerance_percent = 10.0
		self.fuzzy_match_threshold = 70
		self.enable_fuzzy_matching = True

		if self.settings:
			self.amount_tolerance_percent = flt(self.settings.get("amount_tolerance_percent") or 10.0)
			self.fuzzy_match_threshold = int(self.settings.get("fuzzy_match_threshold") or 70)
			self.enable_fuzzy_matching = bool(self.settings.get("enable_fuzzy_matching", 1))
	
	def match_transaction(self, transaction):
		"""
		Try to match a Ponto Transaction to a Sales Invoice (Credit) or Purchase Order (Debit).
		
		Args:
			transaction: Ponto Transaction document or dict
			
		Returns:
			MatchResult: Result of the matching attempt
		"""
		credit_debit = transaction.get("credit_debit")
		structured_ref = transaction.get("structured_reference")
		amount = flt(transaction.get("amount"))
		counterpart_name = transaction.get("counterpart_name", "")
		
		# Process Credit transactions (incoming payments) -> match to Sales Invoices
		if credit_debit == "Credit":
			# ============ PHASE 1: Structured Reference Matching ============
			if structured_ref:
				result = self._match_by_structured_reference(structured_ref, amount)
				if result.match_type != MatchResult.NO_MATCH:
					result.phase = 1
					result.notes.insert(0, "Phase 1: Matched by structured reference")
					return result
			
			# ============ PHASE 2: Fuzzy Matching (Amount + Name) ============
			if self.enable_fuzzy_matching and counterpart_name:
				result = self._match_by_fuzzy(amount, counterpart_name)
				if result.match_type != MatchResult.NO_MATCH:
					result.phase = 2
					result.notes.insert(0, "Phase 2: Matched by amount + customer name")
					return result
		
		# Process Debit transactions (outgoing payments) -> match to Purchase Orders
		elif credit_debit == "Debit":
			# ============ PHASE 1: Fuzzy Matching (Amount + Supplier Name) ============
			if self.enable_fuzzy_matching and counterpart_name:
				result = self._match_purchase_order_by_fuzzy(amount, counterpart_name)
				if result.match_type != MatchResult.NO_MATCH:
					result.phase = 1
					result.notes.insert(0, "Phase 1: Matched by amount + supplier name")
					return result
		else:
			return MatchResult(
				MatchResult.NO_MATCH,
				notes=[f"Unknown transaction type: {credit_debit}"]
			)
		
		# No match found
		return MatchResult(
			MatchResult.NO_MATCH,
			notes=[
				f"No match found for payment of {amount}",
				f"Counterpart: {counterpart_name}",
				f"Structured ref: {structured_ref or 'None'}",
				f"Type: {credit_debit}"
			]
		)
	
	def _match_by_structured_reference(self, structured_ref, amount):
		"""
		Phase 1: Match transaction by structured reference (gestructureerde mededeling).
		
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
				"customer", "customer_name", "gestructureerde_mededeling", "status"
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
	
	def _match_by_fuzzy(self, amount, counterpart_name):
		"""
		Phase 2: Match by amount (within tolerance) and fuzzy customer name.
		
		Args:
			amount: Transaction amount
			counterpart_name: Name from the bank transaction
			
		Returns:
			MatchResult
		"""
		# Calculate amount range
		tolerance = self.amount_tolerance_percent / 100.0
		min_amount = amount * (1 - tolerance)
		max_amount = amount * (1 + tolerance)
		
		# Find unpaid invoices within amount range
		invoices = frappe.db.sql("""
			SELECT 
				si.name, si.grand_total, si.outstanding_amount,
				si.customer, si.customer_name, si.status,
				c.custom_alias
			FROM `tabSales Invoice` si
			LEFT JOIN `tabCustomer` c ON si.customer = c.name
			WHERE si.company = %s
			AND si.docstatus = 1
			AND si.status IN ('Unpaid', 'Partly Paid', 'Overdue')
			AND si.outstanding_amount BETWEEN %s AND %s
		""", (self.company, min_amount, max_amount), as_dict=True)
		
		if not invoices:
			return MatchResult(
				MatchResult.NO_MATCH,
				notes=[f"No unpaid invoices found within {self.amount_tolerance_percent}% of {amount}"]
			)
		
		# Score each invoice based on name matching
		matches = []
		
		for inv in invoices:
			best_score = 0
			matched_name = ""
			
			# Check customer_name
			score = fuzzy_match_score(counterpart_name, inv.customer_name)
			if score > best_score:
				best_score = score
				matched_name = inv.customer_name
			
			# Check custom_alias (comma-separated list)
			if inv.custom_alias:
				aliases = [a.strip() for a in inv.custom_alias.split(",") if a.strip()]
				for alias in aliases:
					score = fuzzy_match_score(counterpart_name, alias)
					if score > best_score:
						best_score = score
						matched_name = alias
			
			if best_score >= self.fuzzy_match_threshold:
				# Calculate amount difference for confidence adjustment
				outstanding = flt(inv.outstanding_amount)
				amount_diff_pct = abs(amount - outstanding) / outstanding * 100 if outstanding else 100
				
				# Adjust confidence based on name score and amount match
				confidence = int((best_score * 0.7) + ((100 - amount_diff_pct) * 0.3))
				
				matches.append({
					"invoice": inv,
					"name_score": best_score,
					"matched_name": matched_name,
					"amount_diff_pct": amount_diff_pct,
					"confidence": confidence
				})
		
		if not matches:
			return MatchResult(
				MatchResult.NO_MATCH,
				notes=[
					f"No matching customer found for '{counterpart_name}'",
					f"Threshold: {self.fuzzy_match_threshold}%"
				]
			)
		
		# Sort by confidence
		matches.sort(key=lambda x: x["confidence"], reverse=True)
		
		if len(matches) > 1 and matches[0]["confidence"] - matches[1]["confidence"] < 10:
			# Multiple close matches - needs review
			return MatchResult(
				MatchResult.MULTIPLE_MATCHES,
				invoice=matches[0]["invoice"],
				confidence=matches[0]["confidence"],
				notes=[
					f"Multiple potential matches found:",
					*[f"  - {m['invoice'].name}: {m['invoice'].customer_name} (score: {m['name_score']}%, amount diff: {m['amount_diff_pct']:.1f}%)" 
					  for m in matches[:3]]
				]
			)
		
		best = matches[0]
		inv = best["invoice"]
		outstanding = flt(inv.outstanding_amount)
		
		# Determine match type based on amount
		if abs(amount - outstanding) < 0.01:
			match_type = MatchResult.FUZZY_MATCH
		elif amount < outstanding:
			match_type = MatchResult.PARTIAL_PAYMENT
		else:
			match_type = MatchResult.OVERPAYMENT
		
		return MatchResult(
			match_type,
			invoice=inv,
			confidence=best["confidence"],
			notes=[
				f"Fuzzy match: '{counterpart_name}' → '{best['matched_name']}' (score: {best['name_score']}%)",
				f"Amount: {amount}, Outstanding: {outstanding} (diff: {best['amount_diff_pct']:.1f}%)",
				f"Customer: {inv.customer_name}"
			]
		)
	
	def _match_purchase_order_by_fuzzy(self, amount, counterpart_name):
		"""
		Match outgoing payment (Debit) by amount (within tolerance) and fuzzy supplier name.
		Matches to Purchase Orders.
		
		Args:
			amount: Transaction amount
			counterpart_name: Name from the bank transaction
			
		Returns:
			MatchResult
		"""
		# Calculate amount range
		tolerance = self.amount_tolerance_percent / 100.0
		min_amount = amount * (1 - tolerance)
		max_amount = amount * (1 + tolerance)
		
		# Find unpaid Purchase Orders within amount range
		# Note: Purchase Orders don't have outstanding_amount, so we use grand_total
		# and check if there are unpaid Purchase Invoices linked to the PO
		purchase_orders = frappe.db.sql("""
			SELECT 
				po.name, po.grand_total, po.supplier, po.supplier_name,
				po.status, po.transaction_date, po.company,
				s.custom_alias,
				COALESCE(
					(SELECT SUM(pi.grand_total - pi.outstanding_amount)
					 FROM `tabPurchase Invoice` pi
					 WHERE pi.po_no = po.name
					 AND pi.docstatus = 1),
					0
				) as paid_amount
			FROM `tabPurchase Order` po
			LEFT JOIN `tabSupplier` s ON po.supplier = s.name
			WHERE po.company = %s
			AND po.docstatus = 1
			AND po.status IN ('To Receive', 'To Receive and Bill', 'To Bill', 'Completed')
			AND po.grand_total BETWEEN %s AND %s
		""", (self.company, min_amount, max_amount), as_dict=True)
		
		if not purchase_orders:
			return MatchResult(
				MatchResult.NO_MATCH,
				notes=[f"No Purchase Orders found within {self.amount_tolerance_percent}% of {amount}"]
			)
		
		# Score each Purchase Order based on name matching
		matches = []
		
		for po in purchase_orders:
			best_score = 0
			matched_name = ""
			
			# Check supplier_name
			score = fuzzy_match_score(counterpart_name, po.supplier_name or "")
			if score > best_score:
				best_score = score
				matched_name = po.supplier_name or ""
			
			# Check custom_alias (comma-separated list)
			if po.custom_alias:
				aliases = [a.strip() for a in po.custom_alias.split(",") if a.strip()]
				for alias in aliases:
					score = fuzzy_match_score(counterpart_name, alias)
					if score > best_score:
						best_score = score
						matched_name = alias
			
			if best_score >= self.fuzzy_match_threshold:
				# Calculate outstanding amount (grand_total - paid_amount)
				outstanding = flt(po.grand_total) - flt(po.paid_amount or 0)
				
				# Calculate amount difference for confidence adjustment
				amount_diff_pct = abs(amount - outstanding) / outstanding * 100 if outstanding else 100
				
				# Adjust confidence based on name score and amount match
				confidence = int((best_score * 0.7) + ((100 - amount_diff_pct) * 0.3))
				
				matches.append({
					"purchase_order": po,
					"name_score": best_score,
					"matched_name": matched_name,
					"amount_diff_pct": amount_diff_pct,
					"outstanding": outstanding,
					"confidence": confidence
				})
		
		if not matches:
			return MatchResult(
				MatchResult.NO_MATCH,
				notes=[
					f"No matching supplier found for '{counterpart_name}'",
					f"Threshold: {self.fuzzy_match_threshold}%"
				]
			)
		
		# Sort by confidence
		matches.sort(key=lambda x: x["confidence"], reverse=True)
		
		if len(matches) > 1 and matches[0]["confidence"] - matches[1]["confidence"] < 10:
			# Multiple close matches - needs review
			return MatchResult(
				MatchResult.MULTIPLE_MATCHES,
				purchase_order=matches[0]["purchase_order"],
				confidence=matches[0]["confidence"],
				notes=[
					f"Multiple potential matches found:",
					*[f"  - {m['purchase_order'].name}: {m['purchase_order'].supplier_name} (score: {m['name_score']}%, amount diff: {m['amount_diff_pct']:.1f}%)" 
					  for m in matches[:3]]
				]
			)
		
		best = matches[0]
		po = best["purchase_order"]
		outstanding = best["outstanding"]
		
		# Determine match type based on amount
		if abs(amount - outstanding) < 0.01:
			match_type = MatchResult.FUZZY_MATCH
		elif amount < outstanding:
			match_type = MatchResult.PARTIAL_PAYMENT
		else:
			match_type = MatchResult.OVERPAYMENT
		
		return MatchResult(
			match_type,
			purchase_order=po,
			confidence=best["confidence"],
			notes=[
				f"Fuzzy match: '{counterpart_name}' → '{best['matched_name']}' (score: {best['name_score']}%)",
				f"Amount: {amount}, Outstanding: {outstanding} (diff: {best['amount_diff_pct']:.1f}%)",
				f"Supplier: {po.supplier_name}"
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
		
		# Find unpaid invoices with similar amounts (wider range for suggestions)
		tolerance = max(self.amount_tolerance_percent * 2, 20) / 100.0
		min_amount = amount * (1 - tolerance)
		max_amount = amount * (1 + tolerance)
		
		invoices = frappe.db.sql("""
			SELECT 
				si.name, si.customer, si.customer_name, si.grand_total,
				si.outstanding_amount, si.posting_date, si.gestructureerde_mededeling,
				c.custom_alias
			FROM `tabSales Invoice` si
			LEFT JOIN `tabCustomer` c ON si.customer = c.name
			WHERE si.company = %s
			AND si.docstatus = 1
			AND si.status IN ('Unpaid', 'Partly Paid', 'Overdue')
			ORDER BY si.posting_date DESC
			LIMIT 50
		""", (self.company,), as_dict=True)
		
		potential_matches = []
		
		for inv in invoices:
			score = 0
			notes = []
			
			# Amount matching
			outstanding = flt(inv.outstanding_amount)
			if outstanding > 0:
				amount_diff = abs(amount - outstanding)
				amount_diff_pct = (amount_diff / outstanding * 100)
				
				if amount_diff < 0.01:
					score += 50
					notes.append("Exact amount match")
				elif amount_diff_pct <= 5:
					score += 35
					notes.append(f"Amount within 5%: diff = {amount_diff:.2f}")
				elif amount_diff_pct <= 10:
					score += 20
					notes.append(f"Amount within 10%")
				elif outstanding >= min_amount and outstanding <= max_amount:
					score += 10
					notes.append(f"Amount roughly similar")
			
			# Customer name matching
			if counterpart:
				best_name_score = 0
				matched_name = ""
				
				# Check customer_name
				name_score = fuzzy_match_score(counterpart, inv.customer_name)
				if name_score > best_name_score:
					best_name_score = name_score
					matched_name = inv.customer_name
				
				# Check aliases
				if inv.custom_alias:
					for alias in [a.strip() for a in inv.custom_alias.split(",") if a.strip()]:
						alias_score = fuzzy_match_score(counterpart, alias)
						if alias_score > best_name_score:
							best_name_score = alias_score
							matched_name = alias
				
				if best_name_score >= 80:
					score += 40
					notes.append(f"Strong name match: '{matched_name}' ({best_name_score}%)")
				elif best_name_score >= 50:
					score += 20
					notes.append(f"Partial name match: '{matched_name}' ({best_name_score}%)")
				elif best_name_score >= 30:
					score += 10
					notes.append(f"Weak name match: '{matched_name}' ({best_name_score}%)")
			
			if score > 0:
				potential_matches.append({
					"invoice": inv,
					"score": score,
					"notes": notes
				})
		
		# Sort by score and return top matches
		potential_matches.sort(key=lambda x: x["score"], reverse=True)
		return potential_matches[:max_results]
