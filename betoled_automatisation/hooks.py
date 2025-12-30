app_name = "betoled_automatisation"
app_title = "Betoled Automatisation"
app_publisher = "BETOWARE"
app_description = "Automation tools for BETOWARE/LASTAMAR ERPNext"
app_email = "bt@betoware.be"
app_license = "mit"

# Required Apps
required_apps = ["frappe", "erpnext"]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/betoled_automatisation/css/betoled_automatisation.css"
# app_include_js = "/assets/betoled_automatisation/js/betoled_automatisation.js"

# Installation
# ------------

after_install = "betoled_automatisation.install.after_install"
after_migrate = "betoled_automatisation.install.after_migrate"

# Scheduled Tasks
# ---------------
# Run payment reconciliation twice a day: at 7:00 and 14:00

scheduler_events = {
	"cron": {
		# Run at 7:00 AM every day
		"0 7 * * *": [
			"betoled_automatisation.tasks.fetch_and_reconcile_all"
		],
		# Run at 2:00 PM (14:00) every day
		"0 14 * * *": [
			"betoled_automatisation.tasks.fetch_and_reconcile_all"
		]
	}
}

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Testing
# -------

# before_tests = "betoled_automatisation.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "betoled_automatisation.event.get_events"
# }

# Log retention settings
default_log_clearing_doctypes = {
	"Ponto Transaction": 90  # Keep for 90 days
}
