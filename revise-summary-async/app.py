# --- Standard Library Imports ---
import os
import json
from typing import List, Optional, Dict, Any
import traceback

# --- Third-party Library Imports ---
import requests # For making HTTP requests to AppSync
import boto3
from pydantic import BaseModel, Field, ValidationError
import openai
from openai import OpenAI

# --- CONFIGURATION ---
OPENAI_API_KEY_FROM_ENV = os.environ.get('OPENAI_API_KEY')
APPSYNC_API_URL = os.environ.get('APPSYNC_API_URL')
APPSYNC_API_KEY_FROM_ENV = os.environ.get('APPSYNC_API_KEY')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-2')
BUCKET_NAME = os.environ.get('BUCKET_NAME')
S3_SOURCE_TRANSCRIPT_PREFIX = os.environ.get('S3_SOURCE_TRANSCRIPT_PREFIX', 'public/transcripts/full')
S3_METADATA_PREFIX = os.environ.get('S3_METADATA_PREFIX', 'public/session-metadata')

# --- VALIDATE ESSENTIAL CONFIGURATION ---
if not OPENAI_API_KEY_FROM_ENV:
    raise ValueError("Environment variable OPENAI_API_KEY not set!")
if not APPSYNC_API_URL:
    raise ValueError("Environment variable APPSYNC_API_URL not set!")
if not APPSYNC_API_KEY_FROM_ENV:
    raise ValueError("Environment variable APPSYNC_API_KEY not set!")
if not BUCKET_NAME:
    raise ValueError("Environment variable BUCKET_NAME not set!")

# --- AWS & OPENAI CLIENTS ---
s3_client = boto3.client("s3", region_name=AWS_REGION)
lambda_client = boto3.client("lambda", region_name=AWS_REGION)
openai_client = OpenAI(api_key=OPENAI_API_KEY_FROM_ENV)

# --- Lookups for Generation Settings ---
content_length_lookup = {
    (0, 0.33): "Each segment length should be short and concise, around 2-4 sentences.",
    (0.33, 0.66): "Segment length should be 4-5 sentences.",
    (0.66, 1.01): "Each segment length should be highly detailed and verbose, around 6-8 sentences."
}

content_style_lookup = {
    (0, 0.33): "Write in a direct, factual, to-the-point style.",
    (0.33, 0.66): "Write in a balanced, narrative style.",
    (0.66, 1.01): "Write in a highly narrative, descriptive, and dramatic manner."
}

def get_generation_settings_string(instructions: Optional[Dict[str, Any]]) -> str:
    if not instructions:
        return "No specific generation settings were provided."

    parts = []
    length_val = instructions.get("contentLength", 0.5)
    for (start, end), desc in content_length_lookup.items():
        if start <= length_val < end:
            parts.append(desc)
            break
            
    style_val = instructions.get("contentStyle", 0.5)
    for (start, end), desc in content_style_lookup.items():
        if start <= style_val < end:
            parts.append(desc)
            break

    tones = instructions.get("selectedTones")
    if tones and isinstance(tones, list):
        parts.append(f"Adopt the following tones: {', '.join(tones)}.")

    emphases = instructions.get("selectedEmphases")
    if emphases and isinstance(emphases, list):
        parts.append(f"Place special emphasis on the following aspects: {', '.join(emphases)}.")

    if instructions.get("includeCharacterQuotes") is True:
        parts.append("You MUST include direct quotes from characters.")
    if instructions.get("includeGameMechanics") is True:
        parts.append("You MUST include references to game mechanics (skill checks, dice rolls, etc.).")
        
    return "\n- ".join(parts) if parts else "Default generation settings were used."

class SegmentContentForLLM(BaseModel):
    title: str
    description: str

class RevisedSummaryFromLLM(BaseModel):
    revised_tldr: str = Field(description="The revised concise 'too long; didn't read' summary of the entire session.")
    revised_sessionSegments: List[SegmentContentForLLM] = Field(description="A list of chronologically revised segments, each with a title and description.")

# --- GraphQL Queries and Mutations ---
GET_SESSION_QUERY = """
query GetSession($id: ID!) {
  getSession(id: $id) {
    id
    _version
    tldr
    owner
    transcriptionStatus
    campaign {
      id
    }
  }
}
"""

