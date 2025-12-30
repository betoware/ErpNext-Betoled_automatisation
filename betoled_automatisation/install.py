# Copyright (c) 2024, BETOWARE and contributors
# For license information, please see license.txt

"""
Installation hooks for betoled_automatisation
"""

import frappe


def after_install():
	"""Run after app installation"""
	print("=" * 50)
	print("betoled_automatisation: Running after_install()")
	print("=" * 50)
	
	_setup_custom_fields()
	_create_default_settings()
	
	print("=" * 50)
	print("betoled_automatisation: Installation complete!")
	print("=" * 50)


def after_migrate():
	"""Run after app migration"""
	print("betoled_automatisation: Running after_migrate()")
	_setup_custom_fields()


def _setup_custom_fields():
	"""
	Set up any custom fields needed on existing doctypes.
	
	Note: The gestructureerde_mededeling field is already managed by 
	betoled_peppol app, so we don't create it here.
	"""
	pass  # No additional custom fields needed at this time


def _create_default_settings():
	"""
	Create placeholder Ponto Settings for the known companies.
	This makes it easier for users to configure the integration.
	"""
	companies = ["BETOWARE", "LASTAMAR"]
	
	for company_name in companies:
		# Check if company exists
		if not frappe.db.exists("Company", company_name):
			print(f"  Company {company_name} does not exist, skipping settings creation")
			continue
		
		# Check if settings already exist
		if frappe.db.exists("Ponto Settings", {"company": company_name}):
			print(f"  Ponto Settings for {company_name} already exists")
			continue
		
		# Check if company has a default bank account
		company = frappe.get_doc("Company", company_name)
		if not company.default_bank_account:
			print(f"  Warning: {company_name} has no default bank account configured")
			print(f"  Please configure the default bank account before enabling Ponto")
		
		# Create placeholder settings (disabled by default)
		try:
			settings = frappe.get_doc({
				"doctype": "Ponto Settings",
				"company": company_name,
				"enabled": 0,  # Disabled until credentials are added
				"client_id": "",
				"client_secret": "",
				"days_to_fetch": 7,
				"auto_reconcile_exact_matches": 1
			})
			settings.flags.ignore_mandatory = True  # Skip validation for placeholder
			settings.insert(ignore_permissions=True)
			
			print(f"  Created Ponto Settings placeholder for {company_name}")
			print(f"  Please configure API credentials and enable the integration")
		except Exception as e:
			print(f"  Could not create settings for {company_name}: {e}")
	
	frappe.db.commit()

