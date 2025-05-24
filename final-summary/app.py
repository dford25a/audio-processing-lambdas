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
DYNAMODB_TABLE_NAME = os.environ.get('DYNAMODB_TABLE') # DynamoDB table name for Sessions

# --- VALIDATE ESSENTIAL CONFIGURATION ---
if not OPENAI_API_KEY_FROM_ENV:
    raise ValueError("Environment variable OPENAI_API_KEY not set!")
if not APPSYNC_API_URL:
    raise ValueError("Environment variable APPSYNC_API_URL not set!")
if not APPSYNC_API_KEY_FROM_ENV:
    raise ValueError("Environment variable APPSYNC_API_KEY not set!")
if not DYNAMODB_TABLE_NAME:
    raise ValueError("Environment variable DYNAMODB_TABLE not set!")


# --- AWS & OPENAI CLIENTS ---
s3_client = boto3.client("s3", region_name=AWS_REGION) # Explicitly set region
dynamodb_resource = boto3.resource('dynamodb', region_name=AWS_REGION) # Initialize DynamoDB resource
openai_client = OpenAI(api_key=OPENAI_API_KEY_FROM_ENV)

# --- Pydantic Data Models ---
class SegmentElement(BaseModel):
    title: str = Field(description="The title of this specific segment of the session.")
    description: str = Field(description="A detailed textual description of what happened in this segment. (5-8 sentences)")
    image_prompt: str = Field(description="A concise, visually descriptive prompt suitable for generating an image for this segment using DALL-E. This prompt should capture the essence of the segment visually.")

class SummaryElements(BaseModel):
    tldr: str = Field(description="A concise 'too long; didn't read' summary of the entire session.")
    sessionSegments: List[SegmentElement] = Field(description="A list of chronological segments detailing the session's events, each with a title, description (5-8 sentence segment summary), and an image prompt.")

# --- EXAMPLE SUMMARY (Updated for Segments with Image Prompts) ---
example_summary_for_segments_with_images = """
Example:
{
  "tldr": "The adventurers navigated the treacherous Sunken City, defeated a kraken cultist leader, and recovered the Tidejewel, narrowly escaping a temple collapse.",
  "sessionSegments": [
    {
      "title": "Descent into the Sunken City",
      "description": "The adventurers—Bron, Donnie, Joe Bangles, and Shifty—carefully explored a mysterious underground tomb marked by a large arched crystal window and a steep drop-off guarded by roped fences. On their way to a side door, they discovered a deep chasm with descending stairs leading to lower platforms, adding complexity to their path. They noted six desiccated corpses wearing black paper mache and feather masks seated on thrones, flanked by two imposing bear statues gripping a bronze disc embossed with a dozen glaring eyes. The group speculated on the significance of the masks and the ominous inscription urging to "don the mask or be seen." ",
      "image_prompt": "A fantasy adventuring party (rogue, paladin, wizard) cautiously entering a dark, vine-covered stone archway leading into a mysterious underwater city. Eerie blue light emanates from within. Ancient, crumbling architecture visible in the background, submerged in murky water."
    },
    {
      "title": "The Cultist's Sanctum",
      "description": "Initially, Bron attempted to smash the crystal window to gain entry but failed to break through. The party persuaded him to stop and instead investigate a side door they discovered nearby. Approaching cautiously through this alternate entrance, they avoided alerting the tomb’s guardians prematurely.

Once inside, Bron swiftly grabbed one of the masks from a corpse just as the undead began to animate, triggering a fierce combat encounter. The party quickly rolled initiative, with Bron raging and attempting to rip the mask off one of the undead, succeeding with a powerful strength check. Shifty conjured a spectral pack of wolves using his fifth-level spell, which inflicted damage and hindered enemy movement. The undead retaliated with life drain attacks, forcing the party to make multiple constitution saving throws to maintain concentration on spells and resist debilitating effects.",
      "image_prompt": "Epic battle scene inside a grand, dimly lit, partially submerged temple. A paladin clashes with a dark sorcerer wielding crackling energy. A rogue attacks from the shadows. A wizard casts a powerful counterspell, deflecting a massive magical wave. Tentacle motifs adorn the temple walls."
    },
    {
      "title": "The Tidejewel and Narrow Escape",
      "description": "The battle was intense and tactical, with enemies casting dispel magic to counter the party’s plant growth spell that had slowed their movement by overgrowing the area with thick vines. Joe Bangles and Donnie coordinated attacks, utilizing Hunter’s Mark and ranged strikes to chip away at the undead, while Shifty cast Moonbeam and Starry Whisp to deal radiant damage. Bron’s relentless axe swings and frenzy attacks cleaved through multiple foes, turning the tide of battle. Despite suffering paralysis and necrotic damage that reduced their maximum hit points, the party persevered, employing spells like Hold Person and Thunderwave to control the battlefield.",
      "image_prompt": "Adventurers frantically escaping a crumbling underwater temple. One clutches a glowing blue jewel. Water surges around them, debris falls. The exit is a distant point of light. Sense of urgency and danger."
    }
  ]
}
"""

