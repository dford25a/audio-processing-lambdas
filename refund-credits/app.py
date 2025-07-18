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

def create_refund_transaction(user_transactions_id: str, session_id: str, credits_refunded: float):
    """Creates a transaction record for the credits refunded."""
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
            "quantity": credits_refunded,  # Positive value for refunding
            "amount": 0,
            "type": "PURCHASE",
            "status": "COMPLETED",
            "stripePaymentIntentId": f"refund_session_{session_id}",
            "description": f"Credits refunded for session {session_id}"
        }
    }
    return execute_graphql_request(mutation, variables)

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

def update_session_purchase_status(session_id: str, new_status: str, version: int):
    """Updates the session's purchaseStatus."""
    mutation = """
    mutation UpdateSession($input: UpdateSessionInput!) {
      updateSession(input: $input) {
        id
        purchaseStatus
        _version
      }
    }
    """
    variables = {"input": {"id": session_id, "purchaseStatus": new_status, "_version": version}}
    return execute_graphql_request(mutation, variables)

# --- Main Lambda Handler ---
def lambda_handler(event, context):
    """
    AWS Lambda handler for refunding credits.
    """
    print(f"💰 refund-credits Lambda started. Event: {json.dumps(event)}")
    
    session_id = None
    try:
        # Prefer 'Payload' if present (Step Function passes input here), else fallback to event itself
        if 'Payload' in event:
            body = event['Payload']
        else:
            body = event

        # Try to get values from body, fallback to event (top-level) if missing
        session_id = body.get('sessionId') or event.get('sessionId')
        credits_to_refund = body.get('creditsToRefund') or event.get('creditsToRefund')
        user_transactions_id = body.get('userTransactionsTransactionsId') or event.get('userTransactionsTransactionsId')

        if not user_transactions_id:
            print("[ERROR] userTransactionsTransactionsId is missing from the request.")
            return {'statusCode': 400, 'body': json.dumps({'error': 'Missing userTransactionsTransactionsId in request'})}

        if not session_id or not isinstance(credits_to_refund, (int, float)) or credits_to_refund <= 0:
            print(f"[ERROR] Invalid input: sessionId={session_id}, creditsToRefund={credits_to_refund}")
            return {'statusCode': 400, 'body': json.dumps({'error': 'sessionId and a positive numeric creditsToRefund value are required.'})}

        print(f"📊 Refund request details: UserTransactionsID={user_transactions_id}, Session={session_id}, Credits={credits_to_refund}")

        user_tx = get_user_transactions(user_transactions_id)
        if not user_tx:
            raise Exception("User transaction record not found.")
        
        current_balance = user_tx.get('creditBalance', 0)
        new_balance = current_balance + credits_to_refund

        print(f"💾 Updating user balance from {current_balance} to {new_balance}...")
        update_user_tx_response = update_user_transactions(user_transactions_id, new_balance, user_tx['_version'])
        if "errors" in update_user_tx_response and update_user_tx_response["errors"]:
            raise Exception(f"Failed to update user balance: {update_user_tx_response['errors']}")

        print(f"📋 Creating refund transaction record...")
        create_tx_response = create_refund_transaction(user_transactions_id, session_id, credits_to_refund)
        if "errors" in create_tx_response and create_tx_response["errors"]:
            raise Exception(f"Failed to create refund transaction record: {create_tx_response['errors']}")

        # Update session purchaseStatus to REFUNDED
        print(f"🔄 Updating session {session_id} purchaseStatus to REFUNDED...")
        session_info = get_session(session_id)
        if not session_info:
            raise Exception("Session record not found for updating purchaseStatus.")
        update_session_response = update_session_purchase_status(session_id, "REFUNDED", session_info["_version"])
        if "errors" in update_session_response and update_session_response["errors"]:
            raise Exception(f"Failed to update session purchaseStatus: {update_session_response['errors']}")

        success_response = {
            "success": True,
            "error": None,
            "sessionId": session_id,
            "creditsRefunded": credits_to_refund,
            "newBalance": new_balance,
        }
        print(f"✅ refund-credits completed successfully: {json.dumps(success_response)}")
        return {'statusCode': 200, 'body': json.dumps(success_response)}

    except Exception as e:
        import traceback
        print(f"❌ refund-credits failed: {e}\n{traceback.format_exc()}")
        error_body = {
            "success": False,
            "error": str(e),
            "sessionId": session_id,
        }
        return {'statusCode': 500, 'body': json.dumps(error_body)}
