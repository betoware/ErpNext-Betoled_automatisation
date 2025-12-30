// Copyright (c) 2024, BETOWARE and contributors
// For license information, please see license.txt

frappe.ui.form.on("Ponto Settings", {
	refresh(frm) {
		if (!frm.is_new()) {
			// Add Test Connection button
			frm.add_custom_button(__("Test Connection"), function() {
				frm.call({
					method: "test_connection",
					doc: frm.doc,
					freeze: true,
					freeze_message: __("Testing connection to Ponto...")
				});
			}, __("Actions"));
			
			// Add Fetch Transactions Now button
			if (frm.doc.enabled) {
				frm.add_custom_button(__("Fetch Transactions Now"), function() {
					frappe.confirm(
						__("This will fetch and process transactions for {0}. Continue?", [frm.doc.company]),
						function() {
							frm.call({
								method: "fetch_transactions_now",
								doc: frm.doc,
								freeze: true,
								freeze_message: __("Fetching transactions from Ponto...")
							});
						}
					);
				}, __("Actions"));
			}
		}
		
		// Show warning if not enabled
		if (!frm.doc.enabled && !frm.is_new()) {
			frm.dashboard.add_comment(
				__("This Ponto integration is disabled. Enable it to start fetching transactions."),
				"yellow"
			);
		}
		
		// Show last sync info
		if (frm.doc.last_sync) {
			frm.dashboard.add_comment(
				__("Last synchronized: {0}", [frappe.datetime.prettyDate(frm.doc.last_sync)]),
				"blue"
			);
		}
	},
	
	company(frm) {
		// When company changes, try to fetch the IBAN
		if (frm.doc.company) {
			frappe.call({
				method: "frappe.client.get_value",
				args: {
					doctype: "Company",
					filters: { name: frm.doc.company },
					fieldname: "default_bank_account"
				},
				callback: function(r) {
					if (r.message && r.message.default_bank_account) {
						let bank_account_name = r.message.default_bank_account;
						
						// Use frappe.call instead of frappe.db.get_value for better error handling
						frappe.call({
							method: "frappe.client.get_value",
							args: {
								doctype: "Bank Account",
								filters: { name: bank_account_name },
								fieldname: ["iban", "bank_account_no"]
							},
							callback: function(r2) {
								if (r2.message) {
									let iban = r2.message.iban || r2.message.bank_account_no;
									if (iban) {
										frm.set_value("iban", iban.replace(/\s/g, "").toUpperCase());
									}
								}
							},
							error: function(e) {
								// Silently ignore errors - IBAN can be set manually or during save
								console.log("Could not fetch bank account details:", e);
							}
						});
					} else {
						frappe.msgprint({
							title: __("Warning"),
							indicator: "orange",
							message: __("Company {0} does not have a default bank account configured. Please set up the default bank account first.", [frm.doc.company])
						});
					}
				}
			});
		}
	}
});

