# --- Standard Library Imports ---
import os
import json
import urllib.parse
from typing import List, Optional, Dict, Any, Union
import base64 # For decoding image data
import re # For slugifying titles for filenames
import traceback # Added to be globally available
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- Third-party Library Imports ---
import requests # For making HTTP requests to AppSync
import boto3
from pydantic import BaseModel, Field
import openai # Added for openai.APIError
from openai import OpenAI
from thefuzz import process # For fuzzy string matching

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
    description: str = Field(description="A detailed textual description of what happened in this segment, following the user-defined length and style.")
    image_prompt: str = Field(description="A concise, visually descriptive prompt suitable for generating an image for this segment using gpt-image-1. This prompt should capture the essence of the segment visually.")

class HighlightElement(BaseModel):
    name: str = Field(description="The name of the adventurer, location, or NPC.")
    highlights: List[str] = Field(description="A list of key moments or actions related to this entity during the session.")
    id: Optional[str] = Field(None, description="The ID of the entity, if it exists in the campaign.")

class SummaryElements(BaseModel):
    tldr: str = Field(description="A concise 'too long; didn't read' summary of the entire session.")
    sessionSegments: List[SegmentElement] = Field(description="A list of chronological segments detailing the session's events, each with a title, description, and an image prompt.")
    adventurerHighlights: List[HighlightElement] = Field(description="Highlights for each adventurer involved in the session.")
    locationHighlights: List[HighlightElement] = Field(description="Highlights for each location visited in the session.")
    npcHighlights: List[HighlightElement] = Field(description="Highlights for each NPC that played a role in the session.")

image_quality_lookup = {
    "Low quality": "low", # Changed to standard as 'low' is not a valid API value
    "Standard quality": "medium",
    "High quality": "high"
}

image_format_lookup = {
    "fantasy": {
        "name": "Default",
        "description": "Classic artistic style",
        "longDescription": "A semi-photorealistic fantasy style with bold, directional lighting, rich color saturation, and cinematic composition. Realistic textures, lifelike character detail, and a polished finish create a grounded yet visually striking world with a heightened sense of drama and scale."
    },
    "dark-fantasy": {
        "name": "Dark fantasy",
        "description": "Dark fantasy style",
        "longDescription": "A cinematic stylized realism with rich color depth and dynamic lighting. The palette uses vibrant yet grounded tones with strong value contrast to enhance atmosphere and emotional impact, while preserving detail in shadow and highlight areas. Lighting is volumetric and directional, often cutting through mist, smoke, or haze to reveal depth and form. The overall aesthetic is dark and serious in tone — evoking tension, mystery, and scale — yet maintains enough visibility and texture for every element to feel tangible and alive. The mood is dramatic, immersive, and painterly, blending realistic detail with heightened color and light expression."
    },
    "watercolor": {
        "name": "Watercolor",
        "description": "detailed watercolor style",
        "longDescription": "A refined watercolor style that preserves the medium’s softness and translucency while enhancing structure and depth. Colors remain fluid and luminous, but with richer pigment, sharper contrast, and defined brush textures that retain fine detail without losing the organic, hand-painted feel."
    },
    "Sketchbook": {
        "name": "Sketchbook",
        "description": "Sketchbook style",
        "longDescription": "A traditional pen-and-ink illustration style with muted, earthy tones and fine crosshatching, evoking the look of a classic fantasy storybook or vintage map."
    },
    "photo-releastic": { # Note: Typo in original key "photo-releastic" is kept for consistency
        "name": "Photo realistic",
        "description": "Photo realistic style",
        "longDescription": "A lifelike, cinematic style with natural lighting, vibrant colors, sharp detail, and dramatic depth of field."
    },
    "cyberpunk": {
        "name": "Cyberpunk",
        "description": "Luminous Cyber Noir",
        "longDescription": "A cinematic, futuristic rendering style defined by luminous contrast and rich neon hues of violet, cyan, and magenta, balanced against cool, atmospheric shadows. Lighting glows through haze and reflection, creating a moody yet clearly legible composition with preserved midtone detail and visible texture. The overall look feels immersive, stylized, and vividly illuminated without becoming overly dark."
    },
    "retro-vibrant": {
        "name": "Retro illustration",
        "description": "Retro illustration style",
        "longDescription": "A bold, 1980s fantasy style with vivid colors, heroic poses, and painterly textures."
    },
    "graphic-novel": {
        "name": "Graphic Novel",
        "description": "Graphic novel style",
        "longDescription": "A clean, inked comic style with vibrant colors, balanced outlines, and cinematic composition."
    },
    "ink-sketch": {
        "name": "B&W ink sketch",
        "description": "B&W ink sketch style",
        "longDescription": "A rough, black-and-white ink style with scratchy lines, heavy cross-hatching, and surreal fantasy elements."
    },
    "retro": {
        "name": "Retro video game",
        "description": "Retro video game style",
        "longDescription": "A pixelated, 8-bit style with chunky forms, limited palettes, and nostalgic charm."
    },
    "3d-animation": {
        "name": "3D Animation",
        "description": "3D animation style",
        "longDescription": "A polished 3D style with stylized characters, expressive faces, and cinematic lighting."
    },
    "anime": {
        "name": "Anime",
        "description": "Anime style",
        "longDescription": "A vibrant, cel-shaded style with dynamic poses, clean lines, and painterly backgrounds."
    },
    "studio-ghibli": {
        "name": "Studio Ghibli",
        "description": "Studio Ghibli style",
        "longDescription": "A Studio Ghibli film scene"
    },
    "painting": {
        "name": "Painterly",
        "description": "Painting style",
        "longDescription": "A painterly, realistic style with warm lighting, rich detail, and heroic figures in vast, mythic landscapes."
    }
}