LIST_SEGMENTS_BY_SESSION_QUERY = """
query ListSegmentsBySession($sessionSegmentsId: ID!, $limit: Int, $nextToken: String) {
  listSegments(filter: {sessionSegmentsId: {eq: $sessionSegmentsId}}, limit: $limit, nextToken: $nextToken) {
    items {
      id
      _version
      title
      description
      index
      owner
    }
    nextToken
  }
}
"""

UPDATE_SESSION_MUTATION = """
mutation UpdateSession($input: UpdateSessionInput!) {
  updateSession(input: $input) {
    id
    _version
    tldr
    transcriptionStatus
    updatedAt
  }
}
"""

UPDATE_SEGMENT_MUTATION = """
mutation UpdateSegment($input: UpdateSegmentInput!) {
  updateSegment(input: $input) {
    id
    _version
    title
    description
    image 
    index
    updatedAt
  }
}
"""

# --- AppSync & OpenAI Helper Functions ---
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

    except requests.exceptions.RequestException as e: 
        if debug: print(f"Error making AppSync request: {e}")
        return {"errors": [{"message": f"RequestException: {e}"}]}

def get_openai_completion(prompt_text: str, client: OpenAI, model: str = "gpt-5.2", debug: bool = True) -> Optional[str]:
    if debug: print(f"Sending prompt to OpenAI (model: {model}). Prompt length: {len(prompt_text)}")
    messages = [{"role": "user", "content": prompt_text}]
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        if completion.choices and completion.choices[0].message and completion.choices[0].message.content:
            response_content = completion.choices[0].message.content
            if debug: print(f"Raw OpenAI JSON response (first 500 chars):\n{response_content[:500]}...")
            return response_content
        else:
            if debug: print("OpenAI response lacked content or choices.")
            return None
    except openai.APIError as e:
        if debug: print(f"OpenAI API error: {e}")
        return None

# --- Main Handler Logic ---

def lambda_handler(event, context):
    """
    Acts as a dispatcher.
    - If called from the frontend (no 'is_background_worker' flag), it initiates the process.
    - If called asynchronously by itself ('is_background_worker' is True), it performs the rewrite.
    """
    debug = True
    if debug: print(f"Lambda triggered. Event: {json.dumps(event)}")

    if event.get("is_background_worker"):
        if debug: print("Executing as a background worker.")
        handle_background_rewrite(event, context, debug)
        return
    else:
        if debug: print("Executing as a frontend request dispatcher.")
        return handle_frontend_request(event, context, debug)

def handle_frontend_request(event, context, debug: bool = True):
    """
    Handles the initial request from the frontend.
    1. Sets the session status to 'REWRITING'.
    2. Invokes the same Lambda asynchronously to do the work.
    3. Returns an immediate success response to the client.
    """
    try:
        body_str = event.get('body')
        if not body_str:
            return {'statusCode': 400, 'body': json.dumps({'error': 'Missing request body'})}
        
        body = json.loads(body_str)
        session_id = body.get('sessionId')

        if not session_id:
            return {'statusCode': 400, 'body': json.dumps({'error': 'Missing sessionId in request body'})}

        if debug: print(f"Fetching session {session_id} to get current version.")
        session_gql_response = execute_graphql_request(GET_SESSION_QUERY, {"id": session_id}, debug=debug)
        session_data = session_gql_response.get("data", {}).get("getSession")

        if not session_data:
            error_msg = f"Failed to fetch session {session_id} to start rewrite process."
            return {'statusCode': 404, 'body': json.dumps({'error': error_msg})}
        
        session_version = session_data["_version"]

        if debug: print(f"Updating session {session_id} transcriptionStatus to REWRITING (version: {session_version}).")
        update_status_input = {"id": session_id, "_version": session_version, "transcriptionStatus": "REWRITING"}
        update_response = execute_graphql_request(UPDATE_SESSION_MUTATION, {"input": update_status_input}, debug=debug)

        if not update_response.get("data", {}).get("updateSession"):
            error_msg = f"Failed to set session transcriptionStatus to REWRITING. AppSync Errors: {update_response.get('errors')}"
            return {'statusCode': 500, 'body': json.dumps({'error': error_msg})}
        
        async_payload = {"is_background_worker": True, "original_event_body": body}

        if debug: print(f"Invoking self asynchronously. Function: {context.function_name}")
        lambda_client.invoke(
            FunctionName=context.function_name,
            InvocationType='Event',
            Payload=json.dumps(async_payload)
        )

        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Rewrite process initiated successfully. The summary will be updated shortly.'})
        }

    except json.JSONDecodeError as e:
        return {'statusCode': 400, 'body': json.dumps({'error': f'Invalid JSON in request body: {str(e)}'})}
    except Exception as e:
        if debug: print(f"Error in frontend request handler: {str(e)}"); traceback.print_exc()
        return {'statusCode': 500, 'body': json.dumps({'error': f'An unexpected error occurred: {str(e)}'})}

