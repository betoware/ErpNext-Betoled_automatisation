frappe.pages['ponto-dashboard'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Ponto Payment Reconciliation',
		single_column: true
	});

	// Add primary action button
	page.set_primary_action(__('Fetch All Transactions'), function() {
		frappe.confirm(
			__('This will fetch transactions for all enabled companies. Continue?'),
			function() {
				frappe.call({
					method: 'betoled_automatisation.tasks.run_reconciliation_now',
					freeze: true,
					freeze_message: __('Starting reconciliation job...'),
					callback: function(r) {
						frappe.show_alert({
							message: __('Reconciliation job has been queued. Check background jobs for progress.'),
							indicator: 'green'
						});
					}
				});
			}
		);
	}, 'octicon octicon-sync');

	// Add secondary action
	page.set_secondary_action(__('Refresh'), function() {
		load_dashboard(page);
	}, 'octicon octicon-refresh');

	// Store page reference
	page.main = $('<div class="ponto-dashboard"></div>').appendTo(page.body);
	
	// Load dashboard content
	load_dashboard(page);
};

function load_dashboard(page) {
	page.main.html('<div class="text-center" style="padding: 50px;"><i class="fa fa-spinner fa-spin fa-3x"></i></div>');
	
	// Load summary data
	frappe.call({
		method: 'betoled_automatisation.api.get_reconciliation_summary',
		args: { days: 30 },
		callback: function(r) {
			render_dashboard(page, r.message || {});
		}
	});
}

function render_dashboard(page, summary) {
	let html = `
		<div class="container-fluid">
			<!-- Summary Cards -->
			<div class="row" style="margin-bottom: 20px;">
				<div class="col-md-3">
					<div class="card" style="padding: 15px; text-align: center; background: #e8f5e9; border-radius: 8px;">
						<h2 style="margin: 0; color: #2e7d32;">${summary.reconciled || 0}</h2>
						<p style="margin: 5px 0 0; color: #666;">Reconciled (30 days)</p>
					</div>
				</div>
				<div class="col-md-3">
					<div class="card" style="padding: 15px; text-align: center; background: #fff3e0; border-radius: 8px;">
						<h2 style="margin: 0; color: #ef6c00;">${summary.pending_matches || 0}</h2>
						<p style="margin: 5px 0 0; color: #666;">Pending Review</p>
					</div>
				</div>
				<div class="col-md-3">
					<div class="card" style="padding: 15px; text-align: center; background: #e3f2fd; border-radius: 8px;">
						<h2 style="margin: 0; color: #1565c0;">${summary.unmatched || 0}</h2>
						<p style="margin: 5px 0 0; color: #666;">Unmatched</p>
					</div>
				</div>
				<div class="col-md-3">
					<div class="card" style="padding: 15px; text-align: center; background: #f3e5f5; border-radius: 8px;">
						<h2 style="margin: 0; color: #7b1fa2;">${format_currency(summary.reconciled_amount || 0)}</h2>
						<p style="margin: 5px 0 0; color: #666;">Amount Reconciled</p>
					</div>
				</div>
			</div>

			<!-- Quick Actions -->
			<div class="row" style="margin-bottom: 20px;">
				<div class="col-md-12">
					<div class="card" style="padding: 20px; border-radius: 8px; border: 1px solid #ddd;">
						<h4 style="margin-top: 0;"><i class="fa fa-bolt"></i> Quick Actions</h4>
						<div class="btn-group">
							<button class="btn btn-default btn-fetch-company" data-company="">
								<i class="fa fa-download"></i> Fetch for Specific Company
							</button>
							<a href="/app/payment-match?status=Pending+Review" class="btn btn-warning">
								<i class="fa fa-eye"></i> Review Pending Matches (${summary.pending_matches || 0})
							</a>
							<a href="/app/ponto-transaction?status=Pending&credit_debit=Credit" class="btn btn-info">
								<i class="fa fa-search"></i> View Unmatched Transactions
							</a>
							<a href="/app/ponto-settings" class="btn btn-default">
								<i class="fa fa-cog"></i> Ponto Settings
							</a>
						</div>
					</div>
				</div>
			</div>

			<!-- Company Status -->
			<div class="row">
				<div class="col-md-12">
					<div class="card" style="padding: 20px; border-radius: 8px; border: 1px solid #ddd;">
						<h4 style="margin-top: 0;"><i class="fa fa-building"></i> Company Status</h4>
						<div id="company-status-table"></div>
					</div>
				</div>
			</div>
		</div>
	`;
	
	page.main.html(html);
	
	// Load company status
	load_company_status();
	
	// Bind events
	page.main.find('.btn-fetch-company').on('click', function() {
		show_company_selector();
	});
}

