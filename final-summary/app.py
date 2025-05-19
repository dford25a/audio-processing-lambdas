# --- Standard Library Imports ---
import os
import json
import urllib.parse
from typing import List, Optional, Dict, Any, Union
import base64 # For decoding image data
import re # For slugifying titles for filenames
import traceback # Added to be globally available

# --- Third-party Library Imports ---
import requests # For making HTTP requests to AppSync
import boto3
from pydantic import BaseModel, Field
import openai # Added for openai.APIError
from openai import OpenAI


# --- CONFIGURATION ---
OPENAI_API_KEY_FROM_ENV = os.environ.get('OPENAI_API_KEY')
APPSYNC_API_URL = os.environ.get('APPSYNC_API_URL') # AppSync GraphQL Endpoint URL
APPSYNC_API_KEY_FROM_ENV = os.environ.get('APPSYNC_API_KEY')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-2') # Default region if not set
DYNAMODB_TABLE_NAME = os.environ.get('DYNAMODB_TABLE') # DynamoDB table name for Sessions (updated variable name)
# S3_IMAGE_BUCKET = os.environ.get('S3_IMAGE_BUCKET_NAME') # If images go to a different bucket

# --- VALIDATE ESSENTIAL CONFIGURATION ---
if not OPENAI_API_KEY_FROM_ENV:
    raise ValueError("Environment variable OPENAI_API_KEY not set!")
if not APPSYNC_API_URL:
    raise ValueError("Environment variable APPSYNC_API_URL not set!")
if not APPSYNC_API_KEY_FROM_ENV:
    raise ValueError("Environment variable APPSYNC_API_KEY not set!")
if not DYNAMODB_TABLE_NAME: # Updated validation for the environment variable
    raise ValueError("Environment variable DYNAMODB_TABLE not set!")
# if not S3_IMAGE_BUCKET:
#     raise ValueError("Environment variable S3_IMAGE_BUCKET_NAME not set!")


# --- AWS & OPENAI CLIENTS ---
s3_client = boto3.client("s3", region_name=AWS_REGION) # Explicitly set region
dynamodb_resource = boto3.resource('dynamodb', region_name=AWS_REGION) # Initialize DynamoDB resource
openai_client = OpenAI(api_key=OPENAI_API_KEY_FROM_ENV)

# --- Pydantic Data Models ---
class SegmentElement(BaseModel):
    title: str = Field(description="The title of this specific segment of the session.")
    description: str = Field(description="A detailed textual description of what happened in this segment.")
    image_prompt: str = Field(description="A concise, visually descriptive prompt suitable for generating an image for this segment using DALL-E. This prompt should capture the essence of the segment visually.")

class SummaryElements(BaseModel):
    tldr: str = Field(description="A concise 'too long; didn't read' summary of the entire session.")
    sessionSegments: List[SegmentElement] = Field(description="A list of chronological segments detailing the session's events, each with a title, description, and an image prompt.")

