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
openai_client = OpenAI(api_key=OPENAI_API_KEY_FROM_ENV)


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
    characterClass: Optional[List[str]] = Field(None, description="Character class(es)")


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
    _version
  }
}
"""

CREATE_LOCATION_MUTATION = """
mutation CreateLocation($input: CreateLocationInput!) {
  createLocation(input: $input) {
    id
    name
    brief
    description
    type
    approvalStatus
    generatedFromSessionId
    generatedAt
    _version
  }
}
"""

CREATE_ADVENTURER_MUTATION = """
mutation CreateAdventurer($input: CreateAdventurerInput!) {
  createAdventurer(input: $input) {
    id
    name
    brief
    description
    race
    class
    approvalStatus
    generatedFromSessionId
    generatedAt
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
        prompt = f"""Generate a TTRPG NPC profile based on session highlights.

NPC Name: {name}
Session Highlights:
{highlights_str}

Additional Context:
{transcript_context[:2000] if transcript_context else "Not provided"}

Output a JSON object with:
- name: The NPC's name
- brief: A one-sentence summary (max 100 chars)
- description: A detailed 3-6 sentence description
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
- description: A detailed 3-6 sentence description
- type: Location type (e.g., "City", "Dungeon", "Tavern", "Forest", "Temple")

JSON:"""
        model_class = GeneratedLocation
        
    elif entity_type == "Adventurer":
        prompt = f"""Generate a TTRPG adventurer profile based on session highlights.

Adventurer Name: {name}
Session Highlights:
{highlights_str}

Additional Context:
{transcript_context[:2000] if transcript_context else "Not provided"}

Output a JSON object with:
- name: The adventurer's name
- brief: A one-sentence summary (max 100 chars)
- description: A detailed 3-6 sentence description
- race: Race (e.g., "Human", "Elf", "Dwarf", "Halfling") or null
- characterClass: Array of classes (e.g., ["Fighter"], ["Wizard", "Rogue"]) or null

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


def create_campaign_entity_link(entity_type: str, entity_id: str, campaign_id: str) -> bool:
    """Creates a link record between a campaign and an entity (NPC, Location, or Adventurer)."""
    if entity_type == "NPC":
        mutation = CREATE_CAMPAIGN_NPCS_MUTATION
        create_key = "createCampaignNpcs"
        link_input = {
            "campaignId": campaign_id,
            "nPCId": entity_id
        }
    elif entity_type == "Location":
        mutation = CREATE_CAMPAIGN_LOCATIONS_MUTATION
        create_key = "createCampaignLocations"
        link_input = {
            "campaignId": campaign_id,
            "locationId": entity_id
        }
    elif entity_type == "Adventurer":
        mutation = CREATE_CAMPAIGN_ADVENTURERS_MUTATION
        create_key = "createCampaignAdventurers"
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
            print(f"✅ Created Campaign{entity_type}s link (ID: {created['id']})")
            return True
        else:
            print(f"❌ Failed to create Campaign{entity_type}s link: {response.get('errors')}")
            return False
    except Exception as e:
        print(f"Exception creating Campaign{entity_type}s link: {e}")
        return False


def create_entity_in_database(entity_type: str, profile: Dict, session_id: str, campaign_id: str, owner: str) -> Optional[str]:
    """Creates a new entity in the database with PENDING approval status and links it to the campaign."""
    generated_at = datetime.utcnow().isoformat() + "Z"
    
    if entity_type == "NPC":
        mutation = CREATE_NPC_MUTATION
        create_key = "createNPC"
        create_input = {
            "name": profile["name"],
            "brief": profile.get("brief"),
            "description": profile.get("description"),
            "type": profile.get("type"),
            "race": profile.get("race"),
            "approvalStatus": "PENDING",
            "generatedFromSessionId": session_id,
            "generatedAt": generated_at,
            "status": "ACTIVE"
        }
    elif entity_type == "Location":
        mutation = CREATE_LOCATION_MUTATION
        create_key = "createLocation"
        create_input = {
            "name": profile["name"],
            "brief": profile.get("brief"),
            "description": profile.get("description"),
            "type": profile.get("type"),
            "approvalStatus": "PENDING",
            "generatedFromSessionId": session_id,
            "generatedAt": generated_at,
            "status": "ACTIVE"
        }
    elif entity_type == "Adventurer":
        mutation = CREATE_ADVENTURER_MUTATION
        create_key = "createAdventurer"
        create_input = {
            "name": profile["name"],
            "brief": profile.get("brief"),
            "description": profile.get("description"),
            "race": profile.get("race"),
            "class": profile.get("characterClass"),
            "approvalStatus": "PENDING",
            "generatedFromSessionId": session_id,
            "generatedAt": generated_at,
            "status": "ACTIVE"
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
                link_success = create_campaign_entity_link(entity_type, new_entity_id, campaign_id)
                if not link_success:
                    print(f"⚠️ Entity created but campaign link failed for {entity_type} {new_entity_id}")
            
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
        # Aggregate highlights by ID
        for entity_type, entities, result_key in [
            ("Adventurer", existing_adventurers, "adventurers"),
            ("NPC", existing_npcs, "npcs"),
            ("Location", existing_locations, "locations")
        ]:
            highlights_by_id: Dict[str, List[str]] = {}
            for entity in entities:
                if entity.get("id"):
                    highlights_by_id.setdefault(entity["id"], []).extend(entity.get("highlights", []))
            
            for entity_id, highlights in highlights_by_id.items():
                unique_highlights = list(dict.fromkeys(highlights))
                if update_entity_description(entity_id, entity_type, unique_highlights, debug):
                    updated_entities[result_key].append(entity_id)
                else:
                    errors.append(f"Failed to update {entity_type} {entity_id}")
        
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
