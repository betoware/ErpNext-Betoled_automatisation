// Copyright (c) 2024, BETOWARE and contributors
// For license information, please see license.txt

frappe.ui.form.on("Ponto Transaction", {
	refresh(frm) {
		// Set indicator color based on status
		let indicator = "gray";
		switch(frm.doc.status) {
			case "Reconciled": indicator = "green"; break;
			case "Matched": indicator = "blue"; break;
			case "Pending": indicator = "orange"; break;
			case "Error": indicator = "red"; break;
			case "Ignored": indicator = "gray"; break;
		}
		frm.page.set_indicator(frm.doc.status, indicator);
		
		// Add action buttons based on status
		if (frm.doc.status === "Pending" && frm.doc.credit_debit === "Credit") {
			// Find potential matches
			frm.add_custom_button(__("Find Matches"), function() {
				frappe.call({
					method: "betoled_automatisation.api.find_potential_matches",
					args: { transaction_name: frm.doc.name },
					freeze: true,
					callback: function(r) {
						if (r.message && r.message.length > 0) {
							show_match_dialog(frm, r.message);
						} else {
							frappe.msgprint(__("No potential matches found."));
						}
					}
				});
			}, __("Actions"));
			
			// Ignore transaction
			frm.add_custom_button(__("Ignore"), function() {
				frappe.confirm(
					__("Mark this transaction as ignored? It will not be processed."),
					function() {
						frm.call({
							method: "ignore_transaction",
							doc: frm.doc,
							callback: function() {
								frm.reload_doc();
							}
						});
					}
				);
			}, __("Actions"));
		}
		
		if (frm.doc.status === "Matched" && frm.doc.matched_invoice && !frm.doc.payment_entry) {
			// Create Payment Entry
			frm.add_custom_button(__("Create Payment Entry"), function() {
				frappe.confirm(
					__("Create Payment Entry for invoice {0}?", [frm.doc.matched_invoice]),
					function() {
						frm.call({
							method: "create_payment_entry",
							doc: frm.doc,
							freeze: true,
							freeze_message: __("Creating Payment Entry..."),
							callback: function(r) {
								if (r.message) {
									frm.reload_doc();
									frappe.set_route("Form", "Payment Entry", r.message);
								}
							}
						});
					}
				);
			}, __("Actions"));
		}
		
		// Show formatted structured reference
		if (frm.doc.structured_reference && frm.doc.structured_reference.length === 12) {
			let ref = frm.doc.structured_reference;
			let formatted = `+++${ref.slice(0,3)}/${ref.slice(3,7)}/${ref.slice(7)}+++`;
			frm.dashboard.add_comment(
				__("Structured Reference: {0}", [formatted]),
				"blue"
			);
		}
	}
});

function show_match_dialog(frm, matches) {
	let fields = [
		{
			fieldtype: "HTML",
			fieldname: "matches_html"
		}
	];
	
	let d = new frappe.ui.Dialog({
		title: __("Potential Matches"),
		fields: fields,
		size: "large",
		primary_action_label: __("Close"),
		primary_action: function() {
			d.hide();
		}
	});
	
	// Build HTML table of matches
	let html = `
		<table class="table table-bordered">
			<thead>
				<tr>
					<th>${__("Invoice")}</th>
					<th>${__("Customer")}</th>
					<th>${__("Invoice Amount")}</th>
					<th>${__("Outstanding")}</th>
					<th>${__("Score")}</th>
					<th>${__("Action")}</th>
				</tr>
			</thead>
			<tbody>
	`;
	
	matches.forEach(function(m) {
		html += `
			<tr>
				<td><a href="/app/sales-invoice/${m.invoice}">${m.invoice}</a></td>
				<td>${m.customer || ""}</td>
				<td>${format_currency(m.invoice_amount)}</td>
				<td>${format_currency(m.outstanding)}</td>
				<td><span class="indicator ${m.score >= 50 ? 'green' : m.score >= 30 ? 'orange' : 'red'}">${m.score}%</span></td>
				<td>
					<button class="btn btn-xs btn-primary" onclick="match_invoice('${frm.doc.name}', '${m.invoice}')">
						${__("Match")}
					</button>
				</td>
			</tr>
		`;
	});
	
	html += `</tbody></table>`;
	
	d.fields_dict.matches_html.$wrapper.html(html);
	d.show();
}

// Global function for matching from dialog
window.match_invoice = function(transaction_name, invoice_name) {
	frappe.call({
		method: "betoled_automatisation.api.manually_match_transaction",
		args: {
			transaction_name: transaction_name,
			invoice_name: invoice_name
		},
		freeze: true,
		callback: function(r) {
			if (r.message && r.message.success) {
				frappe.msgprint({
					title: __("Success"),
					indicator: "green",
					message: r.message.message
				});
				// Close dialog and reload
				$(".modal").modal("hide");
				cur_frm.reload_doc();
			}
		}
	});
};


