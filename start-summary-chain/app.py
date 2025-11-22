# --- Standard Library Imports ---
import json
import boto3
import time
import os
import re
from typing import Optional, Dict, Any

# --- Third-party Library Imports ---
import requests

# --- AppSync Helper Function ---
def execute_graphql_request(query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Executes a GraphQL query/mutation against the AppSync endpoint using API Key authentication.
    """
    appsync_api_url = os.environ.get('APPSYNC_API_URL')
    appsync_api_key = os.environ.get('APPSYNC_API_KEY')

    if not appsync_api_url or not appsync_api_key:
        raise ValueError("APPSYNC_API_URL and APPSYNC_API_KEY environment variables must be set.")

    headers = {
        'Content-Type': 'application/json',
        'x-api-key': appsync_api_key
    }
    payload = {"query": query, "variables": variables or {}}

    try:
        response = requests.post(appsync_api_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error making AppSync request: {e}")
        return {"errors": [{"message": str(e)}]}

# --- Session ID Parsing Helper ---
def parse_session_id_from_stem(filename_stem: str) -> Optional[str]:
    """
    Parses the Session UUID from a filename stem.
    """
    match = re.search(r"Session([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})", filename_stem)
    return match.group(1) if match else None

# --- Session Status Update Helper ---
def update_session_status(session_id: str, version: int, status: str) -> bool:
    """
    Updates the session's transcription status in AppSync.
    """
    mutation = """
    mutation UpdateSession($input: UpdateSessionInput!) {
      updateSession(input: $input) {
        id
        _version
        transcriptionStatus
      }
    }
    """
    variables = {
        "input": {
            "id": session_id,
            "_version": version,
            "transcriptionStatus": status
        }
    }
    response = execute_graphql_request(mutation, variables)
    if response.get("errors"):
        print(f"Failed to update session status for {session_id}: {response['errors']}")
        return False
    print(f"Successfully updated session {session_id} to status {status}.")
    return True


def lambda_handler(event, context):
    """
    AWS Lambda function to save user-specified fields to an S3 bucket as JSON
    and invoke the Step Function to start the processing chain.
    """
    try:
        # Get environment variables
        bucket = os.environ.get('BUCKET_NAME')
        state_machine_arn = os.environ.get('STATE_MACHINE_ARN')

        if not bucket or not state_machine_arn:
            error_message = "BUCKET_NAME and STATE_MACHINE_ARN environment variables must be set."
            print(f"[ERROR] {error_message}")
            return format_response(500, {"error": error_message})

        # Parse payload
        if event.get('httpMethod') == 'POST' and event.get('body'):
            payload = json.loads(event.get('body', '{}'))
        else:
            payload = event
        
        user_specified_fields = payload.get("user_specified_fields")
        audio_filename = payload.get("audio_filename")

        if not all([user_specified_fields, audio_filename]):
            error_message = "Parameters 'user_specified_fields' and 'audio_filename' are required."
            print(f"[ERROR] {error_message}")
            return format_response(400, {"error": error_message})

        # Save metadata to S3
        s3_client = boto3.client("s3")
        audio_filename_stem = os.path.splitext(audio_filename)[0]
        metadata_s3_key = f"public/session-metadata/{audio_filename_stem}.metadata.json"
        s3_client.put_object(
            Bucket=bucket,
            Key=metadata_s3_key,
            Body=json.dumps(user_specified_fields),
            ContentType="application/json"
        )
        print(f"Metadata saved to S3 at s3://{bucket}/{metadata_s3_key}")

        # Wait for audio file upload to complete
        audio_file_key = f"public/audioUploads/{audio_filename}"
        retries = 10
        wait_time = 10
        for attempt in range(retries):
            try:
                s3_client.head_object(Bucket=bucket, Key=audio_file_key)
                print(f"Audio file '{audio_file_key}' found. Proceeding.")
                break
            except s3_client.exceptions.ClientError as e:
                if e.response['Error']['Code'] == '404':
                    print(f"Audio file not found yet. Retry {attempt + 1}/{retries}...")
                    time.sleep(wait_time)
                else:
                    raise
        else:
            error_message = f"Audio file '{audio_file_key}' not found after {retries} retries."
            print(f"[ERROR] {error_message}")
            return format_response(408, {"error": error_message})

        # --- Validate purchaseStatus before invoking Step Function ---
        session_id = parse_session_id_from_stem(audio_filename_stem)
        if not session_id:
            error_message = f"Could not parse session ID from '{audio_filename_stem}'."
            print(f"[ERROR] {error_message}")
            return format_response(400, {"error": error_message})
        
        # Fetch the current session data including purchaseStatus and version
        get_session_query = """
        query GetSession($id: ID!) {
          getSession(id: $id) {
            _version
            purchaseStatus
          }
        }
        """
        session_data_response = execute_graphql_request(get_session_query, {"id": session_id})
        current_session = session_data_response.get("data", {}).get("getSession")

        if not current_session or "_version" not in current_session:
            error_message = f"Could not fetch session data for session {session_id}."
            print(f"[ERROR] {error_message}")
            return format_response(404, {"error": error_message})
        
        # Validate purchaseStatus
        purchase_status = current_session.get("purchaseStatus")
        if purchase_status != "PURCHASED":
            error_message = f"Session {session_id} has invalid purchaseStatus: '{purchase_status}'. Expected 'PURCHASED'."
            print(f"[ERROR] {error_message}")
            return format_response(403, {"error": error_message})
        
        print(f"Session {session_id} purchaseStatus validated: {purchase_status}")
        session_version = current_session["_version"]

        # Invoke Step Function
        sfn_client = boto3.client('stepfunctions')
        sfn_payload = {
            "bucket": bucket, 
            "audio_filename": audio_file_key,
            "userTransactionsTransactionsId": payload.get("userTransactionsTransactionsId"),
            "sessionId": payload.get("sessionId"),
            "creditsToRefund": payload.get("creditsToSpend")
        }
        response = sfn_client.start_execution(
            stateMachineArn=state_machine_arn,
            input=json.dumps(sfn_payload)
        )

        # --- Update session status to QUEUED ---
        if not update_session_status(session_id, session_version, "QUEUED"):
            # Log error but don't fail the entire operation.
            print(f"Warning: Failed to update session status for {session_id}, but processing was initiated.")
        
        success_message = f"Step Function successfully invoked for '{audio_filename}'."
        return format_response(200, {"message": success_message, "executionArn": response['executionArn']})


    except Exception as e:
        error_message = f"Error in Lambda function: {str(e)}"
        import traceback
        print(f"[ERROR] {error_message}\n{traceback.format_exc()}")
        return format_response(500, {"error": error_message})

def format_response(status_code, body):
    """
    Formats the response for API Gateway.
    """
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "OPTIONS,POST"
        },
        "body": json.dumps(body)
    }
