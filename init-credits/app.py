# --- Standard Library Imports ---
import json
import os
from typing import Optional, Dict, Any

# --- Third-party Library Imports ---
import requests

# --- Global Variables ---
APPSYNC_API_URL = os.environ.get('APPSYNC_API_URL')
APPSYNC_API_KEY = os.environ.get('APPSYNC_API_KEY')

# --- AppSync Helper Function ---
def execute_graphql_request(query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Executes a GraphQL query/mutation against the AppSync endpoint.
    """
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

def create_user_transactions(user_id: str, email: str, initial_balance: float, owner: str):
    """Creates a new user transactions record with initial credit balance."""
    mutation = """
    mutation CreateUserTransactions($input: CreateUserTransactionsInput!) {
      createUserTransactions(input: $input) {
        id
        email
        creditBalance
        owner
        _version
      }
    }
    """
    variables = {"input": {"id": user_id, "email": email, "creditBalance": initial_balance, "owner": owner}}
    return execute_graphql_request(mutation, variables)

# --- Main Lambda Handler ---
def lambda_handler(event, context):
    """
    AWS Lambda handler for adding credits, invoked by Cognito post-confirmation trigger.
    """
    print(f"💰 init-credits Lambda started. Event: {json.dumps(event)}")

    try:
        # Cognito post-confirmation trigger event structure
        user_pool_id = event.get('userPoolId')
        user_name = event.get('userName')  # This is the user's unique ID
        trigger_source = event.get('triggerSource')
        
        # Extract email and user ID from user attributes
        user_attributes = event.get('request', {}).get('userAttributes', {})
        email = user_attributes.get('email')
        user_id = user_attributes.get('sub')  # The actual UUID for the user
        
        # Only process post-confirmation events
        if trigger_source != 'PostConfirmation_ConfirmSignUp':
            print(f"⚠️ Ignoring trigger source: {trigger_source}")
            return event  # Return the event unchanged for Cognito triggers
        
        if not user_id:
            raise Exception("sub (user ID) is missing from the Cognito event user attributes.")
            
        if not email:
            raise Exception("email is missing from the Cognito event user attributes.")
        
        print(f"Processing post-confirmation for user: {user_name} (ID: {user_id}), email: {email}")

        starting_credits_setting = get_system_setting("STARTING_CREDITS")
        if not starting_credits_setting:
            raise Exception("STARTING_CREDITS setting not found or is not active.")
        
        try:
            initial_credits = int(starting_credits_setting.get('settingValue'))
        except (ValueError, TypeError):
             raise Exception("Invalid value for STARTING_CREDITS setting.")

        # Check if UserTransactions record already exists (idempotency check)
        user_transactions_id = user_id  # Use the actual user UUID, not the username
        existing_user_tx = get_user_transactions(user_transactions_id)
        
        if existing_user_tx:
            print(f"⚠️ User transaction record already exists for ID: {user_transactions_id}. Skipping creation to avoid duplicates.")
            return event

        # Create owner field in format UUID:username
        owner = f"{user_id}:{user_name}"
        
        # Create new UserTransactions record with initial credits
        print(f"💾 Creating new UserTransactions record with {initial_credits} credits...")
        create_response = create_user_transactions(user_transactions_id, email, initial_credits, owner)
        if "errors" in create_response and create_response["errors"]:
            raise Exception(f"Failed to create user transactions record: {create_response['errors']}")

        print("✅ init-credits completed successfully.")
        # For Cognito triggers, always return the event
        return event

    except Exception as e:
        import traceback
        print(f"❌ init-credits failed: {e}\n{traceback.format_exc()}")
        # For Cognito triggers, we should still return the event to not break the user flow
        # The user registration should succeed even if credit initialization fails
        print("⚠️ Returning event despite failure to allow user registration to complete.")
        return event
