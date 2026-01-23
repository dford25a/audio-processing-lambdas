# --- Standard Library Imports ---
import os
import json
import traceback
from datetime import datetime
from typing import List, Optional, Dict, Any

# --- Third-party Library Imports ---
import requests
import boto3
from pydantic import BaseModel, Field
from openai import OpenAI

# --- CONFIGURATION ---
OPENAI_API_KEY_FROM_ENV = os.environ.get('OPENAI_API_KEY')
APPSYNC_API_URL = os.environ.get('APPSYNC_API_URL')
APPSYNC_API_KEY_FROM_ENV = os.environ.get('APPSYNC_API_KEY')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-2')

# --- VALIDATE ESSENTIAL CONFIGURATION ---
if not OPENAI_API_KEY_FROM_ENV:
    raise ValueError("Environment variable OPENAI_API_KEY not set!")
if not APPSYNC_API_URL:
    raise ValueError("Environment variable APPSYNC_API_URL not set!")
if not APPSYNC_API_KEY_FROM_ENV:
    raise ValueError("Environment variable APPSYNC_API_KEY not set!")

# --- AWS & OPENAI CLIENTS ---
s3_client = boto3.client("s3", region_name=AWS_REGION)
dynamodb_client = boto3.client("dynamodb", region_name=AWS_REGION)
openai_client = OpenAI(api_key=OPENAI_API_KEY_FROM_ENV)

# --- DynamoDB Table Names (from environment or defaults) ---
CAMPAIGN_NPCS_TABLE = os.environ.get('CAMPAIGN_NPCS_TABLE', 'CampaignNpcs-dev')
CAMPAIGN_LOCATIONS_TABLE = os.environ.get('CAMPAIGN_LOCATIONS_TABLE', 'CampaignLocations-dev')
CAMPAIGN_ADVENTURERS_TABLE = os.environ.get('CAMPAIGN_ADVENTURERS_TABLE', 'CampaignAdventurers-dev')
SESSION_NPCS_TABLE = os.environ.get('SESSION_NPCS_TABLE', 'SessionNpcs-dev')
SESSION_LOCATIONS_TABLE = os.environ.get('SESSION_LOCATIONS_TABLE', 'SessionLocations-dev')
SESSION_ADVENTURERS_TABLE = os.environ.get('SESSION_ADVENTURERS_TABLE', 'SessionAdventurers-dev')


# --- Pydantic Models for LLM Output ---
class GeneratedNPC(BaseModel):
    name: str = Field(description="The NPC's name")
    brief: str = Field(description="A one-sentence summary of the NPC")
    description: str = Field(description="A detailed 3-6 sentence description")
    type: Optional[str] = Field(None, description="NPC type (e.g., Humanoid, Beast, Undead)")
    race: Optional[str] = Field(None, description="NPC race if applicable")

class GeneratedLocation(BaseModel):
    name: str = Field(description="The location's name")
    brief: str = Field(description="A one-sentence summary of the location")
    description: str = Field(description="A detailed 3-6 sentence description")
    type: Optional[str] = Field(None, description="Location type (e.g., City, Dungeon, Tavern)")

class GeneratedAdventurer(BaseModel):
    name: str = Field(description="The adventurer's name")
    brief: str = Field(description="A one-sentence summary of the adventurer")
    description: str = Field(description="A detailed 3-6 sentence description")
    race: Optional[str] = Field(None, description="Adventurer's race")


# --- GraphQL Queries and Mutations ---
GET_ADVENTURER_DETAILS_QUERY = """
query GetAdventurer($id: ID!) {
  getAdventurer(id: $id) { id name description _version }
}
"""

GET_NPC_DETAILS_QUERY = """
query GetNPC($id: ID!) {
  getNPC(id: $id) { id name description _version }
}
"""

GET_LOCATION_DETAILS_QUERY = """
query GetLocation($id: ID!) {
  getLocation(id: $id) { id name description _version }
}
"""

UPDATE_ADVENTURER_MUTATION = """
mutation UpdateAdventurer($input: UpdateAdventurerInput!) {
  updateAdventurer(input: $input) { id _version description }
}
"""

