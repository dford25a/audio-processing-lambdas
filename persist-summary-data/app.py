# --- Standard Library Imports ---
import os
import json
import traceback
from typing import List, Optional, Dict, Any

# --- Third-party Library Imports ---
import requests
import boto3

# --- CONFIGURATION ---
APPSYNC_API_URL = os.environ.get('APPSYNC_API_URL')
APPSYNC_API_KEY_FROM_ENV = os.environ.get('APPSYNC_API_KEY')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-2')

# --- VALIDATE ESSENTIAL CONFIGURATION ---
if not APPSYNC_API_URL:
    raise ValueError("Environment variable APPSYNC_API_URL not set!")
if not APPSYNC_API_KEY_FROM_ENV:
    raise ValueError("Environment variable APPSYNC_API_KEY not set!")

# --- AWS CLIENTS ---
s3_client = boto3.client("s3", region_name=AWS_REGION)

# --- GraphQL Mutations ---
GET_SESSION_QUERY = """
query GetSession($id: ID!) {
  getSession(id: $id) {
    id
    _version
    transcriptionStatus
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
    name
    primaryImage
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
    index
    sessionSegmentsId
    owner
    createdAt
    updatedAt
    _version
  }
}
"""

LIST_SESSION_ADVENTURERS_QUERY = """
query ListSessionAdventurers($filter: ModelSessionAdventurersFilterInput, $limit: Int, $nextToken: String) {
  listSessionAdventurers(filter: $filter, limit: $limit, nextToken: $nextToken) {
    items { id _version sessionId adventurerId }
    nextToken
  }
}
"""

LIST_SESSION_NPCS_QUERY = """
query ListSessionNpcs($filter: ModelSessionNpcsFilterInput, $limit: Int, $nextToken: String) {
  listSessionNpcs(filter: $filter, limit: $limit, nextToken: $nextToken) {
    items { id _version sessionId nPCId }
    nextToken
  }
}
"""

LIST_SESSION_LOCATIONS_QUERY = """
query ListSessionLocations($filter: ModelSessionLocationsFilterInput, $limit: Int, $nextToken: String) {
  listSessionLocations(filter: $filter, limit: $limit, nextToken: $nextToken) {
    items { id _version sessionId locationId }
    nextToken
  }
}
"""

UPDATE_SESSION_ADVENTURERS_MUTATION = """
mutation UpdateSessionAdventurers($input: UpdateSessionAdventurersInput!, $condition: ModelSessionAdventurersConditionInput) {
  updateSessionAdventurers(input: $input, condition: $condition) {
    id _version sessionId adventurerId updatedAt
  }
}
"""

UPDATE_SESSION_NPCS_MUTATION = """
mutation UpdateSessionNpcs($input: UpdateSessionNpcsInput!, $condition: ModelSessionNpcsConditionInput) {
  updateSessionNpcs(input: $input, condition: $condition) {
    id _version sessionId nPCId updatedAt
  }
}
"""

UPDATE_SESSION_LOCATIONS_MUTATION = """
mutation UpdateSessionLocations($input: UpdateSessionLocationsInput!, $condition: ModelSessionLocationsConditionInput) {
  updateSessionLocations(input: $input, condition: $condition) {
    id _version sessionId locationId updatedAt
  }
}
"""

