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
		# Try to find "Bank Transfer" or similar
		modes = frappe.get_all(
			"Mode of Payment",
			filters={"enabled": 1},
			fields=["name"],
			order_by="name"
		)
		
		for mode in modes:
			name_lower = mode.name.lower()
			if "bank" in name_lower or "transfer" in name_lower or "overschrijving" in name_lower:
				return mode.name
		
		# Fallback to first enabled mode
		if modes:
			return modes[0].name
		
		frappe.throw("No Mode of Payment configured. Please create at least one.")
	
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
		
		# Third try: search by IBAN if the bank_account_name contains an IBAN
		# Extract potential IBAN (format: "BE56 7370 4013 3488" or "BE56737040133488")
		import re
		iban_pattern = r'\b([A-Z]{2}\d{2}[\s\d]{12,30})\b'
		iban_match = re.search(iban_pattern, bank_account_name.upper())
		
		if iban_match:
			potential_iban = iban_match.group(1).replace(" ", "").upper()
			if len(potential_iban) >= 15:
				# Search for bank account with matching IBAN
				bank_accounts = frappe.get_all(
					"Bank Account",
					filters={"company": self.company},
					fields=["name", "iban", "bank_account_no"]
				)
				
				for ba in bank_accounts:
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
		
		# Fourth try: partial name match (if account name contains the bank_account_name)
		bank_accounts = frappe.get_all(
			"Bank Account",
			filters={"company": self.company},
			fields=["name"]
		)
		
		for ba in bank_accounts:
			if bank_account_name in ba.name or ba.name in bank_account_name:
				return frappe.get_doc("Bank Account", ba.name)
		
		# If all else fails, throw error
		frappe.throw(
			f"Bank Account '{bank_account_name}' not found for company {self.company}. "
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
	
	if not match.sales_invoice:
		frappe.throw("Match must have a linked Sales Invoice")
	
	invoice = frappe.get_doc("Sales Invoice", match.sales_invoice)
	
	# Get transaction details if available
	transaction = None
	if match.ponto_transaction:
		transaction = frappe.get_doc("Ponto Transaction", match.ponto_transaction)
	
	processor = PaymentProcessor(match.company)
	
	return processor.create_payment_entry(
		invoice=invoice,
		amount=match.transaction_amount,
		transaction=transaction
	)