def handle_background_rewrite(event, context, debug: bool = True):
    """
    Performs the actual heavy lifting of rewriting the summary.
    This function's logic is migrated from the original synchronous Lambda.
    It must reset the session status at the end, whether it succeeds or fails.
    """
    body = event.get('original_event_body', {})
    session_id = body.get('sessionId')

    if not session_id:
        print("CRITICAL ERROR in background worker: sessionId not found in payload.")
        return

    try:
        user_revisions = body.get('userRevisions', "")
        new_generation_instructions = body.get('generation_instructions')

        if not user_revisions:
            user_revisions = "No specific revisions were provided by the user. Please review the TLDR and all segments. Refine them for clarity, accuracy, narrative flow, and engagement, based on the full transcript."

        # 1. Fetch Session & Segments
        session_gql_response = execute_graphql_request(GET_SESSION_QUERY, {"id": session_id}, debug=debug)
        current_session_data = session_gql_response.get("data", {}).get("getSession")
        if not current_session_data:
            raise ValueError(f"Failed to fetch session {session_id} in background worker.")

        session_version = current_session_data["_version"]
        current_tldr_list = current_session_data.get("tldr", [])
        current_tldr_str = current_tldr_list[0] if current_tldr_list and isinstance(current_tldr_list, list) else ""
        campaign_id = current_session_data.get("campaign", {}).get("id")
        if not campaign_id:
            raise ValueError(f"Campaign ID not found for session {session_id}.")

        original_segments = []
        next_token = None
        while True:
            segments_response = execute_graphql_request(LIST_SEGMENTS_BY_SESSION_QUERY, {"sessionSegmentsId": session_id, "limit": 100, "nextToken": next_token}, debug=debug)
            segment_page = segments_response.get("data", {}).get("listSegments", {})
            original_segments.extend(segment_page.get("items", []))
            next_token = segment_page.get("nextToken")
            if not next_token:
                break
        
        if not original_segments:
            raise ValueError(f"No segments found for session {session_id}.")

        original_segments.sort(key=lambda s: s.get('index') if s.get('index') is not None else float('inf'))
        if debug:
            print(f"Fetched and sorted {len(original_segments)} segments.")
            print(f"Segment indices: {[s.get('index') for s in original_segments]}")
            print(f"Segment IDs: {[s.get('id') for s in original_segments]}")

        # 2. Fetch Transcript & Metadata
        filename_stem = f"campaign{campaign_id}Session{session_id}"
        transcript_key = f"{S3_SOURCE_TRANSCRIPT_PREFIX.rstrip('/')}/{filename_stem}.txt"
        metadata_key = f"{S3_METADATA_PREFIX.rstrip('/')}/{filename_stem}.metadata.json"

        try:
            s3_object = s3_client.get_object(Bucket=BUCKET_NAME, Key=transcript_key)
            transcript_text = s3_object['Body'].read().decode('utf-8')
        except s3_client.exceptions.NoSuchKey:
            raise ValueError(f"Transcript file not found at {transcript_key}")

        original_gen_instructions = None
        try:
            metadata_obj = s3_client.get_object(Bucket=BUCKET_NAME, Key=metadata_key)
            original_gen_instructions = json.loads(metadata_obj['Body'].read().decode('utf-8')).get("generation_instructions")
        except s3_client.exceptions.NoSuchKey:
            if debug: print(f"Metadata file not found at {metadata_key}.")

        # 3. Construct LLM Prompt
        segments_for_prompt = [SegmentContentForLLM(title=s.get("title", ""), description=(s.get("description", [""])[-1] if s.get("description") else "")) for s in original_segments]
        
        prompt = f"""You are Scribe, an AI assistant that revises TTRPG session summaries.
Your task is to revise the TLDR and Session Segments based on the full transcript and user requests.
CRITICAL: You MUST return EXACTLY {len(segments_for_prompt)} segments. Do NOT add or remove segments. Also, be mindful of the length of the TLDR and each segment, do not increase the length of these unless explicitly instructed/guided to.

Original Generation Settings:
{get_generation_settings_string(original_gen_instructions)}

User's New Generation Settings:
{get_generation_settings_string(new_generation_instructions)}

Original Full Session Transcript:
<transcript>{transcript_text}</transcript>

Current TLDR: {current_tldr_str}
Current Session Segments: {json.dumps([s.model_dump() for s in segments_for_prompt], indent=2)}
User's Revision Requests: {user_revisions}

Output a single JSON object with 'revised_tldr' (string) and 'revised_sessionSegments' (a list of objects with 'title' and 'description').
"""
        # 4. Call OpenAI
        llm_response_str = get_openai_completion(prompt, openai_client, debug=debug)
        if not llm_response_str:
            raise ValueError("Failed to get response from OpenAI.")

        llm_data = RevisedSummaryFromLLM.model_validate_json(llm_response_str)

        if len(llm_data.revised_sessionSegments) != len(original_segments):
            raise ValueError(f"LLM returned {len(llm_data.revised_sessionSegments)} segments, but expected {len(original_segments)}.")

        # 5. Update AppSync
        # Update TLDR
        update_session_input = {"id": session_id, "_version": session_version, "tldr": [llm_data.revised_tldr]}
        update_session_response = execute_graphql_request(UPDATE_SESSION_MUTATION, {"input": update_session_input}, debug=debug)
        if not update_session_response.get("data", {}).get("updateSession"):
            print(f"Warning: Failed to update Session TLDR for {session_id}.")

        # Update Segments (two-step clear and update)
        for i, revised_segment in enumerate(llm_data.revised_sessionSegments):
            original_segment = original_segments[i]
            
            clear_desc_input = {"id": original_segment["id"], "_version": original_segment["_version"], "description": []}
            clear_response = execute_graphql_request(UPDATE_SEGMENT_MUTATION, {"input": clear_desc_input}, debug=debug)
            
            cleared_segment_data = clear_response.get("data", {}).get("updateSegment")
            if not cleared_segment_data:
                print(f"Warning: Failed to clear description for segment {original_segment['id']}. Skipping update.")
                continue

            new_version = cleared_segment_data["_version"]
            update_segment_input = {
                "id": original_segment["id"],
                "_version": new_version,
                "title": revised_segment.title,
                "description": [revised_segment.description]
            }
            if original_segment.get("index") is not None:
                update_segment_input["index"] = original_segment["index"]

            update_segment_response = execute_graphql_request(UPDATE_SEGMENT_MUTATION, {"input": update_segment_input}, debug=debug)
            if not update_segment_response.get("data", {}).get("updateSegment"):
                print(f"Warning: Failed to update content for segment {original_segment['id']}.")

        if debug: print("Background rewrite process completed successfully.")

    except Exception as e:
        if debug: print(f"An error occurred during background rewrite for session {session_id}: {str(e)}"); traceback.print_exc()
    
    finally:
        # This block ALWAYS runs, ensuring the transcriptionStatus is not left as 'REWRITING'.
        if debug: print(f"Executing finally block to reset transcriptionStatus for session {session_id}.")
        try:
            final_session_gql_response = execute_graphql_request(GET_SESSION_QUERY, {"id": session_id}, debug=debug)
            final_session_data = final_session_gql_response.get("data", {}).get("getSession")

            if final_session_data:
                final_version = final_session_data["_version"]
                reset_status_input = {"id": session_id, "_version": final_version, "transcriptionStatus": "READ"}
                if debug: print(f"Resetting transcriptionStatus to READ for session {session_id} with version {final_version}.")
                execute_graphql_request(UPDATE_SESSION_MUTATION, {"input": reset_status_input}, debug=debug)
                if debug: print("TranscriptionStatus reset to READ successfully.")
            else:
                if debug: print(f"Could not fetch session {session_id} in finally block to reset transcriptionStatus.")

        except Exception as final_e:
            print(f"CRITICAL: Failed to reset transcriptionStatus for session {session_id} in finally block. Manual intervention may be required. Error: {final_e}")
            traceback.print_exc()