selected_tones_lookup = ["Lighthearted", "Serious", "Epic", "Whimsical", "Humorous", "Dark"]
selected_emphases_lookup = ["Combat", "Roleyplay", "Exploration", "Dialogue"]


example_summary_for_segments_with_images = """
Example:
{
  "tldr": "The adventurers navigated the treacherous Sunken City, defeated a kraken cultist leader, and recovered the Tidejewel, narrowly escaping a temple collapse.",
  "sessionSegments": [
    {
      "title": "Descent into the Sunken City",
      "description": "The adventurers—Bron, Donnie, Joe Bangles, and Shifty—carefully explored a mysterious underground tomb marked by a large arched crystal window and a steep drop-off guarded by roped fences. On their way to a side door, they discovered a deep chasm with descending stairs leading to lower platforms, adding complexity to their path. They noted six desiccated corpses wearing black paper mache and feather masks seated on thrones, flanked by two imposing bear statues gripping a bronze disc embossed with a dozen glaring eyes. The group speculated on the significance of the masks and the ominous inscription urging to 'don the mask or be seen.'",
      "image_prompt": "A fantasy adventuring party (rogue, paladin, wizard) cautiously entering a dark, vine-covered stone archway leading into a mysterious underwater city. Eerie blue light emanates from within. Ancient, crumbling architecture visible in the background, submerged in murky water."
    },
    {
      "title": "The Cultist's Sanctum",
      "description": "Initially, Bron attempted to smash the crystal window to gain entry but failed to break through. The party persuaded him to stop and instead investigate a side door they discovered nearby. Approaching cautiously through this alternate entrance, they avoided alerting the tomb’s guardians prematurely. Once inside, Bron swiftly grabbed one of the masks from a corpse just as the undead began to animate, triggering a fierce combat encounter. The party quickly rolled initiative, with Bron raging and attempting to rip the mask off one of the undead, succeeding with a powerful strength check. Shifty conjured a spectral pack of wolves using his fifth-level spell, which inflicted damage and hindered enemy movement. The undead retaliated with life drain attacks, forcing the party to make multiple constitution saving throws to maintain concentration on spells and resist debilitating effects...",
      "image_prompt": "Epic battle scene inside a grand, dimly lit, partially submerged temple. A paladin clashes with a dark sorcerer wielding crackling energy. A rogue attacks from the shadows. A wizard casts a powerful counterspell, deflecting a massive magical wave. Tentacle motifs adorn the temple walls."
    },
    {
      "title": "The Tidejewel and Narrow Escape",
      "description": "The battle was intense and tactical, with enemies casting dispel magic to counter the party’s plant growth spell that had slowed their movement by overgrowing the area with thick vines. Joe Bangles and Donnie coordinated attacks, utilizing Hunter’s Mark and ranged strikes to chip away at the undead, while Shifty cast Moonbeam and Starry Whisp to deal radiant damage. Bron’s relentless axe swings and frenzy attacks cleaved through multiple foes, turning the tide of battle. Despite suffering paralysis and necrotic damage that reduced their maximum hit points, the party persevered, employing spells like Hold Person and Thunderwave to control the battlefield...",
      "image_prompt": "Adventurers frantically escaping a crumbling underwater temple. One clutches a glowing blue jewel. Water surges around them, debris falls. The exit is a distant point of light. Sense of urgency and danger."
    }
  ],
  "adventurerHighlights": [
      {
          "name": "Bron",
          "id": "adv-123",
          "highlights": [
              "Attempted to smash a crystal window to gain entry.",
              "Successfully ripped a mask off an undead foe with a strength check.",
              "Dealt significant damage with relentless axe swings and frenzy attacks."
          ]
      }
  ],
  "locationHighlights": [
      {
          "name": "The Sunken City",
          "id": "loc-456",
          "highlights": [
              "Explored a mysterious underground tomb within the city.",
              "Navigated a deep chasm with descending stairs.",
              "Escaped a collapsing temple at the session's climax."
          ]
      }
  ],
  "npcHighlights": [
      {
          "name": "Cultist Leader",
          "id": "npc-789",
          "highlights": [
              "Animated desiccated corpses to attack the party.",
              "Used life drain attacks, reducing the party's maximum HP.",
              "Was ultimately defeated in a tactical battle."
          ]
      }
  ]
}
"""

# --- GraphQL Queries and Mutations ---
GET_SESSION_QUERY = "query GetSession($id: ID!) { getSession(id: $id) { id _version audioFile owner campaign { id } } }"

GET_NPC_DETAILS_QUERY = """
query GetNPC($id: ID!) {
  getNPC(id: $id) {
    id
    name
    description
    _version
  }
}
"""

GET_LOCATION_DETAILS_QUERY = """
query GetLocation($id: ID!) {
  getLocation(id: $id) {
    id
    name
    description
    _version
  }
}
"""

UPDATE_NPC_MUTATION = """
mutation UpdateNPC($input: UpdateNPCInput!) {
  updateNPC(input: $input) {
    id
    _version
    description
  }
}
"""

