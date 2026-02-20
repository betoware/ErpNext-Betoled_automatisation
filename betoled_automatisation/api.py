# Copyright (c) 2024, BETOWARE and contributors
# For license information, please see license.txt

"""
API endpoints for betoled_automatisation
"""

import frappe
from frappe import _


@frappe.whitelist()
def get_pending_matches(company=None):
	"""
	Get all pending Payment Matches that need review.
	
	Args:
		company: Optional company filter
		
	Returns:
		list: List of pending Payment Match records
	"""
	filters = {"status": "Pending Review"}
	
	if company:
		filters["company"] = company
	
	matches = frappe.get_all(
		"Payment Match",
		filters=filters,
		fields=[
			"name", "company", "ponto_transaction", "sales_invoice",
			"transaction_amount", "transaction_date", "counterpart_name",
			"match_type", "confidence_score", "invoice_amount", 
			"outstanding_amount", "gestructureerde_mededeling", "notes"
		],
		order_by="created_date desc"
	)
	
	return matches


@frappe.whitelist()
def get_unmatched_transactions(company=None, limit=50):
	"""
	Get transactions that could not be matched.
	
	Args:
		company: Optional company filter
		limit: Maximum number of results
		
	Returns:
		list: List of unmatched Ponto Transaction records
	"""
	# Convert limit to int (comes as string from JS)
	limit = int(limit) if limit else 50
	
	filters = {
		"status": "Pending",
		"credit_debit": "Credit"  # Only incoming payments
	}
	
	if company:
		filters["company"] = company
	
	transactions = frappe.get_all(
		"Ponto Transaction",
		filters=filters,
		fields=[
			"name", "company", "transaction_date", "amount",
			"counterpart_name", "counterpart_iban",
			"remittance_information", "structured_reference",
			"match_status", "match_notes"
		],
		order_by="transaction_date desc",
		limit_page_length=limit
	)
	
	return transactions


@frappe.whitelist()
def get_reconciliation_summary(company=None, days=30):
	"""
	Get a summary of reconciliation activity.
	
	Args:
		company: Optional company filter
		days: Number of days to look back
		
	Returns:
		dict: Summary statistics
	"""
	from frappe.utils import add_days, today
	
	# Convert days to int (comes as string from JS)
	days = int(days) if days else 30
	
	start_date = add_days(today(), -days)
	
	filters = {"transaction_date": [">=", start_date]}
	if company:
		filters["company"] = company
	
	# Get transaction counts by status
	total = frappe.db.count("Ponto Transaction", filters)
	
	filters["status"] = "Reconciled"
	reconciled = frappe.db.count("Ponto Transaction", filters)
	
	filters["status"] = "Matched"
	matched = frappe.db.count("Ponto Transaction", filters)
	
	filters["status"] = "Pending"
	pending = frappe.db.count("Ponto Transaction", filters)
	
	filters["status"] = "Error"
	errors = frappe.db.count("Ponto Transaction", filters)
	
	# Get pending matches count
	match_filters = {"status": "Pending Review"}
	if company:
		match_filters["company"] = company
	pending_matches = frappe.db.count("Payment Match", match_filters)
	
	# Get total amount reconciled
	if company:
		amount_filters = f"AND company = '{company}'"
	else:
		amount_filters = ""
	
	reconciled_amount = frappe.db.sql(f"""
		SELECT COALESCE(SUM(amount), 0) as total
		FROM `tabPonto Transaction`
		WHERE status = 'Reconciled'
		AND transaction_date >= %s
		{amount_filters}
	""", (start_date,))[0][0]
	
	return {
		"period_days": days,
		"total_transactions": total,
		"reconciled": reconciled,
		"matched_pending_review": matched,
		"unmatched": pending,
		"errors": errors,
		"pending_matches": pending_matches,
		"reconciled_amount": float(reconciled_amount or 0)
	}


@frappe.whitelist()
def manually_match_transaction(transaction_name, invoice_name):
	"""
	Manually match a transaction to an invoice.
	Creates a Payment Entry immediately so the invoice goes to Paid.
	Also creates a Payment Match record for audit.
	"""
	frappe.only_for(["System Manager", "Accounts Manager"])

	transaction = frappe.get_doc("Ponto Transaction", transaction_name)
	invoice = frappe.get_doc("Sales Invoice", invoice_name)

	# Verify company match
	if transaction.company != invoice.company:
		frappe.throw(_("Transaction company ({0}) does not match invoice company ({1})").format(
			transaction.company, invoice.company
		))

	# Create Payment Match record (for audit); validate will set transaction_amount etc.
	match_doc = frappe.get_doc({
		"doctype": "Payment Match",
		"ponto_transaction": transaction.name,
		"company": transaction.company,
		"status": "Pending Review",
		"sales_invoice": invoice.name,
		"match_type": "Manual Match",
		"confidence_score": 100,
		"notes": f"Manually matched by {frappe.session.user}"
	})
	match_doc.insert(ignore_permissions=True)

	# Create Payment Entry immediately so the invoice is marked Paid
	from betoled_automatisation.reconciliation.processor import create_payment_entry_from_match

	try:
		payment_entry = create_payment_entry_from_match(match_doc)

		# Update Payment Match: approved with payment entry
		match_doc.status = "Approved"
		match_doc.payment_entry = payment_entry.name
		match_doc.processed_date = frappe.utils.now()
		match_doc.processed_by = frappe.session.user
		match_doc.save(ignore_permissions=True)

		# Update Ponto Transaction: reconciled with payment entry
		transaction.matched_invoice = invoice.name
		transaction.status = "Reconciled"
		transaction.payment_entry = payment_entry.name
		transaction.match_status = "Manual Match"
		transaction.match_notes = f"Manually matched to {invoice.name} by {frappe.session.user}"
		transaction.save()

		return {
			"success": True,
			"match": match_doc.name,
			"payment_entry": payment_entry.name,
			"message": _("Payment Entry {0} created. Invoice is marked as paid.").format(payment_entry.name)
		}
	except Exception as e:
		# Payment Entry failed; keep Match for review
		transaction.matched_invoice = invoice.name
		transaction.status = "Matched"
		transaction.match_status = "Manual Review Required"
		transaction.match_notes = f"Manually matched to {invoice.name}. Payment creation failed: {e}"
		transaction.save()
		frappe.throw(
			_("Match created but Payment Entry failed: {0}. You can approve the match at Payment Match {1}.").format(
				str(e), match_doc.name
			)
		)


@frappe.whitelist()
def find_potential_matches(transaction_name):
	"""
	Find potential invoice matches for a transaction.
	
	Args:
		transaction_name: Ponto Transaction name
		
	Returns:
		list: Potential matches with scores
	"""
	from betoled_automatisation.reconciliation.matcher import PaymentMatcher
	
	transaction = frappe.get_doc("Ponto Transaction", transaction_name)
	matcher = PaymentMatcher(transaction.company)
	
	potential = matcher.find_potential_matches(transaction, max_results=10)
	
	# Format for API response
	results = []
	for match in potential:
		inv = match["invoice"]
		results.append({
			"invoice": inv.name,
			"customer": inv.customer_name,
			"invoice_amount": inv.grand_total,
			"outstanding": inv.outstanding_amount,
			"posting_date": str(inv.posting_date),
			"score": match["score"],
			"notes": match["notes"]
		})
	
	return results

