# --- Standard Library Imports ---
import json
import os
import hashlib
from typing import Optional, Dict, Any

# --- Third-party Library Imports ---
import requests
# It's assumed that the 'stripe' library is included in a Lambda Layer.
import stripe

# --- Global Variables ---
# These are now populated directly from Lambda environment variables set by Terraform.
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET')
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
        if "errors" in response_json:
            print(f"[ERROR] GraphQL errors: {response_json['errors']}")
        return response_json
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Error making AppSync request: {e}")
        return {"errors": [{"message": str(e)}]}

# --- AppSync Mutation Helpers ---
def get_pending_transaction(transaction_id: str):
    """Fetches a pending transaction by its ID."""
    query = """
    query GetPendingTransaction($id: ID!) {
      getPendingTransaction(id: $id) {
        id
        userId
        status
        totalTokens
        _version
      }
    }
    """
    variables = {"id": transaction_id}
    response = execute_graphql_request(query, variables)
    return response.get("data", {}).get("getPendingTransaction")

def update_pending_transaction(transaction_id: str, version: int, status: str, error_message: Optional[str] = None):
    """Updates the status of a pending transaction."""
    mutation = """
    mutation UpdatePendingTransaction($input: UpdatePendingTransactionInput!) {
      updatePendingTransaction(input: $input) {
        id
        status
        _version
      }
    }
    """
    input_data = {
        "id": transaction_id,
        "status": status,
        "_version": version
    }
    if error_message:
        input_data["errorMessage"] = error_message
        
    variables = {"input": input_data}
    return execute_graphql_request(mutation, variables)

def get_user_transactions(user_id: str):
    """Fetches a user's transaction record."""
    query = """
    query GetUserTransactions($id: ID!) {
      getUserTransactions(id: $id) {
        id
        creditBalance
        _version
      }
    }
    """
    variables = {"id": user_id}
    response = execute_graphql_request(query, variables)
    return response.get("data", {}).get("getUserTransactions")

def create_user_transactions(user_id: str, email: str):
    """Creates a new user transaction record."""
    mutation = """
    mutation CreateUserTransactions($input: CreateUserTransactionsInput!) {
      createUserTransactions(input: $input) {
        id
        creditBalance
        _version
      }
    }
    """
    variables = {"input": {"id": user_id, "email": email, "creditBalance": 0}}
    response = execute_graphql_request(mutation, variables)
    return response.get("data", {}).get("createUserTransactions")

def update_user_transactions(user_id: str, new_balance: int, version: int):
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
    variables = {"input": {"id": user_id, "creditBalance": new_balance, "_version": version}}
    return execute_graphql_request(mutation, variables)

def create_transaction_record(user_id: str, tokens: int, amount: float, payment_intent: str, session_id: str, description: str):
    """Creates a new transaction record for the purchase."""
    mutation = """
    mutation CreateTransaction($input: CreateTransactionInput!) {
      createTransaction(input: $input) {
        id
      }
    }
    """
    variables = {
        "input": {
            "userTransactionsTransactionsId": user_id,
            "quantity": tokens,
            "amount": amount,
            "type": "PURCHASE",
            "status": "COMPLETED",
            "stripePaymentIntentId": payment_intent,
            "stripeSessionId": session_id,
            "description": description
        }
    }
    return execute_graphql_request(mutation, variables)