UPDATE_LOCATION_MUTATION = """
mutation UpdateLocation($input: UpdateLocationInput!) {
  updateLocation(input: $input) {
    id
    _version
    description
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
      }
    }
    nextToken
  }
}
"""
GET_ADVENTURERS_BY_CAMPAIGN_QUERY = """
query CampaignAdventurersByCampaignId($campaignId: ID!, $limit: Int, $nextToken: String) {
  campaignAdventurersByCampaignId(campaignId: $campaignId, limit: $limit, nextToken: $nextToken) {
    items {
      adventurer {
        id
        name
      }
    }
    nextToken
  }
}
"""
GET_LOCATIONS_BY_CAMPAIGN_QUERY = """
query CampaignLocationsByCampaignId($campaignId: ID!, $limit: Int, $nextToken: String) {
    campaignLocationsByCampaignId(campaignId: $campaignId, limit: $limit, nextToken: $nextToken) {
        items {
            location {
                id
                name
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
    adventurerSegmentsId
    locationSegmentsId
    nPCSegmentsId
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
        
def update_entity_description(
    entity_id: str,
    entity_type: str, # "NPC" or "Location"
    highlights: List[str],
    debug: bool = False
) -> bool:
    """
    Fetches an entity's description, updates it with new highlights using an LLM,
    and saves it back to the database.
    """
    if not entity_id or not highlights:
        if debug: print(f"Skipping description update for {entity_type}: missing ID or highlights.")
        return False

    print(f"--- Starting description update for {entity_type} ID: {entity_id} ---")

    # 1. Determine which GraphQL queries and keys to use
    if entity_type == "NPC":
        get_query = GET_NPC_DETAILS_QUERY
        update_mutation = UPDATE_NPC_MUTATION
        get_key = "getNPC"
        update_key = "updateNPC"
    elif entity_type == "Location":
        get_query = GET_LOCATION_DETAILS_QUERY
        update_mutation = UPDATE_LOCATION_MUTATION
        get_key = "getLocation"
        update_key = "updateLocation"
    else:
        print(f"Error: Invalid entity_type '{entity_type}' for description update.")
        return False

    # 2. Fetch the entity's current state
    try:
        response_gql = execute_graphql_request(get_query, {"id": entity_id})
        entity_data = response_gql.get("data", {}).get(get_key)
        if not entity_data:
            print(f"Warning: Could not fetch {entity_type} with ID {entity_id}. Error: {response_gql.get('errors')}")
            return False
        
        current_description = entity_data.get("description", "") or "This entity has no description yet."
        current_version = entity_data["_version"]
        entity_name = entity_data.get("name", "Unknown")

    except Exception as e:
        print(f"Exception while fetching {entity_type} {entity_id}: {e}")
        return False

    # 3. Construct the prompt for the LLM
    highlights_str = "\n".join(f"- {h}" for h in highlights)
    prompt = f"""You are a narrative assistant for a TTRPG. Your task is to update an entity's description based on recent events from a game session.

Instructions:
- Read the existing description and the new highlights.
- Weave the information from the new highlights into the description naturally.
- Do NOT simply list the new events. Integrate them to enrich the existing narrative.
- Preserve the original tone and style of the description.
- If the description was empty, create a new one based on the highlights. Aim for around 3-6 sentences of quality information.
- The final output should be only the new, complete description text, without any preamble.

Existing Description for {entity_name}:
"{current_description}"

New Highlights from the latest session:
{highlights_str}