GET_SESSION_QUERY = """
query GetSession($id: ID!) {
  getSession(id: $id) {
    id
    _version
    audioFile
    owner
    campaign {
      id
    }
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
    primaryImage # Added primaryImage to response
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
    index # Added index to response
    sessionSegmentsId
    owner
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

        response = openai_client.images.generate(
            model="gpt-image-1", # User requested not to change model IDs
            prompt=full_prompt,
            n=1,
            size="1536x1024", # User requested not to change parameters
            quality="low" # User requested not to change parameters
        )

        if response.data and response.data[0].b64_json:
            image_data_b64 = response.data[0].b64_json
            image_bytes = base64.b64decode(image_data_b64) 

            image_filename = f"{session_id}_segment_{segment_index + 1}.png" 
            s3_image_key = f"{s3_base_prefix.rstrip('/')}/{image_filename}"

            if debug:
                print(f"Uploading image to S3: s3://{s3_bucket}/{s3_image_key}")

            s3_client.put_object(
                Bucket=s3_bucket,
                Key=s3_image_key,
                Body=image_bytes,
                ContentType='image/png' 
            )

            if debug:
                print(f"Image successfully uploaded. S3 Key: {s3_image_key}")
            return s3_image_key 
        else:
            print("Failed to generate image or received no b64_json data from OpenAI. The API response structure might have changed or an error occurred.")
            if debug and response:
                print(f"OpenAI API Response Data: {response.data}")
            return None

    except openai.APIError as e: 
        print(f"OpenAI API error during image generation: {e}")
        return None
    except AttributeError as e: 
        print(f"AttributeError during image processing (likely response structure changed or missing b64_json): {e}")
        if debug and 'response' in locals():
            print(f"Full OpenAI API Response object: {response}")
        traceback.print_exc()
        return None
    except Exception as e: 
        print(f"An unexpected error occurred during image generation or upload: {e}")
        traceback.print_exc() 
        return None

# --- Helper function to parse Session ID from filename stem ---
def parse_session_id_from_stem(filename_stem: str) -> Optional[str]:
    """
    Parses the Session UUID from a filename stem like 'campaign<UUID>Session<SESSION_UUID>'.
    Example: 'campaign727cc722-1e8a-40b9-bf33-c9a5d982f629Session4ad02dcd-38c1-48b3-a0c2-b04ee9e1efbf'
    Returns the Session UUID (e.g., '4ad02dcd-38c1-48b3-a0c2-b04ee9e1efbf') or None if not found.
    """
    match = re.search(r"Session([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})", filename_stem)
    if match:
        return match.group(1) 
    return None

# --- Lambda Handler ---
def lambda_handler(event, context):
    session_info = None 
    key = None 
    debug = True 
    s3_image_upload_bucket = None
    # updated_session_data will store the result of the *final* UpdateSession mutation if successful
    # It's also used by the exception handler to get the latest version if an error occurs.
    updated_session_data_from_final_update = None 

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
        s3_metadata_prefix = 'public/session_metadata/'

        original_filename_with_ext = os.path.basename(key) 
        filename_stem_for_search = os.path.splitext(original_filename_with_ext)[0] 
                                                                                
        if debug:
            print(f"Processing transcript file: {key} from bucket: {s3_transcript_bucket}")
            print(f"Images will be uploaded to bucket: {s3_image_upload_bucket} under prefix: {s3_segment_image_prefix}")
            print(f"Original S3 filename (from event object key): {original_filename_with_ext}")
            print(f"Filename stem for AppSync search AND metadata: {filename_stem_for_search}")

        parsed_session_id = parse_session_id_from_stem(filename_stem_for_search)

        if not parsed_session_id:
            msg = f"Could not parse Session ID from filename stem: '{filename_stem_for_search}'. Cannot proceed."
            print(msg)
            raise ValueError(msg)
        
        if debug:
            print(f"Parsed Session ID for direct query: {parsed_session_id}")

        print(f"Attempting to fetch Session directly with ID: {parsed_session_id}")
        get_session_vars = {"id": parsed_session_id}
        session_response_gql = execute_graphql_request(GET_SESSION_QUERY, get_session_vars)

        if "errors" in session_response_gql and not session_response_gql.get("data"):
            raise Exception(f"Critical error fetching session via GetSession(id: {parsed_session_id}): {session_response_gql['errors']}")

        session_info = session_response_gql.get("data", {}).get("getSession") # Store initial session data

        if not session_info:
            msg = f"No AppSync Session found via GetSession for ID '{parsed_session_id}' derived from filename stem '{filename_stem_for_search}'."
            print(msg)
            raise ValueError(msg) 
        
        if debug:
            print(f"Successfully fetched session via GetSession: {json.dumps(session_info)}")
        
        session_id = session_info["id"]
        initial_session_version = session_info["_version"] # Store initial version for final update

        # --- Fetch Session Metadata ---
        session_metadata_content = {}
        metadata_instructions_str = "Not provided."
        metadata_adventurers_str = "Not provided."
        metadata_locations_str = "Not provided."
        metadata_npcs_str = "Not provided."

        metadata_filename = f"{filename_stem_for_search}.metadata.json"
        metadata_s3_key = f"{s3_metadata_prefix.rstrip('/')}/{metadata_filename}"

        if debug:
            print(f"Attempting to fetch session metadata from: s3://{s3_transcript_bucket}/{metadata_s3_key}")
        try:
            metadata_obj = s3_client.get_object(Bucket=s3_transcript_bucket, Key=metadata_s3_key)
            metadata_file_content = metadata_obj['Body'].read().decode('utf-8')
            session_metadata_content = json.loads(metadata_file_content)
            if debug: print(f"Successfully fetched and parsed metadata: {json.dumps(session_metadata_content)}")
            metadata_instructions_str = session_metadata_content.get("instructions", "Not provided.")
            adventurers_list = session_metadata_content.get("adventurers")
            metadata_adventurers_str = "\n- " + "\n- ".join(adventurers_list) if adventurers_list and isinstance(adventurers_list, list) else "Not provided or invalid format."
            locations_list = session_metadata_content.get("locations")
            metadata_locations_str = "\n- " + "\n- ".join(locations_list) if locations_list and isinstance(locations_list, list) else "Not provided or invalid format."
            npcs_list = session_metadata_content.get("npcs")
            metadata_npcs_str = "\n- " + "\n- ".join(npcs_list) if npcs_list and isinstance(npcs_list, list) else "Not provided or invalid format."
        except s3_client.exceptions.NoSuchKey:
            if debug: print(f"Metadata file not found at {metadata_s3_key}. Proceeding without it.")
        except json.JSONDecodeError as e:
            print(f"Error decoding metadata JSON from {metadata_s3_key}: {e}. Proceeding without it.")
        except Exception as e:
            print(f"An unexpected error occurred while fetching or parsing metadata from {metadata_s3_key}: {e}. Proceeding without it.")
            traceback.print_exc()
        # --- End of Fetch Session Metadata ---

        segment_owner_value_for_appsync = None
        session_table = dynamodb_resource.Table(DYNAMODB_TABLE_NAME)
        try:
            if debug: print(f"Fetching session item directly from DynamoDB table '{DYNAMODB_TABLE_NAME}' using ID: {session_id} (for owner field)")
            response_ddb = session_table.get_item(Key={'id': session_id})
            if 'Item' in response_ddb:
                dynamodb_session_item = response_ddb['Item']
                segment_owner_value_for_appsync = dynamodb_session_item.get("owner")
                if debug: print(f"Owner value retrieved directly from DynamoDB: '{segment_owner_value_for_appsync}'")
                if not segment_owner_value_for_appsync: print(f"Warning: 'owner' field is missing or empty in DynamoDB item for Session {session_id}.")
                elif "::" not in segment_owner_value_for_appsync: print(f"Warning: Session {session_id} owner field ('{segment_owner_value_for_appsync}') from DynamoDB does not contain '::'.")
            else: print(f"Warning: Session item with ID '{session_id}' NOT found directly in DynamoDB table '{DYNAMODB_TABLE_NAME}' for owner lookup.")
        except Exception as ddb_e:
            print(f"Error fetching session owner directly from DynamoDB table '{DYNAMODB_TABLE_NAME}': {str(ddb_e)}. Segments may be created without an owner.")
            traceback.print_exc()
        if not segment_owner_value_for_appsync: print(f"Warning: Session {session_id} will have segments created with a null or empty owner.")

        if debug:
            print(f"Using Session ID: {session_id} (initial_v: {initial_session_version}), Effective Segment Owner: {segment_owner_value_for_appsync}")

        campaign_id = session_info.get("campaign", {}).get("id")
        if not campaign_id: print(f"Warning: Session {session_id} lacks campaign ID. NPC context will be limited.")
        if debug: print(f"Associated audioFile from GetSession AppSync: {session_info.get('audioFile')}")

        npc_context_string_campaign = "No specific NPC context available from campaign."
        if campaign_id:
            print(f"Fetching NPCs for Campaign ID: {campaign_id}")
            all_npc_items, npc_current_next_token, npc_pages_queried, MAX_PAGES_NPC = [], None, 0, 25
            while npc_pages_queried < MAX_PAGES_NPC: 
                npc_pages_queried +=1
                npc_query_vars = {"campaignId": campaign_id, "limit": 50, "nextToken": npc_current_next_token}
                npc_response_gql = execute_graphql_request(GET_NPCS_BY_CAMPAIGN_QUERY, npc_query_vars)
                if "errors" in npc_response_gql and not npc_response_gql.get("data"):
                    print(f"Warning: GraphQL error during GetNpcs: {npc_response_gql['errors']}. Proceeding without full NPC context."); break
                npc_data = npc_response_gql.get("data", {}).get("campaignNpcsByCampaignId", {})
                all_npc_items.extend(npc_data.get("items", []))
                npc_current_next_token = npc_data.get("nextToken")
                if not npc_current_next_token: break
            npc_details = [f"- {item.get('nPC', {}).get('name', 'Unknown NPC')}: {item.get('nPC', {}).get('brief', 'No brief.')}" for item in all_npc_items if item.get("nPC")]
            npc_context_string_campaign = "Relevant NPCs in this campaign:\n" + "\n".join(npc_details) if npc_details else "No NPCs found for this campaign."
            if debug: print(f"NPC Context String (Campaign):\n{npc_context_string_campaign}")
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
  b. 'description': A very detailed narrative of events, actions, character interactions, plot twists, and key moments in that segment (5-8 sentences)
  c. 'image_prompt': A concise, visually descriptive prompt (max 2-3 sentences) suitable for generating an image for this segment using a model like DALL-E. This prompt should capture the visual essence of the segment (key characters, setting, action, mood). DO NOT include the prefix 'fantasy-style painting in the dungeons and dragons DND theme... ' in this 'image_prompt' field; the system will add it automatically.

The output must be a JSON object matching the Pydantic model `SummaryElements` which includes `tldr` (a string) and `sessionSegments` (a list of objects, where each object has `title` (string), `description` (string), and `image_prompt` (string)).

Session Transcript:
<session_text>
{text_to_summarize}
</session_text>

User-Provided Instructions (if any from metadata):
<user_instructions>
{metadata_instructions_str}
</user_instructions>

Key Adventurers from Metadata (if any):
<adventurers_metadata>
{metadata_adventurers_str}
</adventurers_metadata>

Key Locations from Metadata (if any):
<locations_metadata>
{metadata_locations_str}
</locations_metadata>

Key NPCs from Metadata (if any):
<npcs_metadata>
{metadata_npcs_str}
</npcs_metadata>

NPC Context from Campaign (use for names and roles, if available):
<npc_context_campaign>
{npc_context_string_campaign}
</npc_context_campaign>

Example Output Structure (follow this JSON format precisely):
<example_summary>
{example_summary_for_segments_with_images}
</example_summary>

Guidelines for Segments:
- Chronological order.
- Divide the session into 2-5 meaningful segments.
- Distinct parts of the session (e.g., exploration, social interaction, combat, major plot points).
- Detailed, narrative descriptions.
- Use character/NPC names as mentioned in the transcript or any provided context (metadata, campaign).
- Mention important locations, items, or loot if applicable.
- The 'image_prompt' field from the LLM should be just the specific details for that segment, not the DND theme prefix.
"""
        if debug:
            print(f"Full prompt for OpenAI:\n{prompt[:1000]}...\n...\n...{prompt[-500:]}") 

        def get_openai_summary_segments_with_image_prompts(prompt_text: str, model: str = "gpt-4.1-mini") -> Optional[SummaryElements]:
            messages = [{"role": "user", "content": prompt_text}]
            try:
                completion = openai_client.chat.completions.create(
                    model=model, # User requested not to change model IDs
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0.2, # User requested not to change parameters
                )
                if completion.choices and completion.choices[0].message and completion.choices[0].message.content:
                    json_content = completion.choices[0].message.content
                    if debug: print(f"Raw OpenAI JSON (summary/segments/prompts):\n{json_content}")
                    return SummaryElements.model_validate_json(json_content)
                else: print("OpenAI response for summary/segments lacked content or choices."); return None
            except openai.APIError as e: print(f"OpenAI API error during summary/segment generation: {e}"); return None
            except Exception as e: print(f"Error calling OpenAI for summary/segments or parsing/validating response: {e}"); traceback.print_exc(); return None

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
        
        # --- Segment Processing and Image Generation ---
        print(f"Processing {len(summary_elements_response.sessionSegments)} segments for image generation and AppSync creation...")
        created_segment_appsync_details = []
        segment_processing_errors = []
        first_segment_image_s3_key = None # To store the S3 key for the first segment's image

        for idx, segment in enumerate(summary_elements_response.sessionSegments):
            segment_image_s3_key_or_none = None
            try:
                print(f"Processing segment {idx + 1}/{len(summary_elements_response.sessionSegments)}: '{segment.title}'")

                if segment.image_prompt:
                    segment_image_s3_key_or_none = generate_and_upload_image(
                        prompt_suffix=segment.image_prompt,
                        s3_bucket=s3_image_upload_bucket,
                        s3_base_prefix=s3_segment_image_prefix,
                        session_id=session_id,
                        segment_index=idx,
                        debug=debug
                    )
                    if idx == 0 and segment_image_s3_key_or_none: # Check if it's the first segment and image was generated
                        first_segment_image_s3_key = segment_image_s3_key_or_none
                        if debug: print(f"First segment image S3 key set to: {first_segment_image_s3_key}")
                else:
                    if debug: print(f"Skipping image generation for segment '{segment.title}' as image_prompt is empty.")

                create_segment_input = {
                    "sessionSegmentsId": session_id,
                    "title": segment.title,
                    "description": [segment.description] if segment.description else [],
                    "image": segment_image_s3_key_or_none,
                    "owner": segment_owner_value_for_appsync,
                    "index": -idx # Added 0-based index
                }
                
                if segment_owner_value_for_appsync is None:
                    print(f"Warning: Attempting to create segment '{segment.title}' for session '{session_id}' with a null owner value.")

                segment_vars = {"input": create_segment_input}
                segment_response = execute_graphql_request(CREATE_SEGMENT_MUTATION, segment_vars)

                created_segment_data = None
                if segment_response and isinstance(segment_response.get("data"), dict):
                    created_segment_data = segment_response["data"].get("createSegment")

                if created_segment_data and created_segment_data.get("id"):
                    created_segment_appsync_details.append(created_segment_data)
                    print(f"Successfully created segment ID: {created_segment_data['id']} - '{segment.title}' (Index: {created_segment_data.get('index')}, Image Key: {created_segment_data.get('image', 'N/A')}, Owner: {created_segment_data.get('owner')})")
                else:
                    appsync_errors = segment_response.get('errors') if isinstance(segment_response, dict) else 'execute_graphql_request returned non-dict or None for segment creation'
                    error_details_str = json.dumps(appsync_errors) if isinstance(appsync_errors, list) and len(appsync_errors) > 0 else str(appsync_errors) if appsync_errors else "No specific error details in response."
                    err_msg = f"Failed to create segment '{segment.title}' in AppSync or no segment data returned. AppSync Response: {error_details_str}"
                    print(err_msg)
                    segment_processing_errors.append(err_msg)
                    if "The variables input contains a field that is not defined for input object type 'CreateSegmentInput'" in error_details_str:
                        print("ADVICE: Verify your AppSync schema's 'CreateSegmentInput' definition against these fields being sent:")
                        print(f"Sent fields for CreateSegmentInput: {list(create_segment_input.keys())}")
            
            except Exception as seg_proc_e:
                err_msg = f"Exception during processing segment '{segment.title}' (image gen or AppSync create): {str(seg_proc_e)}"
                print(err_msg); segment_processing_errors.append(err_msg)
                traceback.print_exc()

        if segment_processing_errors:
            # If there were errors creating segments, do not proceed to set session to READ.
            # Instead, aggregate errors and raise an exception to be caught by the main handler, which will set session to ERROR.
            aggregated_error_message = f"Encountered {len(segment_processing_errors)} error(s) during segment processing for session {session_id}. First error: {segment_processing_errors[0]}"
            print(aggregated_error_message)
            for i, error_detail in enumerate(segment_processing_errors): print(f"  Segment Error {i+1}: {error_detail}")
            raise Exception(aggregated_error_message)

        print(f"Successfully processed and created {len(created_segment_appsync_details)} out of {len(summary_elements_response.sessionSegments)} segments for session {session_id}.")

        # --- Final Session Update (TLDR, Primary Image, Status to READ) ---
        print(f"Updating Session {session_id} with TLDR, Primary Image, and status to READ via AppSync...")
        final_update_input = {
            "id": session_id,
            "_version": initial_session_version, # Use the version from the initial GetSession call
            "transcriptionStatus": "READ",
            "tldr": [summary_elements_response.tldr] if summary_elements_response.tldr else [],
            "primaryImage": first_segment_image_s3_key, # Set the primary image from the first segment
            "errorMessage": None 
        }
        final_update_vars = {"input": final_update_input}

        final_update_response_gql = execute_graphql_request(UPDATE_SESSION_MUTATION, final_update_vars)
        if "errors" in final_update_response_gql and not final_update_response_gql.get("data", {}).get("updateSession"):
            raise Exception(f"Final AppSync mutation to update Session to READ state failed: {final_update_response_gql['errors']}")

        updated_session_data_from_final_update = final_update_response_gql.get("data", {}).get("updateSession")
        if not updated_session_data_from_final_update or "_version" not in updated_session_data_from_final_update:
            raise Exception("Final AppSync Session update mutation (to READ) returned no data, unexpected structure, or missing _version.")

        new_session_version = updated_session_data_from_final_update["_version"]
        print(f"Successfully updated Session {session_id} to READ state. New version: {new_session_version}. Primary Image: {updated_session_data_from_final_update.get('primaryImage')}")

        return {
            'statusCode': 200,
            'body': json.dumps(f"Processed successfully: {key}. TLDR, Primary Image, and {len(created_segment_appsync_details)} segments created/updated. Session status set to READ.")
        }

    except Exception as e:
        error_message = str(e)
        print(f"FATAL Error processing file {key if key else 'unknown'}: {error_message}")
        traceback.print_exc()

        if session_info and 'id' in session_info: # Check if session_id and initial_version are available
            session_id_for_error = session_info['id']
            # Use the version from the final update if it happened, otherwise use initial version.
            # If an error occurred *before* the final update attempt, updated_session_data_from_final_update would be None.
            session_version_for_error = updated_session_data_from_final_update["_version"] if updated_session_data_from_final_update and "_version" in updated_session_data_from_final_update else session_info.get('_version', 1) # Fallback to initial or 1
            
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
            print("Cannot update session to ERROR state: session_info not available (e.g., GetSession failed or ID parsing error).")

        return {
            "statusCode": 500,
            "body": json.dumps(f"Error processing file: {error_message}")
        }