# --- EXAMPLE SUMMARY (Updated for Segments with Image Prompts) ---
example_summary_for_segments_with_images = """
Example:
{
  "tldr": "The adventurers navigated the treacherous Sunken City, defeated a kraken cultist leader, and recovered the Tidejewel, narrowly escaping a temple collapse.",
  "sessionSegments": [
    {
      "title": "Descent into the Sunken City",
      "description": "The party, guided by an ancient map, found the hidden entrance to the Sunken City of Eldoria. Elara, the rogue, disarmed several water-themed traps, while Grom, the paladin, used his divine sense to detect lingering magical auras. Lyra, the wizard, cast water breathing on everyone. They encountered mutated merfolk, which they managed to bypass through a combination of stealth and diplomacy, learning about the 'Kraken's Voice' who ruled the city.",
      "image_prompt": "A fantasy adventuring party (rogue, paladin, wizard) cautiously entering a dark, vine-covered stone archway leading into a mysterious underwater city. Eerie blue light emanates from within. Ancient, crumbling architecture visible in the background, submerged in murky water. Digital art, detailed, atmospheric."
    },
    {
      "title": "The Cultist's Sanctum",
      "description": "Deeper in, they reached a grand, partially submerged temple. Inside, the Kraken's Voice, a powerful sorcerer named Vorlag, was performing a ritual to awaken a dormant leviathan. Combat ensued. Grom engaged Vorlag directly, while Elara picked off cultist acolytes from the shadows. Lyra's counterspells were crucial in disrupting Vorlag's potent magic. Key Moment: Lyra successfully dispelled a tidal wave spell that would have crushed the party.",
      "image_prompt": "Epic battle scene inside a grand, dimly lit, partially submerged temple. A paladin clashes with a dark sorcerer wielding crackling energy. A rogue attacks from the shadows. A wizard casts a powerful counterspell, deflecting a massive magical wave. Tentacle motifs adorn the temple walls. Dynamic action, fantasy art."
    },
    {
      "title": "The Tidejewel and Narrow Escape",
      "description": "After a grueling battle, Vorlag was defeated. On his altar, they found the Tidejewel, an artifact said to control local currents. As Elara grabbed it, the temple began to shake violently, a failsafe triggered by Vorlag's demise. The party raced out, dodging falling debris and surging waters, making it back to the entrance just as the main chamber collapsed.",
      "image_prompt": "Adventurers frantically escaping a crumbling underwater temple. One clutches a glowing blue jewel. Water surges around them, debris falls. The exit is a distant point of light. Sense of urgency and danger. Fantasy illustration."
    }
  ]
}
"""

# --- GraphQL Definitions ---
# The 'owner' field in the Session table is assumed to already contain the "id::name" formatted string.
LIST_SESSIONS_QUERY = """
query ListSessions($filter: ModelSessionFilterInput, $limit: Int, $nextToken: String) {
  listSessions(filter: $filter, limit: $limit, nextToken: $nextToken) {
    items {
      id
      _version
      audioFile
      owner # This field might not return the full cognitoId::username as per user's observation
      campaign {
        id
      }
    }
    nextToken
  }
}
"""

GET_NPCS_BY_CAMPAIGN_QUERY = """
query CampaignNpcsByCampaignId($campaignId: ID!, $limit: Int, $nextToken: String) {
  campaignNpcsByCampaignId(campaignId: $campaignId, limit: $limit, nextToken: $nextToken) {
    items {
      nPC {
        id
        name
        brief
      }
    }
    nextToken
  }
}
"""

UPDATE_SESSION_MUTATION = """
mutation UpdateSession($input: UpdateSessionInput!, $condition: ModelSessionConditionInput) {
  updateSession(input: $input, condition: $condition) {
    id
    _version
    transcriptionStatus
    tldr
    errorMessage
    updatedAt
  }
}
"""

CREATE_SEGMENT_MUTATION = """
mutation CreateSegment($input: CreateSegmentInput!) {
  createSegment(input: $input) {
    id
    title
    description
    image
    sessionSegmentsId
    owner # This field will receive the "id::name" formatted string directly from the Session's owner field
    createdAt
    updatedAt
    _version
  }
}
"""

