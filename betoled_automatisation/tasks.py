# Copyright (c) 2024, BETOWARE and contributors
# For license information, please see license.txt

"""
Scheduled tasks for payment reconciliation.

These tasks run automatically based on the schedule defined in hooks.py
"""

import frappe
from frappe.utils import now_datetime
import json


def fetch_and_reconcile_all():
	"""
	Main scheduled task: Fetch transactions and reconcile for all enabled companies.
	
	This task:
	1. Finds all enabled Ponto Settings
	2. Fetches new transactions for each company
	3. Attempts to match transactions with Sales Invoices
	4. Creates Payment Entries for exact matches (if auto-reconcile is enabled)
	5. Creates Payment Match records for matches requiring review
	"""
	frappe.logger().info("Starting Ponto payment reconciliation...")
	
	# Get all enabled Ponto Settings
	settings_list = frappe.get_all(
		"Ponto Settings",
		filters={"enabled": 1},
		fields=["name", "company"]
	)
	
	if not settings_list:
		frappe.logger().info("No enabled Ponto Settings found. Skipping reconciliation.")
		return
	
	results = {
		"success": [],
		"errors": []
	}
	
	for setting in settings_list:
		try:
			result = fetch_transactions_for_company(setting.company)
			results["success"].append({
				"company": setting.company,
				"result": result
			})
			frappe.logger().info(f"Reconciliation completed for {setting.company}: {result}")
		except Exception as e:
			error_msg = str(e)
			frappe.log_error(
				title=f"Ponto Reconciliation Error - {setting.company}",
				message=f"Error during reconciliation for {setting.company}:\n{error_msg}\n\n{frappe.get_traceback()}"
			)
			results["errors"].append({
				"company": setting.company,
				"error": error_msg
			})
	
	frappe.logger().info(f"Ponto reconciliation completed. Results: {json.dumps(results)}")
	
	return results


def fetch_transactions_for_company(company):
	"""
	Fetch and process transactions for a specific company.
	
	Args:
		company: Company name
		
	Returns:
		dict: Summary of results
	"""
	from betoled_automatisation.ponto.api import PontoAPI, PontoAPIError
	from betoled_automatisation.reconciliation.matcher import PaymentMatcher, MatchResult
	from betoled_automatisation.reconciliation.processor import PaymentProcessor
	
	# Get Ponto Settings for this company
	settings = frappe.get_doc("Ponto Settings", {"company": company})
	
	if not settings.enabled:
		return {"status": "skipped", "reason": "Company not enabled"}
	
	result = {
		"fetched": 0,
		"new": 0,
		"matched": 0,
		"auto_reconciled": 0,
		"pending_review": 0,
		"no_match": 0,
		"errors": 0
	}
	
	try:
		# Initialize API
		api = PontoAPI(settings)
		
		# Determine which account to use
		account_id = settings.ponto_account_id
		
		if not account_id:
			# Try to find account by IBAN
			if not settings.iban:
				frappe.throw("No Ponto Account ID or IBAN configured")
			
			account = api.get_account_by_iban(settings.iban)
			if not account:
				frappe.throw(f"Could not find Ponto account for IBAN {settings.iban}")
			
			account_id = account["id"]
			
			# Save for future use
			frappe.db.set_value("Ponto Settings", settings.name, "ponto_account_id", account_id)
		
		# Fetch transactions
		days_to_fetch = settings.days_to_fetch or 7
		transactions = api.get_new_transactions(account_id, days_back=days_to_fetch)
		result["fetched"] = len(transactions)
		
		# Initialize matcher and processor
		matcher = PaymentMatcher(company)
		processor = PaymentProcessor(company)
		
		# Process each transaction
		for txn_data in transactions:
			try:
				# Check if transaction already exists
				txn_id = txn_data.get("id")
				existing = frappe.db.exists("Ponto Transaction", {"ponto_transaction_id": txn_id})
				
				if existing:
					continue
				
				result["new"] += 1
				
				# Create Ponto Transaction record
				ponto_txn = _create_ponto_transaction(txn_data, company)
				
				# Only process credit transactions (incoming payments)
				if ponto_txn.credit_debit != "Credit":
					continue
				
				# Try to match
				match_result = matcher.match_transaction(ponto_txn)
				
				if match_result.match_type == MatchResult.NO_MATCH:
					ponto_txn.status = "Pending"
					ponto_txn.match_status = "No Match"
					ponto_txn.match_notes = "\n".join(match_result.notes)
					ponto_txn.save()
					result["no_match"] += 1
				
				elif match_result.is_exact() and settings.auto_reconcile_exact_matches:
					# Auto-reconcile exact matches
					try:
						payment_entry = processor.create_payment_entry(
							invoice=match_result.invoice,
							amount=ponto_txn.amount,
							transaction=ponto_txn
						)
						
						ponto_txn.status = "Reconciled"
						ponto_txn.matched_invoice = match_result.invoice.name
						ponto_txn.payment_entry = payment_entry.name
						ponto_txn.match_status = "Exact Match"
						ponto_txn.match_notes = "\n".join(match_result.notes)
						ponto_txn.save()
						
						result["matched"] += 1
						result["auto_reconciled"] += 1
					except Exception as e:
						# If payment entry fails, create for review
						_create_payment_match(ponto_txn, match_result)
						ponto_txn.status = "Error"
						ponto_txn.match_notes = f"Auto-reconcile failed: {str(e)}"
						ponto_txn.save()
						result["errors"] += 1
				
				else:
					# Create Payment Match for review
					_create_payment_match(ponto_txn, match_result)
					
					ponto_txn.status = "Matched"
					ponto_txn.matched_invoice = match_result.invoice.name if match_result.invoice else None
					ponto_txn.match_status = match_result.match_type
					ponto_txn.match_notes = "\n".join(match_result.notes)
					ponto_txn.save()
					
					result["matched"] += 1
					result["pending_review"] += 1
				
			except Exception as e:
				frappe.log_error(
					title=f"Error processing transaction",
					message=f"Transaction ID: {txn_data.get('id')}\nError: {str(e)}\n\n{frappe.get_traceback()}"
				)
				result["errors"] += 1
		
		# Update last sync time
		frappe.db.set_value("Ponto Settings", settings.name, "last_sync", now_datetime())
		frappe.db.commit()
		
	except PontoAPIError as e:
		frappe.log_error(
			title=f"Ponto API Error - {company}",
			message=f"API Error: {str(e)}\nStatus Code: {e.status_code}\nResponse: {e.response}"
		)
		raise
	
	return result