UPDATE_NPC_MUTATION = """
mutation UpdateNPC($input: UpdateNPCInput!) {
  updateNPC(input: $input) { id _version description }
}
"""

UPDATE_LOCATION_MUTATION = """
mutation UpdateLocation($input: UpdateLocationInput!) {
  updateLocation(input: $input) { id _version description }
}
"""

# --- Session Link List Queries (for duplicate checking) ---
LIST_SESSION_ADVENTURERS_QUERY = """
query ListSessionAdventurers($filter: ModelSessionAdventurersFilterInput, $limit: Int, $nextToken: String) {
  listSessionAdventurers(filter: $filter, limit: $limit, nextToken: $nextToken) {
    items {
      id
      sessionId
      adventurerId
    }
    nextToken
  }
}
"""

LIST_SESSION_NPCS_QUERY = """
query ListSessionNpcs($filter: ModelSessionNpcsFilterInput, $limit: Int, $nextToken: String) {
  listSessionNpcs(filter: $filter, limit: $limit, nextToken: $nextToken) {
    items {
      id
      sessionId
      nPCId
    }
    nextToken
  }
}
"""

LIST_SESSION_LOCATIONS_QUERY = """
query ListSessionLocations($filter: ModelSessionLocationsFilterInput, $limit: Int, $nextToken: String) {
  listSessionLocations(filter: $filter, limit: $limit, nextToken: $nextToken) {
    items {
      id
      sessionId
      locationId
    }
    nextToken
  }
}
"""

CREATE_NPC_MUTATION = """
mutation CreateNPC($input: CreateNPCInput!) {
  createNPC(input: $input) {
    id
    name
    brief
    description
    type
    race
    approvalStatus
    generatedFromSessionId
    generatedAt
    owner
    _version
  }
}
"""

CREATE_LOCATION_MUTATION = """
mutation CreateLocation($input: CreateLocationInput!) {
  createLocation(input: $input) {
    id
    name
    description
    approvalStatus
    generatedFromSessionId
    generatedAt
    owner
    _version
  }
}
"""

CREATE_ADVENTURER_MUTATION = """
mutation CreateAdventurer($input: CreateAdventurerInput!) {
  createAdventurer(input: $input) {
    id
    name
    description
    race
    class
    approvalStatus
    generatedFromSessionId
    generatedAt
    owner
    _version
  }
}
"""

# --- Segment Mutation ---
CREATE_SEGMENT_MUTATION = """
mutation CreateSegment($input: CreateSegmentInput!) {
  createSegment(input: $input) {
    id
    title
    description
    sessionSegmentsId
    adventurerSegmentsId
    locationSegmentsId
    nPCSegmentsId
    owner
    _version
  }
}
"""

# --- Session Link Mutations ---
CREATE_SESSION_NPCS_MUTATION = """
mutation CreateSessionNpcs($input: CreateSessionNpcsInput!) {
  createSessionNpcs(input: $input) {
    id
    sessionId
    nPCId
    _version
  }
}
"""

CREATE_SESSION_LOCATIONS_MUTATION = """
mutation CreateSessionLocations($input: CreateSessionLocationsInput!) {
  createSessionLocations(input: $input) {
    id
    sessionId
    locationId
    _version
  }
}
"""

CREATE_SESSION_ADVENTURERS_MUTATION = """
mutation CreateSessionAdventurers($input: CreateSessionAdventurersInput!) {
  createSessionAdventurers(input: $input) {
    id
    sessionId
    adventurerId
    _version
  }
}
"""

# --- Campaign Link Mutations ---
CREATE_CAMPAIGN_NPCS_MUTATION = """
mutation CreateCampaignNpcs($input: CreateCampaignNpcsInput!) {
  createCampaignNpcs(input: $input) {
    id
    campaignId
    nPCId
    _version
  }
}
"""

CREATE_CAMPAIGN_LOCATIONS_MUTATION = """
mutation CreateCampaignLocations($input: CreateCampaignLocationsInput!) {
  createCampaignLocations(input: $input) {
    id
    campaignId
    locationId
    _version
  }
}
"""

