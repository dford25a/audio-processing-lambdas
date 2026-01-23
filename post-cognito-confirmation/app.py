from __future__ import print_function
import json
import os
from typing import Optional, Dict, Any

import requests
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from pprint import pprint

# --- Global Variables ---
APPSYNC_API_URL = os.environ.get('APPSYNC_API_URL')
APPSYNC_API_KEY = os.environ.get('APPSYNC_API_KEY')

# --- AppSync Helper Function ---
def execute_graphql_request(query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Executes a GraphQL query/mutation against the AppSync endpoint."""
    if not APPSYNC_API_URL or not APPSYNC_API_KEY:
        raise ValueError("APPSYNC_API_URL and APPSYNC_API_KEY environment variables must be set.")

    headers = {
        'Content-Type': 'application/json',
        'x-api-key': APPSYNC_API_KEY
    }
    payload = {"query": query, "variables": variables or {}}

    try:
        print(f"Executing AppSync request with payload: {json.dumps(payload)}")
        response = requests.post(APPSYNC_API_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        response_json = response.json()
        print(f"Received AppSync response: {json.dumps(response_json)}")
        if "errors" in response_json and response_json["errors"]:
            print(f"[ERROR] GraphQL errors: {response_json['errors']}")
        return response_json
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Error making AppSync request: {e}")
        return {"errors": [{"message": str(e)}]}

# --- AppSync Data Access Helpers ---
def get_system_setting(setting_key: str):
    """Fetches a system setting by its key."""
    query = """
    query GetSystemSettingByKey($settingKey: String!, $filter: ModelSystemSettingsFilterInput) {
      getSystemSettingByKey(settingKey: $settingKey, filter: $filter) {
        items {
          id
          settingKey
          settingValue
          isActive
          _version
        }
      }
    }
    """
    variables = {"settingKey": setting_key, "filter": {"isActive": {"eq": True}}}
    response = execute_graphql_request(query, variables)
    items = response.get("data", {}).get("getSystemSettingByKey", {}).get("items", [])
    return items[0] if items else None

def get_user_transactions(user_transactions_id: str):
    """Fetches a user's transaction record to get their balance."""
    query = """
    query GetUserTransactions($id: ID!) {
      getUserTransactions(id: $id) {
        id
        creditBalance
        _version
      }
    }
    """
    variables = {"id": user_transactions_id}
    response = execute_graphql_request(query, variables)
    return response.get("data", {}).get("getUserTransactions")

def create_user_transactions(user_id: str, email: str, initial_balance: float, username: str):
    """Creates a new user transactions record with initial credit balance."""
    mutation = """
    mutation CreateUserTransactions($input: CreateUserTransactionsInput!) {
      createUserTransactions(input: $input) {
        id
        email
        creditBalance
        username
        _version
      }
    }
    """
    variables = {"input": {"id": user_id, "email": email, "creditBalance": initial_balance, "username": username}}
    return execute_graphql_request(mutation, variables)

# --- Credit Initialization ---
def initialize_user_credits(event):
    """Initialize credits for a new user."""
    user_name = event.get('userName')
    user_attributes = event.get('request', {}).get('userAttributes', {})
    email = user_attributes.get('email')
    user_id = user_attributes.get('sub')

    if not user_id:
        print("sub (user ID) is missing from the Cognito event user attributes.")
        return

    if not email:
        print("email is missing from the Cognito event user attributes.")
        return

    print(f"Processing credits for user: {user_name} (ID: {user_id}), email: {email}")

    starting_credits_setting = get_system_setting("STARTING_CREDITS")
    if not starting_credits_setting:
        print("STARTING_CREDITS setting not found or is not active.")
        return

    try:
        initial_credits = int(starting_credits_setting.get('settingValue'))
    except (ValueError, TypeError):
        print("Invalid value for STARTING_CREDITS setting.")
        return

    # Check if UserTransactions record already exists (idempotency check)
    existing_user_tx = get_user_transactions(user_id)

    if existing_user_tx:
        print(f"User transaction record already exists for ID: {user_id}. Skipping creation.")
        return

    # Create new UserTransactions record with initial credits
    print(f"Creating new UserTransactions record with {initial_credits} credits...")
    create_response = create_user_transactions(user_id, email, initial_credits, user_name)
    if "errors" in create_response and create_response["errors"]:
        print(f"Failed to create user transactions record: {create_response['errors']}")
        return

    print("Credits initialized successfully.")

# --- Brevo Contact Creation ---
def create_brevo_contact(email, username):
    """Create a contact in Brevo."""
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key['api-key'] = os.environ['BREVO_API_KEY']

    api_instance = sib_api_v3_sdk.ContactsApi(sib_api_v3_sdk.ApiClient(configuration))
    create_contact = sib_api_v3_sdk.CreateContact(
        email=email,
        attributes={"USERNAME": username},
        list_ids=[16],
        update_enabled=False
    )

    try:
        api_response = api_instance.create_contact(create_contact)
        pprint(api_response)
    except ApiException as e:
        print("Exception when calling ContactsApi->create_contact: %s\n" % e)

# --- Main Lambda Handler ---
def handler(event, context):
    print(event)

    trigger_source = event.get('triggerSource')
    if trigger_source != 'PostConfirmation_ConfirmSignUp':
        print(f"Ignoring trigger source: {trigger_source}")
        return event

    user_attributes = event['request']['userAttributes']
    email = user_attributes.get('email')
    username = event['userName']

    if not email:
        print("Email not found in user attributes")
        return event

    # Initialize credits for the new user
    try:
        initialize_user_credits(event)
    except Exception as e:
        print(f"Failed to initialize credits: {e}")

    # Create Brevo contact
    try:
        create_brevo_contact(email, username)
    except Exception as e:
        print(f"Failed to create Brevo contact: {e}")

    return event