def _create_ponto_transaction(txn_data, company):
	"""
	Create a Ponto Transaction record from API data.
	
	Args:
		txn_data: Transaction data from Ponto API
		company: Company name
		
	Returns:
		Ponto Transaction document
	"""
	from betoled_automatisation.betoled_automatisation.doctype.ponto_transaction.ponto_transaction import PontoTransaction
	
	attrs = txn_data.get("attributes", {})
	
	# Determine credit/debit
	amount = float(attrs.get("amount", 0))
	credit_debit = "Credit" if amount > 0 else "Debit"
	
	# Extract structured reference
	remittance = attrs.get("remittanceInformation", "") or ""
	structured_ref = PontoTransaction.extract_structured_reference(remittance)
	
	ponto_txn = frappe.get_doc({
		"doctype": "Ponto Transaction",
		"company": company,
		"ponto_transaction_id": txn_data.get("id"),
		"status": "Pending",
		"transaction_date": attrs.get("executionDate", "")[:10] if attrs.get("executionDate") else None,
		"value_date": attrs.get("valueDate", "")[:10] if attrs.get("valueDate") else None,
		"amount": abs(amount),
		"currency": attrs.get("currency", "EUR"),
		"credit_debit": credit_debit,
		"counterpart_name": attrs.get("counterpartName", ""),
		"counterpart_iban": attrs.get("counterpartReference", ""),
		"remittance_information": remittance,
		"structured_reference": structured_ref,
		"raw_data": json.dumps(txn_data, indent=2, default=str)
	})
	
	ponto_txn.insert(ignore_permissions=True)
	
	return ponto_txn


def _create_payment_match(transaction, match_result):
	"""
	Create a Payment Match record for manual review.
	
	Args:
		transaction: Ponto Transaction document
		match_result: MatchResult object
		
	Returns:
		Payment Match document
	"""
	from betoled_automatisation.reconciliation.matcher import MatchResult
	
	match_doc = frappe.get_doc({
		"doctype": "Payment Match",
		"ponto_transaction": transaction.name,
		"company": transaction.company,
		"status": "Pending Review",
		"sales_invoice": match_result.invoice.name if match_result.invoice else None,
		"match_type": match_result.match_type,
		"confidence_score": match_result.confidence,
		"notes": "\n".join(match_result.notes) if match_result.notes else None
	})
	
	match_doc.insert(ignore_permissions=True)
	
	return match_doc


# Convenience functions for manual execution

@frappe.whitelist()
def run_reconciliation_now():
	"""
	Manually trigger reconciliation for all companies.
	Can be called from the desk or console.
	"""
	frappe.only_for("System Manager")
	
	frappe.enqueue(
		fetch_and_reconcile_all,
		queue="long",
		timeout=1800,  # 30 minutes
		job_name="ponto_reconciliation_manual"
	)
	
	frappe.msgprint(
		"Payment reconciliation job has been queued. Check the background jobs for status.",
		title="Reconciliation Started",
		indicator="green"
	)


@frappe.whitelist()
def run_reconciliation_for_company(company):
	"""
	Manually trigger reconciliation for a specific company.
	
	Args:
		company: Company name
	"""
	frappe.only_for(["System Manager", "Accounts Manager"])
	
	result = fetch_transactions_for_company(company)
	
	return result