function load_company_status() {
	frappe.call({
		method: 'frappe.client.get_list',
		args: {
			doctype: 'Ponto Settings',
			fields: ['name', 'company', 'enabled', 'last_sync', 'iban'],
			limit_page_length: 0
		},
		callback: function(r) {
			let html = `
				<table class="table table-bordered">
					<thead>
						<tr>
							<th>Company</th>
							<th>Status</th>
							<th>IBAN</th>
							<th>Last Sync</th>
							<th>Actions</th>
						</tr>
					</thead>
					<tbody>
			`;
			
			if (r.message && r.message.length > 0) {
				r.message.forEach(function(setting) {
					let status_badge = setting.enabled 
						? '<span class="indicator-pill green">Enabled</span>'
						: '<span class="indicator-pill gray">Disabled</span>';
					
					let last_sync = setting.last_sync 
						? frappe.datetime.prettyDate(setting.last_sync)
						: '<span class="text-muted">Never</span>';
					
					html += `
						<tr>
							<td><a href="/app/ponto-settings/${setting.name}">${setting.company}</a></td>
							<td>${status_badge}</td>
							<td><code>${setting.iban || '-'}</code></td>
							<td>${last_sync}</td>
							<td>
								<button class="btn btn-xs btn-primary btn-fetch-single" data-company="${setting.company}" ${!setting.enabled ? 'disabled' : ''}>
									<i class="fa fa-download"></i> Fetch Now
								</button>
								<a href="/app/ponto-transaction?company=${encodeURIComponent(setting.company)}" class="btn btn-xs btn-default">
									<i class="fa fa-list"></i> Transactions
								</a>
							</td>
						</tr>
					`;
				});
			} else {
				html += `
					<tr>
						<td colspan="5" class="text-center text-muted">
							No Ponto Settings configured. 
							<a href="/app/ponto-settings/new-ponto-settings-1">Create one now</a>
						</td>
					</tr>
				`;
			}
			
			html += '</tbody></table>';
			$('#company-status-table').html(html);
			
			// Bind fetch buttons
			$('.btn-fetch-single').on('click', function() {
				let company = $(this).data('company');
				fetch_for_company(company);
			});
		}
	});
}

function show_company_selector() {
	frappe.call({
		method: 'frappe.client.get_list',
		args: {
			doctype: 'Ponto Settings',
			filters: { enabled: 1 },
			fields: ['company']
		},
		callback: function(r) {
			if (!r.message || r.message.length === 0) {
				frappe.msgprint(__('No enabled Ponto Settings found.'));
				return;
			}
			
			let options = r.message.map(s => s.company);
			
			frappe.prompt({
				fieldtype: 'Select',
				fieldname: 'company',
				label: __('Select Company'),
				options: options,
				reqd: 1
			}, function(values) {
				fetch_for_company(values.company);
			}, __('Fetch Transactions'), __('Fetch'));
		}
	});
}

function fetch_for_company(company) {
	frappe.call({
		method: 'betoled_automatisation.tasks.run_reconciliation_for_company',
		args: { company: company },
		freeze: true,
		freeze_message: __('Fetching transactions for {0}...', [company]),
		callback: function(r) {
			if (r.message) {
				let result = r.message;
				frappe.msgprint({
					title: __('Fetch Complete'),
					indicator: 'green',
					message: `
						<p><strong>${company}</strong></p>
						<ul>
							<li>Transactions fetched: ${result.fetched || 0}</li>
							<li>New transactions: ${result.new || 0}</li>
							<li>Matched: ${result.matched || 0}</li>
							<li>Auto-reconciled: ${result.auto_reconciled || 0}</li>
							<li>Pending review: ${result.pending_review || 0}</li>
							<li>No match found: ${result.no_match || 0}</li>
						</ul>
					`
				});
				// Refresh dashboard
				load_company_status();
			}
		}
	});
}







