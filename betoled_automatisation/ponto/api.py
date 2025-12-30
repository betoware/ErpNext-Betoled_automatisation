# Copyright (c) 2024, BETOWARE and contributors
# For license information, please see license.txt

"""
Ponto API Client for Isabel Group's Ponto service.

Ponto API Documentation: https://documentation.ibanity.com/ponto-connect/api
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
	
	Ponto uses OAuth2 for authentication. This client handles:
	- OAuth2 token management (obtaining and refreshing tokens)
	- Fetching financial institution accounts
	- Fetching transactions from accounts
	"""
	
	# Ponto API Base URLs
	BASE_URL = "https://api.ibanity.com/ponto-connect"
	AUTH_URL = "https://api.ibanity.com/ponto-connect/oauth2/token"
	
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
		# Check if current token is still valid (with 5 minute buffer)
		if self.access_token and self.token_expiry:
			if self.token_expiry > now_datetime() + timedelta(minutes=5):
				return self.access_token
		
		# Need to get a new token
		return self._request_new_token()
	
	def _request_new_token(self):
		"""
		Request a new access token from Ponto.
		
		Returns:
			str: New access token
		"""
		try:
			response = requests.post(
				self.AUTH_URL,
				data={
					"grant_type": "client_credentials",
					"client_id": self.client_id,
					"client_secret": self.client_secret,
				},
				headers={
					"Content-Type": "application/x-www-form-urlencoded",
					"Accept": "application/json"
				},
				timeout=30
			)
			
			if response.status_code != 200:
				error_detail = response.json() if response.text else {}
				raise PontoAPIError(
					f"Failed to obtain access token: {error_detail.get('error_description', response.text)}",
					status_code=response.status_code,
					response=error_detail
				)
			
			token_data = response.json()
			
			self.access_token = token_data["access_token"]
			expires_in = token_data.get("expires_in", 3600)  # Default to 1 hour
			self.token_expiry = now_datetime() + timedelta(seconds=expires_in)
			
			# Store token in settings for reuse
			self._save_token_to_settings()
			
			return self.access_token
			
		except requests.RequestException as e:
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
	
	def _make_request(self, method, endpoint, params=None, data=None):
		"""
		Make an authenticated request to the Ponto API.
		
		Args:
			method: HTTP method (GET, POST, etc.)
			endpoint: API endpoint (without base URL)
			params: Query parameters
			data: Request body data
			
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
				json=data,
				timeout=60
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
					json=data,
					timeout=60
				)
			
			if response.status_code not in [200, 201, 204]:
				error_detail = response.json() if response.text else {}
				raise PontoAPIError(
					f"API request failed: {error_detail.get('errors', response.text)}",
					status_code=response.status_code,
					response=error_detail
				)
			
			if response.status_code == 204:
				return None
			
			return response.json()
			
		except requests.RequestException as e:
			raise PontoAPIError(f"Network error: {str(e)}")
	
	def get_accounts(self):
		"""
		Get all financial institution accounts.
		
		Returns:
			list: List of account objects
		"""
		response = self._make_request("GET", "/accounts")
		return response.get("data", [])
	
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
			account_iban = account.get("attributes", {}).get("reference", "")
			if account_iban.replace(" ", "").upper() == iban_normalized:
				return account
		
		return None
	
	def get_transactions(self, account_id, from_date=None, to_date=None, limit=100):
		"""
		Get transactions for a specific account.
		
		Args:
			account_id: Ponto account ID (UUID)
			from_date: Start date for transactions (optional)
			to_date: End date for transactions (optional)
			limit: Maximum number of transactions to fetch
			
		Returns:
			list: List of transaction objects
		"""
		all_transactions = []
		endpoint = f"/accounts/{account_id}/transactions"
		params = {"page[limit]": min(limit, 100)}  # Ponto max is 100 per page
		
		while True:
			response = self._make_request("GET", endpoint, params=params)
			
			transactions = response.get("data", [])
			
			for txn in transactions:
				# Filter by date if specified
				txn_date = txn.get("attributes", {}).get("executionDate")
				if txn_date:
					txn_date_obj = datetime.strptime(txn_date[:10], "%Y-%m-%d").date()
					
					if from_date and txn_date_obj < from_date:
						continue
					if to_date and txn_date_obj > to_date:
						continue
				
				all_transactions.append(txn)
				
				if len(all_transactions) >= limit:
					break
			
			if len(all_transactions) >= limit:
				break
			
			# Check for next page
			next_link = response.get("links", {}).get("next")
			if not next_link:
				break
			
			# Extract cursor from next link
			# The next link contains the full URL, we need to extract the after parameter
			import urllib.parse as urlparse
			parsed = urlparse.urlparse(next_link)
			query_params = urlparse.parse_qs(parsed.query)
			
			if "page[after]" in query_params:
				params["page[after]"] = query_params["page[after]"][0]
			else:
				break
		
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
		from_date = (datetime.now() - timedelta(days=days_back)).date()
		to_date = datetime.now().date()
		
		return self.get_transactions(
			account_id=account_id,
			from_date=from_date,
			to_date=to_date,
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
		
		response = self._make_request("POST", endpoint, data={
			"data": {
				"type": "synchronization",
				"attributes": {
					"resourceType": "account",
					"subtype": "accountTransactions"
				}
			}
		})
		
		return response

