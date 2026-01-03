# Copyright (c) 2024, BETOWARE and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PontoTransaction(Document):
	def validate(self):
		"""Extract structured reference from remittance information if present"""
		if self.remittance_information and not self.structured_reference:
			self.structured_reference = self.extract_structured_reference(self.remittance_information)
	
	@staticmethod
	def extract_structured_reference(text):
		"""
		Extract Belgian structured reference (gestructureerde mededeling) from text.
		Format: +++XXX/XXXX/XXXXX+++ or ***XXX/XXXX/XXXXX***
		Or just 12 digits that validate with modulo 97
		"""
		import re
		
		if not text:
			return None
		
		# Pattern for structured reference with delimiters
		# +++123/1234/12345+++ or ***123/1234/12345***
		pattern_delimited = r'[\+\*]{3}(\d{3})/(\d{4})/(\d{5})[\+\*]{3}'
		match = re.search(pattern_delimited, text)
		
		if match:
			return match.group(1) + match.group(2) + match.group(3)
		
		# Pattern for 12 consecutive digits
		pattern_digits = r'\b(\d{12})\b'
		matches = re.findall(pattern_digits, text)
		
		for digits in matches:
			if PontoTransaction.validate_structured_reference(digits):
				return digits
		
		# Also try without word boundaries for embedded numbers
		pattern_digits_embedded = r'(\d{12})'
		matches = re.findall(pattern_digits_embedded, text)
		
		for digits in matches:
			if PontoTransaction.validate_structured_reference(digits):
				return digits
		
		return None
	
	@staticmethod
	def validate_structured_reference(reference):
		"""
		Validate Belgian structured reference using modulo 97 check.
		The last 2 digits are the check digits.
		"""
		if not reference or len(reference) != 12:
			return False
		
		try:
			base_number = int(reference[:10])
			check_digits = int(reference[10:12])
			
			calculated_check = base_number % 97
			if calculated_check == 0:
				calculated_check = 97
			
			return calculated_check == check_digits
		except ValueError:
			return False
	
	@frappe.whitelist()
	def create_payment_entry(self):
		"""Create a Payment Entry for this transaction"""
		if not self.matched_invoice:
			frappe.throw("No matched invoice found. Please match an invoice first.")
		
		if self.payment_entry:
			frappe.throw(f"Payment Entry {self.payment_entry} already exists for this transaction.")
		
		if self.credit_debit != "Credit":
			frappe.throw("Can only create Payment Entry for credit (incoming) transactions.")
		
		from betoled_automatisation.reconciliation.processor import create_payment_entry_from_transaction
		
		payment_entry = create_payment_entry_from_transaction(self)
		
		self.payment_entry = payment_entry.name
		self.status = "Reconciled"
		self.save()
		
		frappe.msgprint(
			f"Payment Entry {payment_entry.name} created successfully.",
			title="Payment Entry Created",
			indicator="green"
		)
		
		return payment_entry.name
	
	@frappe.whitelist()
	def ignore_transaction(self):
		"""Mark this transaction as ignored"""
		self.status = "Ignored"
		self.match_notes = (self.match_notes or "") + f"\nIgnored by {frappe.session.user} on {frappe.utils.now()}"
		self.save()
		
		frappe.msgprint("Transaction marked as ignored.", indicator="orange")







