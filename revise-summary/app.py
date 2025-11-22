# --- Standard Library Imports ---
import os
import json
from typing import List, Optional, Dict, Any # Union removed as not used
import traceback

# --- Third-party Library Imports ---
import requests # For making HTTP requests to AppSync
import boto3
from pydantic import BaseModel, Field, ValidationError
import openai # Added for openai.APIError
from openai import OpenAI

# --- CONFIGURATION ---
OPENAI_API_KEY_FROM_ENV = os.environ.get('OPENAI_API_KEY')
APPSYNC_API_URL = os.environ.get('APPSYNC_API_URL')
APPSYNC_API_KEY_FROM_ENV = os.environ.get('APPSYNC_API_KEY')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-2') # Default region if not set
BUCKET_NAME = os.environ.get('BUCKET_NAME') # Bucket where transcripts are stored
S3_SOURCE_TRANSCRIPT_PREFIX = os.environ.get('S3_SOURCE_TRANSCRIPT_PREFIX', 'public/transcripts/full') # Prefix for source transcript files
S3_METADATA_PREFIX = os.environ.get('S3_METADATA_PREFIX', 'public/session-metadata') # Prefix for metadata files

# --- VALIDATE ESSENTIAL CONFIGURATION ---
if not OPENAI_API_KEY_FROM_ENV:
    raise ValueError("Environment variable OPENAI_API_KEY not set!")
if not APPSYNC_API_URL:
    raise ValueError("Environment variable APPSYNC_API_URL not set!")
if not APPSYNC_API_KEY_FROM_ENV:
    raise ValueError("Environment variable APPSYNC_API_KEY not set!")
if not BUCKET_NAME:
    raise ValueError("Environment variable BUCKET_NAME not set!")
if not S3_SOURCE_TRANSCRIPT_PREFIX:
    # Default is provided, but good to be aware if it needs to be explicit.
    print(f"Warning: Environment variable S3_SOURCE_TRANSCRIPT_PREFIX not explicitly set. Using default: '{S3_SOURCE_TRANSCRIPT_PREFIX}'")


# --- AWS & OPENAI CLIENTS ---
s3_client = boto3.client("s3", region_name=AWS_REGION)
openai_client = OpenAI(api_key=OPENAI_API_KEY_FROM_ENV)

# --- Pydantic Data Models ---
# For structuring data passed to and received from the LLM

# --- Lookups for Generation Settings ---
# Copied from final-summary/app.py for consistency
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
    """Converts a generation_instructions object into a human-readable string."""
    if not instructions:
        return "No specific generation settings were provided."

    parts = []
    
    # Content Length
    length_val = instructions.get("contentLength", 0.5)
    for (start, end), desc in content_length_lookup.items():
        if start <= length_val < end:
            parts.append(desc)
            break
            
    # Content Style
    style_val = instructions.get("contentStyle", 0.5)
    for (start, end), desc in content_style_lookup.items():
        if start <= style_val < end:
            parts.append(desc)
            break

    # Tones
    tones = instructions.get("selectedTones")
    if tones and isinstance(tones, list):
        parts.append(f"Adopt the following tones: {', '.join(tones)}.")

    # Emphases
    emphases = instructions.get("selectedEmphases")
    if emphases and isinstance(emphases, list):
        parts.append(f"Place special emphasis on the following aspects: {', '.join(emphases)}.")

    # Booleans
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
# Query to get session details including TLDR and campaign ID (to reconstruct transcript path)
GET_SESSION_QUERY = """
query GetSession($id: ID!) {
  getSession(id: $id) {
    id
    _version
    tldr
    owner
    campaign {
      id
    }
  }
}
"""

# Query to list all segments associated with a session
# ADDED: index to items
LIST_SEGMENTS_BY_SESSION_QUERY = """
query ListSegmentsBySession($sessionSegmentsId: ID!, $limit: Int, $nextToken: String) {
  listSegments(filter: {sessionSegmentsId: {eq: $sessionSegmentsId}}, limit: $limit, nextToken: $nextToken) {
    items {
      id
      _version
      title
      description
      index # ADDED: Fetch the index of the segment
      owner
    }
    nextToken
  }
}
"""