Updated Description:
"""

    # 4. Call OpenAI to get the updated description
    try:
        if debug: print(f"Generating updated description for {entity_name}...")
        messages = [{"role": "user", "content": prompt}]
        completion = openai_client.chat.completions.create(
            model="gpt-4.1-2025-04-14",
            messages=messages,
            temperature=0.4, # Allow for some creativity in merging text
        )
        updated_description = completion.choices[0].message.content.strip()

        if not updated_description or updated_description == current_description:
            if debug: print("LLM did not produce a new description. Skipping update.")
            return True # Not an error, just no change needed

        if debug: print(f"New Description:\n{updated_description}")

    except Exception as e:
        print(f"Error calling OpenAI for description update on {entity_name}: {e}")
        return False

    # 5. Execute the update mutation
    try:
        update_input = {
            "id": entity_id,
            "description": updated_description,
            "_version": current_version
        }
        update_response = execute_graphql_request(update_mutation, {"input": update_input})
        if update_response.get("data", {}).get(update_key):
            print(f"✅ Successfully updated description for {entity_type}: {entity_name} (ID: {entity_id})")
            return True
        else:
            print(f"❌ Failed to update description for {entity_type} {entity_name}. Error: {update_response.get('errors')}")
            return False
    except Exception as e:
        print(f"Exception during {entity_type} update mutation for {entity_name}: {e}")
        return False


# --- Replace the old helper function with this enhanced version ---

def map_ids_to_highlights(
    highlights: List[HighlightElement],
    authoritative_entities: List[Dict],
    entity_key_for_db_data: str,
    score_cutoff: int = 85,
    debug: bool = False
):
    """
    Correctly maps entity IDs to highlight elements using an authoritative list of entities,
    falling back to fuzzy string matching. This function intentionally OVERWRITES any existing ID
    on the highlight object to ensure correctness against the provided sources of truth.

    Args:
        highlights: The list of HighlightElement objects from the LLM.
        authoritative_entities: A combined list of entities from both the database (campaign-wide)
                                and the session metadata.
        entity_key_for_db_data: The key used in the database query results to access the
                                nested entity data (e.g., 'adventurer', 'nPC', 'location').
        score_cutoff: The minimum score for a fuzzy match to be considered valid.
        debug: Flag for verbose logging.
    """
    # Step 1: Build the authoritative name-to-ID map from all trusted sources.
    # This map uses lowercase names for robust, case-insensitive matching.
    name_to_id_map = {}
    for entity in authoritative_entities:
        # Handles both structures: nested from DB query and flat from metadata
        name = (entity.get('name') or entity.get(entity_key_for_db_data, {}).get('name', '')).lower()
        entity_id = entity.get('id') or entity.get(entity_key_for_db_data, {}).get('id')
        if name and entity_id:
            name_to_id_map[name] = entity_id

    if not name_to_id_map:
        if debug: print(f"Warning: The authoritative name map for '{entity_key_for_db_data}' is empty. Cannot map IDs.")
        return

    canonical_names = list(name_to_id_map.keys())
    if debug: print(f"Starting ID mapping for '{entity_key_for_db_data}'. Authoritative names: {canonical_names}")

    # Step 2: Iterate through highlights and assign the correct ID.
    for highlight in highlights:
        original_llm_id = highlight.id  # Keep for logging
        # CRITICAL: Reset the ID to null. We will only use an ID from our trusted map.
        highlight.id = None

        highlight_name_lower = highlight.name.lower()

        # Priority 1: Attempt a direct, case-insensitive match.
        if highlight_name_lower in name_to_id_map:
            highlight.id = name_to_id_map[highlight_name_lower]
            print(f"✅ SUCCESS (Direct): Mapped '{highlight.name}' to ID '{highlight.id}'. (LLM originally suggested: {original_llm_id})")
            continue  # Successfully mapped, move to the next highlight

        # Priority 2: If no direct match, fall back to fuzzy matching.
        match = process.extractOne(highlight.name, canonical_names)
        if match:
            best_match_name, score = match
            if score >= score_cutoff:
                matched_id = name_to_id_map.get(best_match_name)
                highlight.id = matched_id
                print(f"✅ SUCCESS (Fuzzy): Mapped '{highlight.name}' to '{best_match_name}' (ID: {matched_id}) with score {score}. (LLM ID was: {original_llm_id})")
            else:
                print(f"❌ FAILED: Fuzzy match for '{highlight.name}' to '{best_match_name}' was below threshold (Score: {score} < {score_cutoff}). No ID assigned.")
        else:
            if debug: print(f"Warning: `process.extractOne` returned no match for '{highlight.name}'.")


# --- Image Generation and Upload Helper ---
def generate_and_upload_image(
    prompt_suffix: str,
    s3_bucket: str,
    s3_base_prefix: str,
    session_id: str,
    segment_index: int,
    image_style_prompt: str, # NEW: The full style description from metadata
    image_quality: str,      # NEW: The quality setting ('standard' or 'hd')
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
    
    full_prompt = f"{image_style_prompt}. {prompt_suffix}"

    try:
        if debug:
            print(f"Generating image... \n  Quality: '{image_quality}'\n  Prompt: '{full_prompt}'")

        response = openai_client.images.generate(
            model="gpt-image-1",
            prompt=full_prompt,
            n=1,
            size="1536x1024",
            quality=image_quality
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

# --- Parallel Image Generation Helper ---
def generate_and_upload_images_parallel(
    segments: List[SegmentElement],
    s3_bucket: str,
    s3_base_prefix: str,
    session_id: str,
    image_style_prompt: str,
    image_quality: str,
    img_enabled: bool = True,
    debug: bool = False,
    max_workers: int = 5
) -> List[Optional[str]]:
    """
    Generates and uploads images for multiple segments in parallel.
    Returns a list of S3 keys (or None for failed generations) in the same order as input segments.
    """
    if not img_enabled:
        if debug:
            print("Image generation disabled. Returning None for all segments.")
        return [None] * len(segments)
    
    if not segments:
        return []
    
    print(f"Starting parallel image generation for {len(segments)} segments using {max_workers} workers...")
    
    def generate_single_image(segment_data):
        """Helper function for generating a single image"""
        segment, segment_index = segment_data
        return generate_and_upload_image(
            prompt_suffix=segment.image_prompt,
            s3_bucket=s3_bucket,
            s3_base_prefix=s3_base_prefix,
            session_id=session_id,
            segment_index=segment_index,
            image_style_prompt=image_style_prompt,
            image_quality=image_quality,
            debug=debug
        )
    
    # Prepare data for parallel processing
    segment_data_list = [(segment, idx) for idx, segment in enumerate(segments)]
    results = [None] * len(segments)  # Initialize results list
    
    # Use ThreadPoolExecutor for parallel processing
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_index = {
            executor.submit(generate_single_image, segment_data): idx 
            for idx, segment_data in enumerate(segment_data_list)
        }
        
        # Collect results as they complete
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            try:
                result = future.result()
                results[index] = result
                if debug:
                    print(f"Completed image generation for segment {index + 1}")
            except Exception as e:
                print(f"Error generating image for segment {index + 1}: {e}")
                results[index] = None
    
    successful_generations = sum(1 for r in results if r is not None)
    print(f"Parallel image generation completed: {successful_generations}/{len(segments)} successful")
    
    return results

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

def fetch_campaign_data(campaign_id, query, data_key, item_key, debug=False):
    if not campaign_id:
        if debug: print(f"Skipping fetch for {data_key} as Campaign ID is missing.")
        return [], f"No {item_key} context available from campaign."
    print(f"Fetching {data_key} for Campaign ID: {campaign_id}")
    all_items, next_token, pages_queried, max_pages = [], None, 0, 25
    while pages_queried < max_pages:
        pages_queried += 1
        query_vars = {"campaignId": campaign_id, "limit": 50, "nextToken": next_token}
        response_gql = execute_graphql_request(query, query_vars)
        if "errors" in response_gql and not response_gql.get("data"):
            print(f"Warning: GraphQL error during Get{data_key}: {response_gql['errors']}. Proceeding with partial context."); break
        data = response_gql.get("data", {}).get(f"campaign{data_key}ByCampaignId", {})
        all_items.extend(data.get("items", []))
        next_token = data.get("nextToken")
        if not next_token: break
    
    details = []
    for item in all_items:
        if item.get(item_key):
            name = item.get(item_key, {}).get('name', f'Unknown {item_key}')
            item_id = item.get(item_key, {}).get('id')
            details.append(f"- {name} (ID: {item_id})")

    context_string = f"Relevant {data_key} in this campaign:\n" + "\n".join(details) if details else f"No {data_key} found for this campaign."
    if debug: print(f"{data_key} Context String (Campaign):\n{context_string}")
    return all_items, context_string

# --- Lambda Handler ---
def lambda_handler(event, context):
    session_info = None
    key = None
    debug = True
    s3_image_upload_bucket = None
    updated_session_data_from_final_update = None

    try:
        if debug:
            print(f"Received event: {json.dumps(event)}")
            print(f"Using AppSync Endpoint: {APPSYNC_API_URL}")
            print(f"AWS Region: {AWS_REGION}")
            print(f"DynamoDB Session Table (from DYNAMODB_TABLE env var): {DYNAMODB_TABLE_NAME}")

        # Support both Step Functions (direct event) and legacy SNS/S3 (event['Records'])
        if "Records" in event and isinstance(event["Records"], list) and event["Records"]:
            # Legacy SNS/S3 trigger
            record = event['Records'][0]
            s3_transcript_bucket = record["s3"]["bucket"]["name"]
            key = urllib.parse.unquote_plus(record['s3']['object']['key'], encoding='utf-8')
            s3_image_upload_bucket = os.environ.get('S3_IMAGE_BUCKET_NAME', s3_transcript_bucket)
            if debug:
                print("Event detected as legacy SNS/S3 trigger format.")
        else:
            # Step Functions direct input (expects {"bucket": "...", "key": "..."})
            s3_transcript_bucket = event["bucket"]
            key = urllib.parse.unquote_plus(event["key"], encoding='utf-8')
            s3_image_upload_bucket = os.environ.get('S3_IMAGE_BUCKET_NAME', s3_transcript_bucket)
            if debug:
                print("Event detected as Step Functions direct input format (bucket/key at top level).")

        s3_transcript_output_prefix = 'public/summaries/final/'
        s3_segment_image_prefix = 'public/segment-images/'
        s3_metadata_prefix = 'public/session-metadata/'

        original_filename_with_ext = os.path.basename(key)
        filename_stem_for_search = os.path.splitext(original_filename_with_ext)[0]

        # --- Extract the base name for metadata lookup ---
        # The filename might be post-processed (e.g., '..._combined.txt'), so we need the original stem.
        metadata_stem_match = re.match(r"(campaign[0-9a-fA-F-]+Session[0-9a-fA-F-]+)", filename_stem_for_search)
        if metadata_stem_match:
            filename_stem_for_metadata = metadata_stem_match.group(1)
        else:
            filename_stem_for_metadata = filename_stem_for_search # Fallback to the original stem if no match
                                                                                
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

        # --- IDEMPOTENCY CHECK ---
        # If the session is already processed, exit to prevent duplicates from retries.
        current_status = session_info.get("transcriptionStatus")
        if current_status in ["READ", "ERROR"]:
            print(f"Session {session_info['id']} has status '{current_status}'. Halting execution to prevent duplicate processing.")
            return {
                'statusCode': 200,
                'body': json.dumps(f"Session already processed with status: {current_status}. No action taken.")
            }
        
        session_id = session_info["id"]
        # Use session's title for highlights, with a fallback name if title is missing
        session_title = session_info.get("name") or "Unnamed Session"
        initial_session_version = session_info["_version"]

        # --- Fetch Session Metadata ---
        session_metadata_content = {}
        metadata_instructions_str = "Not provided."
        
        # Generation instruction defaults
        gen_content_length_str = "Segment length should be 4-5 sentences."
        gen_content_style_str = "Write in a balanced, narrative style."
        gen_tones_str = "Use a neutral, standard TTRPG tone."
        gen_emphases_str = "Give balanced attention to all aspects of the session."
        gen_quotes_str = "You may include character quotes if they are impactful."
        gen_mechanics_str = "Focus on the narrative events over game mechanics."

        # Image instruction defaults
        img_enabled = True # Default to True if metadata is missing
        img_quality = 'medium' 
        img_style_prompt = image_format_lookup["fantasy"]["longDescription"] 

        metadata_filename = f"{filename_stem_for_metadata}.metadata.json"
        metadata_s3_key = f"{s3_metadata_prefix.rstrip('/')}/{metadata_filename}"

        if debug:
            print(f"Attempting to fetch session metadata from: s3://{s3_transcript_bucket}/{metadata_s3_key}")
        try:
            metadata_obj = s3_client.get_object(Bucket=s3_transcript_bucket, Key=metadata_s3_key)
            metadata_file_content = metadata_obj['Body'].read().decode('utf-8')
            session_metadata_content = json.loads(metadata_file_content)
            if debug: print(f"Successfully fetched and parsed metadata: {json.dumps(session_metadata_content)}")

            # --- Parse Generation Instructions ---
            gen_instructions = session_metadata_content.get("generation_instructions", {})
            if gen_instructions:
                length_val = gen_instructions.get("contentLength", 0.5)
                if length_val < 0.33:
                    gen_content_length_str = "Each segment length should be short and concise, around 2-4 sentences."
                elif length_val > 0.66:
                    gen_content_length_str = "Each segment length should be highly detailed and verbose, around 6-8 sentences."
                
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
                    gen_emphases_str = f"Place special emphasis on the following aspects: {', '.join(emphases)}."

                if gen_instructions.get("includeCharacterQuotes") is True:
                    gen_quotes_str = "You MUST include direct quotes from characters in the transcript to bring the dialogue to life."
                if gen_instructions.get("includeGameMechanics") is True:
                    gen_mechanics_str = "You MUST include references to game mechanics, such as skill checks, dice rolls, and spell names."

            # --- Parse Image Instructions ---
            image_instructions = session_metadata_content.get("image_instructions", {})
            if image_instructions:
                img_enabled = image_instructions.get("imageGenerationEnabled", True)
                
                quality_key = image_instructions.get("imageQuality", "medium")
                img_quality = image_quality_lookup.get(quality_key, "medium")

                style_key = image_instructions.get("selectedStyle", "fantasy")
                img_style_prompt = image_format_lookup.get(style_key, {}).get("longDescription", img_style_prompt)

            # --- Parse Other Instructions ---
            metadata_instructions_str = session_metadata_content.get("instructions", "Not provided.")
            
        except s3_client.exceptions.NoSuchKey:
            if debug: print(f"Metadata file not found at {metadata_s3_key}. Proceeding with defaults.")
        except json.JSONDecodeError as e:
            print(f"Error decoding metadata JSON from {metadata_s3_key}: {e}. Proceeding with defaults.")
        except Exception as e:
            print(f"An unexpected error occurred while fetching or parsing metadata from {metadata_s3_key}: {e}. Proceeding with defaults.")
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
                if debug: print(f"Owner value retrieved from DynamoDB: '{segment_owner_value_for_appsync}'")
                if not segment_owner_value_for_appsync: print(f"Warning: 'owner' field is missing or empty in DynamoDB item for Session {session_id}.")
            else: print(f"Warning: Session item with ID '{session_id}' NOT found directly in DynamoDB table '{DYNAMODB_TABLE_NAME}' for owner lookup.")
        except Exception as ddb_e:
            print(f"Error fetching session owner directly from DynamoDB table '{DYNAMODB_TABLE_NAME}': {str(ddb_e)}. Segments may be created without an owner.")
            traceback.print_exc()
        if not segment_owner_value_for_appsync: print(f"Warning: Session {session_id} will have segments created with a null or empty owner.")

        if debug:
            print(f"Using Session ID: {session_id} (initial_v: {initial_session_version}), Effective Segment Owner: {segment_owner_value_for_appsync}")

        campaign_id = session_info.get("campaign", {}).get("id")
        
        # --- Fetch Campaign Context ---
        campaign_id = session_info.get("campaign", {}).get("id")
        all_npcs, npc_context_string_campaign = fetch_campaign_data(campaign_id, GET_NPCS_BY_CAMPAIGN_QUERY, 'Npcs', 'nPC', debug)
        all_adventurers, adventurer_context_string_campaign = fetch_campaign_data(campaign_id, GET_ADVENTURERS_BY_CAMPAIGN_QUERY, 'Adventurers', 'adventurer', debug)
        all_locations, location_context_string_campaign = fetch_campaign_data(campaign_id, GET_LOCATIONS_BY_CAMPAIGN_QUERY, 'Locations', 'location', debug)

        # Always read the full transcript from the new location
        # key is expected to be the full transcript key (public/transcripts/full/{base}.txt)
        s3_object_data = s3_client.get_object(Bucket=s3_transcript_bucket, Key=key)
        text_to_summarize = s3_object_data['Body'].read().decode('utf-8')
        if not text_to_summarize.strip():
            raise ValueError(f"Transcript file {key} is empty or contains only whitespace.")

        prompt = f"""You are Scribe, an AI-powered assistant that summarizes table top role playing game (TTRPG) sessions.
