# --- Standard Library Imports ---
import os
import json
import urllib.parse
from typing import List, Optional, Dict, Any
import re
import traceback

# --- Third-party Library Imports ---
import requests
import boto3
from pydantic import BaseModel, Field
import openai
from openai import OpenAI

# --- CONFIGURATION ---
OPENAI_API_KEY_FROM_ENV = os.environ.get('OPENAI_API_KEY')
APPSYNC_API_URL = os.environ.get('APPSYNC_API_URL')
APPSYNC_API_KEY_FROM_ENV = os.environ.get('APPSYNC_API_KEY')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-2')
DYNAMODB_TABLE_NAME = os.environ.get('DYNAMODB_TABLE')

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
s3_client = boto3.client("s3", region_name=AWS_REGION)
dynamodb_resource = boto3.resource('dynamodb', region_name=AWS_REGION)
openai_client = OpenAI(api_key=OPENAI_API_KEY_FROM_ENV)

# --- Pydantic Data Models ---
class SegmentElement(BaseModel):
    title: str = Field(description="The title of this specific segment of the session.")
    description: str = Field(description="A detailed textual description of what happened in this segment.")
    image_prompt: str = Field(description="A concise, visually descriptive prompt for image generation.")

class HighlightElement(BaseModel):
    name: str = Field(description="The name of the adventurer, location, or NPC.")
    highlights: List[str] = Field(description="A list of key moments or actions related to this entity.")
    id: Optional[str] = Field(None, description="The ID of the entity, if it exists in the campaign.")
    is_new: bool = Field(default=False, description="Whether this is a new entity not found in the campaign.")

class NarrativeSummary(BaseModel):
    """Output model for the narrative summary generation."""
    tldr: str = Field(description="A concise summary of the entire session.")
    sessionName: Optional[str] = Field(None, description="A generated session title (3-7 words).")
    sessionSegments: List[SegmentElement] = Field(description="Chronological segments of the session.")
    adventurerHighlights: List[HighlightElement] = Field(description="Highlights for adventurers.")
    locationHighlights: List[HighlightElement] = Field(description="Highlights for locations.")
    npcHighlights: List[HighlightElement] = Field(description="Highlights for NPCs.")

# --- Lookup Tables ---
image_quality_lookup = {
    "Low quality": "low",
    "Standard quality": "medium",
    "High quality": "high"
}

image_format_lookup = {
    "fantasy": {
        "name": "Default",
        "longDescription": "A semi-photorealistic fantasy style with bold, directional lighting, rich color saturation, and cinematic composition."
    },
    "dark-fantasy": {
        "name": "Dark fantasy",
        "longDescription": "A cinematic stylized realism with rich color depth and dynamic lighting. The palette uses vibrant yet grounded tones with strong value contrast."
    },
    "watercolor": {
        "name": "Watercolor",
        "longDescription": "A refined watercolor style that preserves the medium's softness and translucency while enhancing structure and depth."
    },
    "Sketchbook": {
        "name": "Sketchbook",
        "longDescription": "A traditional pen-and-ink illustration style with muted, earthy tones and fine crosshatching."
    },
    "photo-releastic": {
        "name": "Photo realistic",
        "longDescription": "A lifelike, cinematic style with natural lighting, vibrant colors, sharp detail, and dramatic depth of field."
    },
    "cyberpunk": {
        "name": "Cyberpunk",
        "longDescription": "A cinematic, futuristic rendering style defined by luminous contrast and rich neon hues."
    },
    "retro-vibrant": {
        "name": "Retro illustration",
        "longDescription": "A bold, 1980s fantasy style with vivid colors, heroic poses, and painterly textures."
    },
    "graphic-novel": {
        "name": "Graphic Novel",
        "longDescription": "A clean, inked comic style with vibrant colors, balanced outlines, and cinematic composition."
    },
    "ink-sketch": {
        "name": "B&W ink sketch",
        "longDescription": "A rough, black-and-white ink style with scratchy lines, heavy cross-hatching, and surreal fantasy elements."
    },
    "retro": {
        "name": "Retro video game",
        "longDescription": "A pixelated, 8-bit style with chunky forms, limited palettes, and nostalgic charm."
    },
    "3d-animation": {
        "name": "3D Animation",
        "longDescription": "A polished 3D style with stylized characters, expressive faces, and cinematic lighting."
    },
    "anime": {
        "name": "Anime",
        "longDescription": "A vibrant, cel-shaded style with dynamic poses, clean lines, and painterly backgrounds."
    },
    "studio-ghibli": {
        "name": "Studio Ghibli",
        "longDescription": "A Studio Ghibli film scene"
    },
    "painting": {
        "name": "Painterly",
        "longDescription": "A painterly, realistic style with warm lighting, rich detail, and heroic figures in vast, mythic landscapes."
    }
}