CREATE_CAMPAIGN_ADVENTURERS_MUTATION = """
mutation CreateCampaignAdventurers($input: CreateCampaignAdventurersInput!) {
  createCampaignAdventurers(input: $input) {
    id
    campaignId
    adventurerId
    _version
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


def update_entity_description(entity_id: str, entity_type: str, highlights: List[str], debug: bool = False) -> bool:
    """Updates an existing entity's description with new highlights using LLM."""
    if not entity_id or not highlights:
        return False

    print(f"Updating description for {entity_type} ID: {entity_id}")

    if entity_type == "Adventurer":
        get_query, update_mutation = GET_ADVENTURER_DETAILS_QUERY, UPDATE_ADVENTURER_MUTATION
        get_key, update_key = "getAdventurer", "updateAdventurer"
    elif entity_type == "NPC":
        get_query, update_mutation = GET_NPC_DETAILS_QUERY, UPDATE_NPC_MUTATION
        get_key, update_key = "getNPC", "updateNPC"
    elif entity_type == "Location":
        get_query, update_mutation = GET_LOCATION_DETAILS_QUERY, UPDATE_LOCATION_MUTATION
        get_key, update_key = "getLocation", "updateLocation"
    else:
        return False

    try:
        response_gql = execute_graphql_request(get_query, {"id": entity_id})
        entity_data = response_gql.get("data", {}).get(get_key)
        if not entity_data:
            return False
        
        current_description = entity_data.get("description", "") or "This entity has no description yet."
        current_version = entity_data["_version"]
        entity_name = entity_data.get("name", "Unknown")

        highlights_str = "\n".join(f"- {h}" for h in highlights)
        prompt = f"""Update this TTRPG entity's description with new session highlights.
Weave the highlights naturally into the existing description. Output only the updated description. 
Please keep the description concise, do not be too verbose.

Entity: {entity_name}
Current Description: "{current_description}"

New Highlights:
{highlights_str}

Updated Description:"""

        completion = openai_client.chat.completions.create(
            model="gpt-5.1",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
        )
        updated_description = completion.choices[0].message.content.strip()

        if updated_description and updated_description != current_description:
            update_response = execute_graphql_request(update_mutation, {
                "input": {"id": entity_id, "description": updated_description, "_version": current_version}
            })
            if update_response.get("data", {}).get(update_key):
                print(f"✅ Updated {entity_type}: {entity_name}")
                return True
        return True  # No change needed is still success

    except Exception as e:
        print(f"Error updating {entity_type} {entity_id}: {e}")
        return False