SEND_PUSH_NOTIFICATION_MUTATION = """
mutation SendPushNotification($input: SendPushNotificationInput!) {
  sendPushNotification(input: $input) {
    success
    ticketId
    error
    message
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


def send_push_notification(user_id: str, title: str, body: str, data: dict = None, channel_id: str = "sessions"):
    """Send a push notification to a user."""
    variables = {
        "input": {
            "userId": user_id,
            "title": title,
            "body": body,
            "data": json.dumps(data) if data else None,
            "channelId": channel_id
        }
    }
    
    response = execute_graphql_request(SEND_PUSH_NOTIFICATION_MUTATION, variables)
    
    if "errors" in response:
        raise Exception(f"Push notification error: {response['errors']}")
    
    result = response.get("data", {}).get("sendPushNotification", {})
    if not result.get("success"):
        raise Exception(f"Push notification failed: {result.get('error') or result.get('message')}")
    
    print(f"Push notification sent. Ticket ID: {result.get('ticketId')}")
    return response


def fetch_session_links(query_str: str, list_key: str, session_id: str) -> List[Dict[str, Any]]:
    """Fetch existing session link records (adventurers, NPCs, locations)."""
    items = []
    next_token = None
    max_pages = 25
    
    for _ in range(max_pages):
        variables = {
            "filter": {"sessionId": {"eq": session_id}},
            "limit": 100,
            "nextToken": next_token
        }
        resp = execute_graphql_request(query_str, variables)
        data = resp.get("data", {})
        page = data.get(list_key) or {}
        items.extend(page.get("items", []))
        next_token = page.get("nextToken")
        if not next_token:
            break
    
    return items


def update_link_item(mutation_str: str, item: Dict, id_field_name: str, session_id: str, entity_id: str) -> bool:
    """Update a session link record with an entity ID."""
    update_input = {
        "id": item["id"],
        "_version": item["_version"],
        "sessionId": session_id,
        id_field_name: entity_id
    }
    resp = execute_graphql_request(mutation_str, {"input": update_input})
    return resp.get("data") is not None and any(v is not None for v in resp.get("data", {}).values())


def lambda_handler(event, context):
    """
    Persist summary data to database.
    
    Input: {
        narrativeSummaryS3Key, sessionId, sessionName, campaignId, owner, bucket,
        imageKeys, primaryImage, entityMentions, generateName,
        userTransactionsTransactionsId, creditsToRefund
    }
    
    Output: { statusCode, sessionId, ... }
    """
    debug = False
    session_info = None
    updated_session_version = None
    
    try:
        print("Starting persist-summary-data")
        
        # Extract input
        s3_bucket = event["bucket"]
        session_id = event["sessionId"]
        narrative_summary_key = event["narrativeSummaryS3Key"]
        session_name = event.get("sessionName")
        owner = event.get("owner")
        image_keys = event.get("imageKeys", [])
        primary_image = event.get("primaryImage")
        entity_mentions = event.get("entityMentions", {})
        generate_name = event.get("generateName", False)
        
        # Read narrative summary from S3
        print(f"Reading narrative summary: {narrative_summary_key}")
        summary_obj = s3_client.get_object(Bucket=s3_bucket, Key=narrative_summary_key)
        summary_content = json.loads(summary_obj['Body'].read().decode('utf-8'))
        
        tldr = summary_content.get("tldr", "")
        segments = summary_content.get("sessionSegments", [])
        
        # Fetch current session state
        print(f"Fetching session: {session_id}")
        session_response = execute_graphql_request(GET_SESSION_QUERY, {"id": session_id})
        
        if "errors" in session_response and not session_response.get("data"):
            raise Exception(f"Error fetching session: {session_response['errors']}")
        
        session_info = session_response.get("data", {}).get("getSession")
        if not session_info:
            raise ValueError(f"No session found for ID '{session_id}'")
        
        session_version = session_info["_version"]
        
        # Check idempotency
        current_status = session_info.get("transcriptionStatus")
        if current_status in ["READ", "ERROR"]:
            print(f"Session already has status '{current_status}'. Skipping to prevent duplicates.")
            return {
                "statusCode": 200,
                "body": f"Session already processed with status: {current_status}",
                "sessionId": session_id,
                "userTransactionsTransactionsId": event.get("userTransactionsTransactionsId"),
                "creditsToRefund": event.get("creditsToRefund")
            }
        
        # --- Create Segments ---
        print(f"Creating {len(segments)} segments")
        processing_errors = []
        created_segments_count = 0
        
        for idx, segment in enumerate(segments):
            try:
                # Get corresponding image key
                segment_image_key = image_keys[idx] if idx < len(image_keys) else None
                
                create_segment_input = {
                    "sessionSegmentsId": session_id,
                    "title": segment.get("title", f"Segment {idx + 1}"),
                    "description": [segment.get("description", "")] if segment.get("description") else [],
                    "image": segment_image_key,
                    "owner": owner,
                    "index": idx
                }
                
                segment_response = execute_graphql_request(CREATE_SEGMENT_MUTATION, {"input": create_segment_input})
                created_record = segment_response.get("data", {}).get("createSegment")
                
                if created_record:
                    created_segments_count += 1
                    print(f"✅ Created segment {idx + 1}: '{segment.get('title')}'")
                else:
                    err_msg = f"Failed to create segment '{segment.get('title')}'"
                    print(f"❌ {err_msg}")
                    processing_errors.append(err_msg)
                    
            except Exception as e:
                err_msg = f"Exception creating segment {idx + 1}: {e}"
                print(f"❌ {err_msg}")
                processing_errors.append(err_msg)
        
        print(f"Created {created_segments_count}/{len(segments)} segments")
        
        # --- Link Session to Entities ---
        print("Linking session to entities")
        
        # Collect entity IDs from existing entities
        existing_adventurers = entity_mentions.get("existingAdventurers", [])
        existing_npcs = entity_mentions.get("existingNPCs", [])
        existing_locations = entity_mentions.get("existingLocations", [])
        
        adventurer_ids = sorted({e["id"] for e in existing_adventurers if e.get("id")})
        npc_ids = sorted({e["id"] for e in existing_npcs if e.get("id")})
        location_ids = sorted({e["id"] for e in existing_locations if e.get("id")})
        
        print(f"Linking: {len(adventurer_ids)} adventurers, {len(npc_ids)} NPCs, {len(location_ids)} locations")
        
        try:
            # Fetch existing link records
            existing_adv_items = fetch_session_links(LIST_SESSION_ADVENTURERS_QUERY, "listSessionAdventurers", session_id)
            existing_npc_items = fetch_session_links(LIST_SESSION_NPCS_QUERY, "listSessionNpcs", session_id)
            existing_loc_items = fetch_session_links(LIST_SESSION_LOCATIONS_QUERY, "listSessionLocations", session_id)
            
            # Build maps of already-linked entities and placeholders
            adv_by_entity = {it.get("adventurerId"): it for it in existing_adv_items if it.get("adventurerId")}
            npc_by_entity = {it.get("nPCId"): it for it in existing_npc_items if it.get("nPCId")}
            loc_by_entity = {it.get("locationId"): it for it in existing_loc_items if it.get("locationId")}
            
            adv_placeholders = [it for it in existing_adv_items if not it.get("adventurerId")]
            npc_placeholders = [it for it in existing_npc_items if not it.get("nPCId")]
            loc_placeholders = [it for it in existing_loc_items if not it.get("locationId")]
            
            # Link adventurers
            for adv_id in adventurer_ids:
                if adv_id in adv_by_entity:
                    continue
                if adv_placeholders:
                    item = adv_placeholders.pop(0)
                    if update_link_item(UPDATE_SESSION_ADVENTURERS_MUTATION, item, "adventurerId", session_id, adv_id):
                        print(f"✅ Linked adventurer {adv_id}")
                    else:
                        processing_errors.append(f"Failed to link adventurer {adv_id}")
                else:
                    print(f"⚠️ No placeholder for adventurer {adv_id}")
            
            # Link NPCs
            for npc_id in npc_ids:
                if npc_id in npc_by_entity:
                    continue
                if npc_placeholders:
                    item = npc_placeholders.pop(0)
                    if update_link_item(UPDATE_SESSION_NPCS_MUTATION, item, "nPCId", session_id, npc_id):
                        print(f"✅ Linked NPC {npc_id}")
                    else:
                        processing_errors.append(f"Failed to link NPC {npc_id}")
                else:
                    print(f"⚠️ No placeholder for NPC {npc_id}")
            
            # Link locations
            for loc_id in location_ids:
                if loc_id in loc_by_entity:
                    continue
                if loc_placeholders:
                    item = loc_placeholders.pop(0)
                    if update_link_item(UPDATE_SESSION_LOCATIONS_MUTATION, item, "locationId", session_id, loc_id):
                        print(f"✅ Linked location {loc_id}")
                    else:
                        processing_errors.append(f"Failed to link location {loc_id}")
                else:
                    print(f"⚠️ No placeholder for location {loc_id}")
                    
        except Exception as e:
            err_msg = f"Exception linking entities: {e}"
            print(f"❌ {err_msg}")
            processing_errors.append(err_msg)
        
        # --- Update Session to READ ---
        print("Updating session to READ status")
        
        final_update_input = {
            "id": session_id,
            "_version": session_version,
            "transcriptionStatus": "READ",
            "tldr": [tldr] if tldr else [],
            "primaryImage": primary_image,
            "errorMessage": None
        }
        
        # Add session name if generated
        if generate_name and session_name:
            final_update_input["name"] = session_name
            print(f"Setting session name: '{session_name}'")
        
        final_update_response = execute_graphql_request(UPDATE_SESSION_MUTATION, {"input": final_update_input})
        
        if "errors" in final_update_response and not final_update_response.get("data", {}).get("updateSession"):
            raise Exception(f"Failed to update session: {final_update_response['errors']}")
        
        updated_session = final_update_response.get("data", {}).get("updateSession")
        if not updated_session or "_version" not in updated_session:
            raise Exception("Session update returned no data")
        
        updated_session_version = updated_session["_version"]
        print("✅ Session updated to READ status")
        
        # --- Send Push Notification ---
        user_id_for_notification = None
        if owner:
            user_id_for_notification = owner.split(":")[0] if ":" in owner else owner
        
        if user_id_for_notification:
            try:
                print(f"Sending push notification to user: {user_id_for_notification}")
                send_push_notification(
                    user_id=user_id_for_notification,
                    title="Session Ready",
                    body="Your session has been processed and is ready to view!",
                    data={"type": "session_complete", "sessionId": session_id},
                    channel_id="sessions"
                )
                print("✅ Push notification sent")
            except Exception as push_err:
                print(f"⚠️ Push notification failed (non-critical): {push_err}")
        
        # --- Return Result ---
        if processing_errors:
            print(f"⚠️ Completed with {len(processing_errors)} errors")
        
        print("persist-summary-data completed successfully")
        
        return {
            "statusCode": 200,
            "body": json.dumps(f"Processing complete: {created_segments_count} segments created"),
            "sessionId": session_id,
            "segmentsCreated": created_segments_count,
            "processingErrors": processing_errors if processing_errors else None,
            "userTransactionsTransactionsId": event.get("userTransactionsTransactionsId"),
            "creditsToRefund": event.get("creditsToRefund")
        }

    except Exception as e:
        error_message = str(e)
        print(f"ERROR: {error_message}")
        traceback.print_exc()
        
        # Try to update session to ERROR state
        if session_info and 'id' in session_info:
            try:
                version = updated_session_version if updated_session_version else session_info.get('_version', 1)
                error_update_input = {
                    "id": session_info['id'],
                    "_version": version,
                    "transcriptionStatus": "ERROR",
                    "errorMessage": error_message[:1000]
                }
                error_response = execute_graphql_request(UPDATE_SESSION_MUTATION, {"input": error_update_input})
                if error_response.get("data", {}).get("updateSession"):
                    print("Session status updated to ERROR")
                else:
                    print(f"Failed to update session to ERROR: {error_response.get('errors')}")
            except Exception as update_err:
                print(f"Could not update session to ERROR: {update_err}")
        
        return {
            "statusCode": 500,
            "error": error_message,
            "sessionId": event.get("sessionId"),
            "userTransactionsTransactionsId": event.get("userTransactionsTransactionsId"),
            "creditsToRefund": event.get("creditsToRefund")
        }