example_summary = """
{
  "tldr": "The adventurers navigated the treacherous Sunken City, defeated a kraken cultist leader, and recovered the Tidejewel.",
  "sessionName": "Descent into the Sunken City",
  "sessionSegments": [
    {
      "title": "Descent into the Sunken City",
      "description": "The adventurers carefully explored a mysterious underground tomb...",
      "image_prompt": "A fantasy adventuring party cautiously entering a dark, vine-covered stone archway..."
    }
  ],
  "adventurerHighlights": [
    {
      "name": "Bron",
      "highlights": ["Attempted to smash a crystal window", "Dealt significant damage with axe swings"],
      "id": null,
      "is_new": false
    }
  ],
  "locationHighlights": [
    {
      "name": "The Sunken City",
      "highlights": ["Explored a mysterious underground tomb"],
      "id": null,
      "is_new": true
    }
  ],
  "npcHighlights": [
    {
      "name": "Cultist Leader",
      "highlights": ["Animated desiccated corpses to attack the party"],
      "id": null,
      "is_new": true
    }
  ]
}
"""

# --- GraphQL Queries ---
GET_SESSION_QUERY = "query GetSession($id: ID!) { getSession(id: $id) { id _version audioFile owner campaign { id } } }"

GET_NPCS_BY_CAMPAIGN_QUERY = """
query CampaignNpcsByCampaignId($campaignId: ID!, $limit: Int, $nextToken: String) {
  campaignNpcsByCampaignId(campaignId: $campaignId, limit: $limit, nextToken: $nextToken) {
    items { nPC { id name } }
    nextToken
  }
}
"""

GET_ADVENTURERS_BY_CAMPAIGN_QUERY = """
query CampaignAdventurersByCampaignId($campaignId: ID!, $limit: Int, $nextToken: String) {
  campaignAdventurersByCampaignId(campaignId: $campaignId, limit: $limit, nextToken: $nextToken) {
    items { adventurer { id name } }
    nextToken
  }
}
"""

GET_LOCATIONS_BY_CAMPAIGN_QUERY = """
query CampaignLocationsByCampaignId($campaignId: ID!, $limit: Int, $nextToken: String) {
  campaignLocationsByCampaignId(campaignId: $campaignId, limit: $limit, nextToken: $nextToken) {
    items { location { id name } }
    nextToken
  }
}
"""


