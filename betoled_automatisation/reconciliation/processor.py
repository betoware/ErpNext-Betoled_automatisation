# Copyright (c) 2024, BETOWARE and contributors
# For license information, please see license.txt

"""
Payment processing logic for creating Payment Entries from matched transactions.
"""

import frappe
from frappe.utils import flt, today


class PaymentProcessor:
	"""
	Processes matched transactions and creates Payment Entries.
	"""
	
	def __init__(self, company):
		"""
		Initialize the processor for a specific company.
		
		Args:
			company: Company name
		"""
		self.company = company
		self._load_company_settings()
	
	def _load_company_settings(self):
		"""Load company-specific settings for payment entry creation"""
		company_doc = frappe.get_doc("Company", self.company)
		
		self.default_currency = company_doc.default_currency
		self.default_bank_account = company_doc.default_bank_account
		
		# Get the Mode of Payment for bank transfers
		# Default to "Bank Transfer" or first available mode
		self.mode_of_payment = self._get_default_mode_of_payment()
	
	def _get_default_mode_of_payment(self):
		"""Get the default mode of payment for bank transfers"""
		# Get all enabled modes of payment
		modes = frappe.get_all(
			"Mode of Payment",
			filters={"enabled": 1},
			fields=["name"],
			order_by="name"
		)
		
		if not modes:
			frappe.throw("No Mode of Payment configured. Please create at least one.")
		
		# First priority: look for "overbooking" (case-insensitive)
		for mode in modes:
			name_lower = mode.name.lower()
			if "overbooking" in name_lower:
				return mode.name
		
		# Second priority: look for "bank", "transfer" or "overschrijving"
		for mode in modes:
			name_lower = mode.name.lower()
			if "bank" in name_lower or "transfer" in name_lower or "overschrijving" in name_lower:
				return mode.name
		
		# Fallback to first enabled mode
		return modes[0].name
	
	def _get_bank_account(self, bank_account_name):
		"""
		Get Bank Account document by name, with fallback logic.
		
		Args:
			bank_account_name: Bank account name from company settings (may include IBAN)
			
		Returns:
			Bank Account document
		"""
		if not bank_account_name:
			return None
		
		# Get all bank accounts for this company to work with
		all_bank_accounts = frappe.get_all(
			"Bank Account",
			filters={"company": self.company},
			fields=["name", "iban", "bank_account_no"]
		)
		
		if not all_bank_accounts:
			frappe.throw(
				f"No Bank Accounts found for company {self.company}. "
				f"Please create at least one Bank Account for this company."
			)
		
		# First try: exact match
		if frappe.db.exists("Bank Account", bank_account_name):
			return frappe.get_doc("Bank Account", bank_account_name)
		
		# Second try: extract account name if format is "IBAN - Account Name"
		# Pattern: "BE56 7370 4013 3488 - Zichtrekening KBC Lastamar - L"
		if " - " in bank_account_name:
			parts = bank_account_name.split(" - ", 1)
			if len(parts) == 2:
				# Try the part after " - " (the account name)
				account_name = parts[1].strip()
				if frappe.db.exists("Bank Account", account_name):
					return frappe.get_doc("Bank Account", account_name)
				
				# Also try without the last part (e.g., "Zichtrekening KBC BETOWARE - B" -> "Zichtrekening KBC BETOWARE")
				if " - " in account_name:
					account_name_parts = account_name.rsplit(" - ", 1)
					if len(account_name_parts) == 2:
						account_name_base = account_name_parts[0].strip()
						# Try exact match with base name
						if frappe.db.exists("Bank Account", account_name_base):
							return frappe.get_doc("Bank Account", account_name_base)
						
						# Try matching with all bank accounts (case-insensitive)
						account_name_base_lower = account_name_base.lower()
						for ba in all_bank_accounts:
							ba_name_lower = ba.name.lower()
							# Exact match (case-insensitive)
							if ba_name_lower == account_name_base_lower:
								return frappe.get_doc("Bank Account", ba.name)
							# Contains match
							if account_name_base_lower in ba_name_lower or ba_name_lower in account_name_base_lower:
								return frappe.get_doc("Bank Account", ba.name)
				
				# Also try matching the full account_name (after " - ") with all bank accounts
				account_name_lower = account_name.lower()
				for ba in all_bank_accounts:
					ba_name_lower = ba.name.lower()
					if ba_name_lower == account_name_lower:
						return frappe.get_doc("Bank Account", ba.name)
					if account_name_lower in ba_name_lower or ba_name_lower in account_name_lower:
						return frappe.get_doc("Bank Account", ba.name)
		
		# Third try: search by IBAN if the bank_account_name contains an IBAN
		# Extract potential IBAN (format: "BE56 7370 4013 3488" or "BE56737040133488")
		import re
		iban_pattern = r'\b([A-Z]{2}\d{2}[\s\d]{12,30})\b'
		iban_match = re.search(iban_pattern, bank_account_name.upper())
		
		if iban_match:
			potential_iban = iban_match.group(1).replace(" ", "").upper()
			if len(potential_iban) >= 15:
				# Search for bank account with matching IBAN
				for ba in all_bank_accounts:
					# Check IBAN field
					if ba.get("iban"):
						ba_iban = ba.iban.replace(" ", "").upper()
						if ba_iban == potential_iban:
							return frappe.get_doc("Bank Account", ba.name)
					
					# Check bank_account_no field as fallback
					if ba.get("bank_account_no"):
						ba_account_no = ba.bank_account_no.replace(" ", "").upper()
						if ba_account_no == potential_iban:
							return frappe.get_doc("Bank Account", ba.name)
		
		# Fourth try: fuzzy name matching - extract key words from account name
		# Remove IBAN and common separators, then match on key words
		search_terms = bank_account_name.upper()
		# Remove IBAN pattern
		search_terms = re.sub(iban_pattern, "", search_terms)
		# Remove common separators and clean up
		search_terms = re.sub(r'[-–—]', ' ', search_terms)
		search_terms = ' '.join([t for t in search_terms.split() if len(t) > 2])  # Keep only meaningful words
		
		best_match = None
		best_score = 0
		
		for ba in all_bank_accounts:
			ba_name_upper = ba.name.upper()
			# Count matching words
			score = 0
			for term in search_terms.split():
				if term in ba_name_upper:
					score += len(term)
			
			# Also check reverse (if bank account name words are in search terms)
			ba_words = [w for w in ba_name_upper.split() if len(w) > 2]
			for word in ba_words:
				if word in search_terms:
					score += len(word)
			
			if score > best_score:
				best_score = score
				best_match = ba.name
		
		# If we found a reasonable match (at least 5 characters matched), use it
		if best_match and best_score >= 5:
			return frappe.get_doc("Bank Account", best_match)
		
		# Fifth try: simple partial match as last resort
		for ba in all_bank_accounts:
			# Check if any significant part of the name matches
			ba_name_lower = ba.name.lower()
			search_lower = bank_account_name.lower()
			
			# Extract meaningful words (length > 3) from both
			ba_words = [w for w in ba_name_lower.split() if len(w) > 3]
			search_words = [w for w in search_lower.split() if len(w) > 3 and not re.match(r'^[a-z]{2}\d+', w)]  # Exclude IBAN-like patterns
			
			# If we have at least one matching word, consider it
			if any(word in ba_name_lower for word in search_words) or any(word in search_lower for word in ba_words):
				return frappe.get_doc("Bank Account", ba.name)
		
		# If all else fails, provide helpful error with available bank accounts
		available_accounts = [ba.name for ba in all_bank_accounts]
		frappe.throw(
			f"Bank Account '{bank_account_name}' not found for company {self.company}. "
			f"Available Bank Accounts: {', '.join(available_accounts)}. "
			f"Please check the Default Bank Account setting on the Company."
		)
	
	def create_payment_entry(self, invoice, amount, transaction=None, reference=None):
		"""
		Create a Payment Entry for a Sales Invoice.
		
		Args:
			invoice: Sales Invoice document or name
			amount: Payment amount
			transaction: Optional Ponto Transaction for reference
			reference: Optional reference string
			
		Returns:
			Payment Entry document
		"""
		if isinstance(invoice, str):
			invoice = frappe.get_doc("Sales Invoice", invoice)
		
		# Get bank account details
		bank_account_name = self.default_bank_account
		if not bank_account_name:
			frappe.throw(f"No default bank account configured for company {self.company}")
		
		bank_account_doc = self._get_bank_account(bank_account_name)
		gl_account = bank_account_doc.account
		
		if not gl_account:
			frappe.throw(f"Bank Account {bank_account} has no linked GL Account")
		
		# Determine posting date
		posting_date = today()
		if transaction:
			posting_date = transaction.get("transaction_date") or transaction.get("value_date") or today()
		
		# Build reference string
		references = []
		if reference:
			references.append(reference)
		if transaction:
			if transaction.get("ponto_transaction_id"):
				references.append(f"Ponto: {transaction.get('ponto_transaction_id')}")
			if transaction.get("structured_reference"):
				references.append(f"+++{transaction.get('structured_reference')[:3]}/{transaction.get('structured_reference')[3:7]}/{transaction.get('structured_reference')[7:]}+++")
		
		reference_no = " | ".join(references) if references else invoice.name
		
		# Create the Payment Entry
		payment_entry = frappe.get_doc({
			"doctype": "Payment Entry",
			"payment_type": "Receive",
			"posting_date": posting_date,
			"company": self.company,
			"mode_of_payment": self.mode_of_payment,
			"party_type": "Customer",
			"party": invoice.customer,
			"party_name": invoice.customer_name,
			"paid_from": invoice.debit_to,
			"paid_to": gl_account,
			"paid_amount": flt(amount),
			"received_amount": flt(amount),
			"source_exchange_rate": 1,
			"target_exchange_rate": 1,
			"reference_no": reference_no[:140] if reference_no else None,  # Limit to 140 chars
			"reference_date": posting_date,
			"references": [
				{
					"reference_doctype": "Sales Invoice",
					"reference_name": invoice.name,
					"total_amount": invoice.grand_total,
					"outstanding_amount": invoice.outstanding_amount,
					"allocated_amount": min(flt(amount), flt(invoice.outstanding_amount))
				}
			],
			"remarks": self._build_remarks(transaction, invoice)
		})
		
		payment_entry.insert(ignore_permissions=True)
		
		# Submit the payment entry
		payment_entry.submit()
		
		frappe.db.commit()
		
		return payment_entry
	
	def create_payment_entry_for_po(self, purchase_order, amount, transaction=None, reference=None):
		"""
		Create a Payment Entry for a Purchase Order.
		
		Note: In ERPNext, payments are typically made on Purchase Invoices.
		This method will:
		1. Check if there are Purchase Invoices linked to the PO
		2. If yes, create payment entry for those Purchase Invoices
		3. If no, create a payment entry that can be manually linked later
		
		Args:
			purchase_order: Purchase Order document or name
			amount: Payment amount
			transaction: Optional Ponto Transaction for reference
			reference: Optional reference string
			
		Returns:
			Payment Entry document
		"""
		if isinstance(purchase_order, str):
			purchase_order = frappe.get_doc("Purchase Order", purchase_order)
		
		# Get bank account details
		bank_account_name = self.default_bank_account
		if not bank_account_name:
			frappe.throw(f"No default bank account configured for company {self.company}")
		
		bank_account_doc = self._get_bank_account(bank_account_name)
		gl_account = bank_account_doc.account
		
		if not gl_account:
			frappe.throw(f"Bank Account {bank_account_name} has no linked GL Account")
		
		# Determine posting date
		posting_date = today()
		if transaction:
			posting_date = transaction.get("transaction_date") or transaction.get("value_date") or today()
		
		# Build reference string
		references = []
		if reference:
			references.append(reference)
		if transaction:
			if transaction.get("ponto_transaction_id"):
				references.append(f"Ponto: {transaction.get('ponto_transaction_id')}")
			if transaction.get("structured_reference"):
				references.append(f"+++{transaction.get('structured_reference')[:3]}/{transaction.get('structured_reference')[3:7]}/{transaction.get('structured_reference')[7:]}+++")
		
		reference_no = " | ".join(references) if references else purchase_order.name
		
		# Find Purchase Invoices linked to this PO
		purchase_invoices = frappe.get_all(
			"Purchase Invoice",
			filters={
				"po_no": purchase_order.name,
				"docstatus": 1,
				"company": self.company
			},
			fields=["name", "grand_total", "outstanding_amount", "credit_to"],
			order_by="posting_date desc"
		)
		
		# Calculate total outstanding from Purchase Invoices
		total_outstanding = sum(flt(pi.outstanding_amount) for pi in purchase_invoices)
		
		# Get supplier details
		supplier = frappe.get_doc("Supplier", purchase_order.supplier)
		
		# Determine credit account (from first PI or default)
		credit_to = None
		if purchase_invoices:
			credit_to = purchase_invoices[0].credit_to
		else:
			# Get default payables account for supplier
			credit_to = frappe.db.get_value("Company", self.company, "default_payable_account")
			if not credit_to:
				frappe.throw(f"No default payable account configured for company {self.company}")
		
		# Create the Payment Entry
		payment_entry = frappe.get_doc({
			"doctype": "Payment Entry",
			"payment_type": "Pay",
			"posting_date": posting_date,
			"company": self.company,
			"mode_of_payment": self.mode_of_payment,
			"party_type": "Supplier",
			"party": purchase_order.supplier,
			"party_name": purchase_order.supplier_name,
			"paid_from": gl_account,
			"paid_to": credit_to,
			"paid_amount": flt(amount),
			"received_amount": flt(amount),
			"source_exchange_rate": 1,
			"target_exchange_rate": 1,
			"reference_no": reference_no[:140] if reference_no else None,  # Limit to 140 chars
			"reference_date": posting_date,
			"references": [],
			"remarks": self._build_remarks_for_po(transaction, purchase_order)
		})
		
		# Add references to Purchase Invoices if they exist
		if purchase_invoices:
			remaining_amount = flt(amount)
			for pi in purchase_invoices:
				if remaining_amount <= 0:
					break
				allocated = min(remaining_amount, flt(pi.outstanding_amount))
				if allocated > 0:
					payment_entry.append("references", {
						"reference_doctype": "Purchase Invoice",
						"reference_name": pi.name,
						"total_amount": pi.grand_total,
						"outstanding_amount": pi.outstanding_amount,
						"allocated_amount": allocated
					})
					remaining_amount -= allocated
		else:
			# No Purchase Invoices yet - add a note in remarks
			payment_entry.remarks += f"\nNote: No Purchase Invoices found for PO {purchase_order.name}. Payment may need manual allocation."
		
		payment_entry.insert(ignore_permissions=True)
		
		# Submit the payment entry
		payment_entry.submit()
		
		frappe.db.commit()
		
		return payment_entry
	
	def _build_remarks_for_po(self, transaction, purchase_order):
		"""Build remarks for the Payment Entry for Purchase Order"""
		remarks = [f"Payment for Purchase Order {purchase_order.name}"]
		
		if transaction:
			if transaction.get("counterpart_name"):
				remarks.append(f"To: {transaction.get('counterpart_name')}")
			if transaction.get("counterpart_iban"):
				remarks.append(f"IBAN: {transaction.get('counterpart_iban')}")
			if transaction.get("remittance_information"):
				# Truncate long remittance info
				remittance = transaction.get("remittance_information")
				if len(remittance) > 200:
					remittance = remittance[:197] + "..."
				remarks.append(f"Mededeling: {remittance}")
		
		remarks.append("Auto-reconciled by Betoled Automatisation")
		
		return "\n".join(remarks)
	
	def _build_remarks(self, transaction, invoice):
		"""Build remarks for the Payment Entry"""
		remarks = [f"Payment for {invoice.name}"]
		
		if transaction:
			if transaction.get("counterpart_name"):
				remarks.append(f"From: {transaction.get('counterpart_name')}")
			if transaction.get("counterpart_iban"):
				remarks.append(f"IBAN: {transaction.get('counterpart_iban')}")
			if transaction.get("remittance_information"):
				# Truncate long remittance info
				remittance = transaction.get("remittance_information")
				if len(remittance) > 200:
					remittance = remittance[:197] + "..."
				remarks.append(f"Mededeling: {remittance}")
		
		remarks.append("Auto-reconciled by Betoled Automatisation")
		
		return "\n".join(remarks)


