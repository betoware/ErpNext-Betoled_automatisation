# Copyright (c) 2024, BETOWARE and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PontoSettings(Document):
	def validate(self):
		"""Validate and fetch IBAN from company's default bank account"""
		if self.company and not self.iban:
			# Only try to fetch IBAN if not already set
			self.fetch_iban_from_company()
		
		# Normalize IBAN if set
		if self.iban:
			self.iban = self.iban.replace(" ", "").upper()
		
		# Warn if no IBAN when enabling
		if self.enabled and not self.iban:
			frappe.msgprint(
				"No IBAN configured. Please enter the IBAN manually or configure the "
				"Default Bank Account on the Company with a valid IBAN.",
				title="Warning",
				indicator="orange"
			)
	
	def fetch_iban_from_company(self):
		"""Fetch IBAN from the company's default bank account (non-blocking)"""
		try:
			company_doc = frappe.get_doc("Company", self.company)
			
			if not company_doc.default_bank_account:
				frappe.msgprint(
					f"Company {self.company} does not have a Default Bank Account configured. "
					f"Please enter the IBAN manually or set up the Default Bank Account.",
					title="Info",
					indicator="blue"
				)
				return
			
			bank_account_name = company_doc.default_bank_account
			
			# Check if Bank Account exists
			if not frappe.db.exists("Bank Account", bank_account_name):
				frappe.msgprint(
					f"Bank Account '{bank_account_name}' not found. Please enter IBAN manually.",
					title="Info",
					indicator="blue"
				)
				return
			
			bank_account = frappe.get_doc("Bank Account", bank_account_name)
			
			# Check if IBAN field exists and is set
			iban = None
			if hasattr(bank_account, 'iban') and bank_account.iban:
				iban = bank_account.iban
			elif hasattr(bank_account, 'bank_account_no') and bank_account.bank_account_no:
				# Fallback to bank_account_no if it looks like an IBAN
				account_no = bank_account.bank_account_no
				if account_no and len(account_no.replace(" ", "")) >= 15:
					iban = account_no
			
			if iban:
				self.iban = iban.replace(" ", "").upper()
			else:
				frappe.msgprint(
					f"Bank Account '{bank_account.name}' does not have an IBAN. "
					f"Please enter the IBAN manually.",
					title="Info",
					indicator="blue"
				)
		except Exception as e:
			# Log error but don't block saving
			frappe.log_error(
				title="Ponto Settings - IBAN Fetch Error",
				message=f"Could not fetch IBAN for company {self.company}: {str(e)}\n{frappe.get_traceback()}"
			)
			frappe.msgprint(
				f"Could not automatically fetch IBAN: {str(e)}. Please enter IBAN manually.",
				title="Warning",
				indicator="orange"
			)
	
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