# --- AppSync Helper Function ---
def execute_graphql_request(query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Executes a GraphQL query/mutation against AppSync."""
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
    except requests.exceptions.RequestException as e:
        print(f"Error making AppSync request: {e}")
        return {"errors": [{"message": str(e)}]}


def parse_session_id_from_stem(filename_stem: str) -> Optional[str]:
    """Parses the Session UUID from a filename stem."""
    match = re.search(r"Session([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})", filename_stem)
    return match.group(1) if match else None


def fetch_campaign_data(campaign_id: str, query: str, data_key: str, item_key: str, debug: bool = False):
    """Fetches paginated campaign data (NPCs, Adventurers, Locations)."""
    if not campaign_id:
        return [], f"No {item_key} context available from campaign."
    
    print(f"Fetching {data_key} for Campaign ID: {campaign_id}")
    all_items, next_token, pages_queried, max_pages = [], None, 0, 25
    
    while pages_queried < max_pages:
        pages_queried += 1
        query_vars = {"campaignId": campaign_id, "limit": 50, "nextToken": next_token}
        response_gql = execute_graphql_request(query, query_vars)
        
        if "errors" in response_gql and not response_gql.get("data"):
            print(f"Warning: GraphQL error during Get{data_key}: {response_gql['errors']}")
            break
            
        data = response_gql.get("data", {}).get(f"campaign{data_key}ByCampaignId", {})
        all_items.extend(data.get("items", []))
        next_token = data.get("nextToken")
        if not next_token:
            break
    
    details = []
    for item in all_items:
        if item.get(item_key):
            name = item.get(item_key, {}).get('name', f'Unknown {item_key}')
            item_id = item.get(item_key, {}).get('id')
            details.append(f"- {name} (ID: {item_id})")

    context_string = f"Relevant {data_key} in this campaign:\n" + "\n".join(details) if details else f"No {data_key} found for this campaign."
    return all_items, context_string


def llm_match_entity(query_name: str, candidate_names: List[str], entity_type: str, debug: bool = False) -> Optional[str]:
    """Uses LLM to intelligently match an entity name to candidates."""
    if not candidate_names:
        return None
    
    candidates_list = "\n".join(f"- {name}" for name in candidate_names)
    prompt = f"""You are helping match entity names in a TTRPG session summary.

Task: Determine if "{query_name}" refers to any of these known {entity_type}s:
{candidates_list}

Rules:
1. Return ONLY the exact matching name from the list above, or "NO_MATCH" if none match
2. Consider variations like full names vs nicknames, spelling variations
3. Be strict: only match if confident they refer to the same entity

Response (one line only):"""

    try:
        response = openai_client.chat.completions.create(
            model="gpt-5-mini",
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=50
        )
        result = response.choices[0].message.content.strip()
        
        if result == "NO_MATCH":
            return None
        if result in candidate_names:
            return result
        return None
    except Exception as e:
        print(f"Error in LLM entity matching: {e}")
        return None


def map_ids_to_highlights(highlights: List[HighlightElement], authoritative_entities: List[Dict], 
                          entity_key: str, debug: bool = False):
    """Maps entity IDs to highlights and marks new entities."""
    name_to_id_map = {}
    original_case_map = {}
    
    for entity in authoritative_entities:
        name = entity.get('name') or entity.get(entity_key, {}).get('name', '')
        entity_id = entity.get('id') or entity.get(entity_key, {}).get('id')
        if name and entity_id:
            name_to_id_map[name.lower()] = entity_id
            original_case_map[name.lower()] = name

    canonical_names = list(original_case_map.values())

    for highlight in highlights:
        highlight.id = None
        highlight.is_new = False
        highlight_name_lower = highlight.name.lower()

        # Direct match
        if highlight_name_lower in name_to_id_map:
            highlight.id = name_to_id_map[highlight_name_lower]
            print(f"✅ Direct match: '{highlight.name}' → ID '{highlight.id}'")
            continue

        # LLM fuzzy match
        matched_name = llm_match_entity(highlight.name, canonical_names, entity_key, debug)
        if matched_name:
            matched_id = name_to_id_map.get(matched_name.lower())
            if matched_id:
                highlight.id = matched_id
                print(f"✅ LLM match: '{highlight.name}' → '{matched_name}' (ID: {matched_id})")
                continue

        # No match - mark as new entity
        highlight.is_new = True
        print(f"🆕 New entity: '{highlight.name}' (no match found)")


# --- Lambda Handler ---
def lambda_handler(event, context):
    """
    Generate narrative summary from transcript.
    
    Input: { bucket, key, sessionId, userTransactionsTransactionsId, creditsToRefund }
    Output: { narrativeSummaryS3Key, imageSettings, entityMentions, generateLore, generateName, ... }
    """
    debug = False
    session_info = None
    
    try:
        print("Starting generate-narrative-summary")
        
        # Parse input
        s3_bucket = event["bucket"]
        key = urllib.parse.unquote_plus(event["key"], encoding='utf-8')
        
        print(f"Processing transcript: {key}")

        # Extract filename components
        original_filename = os.path.basename(key)
        filename_stem = os.path.splitext(original_filename)[0]
        
        metadata_stem_match = re.match(r"(campaign[0-9a-fA-F-]+Session[0-9a-fA-F-]+)", filename_stem)
        filename_stem_for_metadata = metadata_stem_match.group(1) if metadata_stem_match else filename_stem

        # Parse session ID
        parsed_session_id = parse_session_id_from_stem(filename_stem)
        if not parsed_session_id:
            raise ValueError(f"Could not parse Session ID from: '{filename_stem}'")

        # Fetch session from AppSync
        print(f"Fetching session: {parsed_session_id}")
        session_response = execute_graphql_request(GET_SESSION_QUERY, {"id": parsed_session_id})
        
        if "errors" in session_response and not session_response.get("data"):
            raise Exception(f"Error fetching session: {session_response['errors']}")

        session_info = session_response.get("data", {}).get("getSession")
        if not session_info:
            raise ValueError(f"No session found for ID '{parsed_session_id}'")

        session_id = session_info["id"]
        campaign_id = session_info.get("campaign", {}).get("id")

        # Get owner from DynamoDB
        owner = None
        try:
            session_table = dynamodb_resource.Table(DYNAMODB_TABLE_NAME)
            ddb_response = session_table.get_item(Key={'id': session_id})
            if 'Item' in ddb_response:
                owner = ddb_response['Item'].get("owner")
        except Exception as e:
            print(f"Warning: Error fetching owner from DynamoDB: {e}")

        # --- Fetch Session Metadata ---
        print("Fetching session metadata")
        metadata_s3_key = f"public/session-metadata/{filename_stem_for_metadata}.metadata.json"
        
        # Defaults
        gen_content_length_str = "Segment length should be 4-5 sentences."
        gen_content_style_str = "Write in a balanced, narrative style."
        gen_tones_str = "Use a neutral, standard TTRPG tone."
        gen_emphases_str = "Give balanced attention to all aspects of the session."
        gen_quotes_str = "You may include character quotes if they are impactful."
        gen_mechanics_str = "Focus on the narrative events over game mechanics."
        metadata_instructions_str = "Not provided."
        
        img_enabled = True
        img_quality = 'medium'
        img_style_prompt = image_format_lookup["fantasy"]["longDescription"]
        
        generate_lore = False
        generate_name = False

        try:
            metadata_obj = s3_client.get_object(Bucket=s3_bucket, Key=metadata_s3_key)
            metadata_content = json.loads(metadata_obj['Body'].read().decode('utf-8'))
            print("Metadata loaded successfully")

            # Parse generation instructions
            gen_instructions = metadata_content.get("generation_instructions", {})
            if gen_instructions:
                length_val = gen_instructions.get("contentLength", 0.5)
                if length_val < 0.33:
                    gen_content_length_str = "Each segment should be short and concise, around 2-4 sentences."
                elif length_val > 0.66:
                    gen_content_length_str = "Each segment should be highly detailed, around 6-8 sentences."
                
                style_val = gen_instructions.get("contentStyle", 0.5)
                if style_val < 0.33:
                    gen_content_style_str = "Write in a direct, factual, to-the-point style."
                elif style_val > 0.66:
                    gen_content_style_str = "Write in a highly narrative, descriptive, and dramatic manner."

                tones = gen_instructions.get("selectedTones")
                if tones and isinstance(tones, list):
                    gen_tones_str = f"Adopt the following tones: {', '.join(tones)}."

                emphases = gen_instructions.get("selectedEmphases")
                if emphases and isinstance(emphases, list):
                    gen_emphases_str = f"Place special emphasis on: {', '.join(emphases)}."

                if gen_instructions.get("includeCharacterQuotes"):
                    gen_quotes_str = "You MUST include direct quotes from characters."
                if gen_instructions.get("includeGameMechanics"):
                    gen_mechanics_str = "You MUST include references to game mechanics."

            # Parse image instructions
            image_instructions = metadata_content.get("image_instructions", {})
            if image_instructions:
                img_enabled = image_instructions.get("imageGenerationEnabled", True)
                quality_key = image_instructions.get("imageQuality", "medium")
                img_quality = image_quality_lookup.get(quality_key, "medium")
                style_key = image_instructions.get("selectedStyle", "fantasy")
                img_style_prompt = image_format_lookup.get(style_key, {}).get("longDescription", img_style_prompt)

            # Parse new flags
            generate_lore = metadata_content.get("generate_lore", False)
            generate_name = metadata_content.get("generate_name", False)
            
            metadata_instructions_str = metadata_content.get("instructions", "Not provided.")

        except s3_client.exceptions.NoSuchKey:
            print("Warning: Metadata file not found. Using defaults.")
        except Exception as e:
            print(f"Warning: Error fetching metadata: {e}")

        # --- Fetch Campaign Context ---
        print("Fetching campaign context")
        all_npcs, npc_context = fetch_campaign_data(campaign_id, GET_NPCS_BY_CAMPAIGN_QUERY, 'Npcs', 'nPC', debug)
        all_adventurers, adventurer_context = fetch_campaign_data(campaign_id, GET_ADVENTURERS_BY_CAMPAIGN_QUERY, 'Adventurers', 'adventurer', debug)
        all_locations, location_context = fetch_campaign_data(campaign_id, GET_LOCATIONS_BY_CAMPAIGN_QUERY, 'Locations', 'location', debug)

        # --- Read Transcript ---
        print("Reading transcript from S3")
        transcript_obj = s3_client.get_object(Bucket=s3_bucket, Key=key)
        transcript_text = transcript_obj['Body'].read().decode('utf-8')
        
        if not transcript_text.strip():
            raise ValueError(f"Transcript file {key} is empty.")

        # --- Build LLM Prompt ---
        session_name_instruction = ""
        if generate_name:
            session_name_instruction = """
Additionally, generate a compelling session title (3-7 words) that captures the essence of this session's events. 
Return it in the "sessionName" field. If not generating a name, set sessionName to null."""

        prompt = f"""You are Scribe, an AI assistant that summarizes TTRPG sessions.
Generate a JSON object containing a TLDR, chronological session segments, and highlights for adventurers, locations, and NPCs.

<generation_instructions>
- Writing Style: {gen_content_style_str}
- Content Length: {gen_content_length_str}
- Tone: {gen_tones_str}
- Emphasis: {gen_emphases_str}
- Character Quotes: {gen_quotes_str}
- Game Mechanics: {gen_mechanics_str}
</generation_instructions>

{session_name_instruction}

Output a JSON object with:
- `tldr`: A string summary of the whole session.
- `sessionName`: A generated title (3-7 words) or null.
- `sessionSegments`: A list of 3-5 chronological segments, each with 'title', 'description', 'image_prompt'.
- `adventurerHighlights`, `locationHighlights`, `npcHighlights`: Lists with 'name', 'highlights' (list of strings), 'id' (null), 'is_new' (boolean - true if entity is NOT in the campaign context below).

Mark entities as is_new=true if they appear in the transcript but are NOT listed in the campaign context below.

Session Transcript:
<session_text>
{transcript_text}
</session_text>

User Instructions:
<user_instructions>
{metadata_instructions_str}
</user_instructions>

Campaign Context (existing entities):
<npc_context>
{npc_context}
</npc_context>
<adventurer_context>
{adventurer_context}
</adventurer_context>
<location_context>
{location_context}
</location_context>

Example Output:
{example_summary}
"""

        # --- Call LLM ---
        print("Generating summary with LLM")
        try:
            completion = openai_client.chat.completions.create(
                model="gpt-5.1",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            
            if not completion.choices or not completion.choices[0].message.content:
                raise Exception("OpenAI response lacked content")
                
            json_content = completion.choices[0].message.content
            summary = NarrativeSummary.model_validate_json(json_content)
            
        except Exception as e:
            print(f"Error calling OpenAI: {e}")
            traceback.print_exc()
            raise Exception(f"Failed to generate summary: {e}")

        print("Summary generated successfully")

        # --- Map Entity IDs ---
        print("Mapping entity IDs")
        map_ids_to_highlights(summary.adventurerHighlights, all_adventurers, 'adventurer', debug)
        map_ids_to_highlights(summary.npcHighlights, all_npcs, 'nPC', debug)
        map_ids_to_highlights(summary.locationHighlights, all_locations, 'location', debug)

        # --- Write Summary to S3 ---
        print("Writing narrative summary to S3")
        summary_s3_key = f"public/summaries/narrative/{filename_stem_for_metadata}.json"
        s3_client.put_object(
            Bucket=s3_bucket,
            Key=summary_s3_key,
            Body=summary.model_dump_json(indent=2),
            ContentType='application/json'
        )
        print(f"Summary written to: {summary_s3_key}")

        # --- Build Output ---
        # Separate existing vs new entities for downstream processing
        existing_adventurers = [h.model_dump() for h in summary.adventurerHighlights if not h.is_new]
        existing_npcs = [h.model_dump() for h in summary.npcHighlights if not h.is_new]
        existing_locations = [h.model_dump() for h in summary.locationHighlights if not h.is_new]
        
        new_adventurers = [h.model_dump() for h in summary.adventurerHighlights if h.is_new]
        new_npcs = [h.model_dump() for h in summary.npcHighlights if h.is_new]
        new_locations = [h.model_dump() for h in summary.locationHighlights if h.is_new]

        output = {
            "statusCode": 200,
            "narrativeSummaryS3Key": summary_s3_key,
            "sessionId": session_id,
            "sessionName": summary.sessionName if generate_name else None,
            "campaignId": campaign_id,
            "owner": owner,
            "bucket": s3_bucket,
            "transcriptKey": key,
            
            # Image settings for generate-segment-images
            "imageSettings": {
                "enabled": img_enabled,
                "quality": img_quality,
                "stylePrompt": img_style_prompt
            },
            
            # Flags for downstream lambdas
            "generateLore": generate_lore,
            "generateName": generate_name,
            
            # Entity data for downstream processing
            "entityMentions": {
                "existingAdventurers": existing_adventurers,
                "existingNPCs": existing_npcs,
                "existingLocations": existing_locations,
                "newAdventurers": new_adventurers,
                "newNPCs": new_npcs,
                "newLocations": new_locations
            },
            
            # Passthrough fields
            "userTransactionsTransactionsId": event.get("userTransactionsTransactionsId"),
            "creditsToRefund": event.get("creditsToRefund")
        }

        print("generate-narrative-summary completed successfully")
        return output

    except Exception as e:
        error_message = str(e)
        print(f"ERROR: {error_message}")
        traceback.print_exc()
        
        return {
            "statusCode": 500,
            "error": error_message,
            "sessionId": event.get("sessionId"),
            "userTransactionsTransactionsId": event.get("userTransactionsTransactionsId"),
            "creditsToRefund": event.get("creditsToRefund")
        }