def create_payment_entry_from_transaction(transaction):
	"""
	Convenience function to create a Payment Entry from a Ponto Transaction.
	
	Args:
		transaction: Ponto Transaction document
		
	Returns:
		Payment Entry document
	"""
	if isinstance(transaction, str):
		transaction = frappe.get_doc("Ponto Transaction", transaction)
	
	if not transaction.matched_invoice:
		frappe.throw("Transaction must have a matched invoice")
	
	invoice = frappe.get_doc("Sales Invoice", transaction.matched_invoice)
	
	processor = PaymentProcessor(transaction.company)
	
	return processor.create_payment_entry(
		invoice=invoice,
		amount=transaction.amount,
		transaction=transaction
	)


def create_payment_entry_from_match(match):
	"""
	Create a Payment Entry from a Payment Match document.
	
	Args:
		match: Payment Match document
		
	Returns:
		Payment Entry document
	"""
	if isinstance(match, str):
		match = frappe.get_doc("Payment Match", match)
	
	if not match.sales_invoice and not match.purchase_order:
		frappe.throw("Match must have a linked Sales Invoice or Purchase Order")
	
	# Get transaction details if available
	transaction = None
	if match.ponto_transaction:
		transaction = frappe.get_doc("Ponto Transaction", match.ponto_transaction)
	
	processor = PaymentProcessor(match.company)
	
	if match.sales_invoice:
		# Credit transaction -> Sales Invoice
		invoice = frappe.get_doc("Sales Invoice", match.sales_invoice)
		return processor.create_payment_entry(
			invoice=invoice,
			amount=match.transaction_amount,
			transaction=transaction
		)
	elif match.purchase_order:
		# Debit transaction -> Purchase Order
		purchase_order = frappe.get_doc("Purchase Order", match.purchase_order)
		return processor.create_payment_entry_for_po(
			purchase_order=purchase_order,
			amount=match.transaction_amount,
			transaction=transaction
		)










