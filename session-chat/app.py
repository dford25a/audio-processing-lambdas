# --- Standard Library Imports ---
import json
import os
import traceback
from typing import List, Optional, Dict, Any

# --- Third-party Library Imports ---
import requests # For making HTTP requests to AppSync
import boto3
from openai import OpenAI
# Pydantic is not strictly needed here unless we add complex response validation from AppSync/OpenAI

# --- CONFIGURATION ---
# Read from environment variables set by Terraform
OPENAI_API_KEY_FROM_ENV = os.environ.get('OPENAI_API_KEY')
APPSYNC_API_URL = os.environ.get('APPSYNC_API_URL') # For AppSync
APPSYNC_API_KEY_FROM_ENV = os.environ.get('APPSYNC_API_KEY') # For AppSync
S3_BUCKET_NAME = os.environ.get('BUCKET_NAME')
# This is the prefix where the summary transcript (JSON) is stored by the other lambda
S3_TRANSCRIPT_FULL_PREFIX = os.environ.get('S3_SOURCE_TRANSCRIPT_PREFIX', 'public/transcripts/full')
S3_TRANSCRIPT_SUMMARY_PREFIX = os.environ.get('S3_SOURCE_TRANSCRIPT_PREFIX', 'public/transcripts/summary')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-2') # Default region if not set

# --- VALIDATE ESSENTIAL CONFIGURATION ---
if not OPENAI_API_KEY_FROM_ENV:
    raise ValueError("Environment variable OPENAI_API_KEY not set!")
if not APPSYNC_API_URL:
    raise ValueError("Environment variable APPSYNC_API_URL not set!")
if not APPSYNC_API_KEY_FROM_ENV:
    raise ValueError("Environment variable APPSYNC_API_KEY not set!")
if not S3_BUCKET_NAME:
    raise ValueError("Environment variable BUCKET_NAME not set!")
if not S3_TRANSCRIPT_SUMMARY_PREFIX:
    print(f"Warning: Environment variable S3_SOURCE_TRANSCRIPT_PREFIX not explicitly set. Using default: '{S3_TRANSCRIPT_SUMMARY_PREFIX}'")


# --- AWS & OPENAI CLIENTS ---
# Initialize outside the handler for better performance
s3_client = boto3.client('s3', region_name=AWS_REGION)
openai_client = OpenAI(api_key=OPENAI_API_KEY_FROM_ENV)


# --- GraphQL Queries (similar to lambda_fix_01) ---
# Query to get session details including TLDR and campaign ID
GET_SESSION_DETAILS_QUERY = """
query GetSession($id: ID!) {
  getSession(id: $id) {
    id
    tldr
    campaign {
      id
    }
    # Add _version if optimistic concurrency is needed for any updates from this lambda (not currently the case)
  }
}
"""

# Query to list all segments associated with a session
LIST_SESSION_SEGMENTS_QUERY = """
query ListSegmentsBySession($sessionSegmentsId: ID!, $limit: Int, $nextToken: String) {
  listSegments(filter: {sessionSegmentsId: {eq: $sessionSegmentsId}}, limit: $limit, nextToken: $nextToken) {
    items {
      id
      title
      description
      # _version if needed
    }
    nextToken
  }
}
"""

# --- AppSync Helper Function (similar to lambda_fix_01) ---
def execute_graphql_request(query: str, variables: Optional[Dict[str, Any]] = None, debug: bool = True) -> Dict[str, Any]:
    headers = {
        'Content-Type': 'application/json',
        'x-api-key': APPSYNC_API_KEY_FROM_ENV
    }
    payload = {"query": query, "variables": variables or {}}

    if debug: print(f"Executing GraphQL. URL: {APPSYNC_API_URL}, Query: {query[:150].replace(os.linesep, ' ')}..., Variables: {json.dumps(variables)}")

    try:
        response = requests.post(APPSYNC_API_URL, headers=headers, json=payload, timeout=90)
        response.raise_for_status()
        response_json = response.json()
        if "errors" in response_json:
            if debug: print(f"GraphQL Error: {json.dumps(response_json['errors'], indent=2)}")
        return response_json
    except requests.exceptions.JSONDecodeError as e:
        response_text = response.text if 'response' in locals() and hasattr(response, 'text') else 'Response object or text not available'
        if debug: print(f"JSONDecodeError making AppSync request: {e}. Response text: {response_text}")
        return {"errors": [{"message": f"JSONDecodeError: {e}. Response was not valid JSON."}]}
    except requests.exceptions.RequestException as e:
        if debug: print(f"Error making AppSync request: {e}")
        return {"errors": [{"message": f"RequestException: {e}"}]}
    except Exception as e:
        if debug: print(f"Unexpected error in execute_graphql_request: {e}"); traceback.print_exc()
        return {"errors": [{"message": f"Unexpected error: {e}"}]}