def generate_entity_profile(entity_type: str, name: str, highlights: List[str], transcript_context: str = "") -> Optional[Dict]:
    """Uses LLM to generate a full entity profile for a new entity."""
    highlights_str = "\n".join(f"- {h}" for h in highlights)
    
    if entity_type == "NPC":
        prompt = f"""Generate a TTRPG NPC profile based on session highlights. Please keep the description concise, do not be too verbose.

NPC Name: {name}
Session Highlights:
{highlights_str}

Additional Context:
{transcript_context[:2000] if transcript_context else "Not provided"}

Output a JSON object with:
- name: The NPC's name
- brief: A one-sentence summary (max 100 chars)
- description: A detailed 2-4 sentence description
- type: NPC type (e.g., "Humanoid", "Beast", "Undead", "Celestial")
- race: Race if applicable (e.g., "Human", "Elf", "Dwarf") or null

JSON:"""
        model_class = GeneratedNPC
        
    elif entity_type == "Location":
        prompt = f"""Generate a TTRPG location profile based on session highlights.

Location Name: {name}
Session Highlights:
{highlights_str}

Additional Context:
{transcript_context[:2000] if transcript_context else "Not provided"}

Output a JSON object with:
- name: The location's name
- brief: A one-sentence summary (max 100 chars)
- description: A detailed 1-3 sentence description
- type: Location type (e.g., "City", "Dungeon", "Tavern", "Forest", "Temple")

JSON:"""
        model_class = GeneratedLocation
        
    elif entity_type == "Adventurer":
        prompt = f"""Generate a TTRPG adventurer profile based on session highlights. Please keep the description concise, do not be too verbose.

Adventurer Name: {name}
Session Highlights:
{highlights_str}

Additional Context:
{transcript_context[:2000] if transcript_context else "Not provided"}

Output a JSON object with:
- name: The adventurer's name
- brief: A one-sentence summary (max 100 chars)
- description: A detailed 1-3 sentence description
- race: Race (e.g., "Human", "Elf", "Dwarf", "Halfling") or null if unknown

JSON:"""
        model_class = GeneratedAdventurer
    else:
        return None

    try:
        completion = openai_client.chat.completions.create(
            model="gpt-5.1",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        json_content = completion.choices[0].message.content
        return model_class.model_validate_json(json_content).model_dump()
    except Exception as e:
        print(f"Error generating {entity_type} profile for {name}: {e}")
        return None


def update_linker_table_owner(table_name: str, link_id: str, owner: str) -> bool:
    """Updates the owner field in a linker table record using DynamoDB directly."""
    try:
        dynamodb_client.update_item(
            TableName=table_name,
            Key={
                'id': {'S': link_id}
            },
            UpdateExpression='SET #owner = :owner',
            ExpressionAttributeNames={
                '#owner': 'owner'
            },
            ExpressionAttributeValues={
                ':owner': {'S': owner}
            }
        )
        print(f"✅ Updated owner in {table_name} for link ID: {link_id}")
        return True
    except Exception as e:
        print(f"❌ Failed to update owner in {table_name} for link ID {link_id}: {e}")
        return False


def create_campaign_entity_link(entity_type: str, entity_id: str, campaign_id: str, owner: str) -> bool:
    """Creates a link record between a campaign and an entity (NPC, Location, or Adventurer)."""
    if entity_type == "NPC":
        mutation = CREATE_CAMPAIGN_NPCS_MUTATION
        create_key = "createCampaignNpcs"
        table_name = CAMPAIGN_NPCS_TABLE
        link_input = {
            "campaignId": campaign_id,
            "nPCId": entity_id
        }
    elif entity_type == "Location":
        mutation = CREATE_CAMPAIGN_LOCATIONS_MUTATION
        create_key = "createCampaignLocations"
        table_name = CAMPAIGN_LOCATIONS_TABLE
        link_input = {
            "campaignId": campaign_id,
            "locationId": entity_id
        }
    elif entity_type == "Adventurer":
        mutation = CREATE_CAMPAIGN_ADVENTURERS_MUTATION
        create_key = "createCampaignAdventurers"
        table_name = CAMPAIGN_ADVENTURERS_TABLE
        link_input = {
            "campaignId": campaign_id,
            "adventurerId": entity_id
        }
    else:
        return False

    try:
        response = execute_graphql_request(mutation, {"input": link_input})
        created = response.get("data", {}).get(create_key)
        if created and created.get("id"):
            link_id = created['id']
            print(f"✅ Created Campaign{entity_type}s link (ID: {link_id})")
            
            # Update the owner field directly in DynamoDB
            if owner:
                update_linker_table_owner(table_name, link_id, owner)
            
            return True
        else:
            print(f"❌ Failed to create Campaign{entity_type}s link: {response.get('errors')}")
            return False
    except Exception as e:
        print(f"Exception creating Campaign{entity_type}s link: {e}")
        return False


def create_entity_highlight_segment(entity_type: str, entity_id: str, entity_name: str,
                                     highlights: List[str], session_id: str, session_name: str, owner: str) -> bool:
    """Creates a Segment record to store entity highlights for a session."""
    if not highlights:
        return True  # No highlights to store

    # Build the segment input with the appropriate entity link field
    # NOTE: Do NOT set sessionSegmentsId here - we only want these segments linked to
    # the entity (adventurer/npc/location), not to the session. If sessionSegmentsId
    # is set, these highlights will show up on the session summary page.
    segment_input = {
        "title": session_name,
        "description": highlights,
        "owner": owner
    }

    # Set the correct entity link field
    if entity_type == "Adventurer":
        segment_input["adventurerSegmentsId"] = entity_id
    elif entity_type == "NPC":
        segment_input["nPCSegmentsId"] = entity_id
    elif entity_type == "Location":
        segment_input["locationSegmentsId"] = entity_id
    else:
        print(f"Unknown entity type: {entity_type}")
        return False

    try:
        response = execute_graphql_request(CREATE_SEGMENT_MUTATION, {"input": segment_input})
        created = response.get("data", {}).get("createSegment")
        if created and created.get("id"):
            print(f"✅ Created highlight segment for {entity_type} '{entity_name}' (Segment ID: {created['id']})")
            return True
        else:
            print(f"❌ Failed to create highlight segment for {entity_type} '{entity_name}': {response.get('errors')}")
            return False
    except Exception as e:
        print(f"Exception creating highlight segment for {entity_type} '{entity_name}': {e}")
        return False


def check_session_link_exists(entity_type: str, entity_id: str, session_id: str) -> bool:
    """Checks if a session-entity link already exists to prevent duplicates."""
    if entity_type == "NPC":
        query = LIST_SESSION_NPCS_QUERY
        list_key = "listSessionNpcs"
        entity_id_field = "nPCId"
    elif entity_type == "Location":
        query = LIST_SESSION_LOCATIONS_QUERY
        list_key = "listSessionLocations"
        entity_id_field = "locationId"
    elif entity_type == "Adventurer":
        query = LIST_SESSION_ADVENTURERS_QUERY
        list_key = "listSessionAdventurers"
        entity_id_field = "adventurerId"
    else:
        return False

    try:
        # Query for links matching this session
        variables = {
            "filter": {"sessionId": {"eq": session_id}},
            "limit": 100
        }
        response = execute_graphql_request(query, variables)
        items = response.get("data", {}).get(list_key, {}).get("items", [])

        # Check if any existing link has this entity ID
        for item in items:
            if item.get(entity_id_field) == entity_id:
                return True
        return False
    except Exception as e:
        print(f"Error checking for existing session link: {e}")
        # On error, return False to allow creation attempt (which may fail if duplicate)
        return False


def create_session_entity_link(entity_type: str, entity_id: str, session_id: str, owner: str) -> bool:
    """Creates a link record between a session and an entity (NPC, Location, or Adventurer).

    Checks for existing links first to prevent duplicates.
    """
    # Check if link already exists
    if check_session_link_exists(entity_type, entity_id, session_id):
        print(f"ℹ️ Session{entity_type}s link already exists for entity {entity_id} in session {session_id}")
        return True  # Return True since the link exists (not an error)

    if entity_type == "NPC":
        mutation = CREATE_SESSION_NPCS_MUTATION
        create_key = "createSessionNpcs"
        table_name = SESSION_NPCS_TABLE
        link_input = {
            "sessionId": session_id,
            "nPCId": entity_id
        }
    elif entity_type == "Location":
        mutation = CREATE_SESSION_LOCATIONS_MUTATION
        create_key = "createSessionLocations"
        table_name = SESSION_LOCATIONS_TABLE
        link_input = {
            "sessionId": session_id,
            "locationId": entity_id
        }
    elif entity_type == "Adventurer":
        mutation = CREATE_SESSION_ADVENTURERS_MUTATION
        create_key = "createSessionAdventurers"
        table_name = SESSION_ADVENTURERS_TABLE
        link_input = {
            "sessionId": session_id,
            "adventurerId": entity_id
        }
    else:
        return False

    try:
        response = execute_graphql_request(mutation, {"input": link_input})
        created = response.get("data", {}).get(create_key)
        if created and created.get("id"):
            link_id = created['id']
            print(f"✅ Created Session{entity_type}s link (ID: {link_id})")

            # Update the owner field directly in DynamoDB
            if owner:
                update_linker_table_owner(table_name, link_id, owner)

            return True
        else:
            print(f"❌ Failed to create Session{entity_type}s link: {response.get('errors')}")
            return False
    except Exception as e:
        print(f"Exception creating Session{entity_type}s link: {e}")
        return False


def create_entity_in_database(entity_type: str, profile: Dict, session_id: str, campaign_id: str, owner: str) -> Optional[str]:
    """Creates a new entity in the database with PENDING approval status and links it to the campaign and session."""
    generated_at = datetime.utcnow().isoformat() + "Z"
    
    # Base input fields common to all entity types
    base_input = {
        "name": profile["name"],
        "description": profile.get("description"),
        "approvalStatus": "PENDING",
        "generatedFromSessionId": session_id,
        "generatedAt": generated_at,
        "owner": owner,
    }
    
    if entity_type == "NPC":
        mutation = CREATE_NPC_MUTATION
        create_key = "createNPC"
        create_input = {
            **base_input,
            "brief": profile.get("brief"),
            "type": profile.get("type"),
            "race": profile.get("race"),
        }
    elif entity_type == "Location":
        mutation = CREATE_LOCATION_MUTATION
        create_key = "createLocation"
        create_input = base_input.copy()
        # Location schema doesn't have 'brief' or 'type' fields
    elif entity_type == "Adventurer":
        mutation = CREATE_ADVENTURER_MUTATION
        create_key = "createAdventurer"
        create_input = {
            **base_input,
            "race": profile.get("race"),
            # Don't auto-assign class - let users set this manually
        }
    else:
        return None

    try:
        # Step 1: Create the entity
        response = execute_graphql_request(mutation, {"input": create_input})
        created = response.get("data", {}).get(create_key)
        if created and created.get("id"):
            new_entity_id = created["id"]
            print(f"✅ Created {entity_type}: {profile['name']} (ID: {new_entity_id}, Status: PENDING)")
            
            # Step 2: Create the campaign link
            if campaign_id:
                link_success = create_campaign_entity_link(entity_type, new_entity_id, campaign_id, owner)
                if not link_success:
                    print(f"⚠️ Entity created but campaign link failed for {entity_type} {new_entity_id}")
            
            # Step 3: Create the session link
            if session_id:
                session_link_success = create_session_entity_link(entity_type, new_entity_id, session_id, owner)
                if not session_link_success:
                    print(f"⚠️ Entity created but session link failed for {entity_type} {new_entity_id}")
            
            return new_entity_id
        else:
            print(f"❌ Failed to create {entity_type} {profile['name']}: {response.get('errors')}")
            return None
    except Exception as e:
        print(f"Exception creating {entity_type} {profile['name']}: {e}")
        return None


def lambda_handler(event, context):
    """
    Generate lore for new entities AND update existing entity descriptions.
    
    This Lambda is called when generate_lore is TRUE.
    - Creates new NPCs/Locations/Adventurers with approvalStatus=PENDING
    - Updates existing entity descriptions with session highlights
    
    Input: {
        entityMentions: {
            existingAdventurers, existingNPCs, existingLocations,
            newAdventurers, newNPCs, newLocations
        },
        sessionId, campaignId, owner, bucket, transcriptKey, ...
    }
    
    Output: { statusCode, createdEntities, updatedEntities, ... }
    """
    debug = False
    
    try:
        print("Starting generate-entity-lore")
        
        # Extract input
        entity_mentions = event.get("entityMentions", {})
        session_id = event.get("sessionId")
        campaign_id = event.get("campaignId")
        owner = event.get("owner")
        bucket = event.get("bucket")
        transcript_key = event.get("transcriptKey")
        
        # Read transcript for context (optional)
        transcript_context = ""
        if bucket and transcript_key:
            try:
                transcript_obj = s3_client.get_object(Bucket=bucket, Key=transcript_key)
                transcript_context = transcript_obj['Body'].read().decode('utf-8')
            except Exception as e:
                print(f"Warning: Could not read transcript for context: {e}")
        
        # Extract entity lists
        existing_adventurers = entity_mentions.get("existingAdventurers", [])
        existing_npcs = entity_mentions.get("existingNPCs", [])
        existing_locations = entity_mentions.get("existingLocations", [])
        new_adventurers = entity_mentions.get("newAdventurers", [])
        new_npcs = entity_mentions.get("newNPCs", [])
        new_locations = entity_mentions.get("newLocations", [])
        
        print(f"Existing: {len(existing_adventurers)} adventurers, {len(existing_npcs)} NPCs, {len(existing_locations)} locations")
        print(f"New: {len(new_adventurers)} adventurers, {len(new_npcs)} NPCs, {len(new_locations)} locations")
        
        created_entities = {"adventurers": [], "npcs": [], "locations": []}
        updated_entities = {"adventurers": [], "npcs": [], "locations": []}
        errors = []
        
        # --- Update Existing Entities ---
        # Aggregate highlights by ID and create session links
        for entity_type, entities, result_key in [
            ("Adventurer", existing_adventurers, "adventurers"),
            ("NPC", existing_npcs, "npcs"),
            ("Location", existing_locations, "locations")
        ]:
            # Build maps: id -> highlights and id -> name
            highlights_by_id: Dict[str, List[str]] = {}
            name_by_id: Dict[str, str] = {}
            for entity in entities:
                if entity.get("id"):
                    highlights_by_id.setdefault(entity["id"], []).extend(entity.get("highlights", []))
                    if entity.get("name"):
                        name_by_id[entity["id"]] = entity["name"]

            for entity_id, highlights in highlights_by_id.items():
                unique_highlights = list(dict.fromkeys(highlights))
                entity_name = name_by_id.get(entity_id, "Unknown")

                if update_entity_description(entity_id, entity_type, unique_highlights, debug):
                    updated_entities[result_key].append(entity_id)
                else:
                    errors.append(f"Failed to update {entity_type} {entity_id}")

                # Create session link for existing entity (records appearance in this session)
                if session_id:
                    session_link_success = create_session_entity_link(entity_type, entity_id, session_id, owner)
                    if not session_link_success:
                        print(f"⚠️ Failed to create session link for existing {entity_type} {entity_id}")

                # Create highlight segment for existing entity
                if session_id and unique_highlights:
                    session_name = event.get("sessionName")
                    create_entity_highlight_segment(entity_type, entity_id, entity_name, unique_highlights, session_id, session_name, owner)
        
        # --- Create New Entities ---
        for entity_type, new_entities, result_key in [
            ("Adventurer", new_adventurers, "adventurers"),
            ("NPC", new_npcs, "npcs"),
            ("Location", new_locations, "locations")
        ]:
            for entity in new_entities:
                name = entity.get("name")
                highlights = entity.get("highlights", [])
                
                if not name:
                    continue
                
                print(f"Generating profile for new {entity_type}: {name}")
                
                # Generate profile using LLM
                profile = generate_entity_profile(entity_type, name, highlights, transcript_context)
                if not profile:
                    errors.append(f"Failed to generate profile for {entity_type} {name}")
                    continue
                
                # Create in database
                new_id = create_entity_in_database(entity_type, profile, session_id, campaign_id, owner)
                if new_id:
                    created_entities[result_key].append({
                        "id": new_id,
                        "name": name,
                        "approvalStatus": "PENDING"
                    })
                    # Create highlight segment for new entity
                    if session_id and highlights:
                        session_name = event.get("sessionName")
                        create_entity_highlight_segment(entity_type, new_id, name, highlights, session_id, session_name, owner)
                else:
                    errors.append(f"Failed to create {entity_type} {name}")
        
        total_created = sum(len(v) for v in created_entities.values())
        total_updated = sum(len(v) for v in updated_entities.values())
        
        print(f"generate-entity-lore completed: {total_created} created, {total_updated} updated")
        
        if errors:
            print(f"⚠️ {len(errors)} errors occurred")
        
        # Build output
        output = {
            "statusCode": 200,
            "createdEntities": created_entities,
            "updatedEntities": updated_entities,
            "errors": errors if errors else None,
            # Passthrough fields
            "narrativeSummaryS3Key": event.get("narrativeSummaryS3Key"),
            "sessionId": session_id,
            "sessionName": event.get("sessionName"),
            "campaignId": campaign_id,
            "owner": owner,
            "bucket": bucket,
            "transcriptKey": transcript_key,
            "generateLore": event.get("generateLore"),
            "generateName": event.get("generateName"),
            "entityMentions": entity_mentions,
            "imageSettings": event.get("imageSettings"),
            "userTransactionsTransactionsId": event.get("userTransactionsTransactionsId"),
            "creditsToRefund": event.get("creditsToRefund")
        }
        
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
            "creditsToRefund": event.get("creditsToRefund"),
            "narrativeSummaryS3Key": event.get("narrativeSummaryS3Key"),
            "entityMentions": event.get("entityMentions"),
            "imageSettings": event.get("imageSettings")
        }