# Mutation to update the session (e.g., for TLDR)
UPDATE_SESSION_MUTATION = """
mutation UpdateSession($input: UpdateSessionInput!) {
  updateSession(input: $input) {
    id
    _version
    tldr
    updatedAt
  }
}
"""

# Mutation to update an individual segment
# index is part of UpdateSegmentInput and will be passed if present in the input object
UPDATE_SEGMENT_MUTATION = """
mutation UpdateSegment($input: UpdateSegmentInput!) {
  updateSegment(input: $input) {
    id
    _version
    title
    description
    image 
    index # Ensure index is returned if updated
    updatedAt
  }
}
"""

# --- AppSync Helper Function ---
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
        if debug: print(f"Unexpected error in execute_graphql_request: {e}")
        if debug: traceback.print_exc()
        return {"errors": [{"message": f"Unexpected error: {e}"}]}


# --- OpenAI Helper Function ---
def get_openai_completion(prompt_text: str, client: OpenAI, model: str = "gpt-5.1", debug: bool = True) -> Optional[str]:
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
    except Exception as e:
        if debug: print(f"Error calling OpenAI or processing its response: {e}"); traceback.print_exc()
        return None

# --- Lambda Handler ---
def lambda_handler(event, context):
    debug = True
    if debug: print(f"Lambda triggered. Event: {json.dumps(event)}")

    try:
        body_str = event.get('body')
        if not body_str:
            if debug: print("Request body is missing.")
            return {'statusCode': 400, 'body': json.dumps({'error': 'Missing request body'})}

        body = json.loads(body_str)
        session_id_from_request = body.get('sessionId')
        user_revisions = body.get('userRevisions', "")
        new_generation_instructions = body.get('generation_instructions')

        if not session_id_from_request:
            if debug: print("sessionId is missing from request body.")
            return {'statusCode': 400, 'body': json.dumps({'error': 'Missing sessionId in request body'})}

        if not user_revisions:
            if debug: print("User revisions string is empty or not provided. LLM will be prompted to refine based on transcript and general quality.")
            user_revisions = "No specific revisions were provided by the user. Please review the TLDR and all segments. Refine them for clarity, accuracy, narrative flow, and engagement, based on the full transcript."

        # 1. Fetch current Session data from AppSync
        if debug: print(f"Fetching session data for ID: {session_id_from_request}")
        session_gql_response = execute_graphql_request(GET_SESSION_QUERY, {"id": session_id_from_request}, debug=debug)

        current_session_data = session_gql_response.get("data", {}).get("getSession")
        if not current_session_data:
            error_msg = f"Failed to fetch session {session_id_from_request} or session not found. AppSync Errors: {session_gql_response.get('errors')}"
            if debug: print(error_msg)
            return {'statusCode': 404, 'body': json.dumps({'error': error_msg})}

        session_version = current_session_data["_version"]
        current_tldr_list = current_session_data.get("tldr", [])
        current_tldr_str = current_tldr_list[0] if current_tldr_list and isinstance(current_tldr_list, list) else (current_tldr_list if isinstance(current_tldr_list, str) else "")

        campaign_data = current_session_data.get("campaign")
        if not campaign_data or not campaign_data.get("id"):
            error_msg = f"Campaign ID not found in Session data for {session_id_from_request}. Cannot construct transcript S3 key."
            if debug: print(error_msg)
            return {'statusCode': 500, 'body': json.dumps({'error': error_msg})}
        campaign_id_from_gql = campaign_data["id"]

        filename_stem = f"campaign{campaign_id_from_gql}Session{session_id_from_request}"
        constructed_transcript_s3_key = f"{S3_SOURCE_TRANSCRIPT_PREFIX.rstrip('/')}/{filename_stem}.txt"
        metadata_s3_key = f"{S3_METADATA_PREFIX.rstrip('/')}/{filename_stem}.metadata.json"

        if debug: print(f"Constructed transcript S3 key: s3://{BUCKET_NAME}/{constructed_transcript_s3_key}")
        if debug: print(f"Constructed metadata S3 key: s3://{BUCKET_NAME}/{metadata_s3_key}")

        # Fetch original generation settings from metadata
        original_generation_instructions = None
        try:
            metadata_obj = s3_client.get_object(Bucket=BUCKET_NAME, Key=metadata_s3_key)
            metadata_content = json.loads(metadata_obj['Body'].read().decode('utf-8'))
            original_generation_instructions = metadata_content.get("generation_instructions")
            if debug: print(f"Successfully fetched and parsed metadata. Original settings: {json.dumps(original_generation_instructions)}")
        except s3_client.exceptions.NoSuchKey:
            if debug: print(f"Metadata file not found at {metadata_s3_key}. Cannot retrieve original generation settings.")
        except Exception as e:
            if debug: print(f"Error fetching or parsing metadata from {metadata_s3_key}: {e}")

        original_settings_str = get_generation_settings_string(original_generation_instructions)
        new_settings_str = get_generation_settings_string(new_generation_instructions)

        # 2. Fetch current Segments for the Session from AppSync
        if debug: print(f"Fetching segments for session ID: {session_id_from_request}")
        original_segments_from_appsync = []
        next_token_segments = None
        segment_page_count = 0
        MAX_SEGMENT_PAGES = 10

        while segment_page_count < MAX_SEGMENT_PAGES:
            segment_page_count += 1
            segments_gql_response = execute_graphql_request(
                LIST_SEGMENTS_BY_SESSION_QUERY,
                {"sessionSegmentsId": session_id_from_request, "limit": 100, "nextToken": next_token_segments},
                debug=debug
            )

            data_field = segments_gql_response.get("data") 
            segment_data_page = None
            if data_field is not None: 
                segment_data_page = data_field.get("listSegments")

            if not segment_data_page:
                gql_errors = segments_gql_response.get('errors')
                error_msg = f"Failed to fetch segments or no segments found on page {segment_page_count} for session {session_id_from_request}."
                if gql_errors: error_msg += f" AppSync Errors: {json.dumps(gql_errors)}"
                if debug: print(error_msg)
                if not original_segments_from_appsync and gql_errors:
                    return {'statusCode': 500, 'body': json.dumps({'error': f"Error fetching segments: {json.dumps(gql_errors)}"})}
                break 

            items_on_page = segment_data_page.get("items", [])
            original_segments_from_appsync.extend(items_on_page)
            next_token_segments = segment_data_page.get("nextToken")
            if not next_token_segments: break
        
        if not original_segments_from_appsync:
            return {'statusCode': 404, 'body': json.dumps({'error': f"No segments found for session {session_id_from_request} to revise."})}
        
        # Sort fetched segments by index to ensure correct order
        # Handle cases where index might be None or missing for robustness, defaulting to a large number to push them to the end or 0 for start.
        # Assuming index is an integer if present.
        def get_segment_index(segment):
            idx = segment.get('index')
            if idx is None:
                if debug: print(f"Warning: Segment ID {segment.get('id')} is missing an index. Defaulting for sort.")
                return float('inf') # Or 0, depending on desired behavior for missing indices
            return idx

        original_segments_from_appsync.sort(key=get_segment_index)
        if debug: 
            print(f"Fetched and sorted {len(original_segments_from_appsync)} segments. Indices: {[s.get('index') for s in original_segments_from_appsync]}")


        # 3. Fetch Original Transcript Text from S3
        if not BUCKET_NAME: 
            return {'statusCode': 500, 'body': json.dumps({'error': 'BUCKET_NAME environment variable not set.'})}

        if debug: print(f"Fetching transcript from S3: bucket='{BUCKET_NAME}', key='{constructed_transcript_s3_key}'")
        try:
            s3_object = s3_client.get_object(Bucket=BUCKET_NAME, Key=constructed_transcript_s3_key)
            original_transcript_text = s3_object['Body'].read().decode('utf-8')
            if not original_transcript_text.strip():
                raise ValueError(f"Transcript file from S3 (s3://{BUCKET_NAME}/{constructed_transcript_s3_key}) is empty.")
            if debug: print(f"Transcript fetched successfully. Length: {len(original_transcript_text)}")
        except s3_client.exceptions.NoSuchKey:
            error_msg = f"Transcript file not found in S3 at s3://{BUCKET_NAME}/{constructed_transcript_s3_key}"
            if debug: print(error_msg)
            return {'statusCode': 404, 'body': json.dumps({'error': error_msg})}
        except Exception as e:
            error_msg = f"Error fetching/reading transcript from S3 (s3://{BUCKET_NAME}/{constructed_transcript_s3_key}): {str(e)}"
            if debug: print(error_msg); traceback.print_exc()
            return {'statusCode': 500, 'body': json.dumps({'error': error_msg})}

        # 4. Prepare current segment data for the LLM prompt (using sorted segments)
        segments_for_llm_prompt = []
        for seg_data in original_segments_from_appsync: # Iterate over sorted segments
            desc_list = seg_data.get("description", [])
            desc_str = desc_list[0] if desc_list and isinstance(desc_list, list) else (desc_list if isinstance(desc_list, str) else "")
            segments_for_llm_prompt.append(SegmentContentForLLM(
                title=seg_data.get("title", "Untitled Segment"),
                description=desc_str
            ))

        # 5. Construct LLM Prompt
        prompt = f"""You are Scribe, an AI assistant that revises TTRPG session summaries.
You will be provided with:
1. The original full session transcript.
2. The current TLDR (Too Long; Didn't Read) summary.
3. A list of current Session Segments, each with a 'title' and 'description', presented in their chronological order.
4. User's specific revision requests.

Your task is to:
- Revise the TLDR based on the transcript and the user's requests. The TLDR should be a concise summary of the whole session. Do NOT simply append to or expand the existing TLDR - create a fresh, concise summary.
- Revise each Session Segment's title and description based on the transcript and user's requests.
- CRITICAL CONSTRAINT: You MUST return EXACTLY {len(segments_for_llm_prompt)} segments - the same number as provided in 'Current Session Segments'. 
- If the user asks to "add" content about a topic, incorporate that content into the appropriate existing segment(s). DO NOT create new segments.
- If the user asks to "remove" content, simply omit that content from the relevant segment(s). DO NOT delete segments.
- You may redistribute content between existing segments, but the total count must remain {len(segments_for_llm_prompt)}.
- Maintain the chronological order of segments.
- Ensure your output is a single, valid JSON object.

Original Generation Settings:
<original_settings>
{original_settings_str}
</original_settings>

User's New Generation Settings:
<new_settings>
{new_settings_str}
</new_settings>

Original Full Session Transcript:
<transcript>
{original_transcript_text}
</transcript>

Current TLDR:
{current_tldr_str}

Current Session Segments (JSON array format, in chronological order):
{json.dumps([s.model_dump() for s in segments_for_llm_prompt], indent=2)}

User's Revision Requests:
{user_revisions}

Output a single JSON object with two top-level keys: 'revised_tldr' (a string) and 'revised_sessionSegments' (a list of JSON objects). Each object in 'revised_sessionSegments' must have 'title' (string) and 'description' (string).
Example of the required JSON output structure:
{{
  "revised_tldr": "The adventurers bravely faced the goblin horde and rescued the artifact...",
  "revised_sessionSegments": [
    {{
      "title": "Revised Ambush in the Woods",
      "description": "The party was ambushed by goblins. Elara used her stealth, while Grom's mighty axe scattered them. They found a map on the goblin leader..."
    }}
    // ... (ensure one object for each original segment, in the same order)
  ]
}}
"""
        # 6. Call OpenAI
        if debug: print("Calling OpenAI for summary revision...")
        llm_response_str = get_openai_completion(prompt, openai_client, debug=debug)

        if not llm_response_str:
            return {'statusCode': 500, 'body': json.dumps({'error': 'Failed to get response from OpenAI or response was empty.'})}

        try:
            llm_data = RevisedSummaryFromLLM.model_validate_json(llm_response_str)
        except ValidationError as e:
            error_msg = f"OpenAI response failed Pydantic validation: {str(e)}. Raw response (first 1000 chars): {llm_response_str[:1000]}"
            if debug: print(error_msg)
            return {'statusCode': 500, 'body': json.dumps({'error': error_msg})}
        except json.JSONDecodeError as e:
            error_msg = f"OpenAI response was not valid JSON: {str(e)}. Raw response (first 1000 chars): {llm_response_str[:1000]}"
            if debug: print(error_msg)
            return {'statusCode': 500, 'body': json.dumps({'error': error_msg})}

        if len(llm_data.revised_sessionSegments) != len(original_segments_from_appsync):
            error_msg = (f"LLM returned {len(llm_data.revised_sessionSegments)} segments, "
                         f"but expected {len(original_segments_from_appsync)} based on input. Cannot proceed with update.")
            if debug: print(error_msg)
            return {'statusCode': 500, 'body': json.dumps({'error': error_msg})}

        # 7. Update Session (TLDR) in AppSync
        if debug: print(f"Updating Session {session_id_from_request} with revised TLDR.")
        update_session_input = {
            "id": session_id_from_request,
            "_version": session_version,
            "tldr": [llm_data.revised_tldr] if llm_data.revised_tldr is not None else []
        }
        update_session_gql_response = execute_graphql_request(UPDATE_SESSION_MUTATION, {"input": update_session_input}, debug=debug)

        session_update_successful = update_session_gql_response.get("data", {}).get("updateSession") is not None
        if not session_update_successful:
            error_msg_session_update = f"Failed to update Session TLDR for {session_id_from_request}. AppSync Errors: {update_session_gql_response.get('errors')}"
            if debug: print(f"Warning: {error_msg_session_update}")
        else:
            if debug: print(f"Session {session_id_from_request} TLDR updated successfully. New version: {update_session_gql_response['data']['updateSession'].get('_version')}")
            # Update session_version for subsequent segment updates if TLDR update was successful
            session_version = update_session_gql_response['data']['updateSession']['_version']


        # 8. Update Segments in AppSync
        if debug: print(f"Updating {len(llm_data.revised_sessionSegments)} segments.")
        segment_update_errors = []
        successful_segment_updates = 0

        for i, revised_segment_content in enumerate(llm_data.revised_sessionSegments):
            original_segment_data = original_segments_from_appsync[i] # Use the sorted original segment data

            update_segment_input = {
                "id": original_segment_data["id"],
                "_version": original_segment_data["_version"], # Use the segment's own version
                "title": revised_segment_content.title,
                "description": revised_segment_content.description if revised_segment_content.description is not None else "",
                "index": original_segment_data.get("index") # Pass the original index back
            }
            # Remove index from input if it's None, in case the schema doesn't allow null for index on update
            if update_segment_input["index"] is None:
                if debug: print(f"Segment ID {original_segment_data['id']} has a None index; not including in update input.")
                del update_segment_input["index"]


            if debug: print(f"Attempting to update segment ID {original_segment_data['id']} (original index {original_segment_data.get('index')}) with title '{revised_segment_content.title}'")
            update_segment_gql_response = execute_graphql_request(UPDATE_SEGMENT_MUTATION, {"input": update_segment_input}, debug=debug)

            if not update_segment_gql_response.get("data", {}).get("updateSegment"):
                err_detail = (f"Failed to update segment {original_segment_data['id']}. "
                              f"AppSync Errors: {update_segment_gql_response.get('errors')}")
                if debug: print(f"Error: {err_detail}")
                segment_update_errors.append(err_detail)
            else:
                if debug: print(f"Segment {original_segment_data['id']} updated successfully. New version: {update_segment_gql_response['data']['updateSegment'].get('_version')}, Index: {update_segment_gql_response['data']['updateSegment'].get('index')}")
                successful_segment_updates += 1

        # 9. Final Response
        if not session_update_successful or segment_update_errors:
            final_status_message = "Summary revision process completed with errors."
            error_details = {}
            if not session_update_successful:
                error_details["session_update"] = f"Failed to update TLDR. Errors: {update_session_gql_response.get('errors')}"
            if segment_update_errors:
                error_details["segment_updates"] = segment_update_errors

            return {
                'statusCode': 207, # Multi-Status
                'body': json.dumps({
                    'message': final_status_message,
                    'details': error_details,
                    'successful_segment_updates': successful_segment_updates,
                    'total_segments_processed': len(llm_data.revised_sessionSegments)
                })
            }

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f'Session {session_id_from_request} summary revised successfully. TLDR updated. {successful_segment_updates} of {len(llm_data.revised_sessionSegments)} segments updated.',
                'revised_tldr': llm_data.revised_tldr,
            })
        }

    except json.JSONDecodeError as e: 
        if debug: print(f"JSON Decode Error in handler (likely request body): {str(e)}")
        return {'statusCode': 400, 'body': json.dumps({'error': f'Invalid JSON in request body: {str(e)}'})}
    except Exception as e:
        if debug: print(f"General unhandled error in lambda_handler: {str(e)}"); traceback.print_exc()
        return {'statusCode': 500, 'body': json.dumps({'error': f'An unexpected error occurred: {str(e)}'})}
