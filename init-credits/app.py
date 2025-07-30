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

def update_user_transactions(user_transactions_id: str, new_balance: float, version: int):
    """Updates a user's credit balance."""
    mutation = """
    mutation UpdateUserTransactions($input: UpdateUserTransactionsInput!) {
      updateUserTransactions(input: $input) {
        id
        creditBalance
        _version
      }
    }
    """
    variables = {"input": {"id": user_transactions_id, "creditBalance": new_balance, "_version": version}}
    return execute_graphql_request(mutation, variables)

# --- Main Lambda Handler ---
def lambda_handler(event, context):
    """
    AWS Lambda handler for adding credits, invoked by a DynamoDB stream.
    """
    print(f"💰 init-credits Lambda started. Event: {json.dumps(event)}")

    try:
        starting_credits_setting = get_system_setting("STARTING_CREDITS")
        if not starting_credits_setting:
            raise Exception("STARTING_CREDITS setting not found or is not active.")
        
        try:
            credits_to_add = int(starting_credits_setting.get('settingValue'))
        except (ValueError, TypeError):
             raise Exception("Invalid value for STARTING_CREDITS setting.")

        for record in event['Records']:
            if record['eventName'] == 'INSERT':
                new_image = record['dynamodb']['NewImage']
                user_transactions_id = new_image.get('id', {}).get('S')
                
                if not user_transactions_id:
                    print("[ERROR] userTransactionsTransactionsId is missing from the DynamoDB record.")
                    continue

                print(f"Processing transaction for UserTransactionsID: {user_transactions_id}")

                user_tx = get_user_transactions(user_transactions_id)
                if not user_tx:
                    raise Exception(f"User transaction record not found for ID: {user_transactions_id}")

                current_balance = user_tx.get('creditBalance', 0)
                new_balance = current_balance + credits_to_add

                print(f"💾 Updating user balance from {current_balance} to {new_balance}...")
                update_user_tx_response = update_user_transactions(user_transactions_id, new_balance, user_tx['_version'])
                if "errors" in update_user_tx_response and update_user_tx_response["errors"]:
                    raise Exception(f"Failed to update user balance: {update_user_tx_response['errors']}")

        print("✅ init-credits completed successfully.")
        return {'statusCode': 200, 'body': json.dumps('Successfully processed records.')}

    except Exception as e:
        import traceback
        print(f"❌ init-credits failed: {e}\n{traceback.format_exc()}")
        # For DynamoDB streams, re-raising the exception is often the best way
        # to handle failures, as it allows AWS to retry the batch.
        raise e