Your task is to process a TTRPG session transcript and generate a JSON object containing a TLDR, chronological session segments, and highlights for adventurers, locations, and NPCs.

Follow these instructions precisely, which are derived from user settings:
<generation_instructions>
- Writing Style: {gen_content_style_str}
- Content Length: {gen_content_length_str}
- Tone: {gen_tones_str}
- Emphasis: {gen_emphases_str}
- Character Quotes: {gen_quotes_str}
- Game Mechanics: {gen_mechanics_str}
</generation_instructions>

The output must be a JSON object matching the Pydantic model `SummaryElements`. This includes:
- `tldr`: A string summary of the whole session.
- `sessionSegments`: A list of 3-5 chronological segment objects. Each must have:
  - 'title': A clear title.
  - 'description': A narrative of events.
  - 'image_prompt': A concise, visual description for gpt-image-1 image generation (describe the scene, not the style).
- `adventurerHighlights`, `locationHighlights`, `npcHighlights`: Lists of highlight objects. Each must have:
    - 'name': The entity's name.
    - 'id': The entity's ID from the context below, if available.
    - 'highlights': A list of key moments for that entity.

- For `adventurerHighlights`, `locationHighlights`, and `npcHighlights`, you MUST find the matching entity in the context and include its ID. If the entity is not in the context, set the ID to null.

