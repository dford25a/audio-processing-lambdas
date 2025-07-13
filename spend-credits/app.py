# --- Standard Library Imports ---
import json
import os
from typing import Optional, Dict, Any

# --- Third-party Library Imports ---
import requests

# --- Global Variables ---
# These should be configured as environment variables in your Lambda function settings.
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
        # Check for GraphQL-level errors in the response body
        if "errors" in response_json and response_json["errors"]:
            print(f"[ERROR] GraphQL errors: {response_json['errors']}")
        return response_json
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Error making AppSync request: {e}")
        return {"errors": [{"message": str(e)}]}

# --- AppSync Data Access Helpers (Unchanged) ---

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

def get_session(session_id: str):
    """Fetches a session to get its current version and status."""
    query = """
    query GetSession($id: ID!) {
      getSession(id: $id) {
        id
        purchaseStatus
        _version
      }
    }
    """
    variables = {"id": session_id}
    response = execute_graphql_request(query, variables)
    return response.get("data", {}).get("getSession")

def update_user_transactions(user_transactions_id: str, new_balance: int, version: int):
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

def update_session_status(session_id: str, version: int):
    """Updates the session's purchase status to PURCHASED."""
    mutation = """
    mutation UpdateSession($input: UpdateSessionInput!) {
      updateSession(input: $input) {
        id
        purchaseStatus
        _version
      }
    }
    """
    variables = {"input": {"id": session_id, "purchaseStatus": "PURCHASED", "_version": version}}
    return execute_graphql_request(mutation, variables)

def create_spend_transaction(user_transactions_id: str, session_id: str, credits_spent: int):
    """Creates a transaction record for the credits spent."""
    mutation = """
    mutation CreateTransaction($input: CreateTransactionInput!) {
      createTransaction(input: $input) {
        id
      }
    }
    """
    variables = {
        "input": {
            "userTransactionsTransactionsId": user_transactions_id,
            "quantity": -credits_spent,  # Negative value for spending
            "amount": 0,  # No monetary amount for spending credits
            "type": "SPEND",
            "status": "COMPLETED",
            "stripePaymentIntentId": f"session_{session_id}",
            "description": f"Credits spent for session {session_id}"
        }
    }
    return execute_graphql_request(mutation, variables)

# --- REFACTORED Main Lambda Handler ---
def lambda_handler(event, context):
    """
    AWS Lambda handler for spending credits, invoked via API Gateway.
    """
    print(f"💳 spendCredits Lambda started. Event: {json.dumps(event)}")
    
    # --- Input Validation ---
    session_id = None # Initialize for the final error block
    try:
        body_str = event.get('body')
        if not body_str:
            print("[ERROR] Request body is missing.")
            return {'statusCode': 400, 'body': json.dumps({'error': 'Missing request body'})}

        body = json.loads(body_str)
        session_id = body.get('sessionId')
        credits_to_spend = body.get('creditsToSpend')
        # CORRECTED: Use the specific ID from the UserTransactions table
        user_transactions_id = body.get('userTransactionsTransactionsId') 

        if not user_transactions_id:
            print("[ERROR] userTransactionsTransactionsId is missing from the request body.")
            return {'statusCode': 400, 'body': json.dumps({'error': 'Missing userTransactionsTransactionsId in request body'})}

        if not session_id or not isinstance(credits_to_spend, int) or credits_to_spend <= 0:
            print(f"[ERROR] Invalid input: sessionId={session_id}, creditsToSpend={credits_to_spend}")
            return {'statusCode': 400, 'body': json.dumps({'error': 'sessionId and a positive integer creditsToSpend value are required.'})}

        print(f"📊 Spend request details: UserTransactionsID={user_transactions_id}, Session={session_id}, Credits={credits_to_spend}")

        # --- Get Current State ---
        user_tx = get_user_transactions(user_transactions_id)
        if not user_tx:
            raise Exception("User transaction record not found.")
        
        session = get_session(session_id)
        if not session:
            raise Exception("Session not found.")

        # --- Business Logic ---
        current_balance = user_tx.get('creditBalance', 0)
        print(f"💰 Current balance: {current_balance}, requesting to spend: {credits_to_spend}")

        if current_balance < credits_to_spend:
            response_body = {
                "success": False,
                "error": f"Insufficient credits. You have {current_balance} but need {credits_to_spend}.",
                "sessionId": session_id,
                "creditsSpent": 0,
                "remainingBalance": current_balance,
                "sessionStatus": "INSUFFICIENT_CREDITS",
            }
            # Using status 200 for a handled business logic failure is a common pattern.
            return {'statusCode': 200, 'body': json.dumps(response_body)}

        new_balance = current_balance - credits_to_spend

        # --- Execute Updates ---
        print(f"💾 Updating user balance from {current_balance} to {new_balance}...")
        update_user_tx_response = update_user_transactions(user_transactions_id, new_balance, user_tx['_version'])
        if "errors" in update_user_tx_response and update_user_tx_response["errors"]:
            raise Exception(f"Failed to update user balance: {update_user_tx_response['errors']}")

        if session.get('purchaseStatus') != 'PURCHASED':
            print(f"📝 Updating session {session_id} status to PURCHASED...")
            update_session_response = update_session_status(session_id, session['_version'])
            if "errors" in update_session_response and update_session_response["errors"]:
                raise Exception(f"Failed to update session status: {update_session_response['errors']}")
        else:
            print(f"ℹ️ Session {session_id} was already marked as PURCHASED.")

        print(f"📋 Creating spend transaction record...")
        create_tx_response = create_spend_transaction(user_transactions_id, session_id, credits_to_spend)
        if "errors" in create_tx_response and create_tx_response["errors"]:
            raise Exception(f"Failed to create spend transaction record: {create_tx_response['errors']}")

        # --- Success Response ---
        success_response = {
            "success": True,
            "error": None,
            "sessionId": session_id,
            "creditsSpent": credits_to_spend,
            "remainingBalance": new_balance,
            "sessionStatus": "PURCHASED",
        }
        print(f"✅ spendCredits completed successfully: {json.dumps(success_response)}")
        return {'statusCode': 200, 'body': json.dumps(success_response)}

    except Exception as e:
        import traceback
        print(f"❌ spendCredits failed: {e}\n{traceback.format_exc()}")
        error_body = {
            "success": False,
            "error": str(e),
            "sessionId": session_id,
            "creditsSpent": 0,
            "remainingBalance": 0, # Cannot determine balance if an error occurred
            "sessionStatus": "ERROR",
        }
        return {'statusCode': 500, 'body': json.dumps(error_body)}
