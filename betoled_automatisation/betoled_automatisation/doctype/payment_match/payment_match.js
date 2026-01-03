// Copyright (c) 2024, BETOWARE and contributors
// For license information, please see license.txt

frappe.ui.form.on("Payment Match", {
	refresh(frm) {
		// Set indicator based on status
		let indicator = "gray";
		switch(frm.doc.status) {
			case "Approved": indicator = "green"; break;
			case "Auto-Reconciled": indicator = "green"; break;
			case "Pending Review": indicator = "orange"; break;
			case "Rejected": indicator = "red"; break;
		}
		frm.page.set_indicator(frm.doc.status, indicator);
		
		// Add action buttons for pending matches
		if (frm.doc.status === "Pending Review") {
			frm.add_custom_button(__("Approve & Create Payment"), function() {
				frappe.confirm(
					__("Approve this match and create a Payment Entry for invoice {0}?", [frm.doc.sales_invoice]),
					function() {
						frm.call({
							method: "approve_match",
							doc: frm.doc,
							freeze: true,
							freeze_message: __("Creating Payment Entry..."),
							callback: function(r) {
								if (r.message) {
									frm.reload_doc();
								}
							}
						});
					}
				);
			}, __("Actions"));
			
			frm.add_custom_button(__("Reject Match"), function() {
				frappe.prompt(
					{
						fieldtype: "Small Text",
						fieldname: "reason",
						label: __("Reason for rejection"),
						reqd: 0
					},
					function(values) {
						frm.call({
							method: "reject_match",
							doc: frm.doc,
							args: { reason: values.reason },
							callback: function() {
								frm.reload_doc();
							}
						});
					},
					__("Reject Match"),
					__("Reject")
				);
			}, __("Actions"));
		}
		
		// Show match summary
		if (frm.doc.sales_invoice && frm.doc.transaction_amount) {
			let diff = flt(frm.doc.transaction_amount) - flt(frm.doc.outstanding_amount);
			let diff_text = "";
			let diff_color = "blue";
			
			if (Math.abs(diff) < 0.01) {
				diff_text = __("Exact match");
				diff_color = "green";
			} else if (diff > 0) {
				diff_text = __("Overpayment: {0}", [format_currency(diff)]);
				diff_color = "orange";
			} else {
				diff_text = __("Partial payment: {0} remaining", [format_currency(-diff)]);
				diff_color = "orange";
			}
			
			frm.dashboard.add_comment(diff_text, diff_color);
		}
		
		// Show confidence indicator
		if (frm.doc.confidence_score) {
			let conf_color = frm.doc.confidence_score >= 80 ? "green" : 
							 frm.doc.confidence_score >= 50 ? "orange" : "red";
			frm.dashboard.add_comment(
				__("Confidence: {0}%", [frm.doc.confidence_score]),
				conf_color
			);
		}
	}
});







