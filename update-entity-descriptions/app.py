# --- Standard Library Imports ---
import os
import json
import traceback
from typing import List, Optional, Dict, Any

# --- Third-party Library Imports ---
import requests
import boto3
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

# --- GraphQL Queries and Mutations ---
GET_ADVENTURER_DETAILS_QUERY = """
query GetAdventurer($id: ID!) {
  getAdventurer(id: $id) {
    id
    name
    description
    _version
  }
}
"""

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

UPDATE_ADVENTURER_MUTATION = """
mutation UpdateAdventurer($input: UpdateAdventurerInput!) {
  updateAdventurer(input: $input) {
    id
    _version
    description
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


def update_entity_description(
    entity_id: str,
    entity_type: str,  # "Adventurer", "NPC", or "Location"
    highlights: List[str],
    debug: bool = False
) -> bool:
    """
    Fetches an entity's description, updates it with new highlights using an LLM,
    and saves it back to the database.
    """
    if not entity_id or not highlights:
        if debug:
            print(f"Skipping description update for {entity_type}: missing ID or highlights.")
        return False

    print(f"Updating description for {entity_type} ID: {entity_id}")

    # Determine which GraphQL queries and keys to use
    if entity_type == "Adventurer":
        get_query = GET_ADVENTURER_DETAILS_QUERY
        update_mutation = UPDATE_ADVENTURER_MUTATION
        get_key = "getAdventurer"
        update_key = "updateAdventurer"
    elif entity_type == "NPC":
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
        print(f"Error: Invalid entity_type '{entity_type}'")
        return False

    # Fetch the entity's current state
    try:
        response_gql = execute_graphql_request(get_query, {"id": entity_id})
        entity_data = response_gql.get("data", {}).get(get_key)
        if not entity_data:
            print(f"Warning: Could not fetch {entity_type} with ID {entity_id}")
            return False
        
        current_description = entity_data.get("description", "") or "This entity has no description yet."
        current_version = entity_data["_version"]
        entity_name = entity_data.get("name", "Unknown")

    except Exception as e:
        print(f"Exception fetching {entity_type} {entity_id}: {e}")
        return False

    # Construct the prompt for the LLM
    highlights_str = "\n".join(f"- {h}" for h in highlights)
    prompt = f"""You are a narrative assistant for a TTRPG. Your task is to update an entity's description based on recent events from a game session.

Instructions:
- Read the existing description and the new highlights.
- Weave the information from the new highlights into the description naturally.
- Do NOT simply list the new events. Integrate them to enrich the existing narrative.
- Preserve the original tone and style of the description.
- If the description was empty, create a new one based on the highlights. Aim for around 3-6 sentences.
- The final output should be only the new, complete description text, without any preamble.

Existing Description for {entity_name}:
"{current_description}"

New Highlights from the latest session:
{highlights_str}

