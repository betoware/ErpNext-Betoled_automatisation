# Copyright (c) 2024, BETOWARE and contributors
# For license information, please see license.txt

"""
Ponto API Client for Ponto (MyPonto) bank integration.

Based on working implementation - uses Basic Auth for OAuth2 token request.
API Base URL: https://api.myponto.com
"""

import frappe
import requests
from datetime import datetime, timedelta
from frappe.utils import now_datetime, get_datetime


class PontoAPIError(Exception):
	"""Custom exception for Ponto API errors"""
	def __init__(self, message, status_code=None, response=None):
		self.message = message
		self.status_code = status_code
		self.response = response
		super().__init__(self.message)


class PontoAPI:
	"""
	Ponto API Client for fetching bank transactions.
	
	Uses OAuth2 client_credentials grant with Basic Auth.
	"""
	
	# Ponto API Base URL - CORRECT URL
	BASE_URL = "https://api.myponto.com"
	
	def __init__(self, settings):
		"""
		Initialize the Ponto API client.
		
		Args:
			settings: PontoSettings document or dict with client_id, client_secret, etc.
		"""
		if isinstance(settings, str):
			settings = frappe.get_doc("Ponto Settings", settings)
		
		self.settings = settings
		self.client_id = settings.client_id
		self.client_secret = settings.get_password("client_secret")
		self.access_token = None
		self.token_expiry = None
		
		# Load existing token if valid
		if settings.access_token and settings.token_expiry:
			expiry = get_datetime(settings.token_expiry)
			if expiry > now_datetime():
				self.access_token = settings.get_password("access_token")
				self.token_expiry = expiry
	
	def get_access_token(self):
		"""
		Get a valid access token, refreshing if necessary.
		
		Returns:
			str: Valid access token
		"""
		# Check if current token is still valid (with 60 second buffer)
		if self.access_token and self.token_expiry:
			if self.token_expiry > now_datetime() + timedelta(seconds=60):
				return self.access_token
		
		# Need to get a new token
		return self._request_new_token()
	
	def _request_new_token(self):
		"""
		Request a new access token from Ponto using Basic Auth.
		
		Returns:
			str: New access token
		"""
		if not self.client_id or not self.client_secret:
			raise PontoAPIError("Ponto Client ID or Secret not configured")
		
		token_url = f"{self.BASE_URL}/oauth2/token"
		
		try:
			# Ponto uses Basic Auth for the token request
			response = requests.post(
				token_url,
				data={"grant_type": "client_credentials"},
				auth=(self.client_id, self.client_secret),  # Basic Auth
				headers={"Accept": "application/json"},
				timeout=15
			)
			
			if response.status_code != 200:
				error_detail = {}
				try:
					error_detail = response.json() if response.text else {}
				except:
					error_detail = {"error": response.text}
				
				raise PontoAPIError(
					f"Failed to obtain access token: {error_detail.get('error_description', error_detail.get('error', response.text))}",
					status_code=response.status_code,
					response=error_detail
				)
			
			token_data = response.json()
			
			self.access_token = token_data.get("access_token")
			if not self.access_token:
				raise PontoAPIError(f"No access_token in Ponto response: {token_data}")
			
			expires_in = token_data.get("expires_in", 3600)  # Default to 1 hour
			self.token_expiry = now_datetime() + timedelta(seconds=expires_in)
			
			# Store token in settings for reuse
			self._save_token_to_settings()
			
			frappe.logger().info("Successfully obtained new Ponto access token")
			return self.access_token
			
		except requests.exceptions.RequestException as e:
			raise PontoAPIError(f"Network error while obtaining token: {str(e)}")
	
	def _save_token_to_settings(self):
		"""Save the access token to Ponto Settings for reuse"""
		try:
			frappe.db.set_value(
				"Ponto Settings",
				self.settings.name,
				{
					"access_token": self.access_token,
					"token_expiry": self.token_expiry
				},
				update_modified=False
			)
			frappe.db.commit()
		except Exception as e:
			frappe.log_error(
				title="Failed to save Ponto token",
				message=str(e)
			)
	
	def _make_request(self, method, endpoint, params=None, json_data=None):
		"""
		Make an authenticated request to the Ponto API.
		
		Args:
			method: HTTP method (GET, POST, etc.)
			endpoint: API endpoint (without base URL)
			params: Query parameters
			json_data: Request body data (JSON)
			
		Returns:
			dict: Response JSON
		"""
		token = self.get_access_token()
		
		url = f"{self.BASE_URL}{endpoint}"
		
		headers = {
			"Authorization": f"Bearer {token}",
			"Accept": "application/json",
			"Content-Type": "application/json"
		}
		
		try:
			response = requests.request(
				method=method,
				url=url,
				headers=headers,
				params=params,
				json=json_data,
				timeout=30
			)
			
			if response.status_code == 401:
				# Token might be expired, try to refresh
				self.access_token = None
				token = self.get_access_token()
				headers["Authorization"] = f"Bearer {token}"
				
				response = requests.request(
					method=method,
					url=url,
					headers=headers,
					params=params,
					json=json_data,
					timeout=30
				)
			
			if response.status_code not in [200, 201, 204]:
				error_detail = {}
				try:
					error_detail = response.json() if response.text else {}
				except:
					error_detail = {"error": response.text}
				
				raise PontoAPIError(
					f"API request failed: {error_detail}",
					status_code=response.status_code,
					response=error_detail
				)
			
			if response.status_code == 204:
				return None
			
			return response.json()
			
		except requests.exceptions.RequestException as e:
			raise PontoAPIError(f"Network error: {str(e)}")
	
	def get_accounts(self):
		"""
		Get all synchronized bank accounts from Ponto.
		
		Returns:
			list: List of account objects
		"""
		frappe.logger().info("Fetching accounts from Ponto...")
		response = self._make_request("GET", "/accounts")
		
		if response and "data" in response:
			accounts = response["data"]
			frappe.logger().info(f"Successfully fetched {len(accounts)} accounts from Ponto")
			return accounts
		
		return []
	
	def get_account_by_iban(self, iban):
		"""
		Find an account by IBAN.
		
		Args:
			iban: The IBAN to search for
			
		Returns:
			dict: Account object or None
		"""
		accounts = self.get_accounts()
		
		# Normalize IBAN for comparison
		iban_normalized = iban.replace(" ", "").upper()
		
		for account in accounts:
			account_ref = account.get("attributes", {}).get("reference", "")
			if account_ref.replace(" ", "").upper() == iban_normalized:
				return account
		
		return None
	
	def get_transactions(self, account_id, date_from=None, date_to=None, limit=100):
		"""
		Get transactions for a specific account.
		
		Args:
			account_id: Ponto account ID (UUID)
			date_from: Start date (datetime.date or YYYY-MM-DD string)
			date_to: End date (datetime.date or YYYY-MM-DD string)
			limit: Maximum number of transactions to fetch
			
		Returns:
			list: List of transaction objects
		"""
		if not account_id:
			return []
		
		frappe.logger().info(f"Fetching transactions for account ID: {account_id}...")
		
		endpoint = f"/accounts/{account_id}/transactions"
		params = {"limit": min(limit, 100)}  # Ponto max is usually 100 per page
		
		if date_from:
			if hasattr(date_from, 'strftime'):
				date_from = date_from.strftime('%Y-%m-%d')
			params["from"] = date_from
		
		if date_to:
			if hasattr(date_to, 'strftime'):
				date_to = date_to.strftime('%Y-%m-%d')
			params["to"] = date_to
		
		all_transactions = []
		
		while True:
			response = self._make_request("GET", endpoint, params=params)
			
			if not response or "data" not in response:
				break
			
			transactions = response["data"]
			all_transactions.extend(transactions)
			
			if len(all_transactions) >= limit:
				break
			
			# Check for next page (pagination)
			links = response.get("links", {})
			next_link = links.get("next")
			
			if not next_link:
				break
			
			# Extract cursor from next link for pagination
			import urllib.parse as urlparse
			parsed = urlparse.urlparse(next_link)
			query_params = urlparse.parse_qs(parsed.query)
			
			if "after" in query_params:
				params["after"] = query_params["after"][0]
			elif "before" in query_params:
				params["before"] = query_params["before"][0]
			else:
				break
		
		frappe.logger().info(f"Successfully fetched {len(all_transactions)} transactions for account {account_id}")
		return all_transactions[:limit]
	
	def get_new_transactions(self, account_id, days_back=7):
		"""
		Get transactions from the last N days.
		
		Args:
			account_id: Ponto account ID (UUID)
			days_back: Number of days to look back
			
		Returns:
			list: List of transaction objects
		"""
		from_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
		
		return self.get_transactions(
			account_id=account_id,
			date_from=from_date,
			limit=500  # Reasonable limit for a week of transactions
		)
	
	def synchronize_account(self, account_id):
		"""
		Trigger a synchronization of the account with the bank.
		
		Note: This requests fresh data from the bank. Use sparingly
		as it may be rate-limited.
		
		Args:
			account_id: Ponto account ID (UUID)
			
		Returns:
			dict: Synchronization status
		"""
		endpoint = f"/accounts/{account_id}/synchronizations"
		
		response = self._make_request("POST", endpoint, json_data={
			"data": {
				"type": "synchronization",
				"attributes": {
					"resourceType": "account",
					"subtype": "accountTransactions"
				}
			}
		})
		
		return response
