# Copyright (c) 2024, BETOWARE and contributors
# For license information, please see license.txt

"""
Installation hooks for betoled_automatisation
"""

import frappe


def after_install():
	"""Run after app installation"""
	frappe.logger().info("betoled_automatisation: Running after_install()")
	print("=" * 50)
	print("betoled_automatisation: Running after_install()")
	print("=" * 50)
	
	try:
		_setup_custom_fields()
		_create_default_settings()
	except Exception as e:
		frappe.log_error(
			title="betoled_automatisation install error",
			message=f"Error during after_install: {str(e)}\n{frappe.get_traceback()}"
		)
		print(f"Error during installation: {e}")
	
	print("=" * 50)
	print("betoled_automatisation: Installation complete!")
	print("=" * 50)


def after_migrate():
	"""Run after app migration"""
	frappe.logger().info("betoled_automatisation: Running after_migrate()")
	print("betoled_automatisation: Running after_migrate()")
	
	try:
		_setup_custom_fields()
	except Exception as e:
		frappe.log_error(
			title="betoled_automatisation migrate error",
			message=f"Error during after_migrate: {str(e)}\n{frappe.get_traceback()}"
		)
		print(f"Error during migration: {e}")


def _setup_custom_fields():
	"""
	Set up any custom fields needed on existing doctypes.
	
	Note: The gestructureerde_mededeling field is already managed by 
	betoled_peppol app, so we don't create it here.
	"""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
	
	# Ensure the module is registered
	try:
		if not frappe.db.exists("Module Def", "Betoled Automatisation"):
			module_def = frappe.get_doc({
				"doctype": "Module Def",
				"module_name": "Betoled Automatisation",
				"app_name": "betoled_automatisation"
			})
			module_def.insert(ignore_permissions=True)
			frappe.db.commit()
			print("  Created Module Def for Betoled Automatisation")
	except Exception as e:
		# Module might already exist or be created by the framework
		pass
	
	# Create custom_alias field on Customer and Supplier for fuzzy matching
	custom_fields = {
		"Customer": [
			{
				"fieldname": "custom_alias",
				"label": "Payment Aliases",
				"fieldtype": "Small Text",
				"insert_after": "customer_name",
				"description": "Comma-separated list of alternative names this customer might use for bank payments (for fuzzy matching)"
			}
		],
		"Supplier": [
			{
				"fieldname": "custom_alias",
				"label": "Payment Aliases",
				"fieldtype": "Small Text",
				"insert_after": "supplier_name",
				"description": "Comma-separated list of alternative names this supplier might use for bank payments (for fuzzy matching)"
			}
		]
	}
	
	# Check and create Customer custom_alias field
	if not frappe.db.exists("Custom Field", {"dt": "Customer", "fieldname": "custom_alias"}):
		try:
			create_custom_fields({"Customer": custom_fields["Customer"]}, update=True)
			print("  Created custom_alias field on Customer")
			frappe.db.commit()
		except Exception as e:
			print(f"  Could not create custom_alias field on Customer: {e}")
	
	# Check and create Supplier custom_alias field
	if not frappe.db.exists("Custom Field", {"dt": "Supplier", "fieldname": "custom_alias"}):
		try:
			create_custom_fields({"Supplier": custom_fields["Supplier"]}, update=True)
			print("  Created custom_alias field on Supplier")
			frappe.db.commit()
		except Exception as e:
			print(f"  Could not create custom_alias field on Supplier: {e}")


def _create_default_settings():
	"""
	Create placeholder Ponto Settings for the known companies.
	This makes it easier for users to configure the integration.
	"""
	# First check if the DocType exists
	if not frappe.db.exists("DocType", "Ponto Settings"):
		print("  Ponto Settings DocType not yet created, skipping default settings")
		return
	
	companies = ["BETOWARE", "LASTAMAR", "Lastamar"]  # Include variations
	
	for company_name in companies:
		# Check if company exists
		if not frappe.db.exists("Company", company_name):
			continue
		
		# Check if settings already exist (using company field)
		existing = frappe.db.exists("Ponto Settings", {"company": company_name})
		if existing:
			print(f"  Ponto Settings for {company_name} already exists")
			continue
		
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
			settings.flags.ignore_validate = True
			settings.insert(ignore_permissions=True)
			
			print(f"  Created Ponto Settings placeholder for {company_name}")
		except frappe.exceptions.DuplicateEntryError:
			print(f"  Ponto Settings for {company_name} already exists (duplicate)")
		except Exception as e:
			print(f"  Could not create settings for {company_name}: {e}")
	
	frappe.db.commit()