# --- OpenAI Helper ---
def get_openai_response(prompt: str, messages: List[Dict[str, str]], debug: bool = True) -> str:
    """ Calls OpenAI's API and gets the full completion response. """
    if debug: print(f"Sending prompt to OpenAI. System Prompt Length: {len(prompt)}, Messages Count: {len(messages)}")
    try:
        # The 'messages' parameter to client.chat.completions.create expects a list of message objects.
        # The first one is the system prompt, followed by the user/assistant messages.
        full_messages = [{"role": "system", "content": prompt}] + messages
        
        completion = openai_client.chat.completions.create(
            model="gpt-5-mini", # Consider making model configurable via env var too
            messages=full_messages,
            stream=False # Not using streaming for this chat response
        )
        if completion.choices and completion.choices[0].message and completion.choices[0].message.content:
            response_content = completion.choices[0].message.content
            if debug: print(f"OpenAI response content (first 300 chars): {response_content[:300]}...")
            return response_content
        else:
            if debug: print("OpenAI response lacked content or choices.")
            return "I'm sorry, I couldn't generate a response at this time."
    except Exception as e:
        if debug: print(f"Error calling OpenAI: {e}"); traceback.print_exc()
        return "There was an error communicating with the AI. Please try again."


def lambda_handler(event, context):
    """ AWS Lambda Handler for retrieving OpenAI responses using AppSync for context. """
    debug = True # Enable verbose logging
    if debug: print(f"Received event: {json.dumps(event)}")
    if debug: print(f"Using AppSync URL: {APPSYNC_API_URL}")
    if debug: print(f"Using S3 bucket: {S3_BUCKET_NAME}")
    if debug: print(f"Using S3 transcript summary prefix: {S3_TRANSCRIPT_SUMMARY_PREFIX}")

    try:
        if not event.get('body'):
            return {'statusCode': 400, 'body': json.dumps({'error': 'Missing request body'})}
        
        body = json.loads(event['body'])
        session_id = body.get('sessionId')
        # campaign_id_from_body = body.get('campaignId') # This might be redundant if fetched via AppSync Session
        user_chat_messages = body.get('messages') # This should be a list of message objects

        if not session_id or not user_chat_messages:
            error_msg = 'Missing required fields in body: sessionId or messages'
            if debug: print(error_msg)
            return {
                'statusCode': 400,
                'headers': {'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token', 'Access-Control-Allow-Methods': 'POST,OPTIONS'},
                'body': json.dumps({'error': error_msg})
            }
        if not isinstance(user_chat_messages, list):
            error_msg = "'messages' field must be a list of message objects."
            if debug: print(error_msg)
            return {
                'statusCode': 400,
                'headers': {'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token', 'Access-Control-Allow-Methods': 'POST,OPTIONS'},
                'body': json.dumps({'error': error_msg})
            }

        # 1. Fetch Session Details (TLDR and Campaign ID) from AppSync
        if debug: print(f"Fetching session details for ID: {session_id}")
        session_details_response = execute_graphql_request(GET_SESSION_DETAILS_QUERY, {"id": session_id}, debug=debug)
        
        session_data = session_details_response.get("data", {}).get("getSession")
        if not session_data:
            error_msg = f"Failed to fetch session details for {session_id}. AppSync Errors: {session_details_response.get('errors')}"
            if debug: print(error_msg)
            return {'statusCode': 404, 'headers': {'Access-Control-Allow-Origin': '*'}, 'body': json.dumps({'error': error_msg})}

        session_tldr_list = session_data.get("tldr", [])
        session_tldr = session_tldr_list[0] if session_tldr_list and isinstance(session_tldr_list, list) else (session_tldr_list if isinstance(session_tldr_list, str) else "No TLDR available.")
        
        campaign_info = session_data.get("campaign")
        if not campaign_info or not campaign_info.get("id"):
            error_msg = f"Campaign ID not found in session data for {session_id}."
            if debug: print(error_msg)
            # Decide if this is critical. If S3 transcript is essential, then it is.
            return {'statusCode': 500, 'headers': {'Access-Control-Allow-Origin': '*'}, 'body': json.dumps({'error': error_msg})}
        campaign_id = campaign_info["id"]
        if debug: print(f"Session TLDR: {session_tldr[:100]}..., Campaign ID: {campaign_id}")

        # 2. Fetch Session Segments from AppSync
        if debug: print(f"Fetching segments for session ID: {session_id}")
        all_segments_content = []
        next_token = None
        page_count = 0
        MAX_PAGES = 10 # Safety break for pagination

        while page_count < MAX_PAGES:
            page_count += 1
            segments_response = execute_graphql_request(
                LIST_SESSION_SEGMENTS_QUERY,
                {"sessionSegmentsId": session_id, "limit": 100, "nextToken": next_token},
                debug=debug
            )
            
            data_field = segments_response.get("data")
            segments_page_data = None
            if data_field:
                segments_page_data = data_field.get("listSegments")

            if not segments_page_data:
                gql_errors = segments_response.get('errors')
                error_msg_segments = f"Failed to fetch segments (page {page_count}) for session {session_id}."
                if gql_errors: error_msg_segments += f" AppSync Errors: {json.dumps(gql_errors)}"
                if debug: print(error_msg_segments)
                # If it's not the first page and we already have some segments, we might proceed.
                # If it's the first page and it fails with errors, it's more critical.
                if not all_segments_content and gql_errors:
                     return {'statusCode': 500, 'headers': {'Access-Control-Allow-Origin': '*'}, 'body': json.dumps({'error': error_msg_segments})}
                break 

            segment_items = segments_page_data.get("items", [])
            for seg_item in segment_items:
                title = seg_item.get("title", "Untitled Segment")
                desc_list = seg_item.get("description", [])
                description = desc_list[0] if desc_list and isinstance(desc_list, list) else (desc_list if isinstance(desc_list, str) else "No description.")
                all_segments_content.append(f"Segment Title: {title}\nSegment Description: {description}")
            
            next_token = segments_page_data.get("nextToken")
            if not next_token:
                break
        
        segments_context_str = "\n\n".join(all_segments_content) if all_segments_content else "No segments available for this session."
        if debug: print(f"Fetched {len(all_segments_content)} segments. Context length: {len(segments_context_str)}")

        # 3. Fetch Original Full Transcript Text from S3
        s3_transcript_text = "No full transcript available from S3."
        transcript_filename = f"campaign{campaign_id}Session{session_id}.txt"
        s3_key = f"{S3_TRANSCRIPT_FULL_PREFIX.rstrip('/')}/{transcript_filename}"
        
        if debug: print(f"Attempting to fetch full transcript from S3: bucket='{S3_BUCKET_NAME}', key='{s3_key}'")
        try:
            s3_object = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=s3_key)
            raw_s3_content = s3_object['Body'].read().decode('utf-8')
            if raw_s3_content.strip():
                s3_transcript_text = raw_s3_content
                if debug: print(f"Full transcript fetched successfully from S3. Length: {len(s3_transcript_text)}")
            else:
                if debug: print(f"Full transcript file from S3 (s3://{S3_BUCKET_NAME}/{s3_key}) is empty.")
        except s3_client.exceptions.NoSuchKey:
            if debug: print(f"Full transcript file not found in S3 at s3://{S3_BUCKET_NAME}/{s3_key}")
            # This might be acceptable, so we proceed with "No full transcript available".
        except Exception as e:
            if debug: print(f"Error fetching/reading full transcript from S3 (s3://{S3_BUCKET_NAME}/{s3_key}): {str(e)}"); traceback.print_exc()
            # Also proceed with default message, but log the error.

        # 4. Construct System Prompt for OpenAI
        system_prompt = f"""You are Scribe, an AI chat assistant for a TTRPG campaign session.
Use the following context to inform your responses:

- **Overall Session TLDR (Too Long; Didn't Read):**
{session_tldr}

- **Detailed Session Segments:**
{segments_context_str}

- **Full Session Transcript (if available):**
<full_transcript>
{s3_transcript_text}
</full_transcript>

Your goal is to be a helpful chat assistant that provides relevant responses, continuing the conversation naturally based on the user's messages and the provided context.
"""

        # 5. Call OpenAI
        if debug: print("Calling OpenAI for chat response...")
        ai_response_content = get_openai_response(system_prompt, user_chat_messages, debug=debug)

        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token',
                'Access-Control-Allow-Methods': 'POST,OPTIONS'
            },
            'body': json.dumps({'message': ai_response_content})
        }

    except json.JSONDecodeError as e: # For errors parsing the initial request body
        if debug: print(f"JSON Decode Error in handler (likely request body): {str(e)}")
        return {'statusCode': 400, 'headers': {'Access-Control-Allow-Origin': '*'}, 'body': json.dumps({'error': f'Invalid JSON in request body: {str(e)}'})}
    except Exception as e:
        if debug: print(f"General unhandled error in lambda_handler: {str(e)}"); traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token',
                'Access-Control-Allow-Methods': 'POST,OPTIONS'
            },
            'body': json.dumps({'error': f'An unexpected internal server error occurred: {str(e)}'})
        }