Updated Description:
"""

    # Call OpenAI to get the updated description
    try:
        completion = openai_client.chat.completions.create(
            model="gpt-5-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
        )
        updated_description = completion.choices[0].message.content.strip()

        if not updated_description or updated_description == current_description:
            print(f"No changes needed for {entity_name}")
            return True

    except Exception as e:
        print(f"Error calling OpenAI for {entity_name}: {e}")
        return False

    # Execute the update mutation
    try:
        update_input = {
            "id": entity_id,
            "description": updated_description,
            "_version": current_version
        }
        update_response = execute_graphql_request(update_mutation, {"input": update_input})
        if update_response.get("data", {}).get(update_key):
            print(f"✅ Updated description for {entity_type}: {entity_name}")
            return True
        else:
            print(f"❌ Failed to update {entity_type} {entity_name}: {update_response.get('errors')}")
            return False
    except Exception as e:
        print(f"Exception updating {entity_type} {entity_name}: {e}")
        return False


def lambda_handler(event, context):
    """
    Update descriptions for existing entities based on session highlights.
    
    This Lambda is called when generate_lore is FALSE - it only updates
    existing entity descriptions, it does NOT create new entities.
    
    Input: {
        entityMentions: {
            existingAdventurers: [{id, name, highlights, ...}],
            existingNPCs: [{id, name, highlights, ...}],
            existingLocations: [{id, name, highlights, ...}],
            newAdventurers: [...],  # Ignored when generate_lore is false
            newNPCs: [...],         # Ignored when generate_lore is false
            newLocations: [...]     # Ignored when generate_lore is false
        },
        sessionId, campaignId, owner, bucket, ...
    }
    
    Output: { statusCode, updatedEntities, ... }
    """
    debug = False
    
    try:
        print("Starting update-entity-descriptions")
        
        # Extract input
        entity_mentions = event.get("entityMentions", {})
        session_id = event.get("sessionId")
        
        existing_adventurers = entity_mentions.get("existingAdventurers", [])
        existing_npcs = entity_mentions.get("existingNPCs", [])
        existing_locations = entity_mentions.get("existingLocations", [])
        
        print(f"Processing: {len(existing_adventurers)} adventurers, {len(existing_npcs)} NPCs, {len(existing_locations)} locations")
        
        updated_entities = {
            "adventurers": [],
            "npcs": [],
            "locations": []
        }
        errors = []
        
        # Aggregate highlights per entity ID to avoid duplicate updates
        adventurer_highlights_by_id: Dict[str, List[str]] = {}
        for entity in existing_adventurers:
            if entity.get("id"):
                adventurer_highlights_by_id.setdefault(entity["id"], []).extend(entity.get("highlights", []))
        
        npc_highlights_by_id: Dict[str, List[str]] = {}
        for entity in existing_npcs:
            if entity.get("id"):
                npc_highlights_by_id.setdefault(entity["id"], []).extend(entity.get("highlights", []))
        
        location_highlights_by_id: Dict[str, List[str]] = {}
        for entity in existing_locations:
            if entity.get("id"):
                location_highlights_by_id.setdefault(entity["id"], []).extend(entity.get("highlights", []))
        
        # Update Adventurer descriptions
        for entity_id, highlights in adventurer_highlights_by_id.items():
            unique_highlights = list(dict.fromkeys(highlights))  # Deduplicate
            if update_entity_description(entity_id, "Adventurer", unique_highlights, debug):
                updated_entities["adventurers"].append(entity_id)
            else:
                errors.append(f"Failed to update adventurer {entity_id}")
        
        # Update NPC descriptions
        for entity_id, highlights in npc_highlights_by_id.items():
            unique_highlights = list(dict.fromkeys(highlights))
            if update_entity_description(entity_id, "NPC", unique_highlights, debug):
                updated_entities["npcs"].append(entity_id)
            else:
                errors.append(f"Failed to update NPC {entity_id}")
        
        # Update Location descriptions
        for entity_id, highlights in location_highlights_by_id.items():
            unique_highlights = list(dict.fromkeys(highlights))
            if update_entity_description(entity_id, "Location", unique_highlights, debug):
                updated_entities["locations"].append(entity_id)
            else:
                errors.append(f"Failed to update location {entity_id}")
        
        total_updated = (
            len(updated_entities["adventurers"]) +
            len(updated_entities["npcs"]) +
            len(updated_entities["locations"])
        )
        
        print(f"update-entity-descriptions completed: {total_updated} entities updated")
        
        if errors:
            print(f"⚠️ {len(errors)} errors occurred")
        
        # Build output - passthrough all input fields plus results
        output = {
            "statusCode": 200,
            "updatedEntities": updated_entities,
            "errors": errors if errors else None,
            # Passthrough fields
            "narrativeSummaryS3Key": event.get("narrativeSummaryS3Key"),
            "sessionId": session_id,
            "sessionName": event.get("sessionName"),
            "campaignId": event.get("campaignId"),
            "owner": event.get("owner"),
            "bucket": event.get("bucket"),
            "transcriptKey": event.get("transcriptKey"),
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
            # Passthrough for downstream error handling
            "narrativeSummaryS3Key": event.get("narrativeSummaryS3Key"),
            "entityMentions": event.get("entityMentions"),
            "imageSettings": event.get("imageSettings")
        }