# --- Event Handlers ---
def handle_checkout_completed(session: Dict[str, Any]):
    """Processes a completed Stripe checkout session."""
    print(f"🛒 Processing completed checkout session: {session['id']}")
    metadata = session.get('metadata', {})
    purchase_id = metadata.get('purchaseId')
    user_id = metadata.get('userId')
    
    if not purchase_id or not user_id:
        print(f"[ERROR] Missing 'purchaseId' or 'userId' in session metadata for session {session['id']}")
        return

    try:
        # 1. Get the pending transaction
        pending_tx = get_pending_transaction(purchase_id)
        if not pending_tx:
            print(f"[ERROR] Pending transaction not found: {purchase_id}")
            return
        if pending_tx['status'] != 'PENDING':
            print(f"ℹ️ Transaction {purchase_id} already processed with status: {pending_tx['status']}")
            return

        # 2. Get or create user transaction record
        user_tx = get_user_transactions(user_id)
        if not user_tx:
            print(f"User transaction record not found for {user_id}. Creating one.")
            email = session.get('customer_details', {}).get('email', 'unknown@email.com')
            user_tx = create_user_transactions(user_id, email)
            if not user_tx:
                raise Exception(f"Failed to create user transaction record for user {user_id}")

        # 3. Update credit balance
        tokens_to_add = int(pending_tx.get('totalTokens', 0))
        new_balance = user_tx.get('creditBalance', 0) + tokens_to_add
        update_user_tx_response = update_user_transactions(user_id, new_balance, user_tx['_version'])
        if "errors" in update_user_tx_response:
                raise Exception(f"Failed to update user credit balance for {user_id}: {update_user_tx_response['errors']}")

        # 4. Create a detailed transaction record
        create_tx_response = create_transaction_record(
            user_id=user_id,
            tokens=tokens_to_add,
            amount=session.get('amount_total', 0) / 100.0,
            payment_intent=session.get('payment_intent'),
            session_id=session.get('id'),
            description=f"Credit purchase: {tokens_to_add} tokens"
        )
        if "errors" in create_tx_response:
            raise Exception(f"Failed to create transaction record for {purchase_id}: {create_tx_response['errors']}")

        # 5. Mark pending transaction as COMPLETED
        update_pending_tx_response = update_pending_transaction(purchase_id, pending_tx['_version'], 'COMPLETED')
        if "errors" in update_pending_tx_response:
                raise Exception(f"Failed to update pending transaction {purchase_id} to COMPLETED: {update_pending_tx_response['errors']}")

        print(f"✅ Checkout session processed successfully for purchase {purchase_id}")

    except Exception as e:
        print(f"[ERROR] Failed to process checkout completion for {purchase_id}: {e}")
        # Attempt to mark the transaction as FAILED
        pending_tx = get_pending_transaction(purchase_id)
        if pending_tx:
            update_pending_transaction(purchase_id, pending_tx['_version'], 'FAILED', str(e))


def handle_checkout_expired(session: Dict[str, Any]):
    """Processes an expired Stripe checkout session."""
    print(f"⏰ Processing expired checkout session: {session['id']}")
    metadata = session.get('metadata', {})
    purchase_id = metadata.get('purchaseId')

    if not purchase_id:
        print(f"[ERROR] Missing 'purchaseId' in session metadata for expired session {session['id']}")
        return

    try:
        pending_tx = get_pending_transaction(purchase_id)
        if not pending_tx:
            print(f"[ERROR] Pending transaction not found for expired session: {purchase_id}")
            return
        if pending_tx['status'] == 'PENDING':
            update_pending_transaction(purchase_id, pending_tx['_version'], 'EXPIRED', 'Checkout session expired')
            print(f"✅ Marked transaction {purchase_id} as EXPIRED.")
        else:
            print(f"ℹ️ Transaction {purchase_id} was already in a non-pending state: {pending_tx['status']}")

    except Exception as e:
        print(f"[ERROR] Failed to process checkout expiration for {purchase_id}: {e}")


# --- Main Lambda Handler ---
def lambda_handler(event, context):
    """
    AWS Lambda handler for Stripe webhooks.
    """
    print("🔔 Stripe webhook received")
    try:
        # CHANGE: Set the stripe API key directly at the beginning of the handler.
        # This ensures it's set for every invocation.
        stripe.api_key = STRIPE_SECRET_KEY
        
        # UPDATED: Case-insensitive header retrieval
        headers = {k.lower(): v for k, v in event.get('headers', {}).items()}
        stripe_signature = headers.get('stripe-signature')
        
        body = event['body']

        if not stripe_signature:
            print("[ERROR] Missing 'stripe-signature' header. Headers received:", json.dumps(headers))
            return {'statusCode': 400, 'body': json.dumps({'error': 'Missing stripe-signature header'})}

        # Verify webhook signature
        try:
            stripe_event = stripe.Webhook.construct_event(
                payload=body, sig_header=stripe_signature, secret=STRIPE_WEBHOOK_SECRET
            )
        except stripe.error.SignatureVerificationError as e:
            print(f"⚠️ Webhook signature verification failed: {e}")
            return {'statusCode': 400, 'body': json.dumps({'error': 'Webhook signature verification failed'})}

        print(f"✅ Webhook verified. Event type: {stripe_event.type}")
        
        # Route event to the appropriate handler
        if stripe_event.type == 'checkout.session.completed':
            handle_checkout_completed(stripe_event.data.object)
        elif stripe_event.type == 'checkout.session.expired':
            handle_checkout_expired(stripe_event.data.object)
        else:
            print(f"🤷‍♀️ Unhandled event type: {stripe_event.type}")

        return {'statusCode': 200, 'body': json.dumps({'received': True})}

    except Exception as e:
        import traceback
        print(f"[ERROR] Unhandled exception in webhook handler: {e}\n{traceback.format_exc()}")
        return {'statusCode': 500, 'body': json.dumps({'error': 'Internal server error'})}
