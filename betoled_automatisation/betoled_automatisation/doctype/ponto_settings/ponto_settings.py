# Copyright (c) 2024, BETOWARE and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PontoSettings(Document):
	def validate(self):
		"""Validate and fetch IBAN from company's default bank account"""
		if self.company:
			self.fetch_iban_from_company()
	
	def fetch_iban_from_company(self):
		"""Fetch IBAN from the company's default bank account"""
		company_doc = frappe.get_doc("Company", self.company)
		
		if company_doc.default_bank_account:
			bank_account = frappe.get_doc("Bank Account", company_doc.default_bank_account)
			if bank_account.iban:
				self.iban = bank_account.iban
			else:
				frappe.throw(f"Bank Account {bank_account.name} does not have an IBAN configured")
		else:
			frappe.throw(f"Company {self.company} does not have a Default Bank Account configured")
	
	def get_access_token(self):
		"""Get a valid access token, refreshing if necessary"""
		from betoled_automatisation.ponto.api import PontoAPI
		
		api = PontoAPI(self)
		return api.get_access_token()
	
	@frappe.whitelist()
	def test_connection(self):
		"""Test the Ponto API connection"""
		from betoled_automatisation.ponto.api import PontoAPI
		
		try:
			api = PontoAPI(self)
			accounts = api.get_accounts()
			
			if accounts:
				account_info = []
				for acc in accounts:
					account_info.append(f"- {acc.get('attributes', {}).get('reference', 'Unknown')} ({acc.get('id', 'No ID')})")
				
				frappe.msgprint(
					f"Connection successful! Found {len(accounts)} account(s):\n" + "\n".join(account_info),
					title="Ponto Connection Test",
					indicator="green"
				)
				return True
			else:
				frappe.msgprint(
					"Connection successful but no accounts found.",
					title="Ponto Connection Test",
					indicator="orange"
				)
				return True
		except Exception as e:
			frappe.throw(f"Connection failed: {str(e)}")
	
	@frappe.whitelist()
	def fetch_transactions_now(self):
		"""Manually trigger transaction fetch for this company"""
		from betoled_automatisation.tasks import fetch_transactions_for_company
		
		try:
			result = fetch_transactions_for_company(self.company)
			frappe.msgprint(
				f"Fetched {result.get('fetched', 0)} transactions, "
				f"matched {result.get('matched', 0)}, "
				f"pending review: {result.get('pending_review', 0)}",
				title="Transaction Fetch Complete",
				indicator="green"
			)
			return result
		except Exception as e:
			frappe.throw(f"Failed to fetch transactions: {str(e)}")