Use the following context to inform your summary:
Session Transcript:
<session_text>
{text_to_summarize}
</session_text>

User Instructions:
<user_instructions>
{metadata_instructions_str}
</user_instructions>

Context from Campaign (use for names, IDs, and roles):
<npc_context_campaign>
{npc_context_string_campaign}
</npc_context_campaign>
<adventurer_context_campaign>
{adventurer_context_string_campaign}
</adventurer_context_campaign>
<location_context_campaign>
{location_context_string_campaign}
</location_context_campaign>


Example Output Structure (follow this JSON format precisely):
<example_summary>
{example_summary_for_segments_with_images}
</example_summary>
"""
        if debug:
            print(f"Full prompt for OpenAI:\n{prompt[:1000]}...\n...\n...{prompt[-500:]}")

        def get_openai_summary_segments_with_image_prompts(prompt_text: str, model: str = "gpt-4.1-2025-04-14") -> Optional[SummaryElements]:
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
                    if debug: print(f"Raw OpenAI JSON:\n{json_content}")
                    return SummaryElements.model_validate_json(json_content)
                else: print("OpenAI response lacked content or choices."); return None
            except openai.APIError as e: print(f"OpenAI API error during summary generation: {e}"); return None
            except Exception as e: print(f"Error calling OpenAI for summary or parsing response: {e}"); traceback.print_exc(); return None

        summary_elements_response = get_openai_summary_segments_with_image_prompts(prompt)
        if not summary_elements_response or not isinstance(summary_elements_response, SummaryElements):
            err_msg = "Failed to get valid SummaryElements from OpenAI or response was not in the expected format."
            print(f"Error: {err_msg}"); raise Exception(err_msg)

        if debug: print(f"### LLM OUTPUT (Pydantic Model) ###\n{summary_elements_response.model_dump_json(indent=2)}")
        
        # --- Post-Processing: Map IDs using Fuzzy Matching ---
        print("--- Starting ID Mapping Process ---")
        map_ids_to_highlights(summary_elements_response.adventurerHighlights, all_adventurers, 'adventurer', debug=debug)
        map_ids_to_highlights(summary_elements_response.npcHighlights, all_npcs, 'nPC', debug=debug)
        map_ids_to_highlights(summary_elements_response.locationHighlights, all_locations, 'location', debug=debug)
        print("--- Finished ID Mapping Process ---")
        if debug: print(f"### LLM OUTPUT (After ID Mapping) ###\n{summary_elements_response.model_dump_json(indent=2)}")

        
        s3_summary_output_key = f"{s3_transcript_output_prefix.rstrip('/')}/{filename_stem_for_metadata}.json"
        s3_client.put_object(
            Bucket=s3_transcript_bucket,
            Key=s3_summary_output_key,
            Body=summary_elements_response.model_dump_json(indent=2),
            ContentType='application/json'
        )
        print(f"Summary saved to S3: s3://{s3_transcript_bucket}/{s3_summary_output_key}")
        
        # --- Segment Processing ---
        processing_errors = []
        created_segments_count = 0
        
        # Generate all images in parallel first to reduce overall runtime
        print(f"Generating images for {len(summary_elements_response.sessionSegments)} session segments in parallel...")
        segment_image_s3_keys = generate_and_upload_images_parallel(
            segments=summary_elements_response.sessionSegments,
            s3_bucket=s3_image_upload_bucket,
            s3_base_prefix=s3_segment_image_prefix,
            session_id=session_id,
            image_style_prompt=img_style_prompt,
            image_quality=img_quality,
            img_enabled=img_enabled,
            debug=debug,
            max_workers=5  # Limit concurrent image generations to avoid rate limits
        )
        
        # Set the first segment image for the session's primary image
        first_segment_image_s3_key = segment_image_s3_keys[0] if segment_image_s3_keys else None
        
        # Process Session Segments with pre-generated images
        print(f"Creating database entries for {len(summary_elements_response.sessionSegments)} session segments...")
        for idx, segment in enumerate(summary_elements_response.sessionSegments):
            try:
                print(f"Processing session segment {idx + 1}/{len(summary_elements_response.sessionSegments)}: '{segment.title}'")
                
                # Use the pre-generated image key
                segment_image_s3_key_or_none = segment_image_s3_keys[idx] if idx < len(segment_image_s3_keys) else None
                
                create_segment_input = {
                    "sessionSegmentsId": session_id, "title": segment.title,
                    "description": [segment.description] if segment.description else [],
                    "image": segment_image_s3_key_or_none, "owner": segment_owner_value_for_appsync, "index": idx
                }
                
                segment_response = execute_graphql_request(CREATE_SEGMENT_MUTATION, {"input": create_segment_input})
                if segment_response.get("data", {}).get("createSegment"):
                    created_segments_count += 1
                else:
                    processing_errors.append(f"Failed to create session segment '{segment.title}': {segment_response.get('errors')}")

            except Exception as e:
                processing_errors.append(f"Exception processing session segment '{segment.title}': {e}")

        # Process Highlight Segments
        def process_highlights(highlights, segment_type_id_key, entity_name):
            nonlocal created_segments_count
            print(f"Processing {len(highlights)} {entity_name} highlight segments...")
            for highlight in highlights:
                if not highlight.id:
                    print(f"Skipping {entity_name} highlight for '{highlight.name}' as it has no ID.")
                    continue
                try:
                    print(f"Processing {entity_name} segment for: '{highlight.name}' (ID: {highlight.id})")
                    create_segment_input = {
                        segment_type_id_key: highlight.id,
                        "title": session_title,
                        "description": highlight.highlights,
                        "owner": segment_owner_value_for_appsync,
                        "sessionId": session_id
                    }
                    segment_response = execute_graphql_request(CREATE_SEGMENT_MUTATION, {"input": create_segment_input})
                    if segment_response.get("data", {}).get("createSegment"):
                        created_segments_count += 1
                    else:
                        processing_errors.append(f"Failed to create {entity_name} highlight for '{highlight.name}': {segment_response.get('errors')}")
                except Exception as e:
                    processing_errors.append(f"Exception processing {entity_name} highlight for '{highlight.name}': {e}")

        process_highlights(summary_elements_response.adventurerHighlights, "adventurerSegmentsId", "Adventurer")
        process_highlights(summary_elements_response.locationHighlights, "locationSegmentsId", "Location")
        process_highlights(summary_elements_response.npcHighlights, "nPCSegmentsId", "NPC")

        if processing_errors:
            aggregated_error_message = f"Encountered {len(processing_errors)} error(s) during segment processing. First error: {processing_errors[0]}"
            raise Exception(aggregated_error_message)

        print(f"Successfully created {created_segments_count} total segments.")
        
        # --- Update NPC and Location Descriptions with Session Highlights ---
        try:
            print("\n--- Starting Post-Session Description Updates ---")
            
            # Update NPCs
            for highlight in summary_elements_response.npcHighlights:
                if highlight.id:
                    update_entity_description(
                        entity_id=highlight.id,
                        entity_type="NPC",
                        highlights=highlight.highlights,
                        debug=debug
                    )

            # Update Locations
            for highlight in summary_elements_response.locationHighlights:
                if highlight.id:
                    update_entity_description(
                        entity_id=highlight.id,
                        entity_type="Location",
                        highlights=highlight.highlights,
                        debug=debug
                    )
            
            print("--- Finished Post-Session Description Updates ---\n")

        except Exception as desc_update_err:
            # Log the error but don't fail the entire lambda, as the main task is complete.
            print(f"An unexpected error occurred during the description update phase: {desc_update_err}")
            traceback.print_exc()

        # --- Final Session Update ---
        print(f"Updating Session {session_id} with TLDR, Primary Image, and status to READ...")
        final_update_input = {
            "id": session_id, "_version": initial_session_version,
            "transcriptionStatus": "READ", "tldr": [summary_elements_response.tldr] if summary_elements_response.tldr else [],
            "primaryImage": first_segment_image_s3_key, "errorMessage": None
        }
        final_update_response_gql = execute_graphql_request(UPDATE_SESSION_MUTATION, {"input": final_update_input})
        
        if "errors" in final_update_response_gql and not final_update_response_gql.get("data", {}).get("updateSession"):
            raise Exception(f"Final AppSync mutation to update Session to READ state failed: {final_update_response_gql['errors']}")

        updated_session_data_from_final_update = final_update_response_gql.get("data", {}).get("updateSession")
        if not updated_session_data_from_final_update or "_version" not in updated_session_data_from_final_update:
            raise Exception("Final AppSync Session update mutation (to READ) returned no data or missing _version.")

        print(f"Successfully updated Session {session_id} to READ state. New version: {updated_session_data_from_final_update['_version']}.")

        return {
            'statusCode': 200,
            'body': json.dumps(f"Processed successfully: {key}. {created_segments_count} segments created. Session status set to READ."),
            'userTransactionsTransactionsId': event.get('userTransactionsTransactionsId'),
            'sessionId': event.get('sessionId'),
            'creditsToRefund': event.get('creditsToRefund')
        }

    except Exception as e:
        error_message = str(e)
        print(f"FATAL Error processing file {key if key else 'unknown'}: {error_message}")
        traceback.print_exc()

        if session_info and 'id' in session_info:
            session_id_for_error = session_info['id']
            session_version_for_error = updated_session_data_from_final_update["_version"] if updated_session_data_from_final_update and "_version" in updated_session_data_from_final_update else session_info.get('_version', 1)
            
            print(f"Attempting to update Session {session_id_for_error} to ERROR state (v: {session_version_for_error})...")
            try:
                error_update_input = {
                    "id": session_id_for_error, "_version": session_version_for_error,
                    "transcriptionStatus": "ERROR", "errorMessage": error_message[:1000]
                }
                error_response = execute_graphql_request(UPDATE_SESSION_MUTATION, {"input": error_update_input})
                if error_response.get("errors") and not error_response.get("data", {}).get("updateSession"):
                    print(f"Failed to update session to ERROR state: {error_response.get('errors')}")
                else:
                    print("Session status successfully updated to ERROR.")
            except Exception as update_err:
                print(f"Could not update session to ERROR state during exception handling: {str(update_err)}")
        else:
            print("Cannot update session to ERROR state: session_info not available.")

        return {
            "statusCode": 500,
            "body": json.dumps(f"Error processing file: {error_message}")
        }

