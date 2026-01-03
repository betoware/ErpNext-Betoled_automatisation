# Copyright (c) 2024, BETOWARE and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PaymentMatch(Document):
	def validate(self):
		"""Fetch invoice details when invoice is linked"""
		if self.sales_invoice:
			self.fetch_invoice_details()
		
		if self.ponto_transaction:
			self.fetch_transaction_details()
	
	def fetch_invoice_details(self):
		"""Fetch details from the linked Sales Invoice"""
		invoice = frappe.get_doc("Sales Invoice", self.sales_invoice)
		self.invoice_amount = invoice.grand_total
		self.outstanding_amount = invoice.outstanding_amount
		self.gestructureerde_mededeling = invoice.get("gestructureerde_mededeling")
		self.company = invoice.company
	
	def fetch_transaction_details(self):
		"""Fetch details from the linked Ponto Transaction"""
		transaction = frappe.get_doc("Ponto Transaction", self.ponto_transaction)
		self.transaction_amount = transaction.amount
		self.transaction_date = transaction.transaction_date
		self.counterpart_name = transaction.counterpart_name
		
		if not self.company:
			self.company = transaction.company
	
	@frappe.whitelist()
	def approve_match(self):
		"""Approve this match and create a Payment Entry"""
		if self.status not in ["Pending Review"]:
			frappe.throw(f"Cannot approve match with status {self.status}")
		
		if not self.sales_invoice:
			frappe.throw("No Sales Invoice linked to this match")
		
		from betoled_automatisation.reconciliation.processor import create_payment_entry_from_match
		
		try:
			payment_entry = create_payment_entry_from_match(self)
			
			self.status = "Approved"
			self.payment_entry = payment_entry.name
			self.processed_date = frappe.utils.now()
			self.processed_by = frappe.session.user
			self.save()
			
			# Update the Ponto Transaction status
			if self.ponto_transaction:
				frappe.db.set_value("Ponto Transaction", self.ponto_transaction, {
					"status": "Reconciled",
					"matched_invoice": self.sales_invoice,
					"payment_entry": payment_entry.name
				})
			
			frappe.msgprint(
				f"Payment Entry {payment_entry.name} created successfully.",
				title="Match Approved",
				indicator="green"
			)
			
			return payment_entry.name
		except Exception as e:
			frappe.throw(f"Failed to create Payment Entry: {str(e)}")
	
	@frappe.whitelist()
	def reject_match(self, reason=None):
		"""Reject this match"""
		if self.status not in ["Pending Review"]:
			frappe.throw(f"Cannot reject match with status {self.status}")
		
		self.status = "Rejected"
		self.processed_date = frappe.utils.now()
		self.processed_by = frappe.session.user
		
		if reason:
			self.notes = (self.notes or "") + f"\nRejected: {reason}"
		
		self.save()
		
		# Update the Ponto Transaction status back to Pending
		if self.ponto_transaction:
			frappe.db.set_value("Ponto Transaction", self.ponto_transaction, {
				"status": "Pending",
				"match_status": "Manual Review Required",
				"match_notes": f"Match rejected: {reason or 'No reason provided'}"
			})
		
		frappe.msgprint("Match rejected.", indicator="orange")