# --- AppSync Helper Function (API Key Auth) ---
def execute_graphql_request(query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Executes a GraphQL query/mutation against the AppSync endpoint using API Key authentication.
    Handles potential HTTP errors, JSON decoding errors, and AppSync GraphQL errors.
    """
    headers = {
        'Content-Type': 'application/json',
        'x-api-key': APPSYNC_API_KEY_FROM_ENV
    }
    payload = {"query": query, "variables": variables or {}}

    try:
        response = requests.post(APPSYNC_API_URL, headers=headers, json=payload, timeout=90)
        response.raise_for_status()
        response_json = response.json()

        if "errors" in response_json:
            print(f"GraphQL Error: {json.dumps(response_json['errors'], indent=2)}")
        return response_json

    except requests.exceptions.JSONDecodeError as e:
        response_text = response.text if 'response' in locals() and hasattr(response, 'text') else 'Response object or text not available'
        print(f"JSONDecodeError making AppSync request: {e}. Response text: {response_text}")
        return {"errors": [{"message": f"JSONDecodeError: {e}. Response was not valid JSON."}]}
    except requests.exceptions.RequestException as e:
        print(f"Error making AppSync request: {e}")
        return {"errors": [{"message": f"RequestException: {e}"}]}
    except Exception as e:
        print(f"Unexpected error in execute_graphql_request: {e}")
        traceback.print_exc()
        return {"errors": [{"message": f"Unexpected error in execute_graphql_request: {e}"}]}


# --- Image Generation and Upload Helper ---
def generate_and_upload_image(
    prompt_suffix: str,
    s3_bucket: str,
    s3_base_prefix: str,
    session_id: str,
    segment_index: int,
    debug: bool = False
) -> Optional[str]:
    """
    Generates an image using the specified OpenAI model based on a prefixed prompt,
    uploads it to S3, and returns the S3 key (not the full URI).
    Includes error handling for OpenAI API calls and S3 uploads.
    """
    if not prompt_suffix:
        if debug:
            print("No prompt suffix provided for image generation. Skipping.")
        return None

    image_prompt_prefix = "fantasy-style painting in the dungeons and dragons DND theme... "
    full_prompt = image_prompt_prefix + prompt_suffix

    try:
        if debug:
            print(f"Generating image ... prompt: '{full_prompt}'")

        # Call to OpenAI API to generate an image - UPDATED PARAMETERS
        response = openai_client.images.generate(
            model="gpt-image-1", 
            prompt=full_prompt,
            n=1,
            size="1536x1024",  
            quality="low"
        )

        if response.data and response.data[0].b64_json:
            image_data_b64 = response.data[0].b64_json
            image_bytes = base64.b64decode(image_data_b64) # Decode base64 string to bytes

            image_filename = f"{session_id}_segment_{segment_index + 1}.png" # Using PNG format
            s3_image_key = f"{s3_base_prefix.rstrip('/')}/{image_filename}"

            if debug:
                print(f"Uploading image to S3: s3://{s3_bucket}/{s3_image_key}")

            s3_client.put_object(
                Bucket=s3_bucket,
                Key=s3_image_key,
                Body=image_bytes,
                ContentType='image/png' # Set the content type for the S3 object
            )

            if debug:
                print(f"Image successfully uploaded. S3 Key: {s3_image_key}")
            return s3_image_key # Return only the S3 key
        else:
            print("Failed to generate image or received no b64_json data from OpenAI.")
            return None

    except openai.APIError as e: # Catch OpenAI specific API errors
        print(f"OpenAI API error during image generation: {e}")
        return None
    except Exception as e: # Catch any other exceptions during the process
        print(f"An unexpected error occurred during image generation or upload: {e}")
        traceback.print_exc() # Print full traceback for unexpected errors
        return None

# --- Lambda Handler ---
def lambda_handler(event, context):
    session_info = None
    key = None
    debug = True # Set to False for production
    s3_image_upload_bucket = None
    updated_session_data = None # Initialize to avoid reference before assignment in error block

    try:
        if debug:
            print(f"Received event: {json.dumps(event)}")
            print(f"Using AppSync Endpoint: {APPSYNC_API_URL}")
            print(f"AWS Region: {AWS_REGION}")
            print(f"DynamoDB Session Table (from DYNAMODB_TABLE env var): {DYNAMODB_TABLE_NAME}")


        record = event["Records"][0]
        s3_transcript_bucket = record["s3"]["bucket"]["name"]
        s3_image_upload_bucket = os.environ.get('S3_IMAGE_BUCKET_NAME', s3_transcript_bucket)
        key = urllib.parse.unquote_plus(record['s3']['object']['key'], encoding='utf-8')

        s3_transcript_output_prefix = 'public/transcriptedSummary/'
        s3_segment_image_prefix = 'public/segmentImages/'

        original_filename_with_ext = os.path.basename(key)
        filename_stem_for_search = os.path.splitext(original_filename_with_ext)[0]

        if debug:
            print(f"Processing transcript file: {key} from bucket: {s3_transcript_bucket}")
            print(f"Images will be uploaded to bucket: {s3_image_upload_bucket} under prefix: {s3_segment_image_prefix}")
            print(f"Original S3 filename (from event object key): {original_filename_with_ext}")
            print(f"Filename stem for AppSync search (derived from S3 key): {filename_stem_for_search}")

        print(f"Searching for Session with audioFile starting with: {filename_stem_for_search}")
        current_next_token = None
        found_matching_session = None
        MAX_PAGES = 25
        pages_queried = 0

        while pages_queried < MAX_PAGES:
            pages_queried += 1
            list_sessions_vars = {
                "filter": {"audioFile": {"beginsWith": filename_stem_for_search}},
                "limit": 25,
                "nextToken": current_next_token
            }
            if debug: print(f"Querying AppSync (Page {pages_queried}): Variables: {json.dumps(list_sessions_vars)}")

            session_response_gql = execute_graphql_request(LIST_SESSIONS_QUERY, list_sessions_vars)

            if "errors" in session_response_gql and not session_response_gql.get("data"):
                raise Exception(f"Critical error fetching session list from AppSync: {session_response_gql['errors']}")

            session_data = session_response_gql.get("data", {}).get("listSessions", {})
            session_items = session_data.get("items", [])

            if debug: print(f"AppSync Response (Page {pages_queried}): Found {len(session_items)} items.")

            if session_items:
                found_matching_session = session_items[0] 
                if debug: print(f"Found potential matching session via ListSessions: {json.dumps(found_matching_session)}")
                break

            current_next_token = session_data.get("nextToken")
            if not current_next_token:
                if debug: print("No nextToken from AppSync, scan complete.")
                break

        if not found_matching_session:
            msg = f"No AppSync Session found via ListSessions for audioFile stem '{filename_stem_for_search}' after {pages_queried} page(s)."
            print(msg); raise ValueError(msg)

        session_info = found_matching_session 
        session_id = session_info["id"]
        session_version = session_info["_version"]

        # --- MODIFIED OWNER HANDLING: Fetch owner directly from DynamoDB ---
        segment_owner_value_for_appsync = None
        # Use DYNAMODB_TABLE_NAME which gets its value from the DYNAMODB_TABLE environment variable
        session_table = dynamodb_resource.Table(DYNAMODB_TABLE_NAME) 

        try:
            if debug: print(f"Fetching session item directly from DynamoDB table '{DYNAMODB_TABLE_NAME}' using ID: {session_id}")
            response_ddb = session_table.get_item(Key={'id': session_id})

            if 'Item' in response_ddb:
                dynamodb_session_item = response_ddb['Item']
                segment_owner_value_for_appsync = dynamodb_session_item.get("owner")
                if debug: print(f"Owner value retrieved directly from DynamoDB: '{segment_owner_value_for_appsync}'")

                if not segment_owner_value_for_appsync:
                    print(f"Warning: 'owner' field is missing or empty in DynamoDB item for Session {session_id}.")
                elif "::" not in segment_owner_value_for_appsync: 
                    print(f"Warning: Session {session_id} owner field ('{segment_owner_value_for_appsync}') from DynamoDB " +
                          "does not contain '::'. It might not be in the expected 'cognitoId::username' format.")
            else:
                print(f"Critical Warning: Session item with ID '{session_id}' was found by ListSessions but NOT found directly in DynamoDB table '{DYNAMODB_TABLE_NAME}'. " +
                      "This indicates a potential data consistency issue or incorrect table name. Proceeding without owner for segments.")
        except Exception as ddb_e:
            print(f"Error fetching session owner directly from DynamoDB table '{DYNAMODB_TABLE_NAME}': {str(ddb_e)}. " +
                  "Segments may be created without an owner or with a null owner.")
            traceback.print_exc()
        # --- END OF MODIFIED OWNER HANDLING ---

        if not segment_owner_value_for_appsync:
            print(f"Warning: Session {session_id} will have segments created with a null or empty owner due to issues fetching/finding it from DynamoDB. " +
                  "Please check DynamoDB table and previous logs.")

        if debug:
            print(f"Found Session ID: {session_id} (v: {session_version}), " +
                  f"Effective Segment Owner for AppSync (from DDB direct read): {segment_owner_value_for_appsync}")

        campaign_id = session_info.get("campaign", {}).get("id")
        if not campaign_id: print(f"Warning: Session {session_id} lacks campaign ID. NPC context will be limited.")
        if debug: print(f"Associated audioFile from ListSessions AppSync: {session_info.get('audioFile')}")


        npc_context_string = "No specific NPC context available."
        if campaign_id:
            print(f"Fetching NPCs for Campaign ID: {campaign_id}")
            all_npc_items = []
            npc_current_next_token = None
            npc_pages_queried = 0
            while npc_pages_queried < MAX_PAGES:
                npc_pages_queried +=1
                npc_query_vars = {"campaignId": campaign_id, "limit": 50, "nextToken": npc_current_next_token}
                npc_response_gql = execute_graphql_request(GET_NPCS_BY_CAMPAIGN_QUERY, npc_query_vars)
                if "errors" in npc_response_gql and not npc_response_gql.get("data"):
                    print(f"Warning: GraphQL error during GetNpcs: {npc_response_gql['errors']}. Proceeding without full NPC context.")
                    break
                npc_data = npc_response_gql.get("data", {}).get("campaignNpcsByCampaignId", {})
                npc_items_on_page = npc_data.get("items", [])
                all_npc_items.extend(npc_items_on_page)
                npc_current_next_token = npc_data.get("nextToken")
                if not npc_current_next_token: break
            
            npc_details = [
                f"- {item.get('nPC', {}).get('name', 'Unknown NPC')}: {item.get('nPC', {}).get('brief', 'No brief available.')}"
                for item in all_npc_items if item.get("nPC")
            ]
            if npc_details:
                npc_context_string = "Relevant NPCs in this campaign:\n" + "\n".join(npc_details)
            else:
                npc_context_string = "No NPCs found or retrieved for this campaign."
            if debug: print(f"NPC Context String:\n{npc_context_string}")
        else:
            if debug: print("Skipping NPC fetch as Campaign ID is missing.")

        s3_object_data = s3_client.get_object(Bucket=s3_transcript_bucket, Key=key)
        text_to_summarize = s3_object_data['Body'].read().decode('utf-8')
        if not text_to_summarize.strip():
            raise ValueError(f"Transcript file {key} is empty or contains only whitespace.")

        prompt = f"""You are Scribe, an AI-powered assistant that summarizes table top role playing game (TTRPG) sessions.
Your task is to process a TTRPG session transcript and generate:
1. A TLDR (Too Long; Didn't Read): A very brief, one or two sentence summary of the entire session.
2. Session Segments: A list of chronological segments. Each segment must have:
   a. 'title': A clear title for the segment.
   b. 'description': A detailed narrative of events, actions, character interactions, plot twists, and key moments in that segment.
   c. 'image_prompt': A concise, visually descriptive prompt (max 2-3 sentences) suitable for generating an image for this segment using DALL-E. This prompt should capture the visual essence of the segment (key characters, setting, action, mood). DO NOT include the prefix 'fantasy-style painting in the dungeons and dragons DND theme... ' in this 'image_prompt' field; the system will add it automatically.

The output must be a JSON object matching the Pydantic model `SummaryElements` which includes `tldr` (a string) and `sessionSegments` (a list of objects, where each object has `title` (string), `description` (string), and `image_prompt` (string)).

Session Transcript:
<session_text>
{text_to_summarize}
</session_text>

NPC Context (use for names and roles, if available):
<npc_context>
{npc_context_string}
</npc_context>

Example Output Structure (follow this JSON format precisely):
<example_summary>
{example_summary_for_segments_with_images}
</example_summary>

Guidelines for Segments:
- Chronological order.
- Divide the session into 2-5 meaningful segments.
- Distinct parts of the session (e.g., exploration, social interaction, combat, major plot points).
- Detailed, narrative descriptions.
- Use character/NPC names as mentioned in the transcript or NPC context.
- Mention important locations, items, or loot if applicable.
- The 'image_prompt' field from the LLM should be just the specific details for that segment, not the DND theme prefix.
"""
        def get_openai_summary_segments_with_image_prompts(prompt_text: str, model: str = "gpt-4o-mini") -> Optional[SummaryElements]:
            messages = [{"role": "user", "content": prompt_text}]
            try:
                completion = openai_client.chat.completions.create(
                    model=model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0.2,
                )
                if completion.choices and completion.choices[0].message and completion.choices[0].message.content:
                    json_content = completion.choices[0].message.content
                    if debug: print(f"Raw OpenAI JSON (summary/segments/prompts):\n{json_content}")
                    return SummaryElements.model_validate_json(json_content)
                else:
                    print("OpenAI response for summary/segments lacked content or choices."); return None
            except openai.APIError as e:
                print(f"OpenAI API error during summary/segment generation: {e}"); return None
            except Exception as e:
                print(f"Error calling OpenAI for summary/segments or parsing/validating response: {e}"); traceback.print_exc(); return None

        summary_elements_response = get_openai_summary_segments_with_image_prompts(prompt)

        if not summary_elements_response or not isinstance(summary_elements_response, SummaryElements):
            err_msg = "Failed to get valid SummaryElements (with image prompts) from OpenAI or response was not in the expected format."
            print(f"Error: {err_msg}"); raise Exception(err_msg)
        if not summary_elements_response.sessionSegments:
            print("Warning: OpenAI returned SummaryElements, but the sessionSegments list is empty. This might be due to a very short transcript or an issue with segment generation.")

        if debug: print(f"### LLM OUTPUT (Pydantic Model) ###\n{summary_elements_response.model_dump_json(indent=2)}")

        s3_summary_output_key = f"{s3_transcript_output_prefix.rstrip('/')}/{filename_stem_for_search}.json"
        s3_client.put_object(
            Bucket=s3_transcript_bucket,
            Key=s3_summary_output_key,
            Body=summary_elements_response.model_dump_json(indent=2),
            ContentType='application/json'
        )
        print(f"Summary (TLDR, Segments, Image Prompts) saved to S3: s3://{s3_transcript_bucket}/{s3_summary_output_key}")

        print(f"Updating Session {session_id} with TLDR and status via AppSync...")
        update_input = {
            "id": session_id,
            "_version": session_version, 
            "transcriptionStatus": "READ",
            "tldr": [summary_elements_response.tldr] if summary_elements_response.tldr else [],
            "errorMessage": None
        }
        update_vars = {"input": update_input}

        update_response_gql = execute_graphql_request(UPDATE_SESSION_MUTATION, update_vars)
        if "errors" in update_response_gql and not update_response_gql.get("data", {}).get("updateSession"):
            raise Exception(f"AppSync mutation to update Session failed: {update_response_gql['errors']}")

        updated_session_data = update_response_gql.get("data", {}).get("updateSession")
        if not updated_session_data or "_version" not in updated_session_data:
            raise Exception("AppSync Session update mutation returned no data, unexpected structure, or missing _version.")

        session_version = updated_session_data["_version"] 
        print(f"Successfully updated Session {session_id}. New version: {session_version}")

        print(f"Processing {len(summary_elements_response.sessionSegments)} segments for image generation and AppSync creation...")
        created_segment_details = []
        segment_processing_errors = []

        for idx, segment in enumerate(summary_elements_response.sessionSegments):
            segment_image_key_or_none = None # Changed variable name for clarity
            try:
                print(f"Processing segment {idx + 1}/{len(summary_elements_response.sessionSegments)}: '{segment.title}'")

                if segment.image_prompt:
                    segment_image_key_or_none = generate_and_upload_image( # Returns S3 key or None
                        prompt_suffix=segment.image_prompt,
                        s3_bucket=s3_image_upload_bucket,
                        s3_base_prefix=s3_segment_image_prefix,
                        session_id=session_id,
                        segment_index=idx,
                        debug=debug
                    )
                else:
                    if debug: print(f"Skipping image generation for segment '{segment.title}' as image_prompt is empty.")

                create_segment_input = {
                    "sessionSegmentsId": session_id,
                    "title": segment.title,
                    "description": [segment.description] if segment.description else [],
                    "image": segment_image_key_or_none, # Use the S3 key (or None)
                    "owner": segment_owner_value_for_appsync 
                }
                
                if segment_owner_value_for_appsync is None:
                     print(f"Warning: Attempting to create segment '{segment.title}' for session '{session_id}' with a null owner value for AppSync (derived from DynamoDB read). " +
                           "This might cause an error if the 'owner' field is mandatory in your 'CreateSegmentInput' or Segment schema.")


                segment_vars = {"input": create_segment_input}
                segment_response = execute_graphql_request(CREATE_SEGMENT_MUTATION, segment_vars)

                created_segment_data = None
                if segment_response and isinstance(segment_response.get("data"), dict):
                    created_segment_data = segment_response["data"].get("createSegment")

                if created_segment_data and created_segment_data.get("id"):
                    created_segment_details.append(created_segment_data)
                    # Log the image key as it's stored in AppSync
                    print(f"Successfully created segment ID: {created_segment_data['id']} - '{segment.title}' (Image Key: {created_segment_data.get('image', 'N/A')}, Owner: {created_segment_data.get('owner')})")
                else:
                    appsync_errors = segment_response.get('errors') if isinstance(segment_response, dict) else 'execute_graphql_request returned non-dict or None for segment creation'
                    error_details_str = "No specific error details in response for segment creation."
                    if isinstance(appsync_errors, list) and len(appsync_errors) > 0:
                        error_details_str = json.dumps(appsync_errors)
                    elif appsync_errors:
                        error_details_str = str(appsync_errors)
                    
                    err_msg = f"Failed to create segment '{segment.title}' in AppSync or no segment data returned. AppSync Response: {error_details_str}"
                    print(err_msg)
                    segment_processing_errors.append(err_msg)

                    if isinstance(error_details_str, str) and "The variables input contains a field that is not defined for input object type 'CreateSegmentInput'" in error_details_str:
                        print("ADVICE: The above error indicates a mismatch between the fields sent to AppSync and what the 'CreateSegmentInput' type expects. Please verify your AppSync schema's 'CreateSegmentInput' definition against these fields being sent:")
                        print(f"Sent fields for CreateSegmentInput: {list(create_segment_input.keys())}")

            except Exception as seg_proc_e:
                err_msg = f"Exception during processing segment '{segment.title}' (image gen or AppSync create): {str(seg_proc_e)}"
                print(err_msg); segment_processing_errors.append(err_msg)
                traceback.print_exc()

        if segment_processing_errors:
            print(f"Completed segment processing with {len(segment_processing_errors)} error(s):")
            for i, error_detail in enumerate(segment_processing_errors):
                print(f"  Segment Error {i+1}: {error_detail}")

        print(f"Successfully processed {len(created_segment_details)} out of {len(summary_elements_response.sessionSegments)} segments for session {session_id}.")

        return {
            'statusCode': 200,
            'body': json.dumps(f"Processed successfully: {key}. TLDR and {len(created_segment_details)} of {len(summary_elements_response.sessionSegments)} segments created/updated. Errors: {len(segment_processing_errors)}")
        }

    except Exception as e:
        error_message = str(e)
        print(f"FATAL Error processing file {key if key else 'unknown'}: {error_message}")
        traceback.print_exc()

        if session_info and 'id' in session_info and '_version' in session_info:
            session_id_for_error = session_info['id']
            session_version_for_error = updated_session_data["_version"] if updated_session_data and "_version" in updated_session_data else session_info['_version']
            
            print(f"Attempting to update Session {session_id_for_error} to ERROR state (v: {session_version_for_error})...")
            try:
                error_update_input = {
                    "id": session_id_for_error,
                    "_version": session_version_for_error,
                    "transcriptionStatus": "ERROR",
                    "errorMessage": error_message[:1000] 
                }
                error_update_vars = {"input": error_update_input}
                error_response = execute_graphql_request(UPDATE_SESSION_MUTATION, error_update_vars)

                if error_response.get("errors") and not error_response.get("data", {}).get("updateSession"):
                    print(f"Failed to update session to ERROR state: {error_response.get('errors')}")
                else:
                    print("Session status successfully updated to ERROR.")
            except Exception as update_err:
                print(f"Could not update session to ERROR state during exception handling: {str(update_err)}")
        else:
            print("Cannot update session to ERROR state: session_info not available or error occurred before session fetch.")

        return {
            "statusCode": 500,
            "body": json.dumps(f"Error processing file: {error_message}")
        }


