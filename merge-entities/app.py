# --- Standard Library Imports ---
import os
import json
import traceback
from typing import Optional, Dict, Any, List

# --- Third-party Library Imports ---
import requests

# --- CONFIGURATION ---
APPSYNC_API_URL = os.environ.get('APPSYNC_API_URL')
APPSYNC_API_KEY = os.environ.get('APPSYNC_API_KEY')

if not APPSYNC_API_URL:
    raise ValueError("Environment variable APPSYNC_API_URL not set!")
if not APPSYNC_API_KEY:
    raise ValueError("Environment variable APPSYNC_API_KEY not set!")


# ---------------------------------------------------------------------------
# AppSync helpers (same pattern as cascade-delete)
# ---------------------------------------------------------------------------

def gql(query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    headers = {'Content-Type': 'application/json', 'x-api-key': APPSYNC_API_KEY}
    payload = {"query": query, "variables": variables or {}}
    try:
        r = requests.post(APPSYNC_API_URL, headers=headers, json=payload, timeout=30)
        r.raise_for_status()
        resp = r.json()
        if "errors" in resp:
            print(f"  [GraphQL errors] {json.dumps(resp['errors'])}")
        return resp
    except requests.exceptions.RequestException as e:
        print(f"AppSync request failed: {e}")
        return {"errors": [{"message": str(e)}]}


def paginate(query: str, data_key: str, variables: Dict[str, Any] = None) -> List[Dict]:
    """Fetches all pages of a paginated AppSync query, filtering out null items."""
    items, next_token = [], None
    while True:
        vars_page = {**(variables or {}), "nextToken": next_token, "limit": 200}
        resp = gql(query, vars_page)
        page = (resp.get("data") or {}).get(data_key) or {}
        items.extend(item for item in (page.get("items") or []) if item is not None)
        next_token = page.get("nextToken")
        if not next_token:
            break
    return items


# ---------------------------------------------------------------------------
# Per-entity-type configuration
#
# Each supported entityType maps to the GraphQL operations needed to re-point
# every relationship from the source entity onto the target entity:
#   - segment_fk:     the Segment foreign-key field pointing at this entity type
#   - session_jn:     the Session<->entity junction table operations
#   - campaign_jn:    the Campaign<->entity junction table operations
#   - get / delete:   fetch + delete the entity record itself
# ---------------------------------------------------------------------------

ENTITY_CONFIG: Dict[str, Dict[str, Any]] = {
    "adventurers": {
        "label": "Adventurer",
        "segment_fk": "adventurerSegmentsId",
        "session_jn": {
            "by_entity_query": ("query Q($id:ID!,$limit:Int,$nextToken:String){sessionAdventurersByAdventurerId(adventurerId:$id,limit:$limit,nextToken:$nextToken){items{id _version sessionId}nextToken}}", "sessionAdventurersByAdventurerId"),
            "other_fk": "sessionId",
            "entity_fk": "adventurerId",
            "update": ("mutation M($input:UpdateSessionAdventurersInput!){updateSessionAdventurers(input:$input){id _version}}", "updateSessionAdventurers"),
            "delete": ("mutation M($input:DeleteSessionAdventurersInput!){deleteSessionAdventurers(input:$input){id}}", "deleteSessionAdventurers"),
            "label": "SessionAdventurers",
        },
        "campaign_jn": {
            "by_entity_query": ("query Q($id:ID!,$limit:Int,$nextToken:String){campaignAdventurersByAdventurerId(adventurerId:$id,limit:$limit,nextToken:$nextToken){items{id _version campaignId}nextToken}}", "campaignAdventurersByAdventurerId"),
            "other_fk": "campaignId",
            "entity_fk": "adventurerId",
            "update": ("mutation M($input:UpdateCampaignAdventurersInput!){updateCampaignAdventurers(input:$input){id _version}}", "updateCampaignAdventurers"),
            "delete": ("mutation M($input:DeleteCampaignAdventurersInput!){deleteCampaignAdventurers(input:$input){id}}", "deleteCampaignAdventurers"),
            "label": "CampaignAdventurers",
        },
        "get": ("query Q($id:ID!){getAdventurer(id:$id){id _version}}", "getAdventurer"),
        "delete_entity": ("mutation M($input:DeleteAdventurerInput!){deleteAdventurer(input:$input){id}}", "deleteAdventurer"),
    },
    "locations": {
        "label": "Location",
        "segment_fk": "locationSegmentsId",
        "session_jn": {
            "by_entity_query": ("query Q($id:ID!,$limit:Int,$nextToken:String){sessionLocationsByLocationId(locationId:$id,limit:$limit,nextToken:$nextToken){items{id _version sessionId}nextToken}}", "sessionLocationsByLocationId"),
            "other_fk": "sessionId",
            "entity_fk": "locationId",
            "update": ("mutation M($input:UpdateSessionLocationsInput!){updateSessionLocations(input:$input){id _version}}", "updateSessionLocations"),
            "delete": ("mutation M($input:DeleteSessionLocationsInput!){deleteSessionLocations(input:$input){id}}", "deleteSessionLocations"),
            "label": "SessionLocations",
        },
        "campaign_jn": {
            "by_entity_query": ("query Q($id:ID!,$limit:Int,$nextToken:String){campaignLocationsByLocationId(locationId:$id,limit:$limit,nextToken:$nextToken){items{id _version campaignId}nextToken}}", "campaignLocationsByLocationId"),
            "other_fk": "campaignId",
            "entity_fk": "locationId",
            "update": ("mutation M($input:UpdateCampaignLocationsInput!){updateCampaignLocations(input:$input){id _version}}", "updateCampaignLocations"),
            "delete": ("mutation M($input:DeleteCampaignLocationsInput!){deleteCampaignLocations(input:$input){id}}", "deleteCampaignLocations"),
            "label": "CampaignLocations",
        },
        "get": ("query Q($id:ID!){getLocation(id:$id){id _version}}", "getLocation"),
        "delete_entity": ("mutation M($input:DeleteLocationInput!){deleteLocation(input:$input){id}}", "deleteLocation"),
    },
    "npcs": {
        "label": "NPC",
        "segment_fk": "nPCSegmentsId",
        "session_jn": {
            "by_entity_query": ("query Q($id:ID!,$limit:Int,$nextToken:String){sessionNpcsByNPCId(nPCId:$id,limit:$limit,nextToken:$nextToken){items{id _version sessionId}nextToken}}", "sessionNpcsByNPCId"),
            "other_fk": "sessionId",
            "entity_fk": "nPCId",
            "update": ("mutation M($input:UpdateSessionNpcsInput!){updateSessionNpcs(input:$input){id _version}}", "updateSessionNpcs"),
            "delete": ("mutation M($input:DeleteSessionNpcsInput!){deleteSessionNpcs(input:$input){id}}", "deleteSessionNpcs"),
            "label": "SessionNpcs",
        },
        "campaign_jn": {
            "by_entity_query": ("query Q($id:ID!,$limit:Int,$nextToken:String){campaignNpcsByNPCId(nPCId:$id,limit:$limit,nextToken:$nextToken){items{id _version campaignId}nextToken}}", "campaignNpcsByNPCId"),
            "other_fk": "campaignId",
            "entity_fk": "nPCId",
            "update": ("mutation M($input:UpdateCampaignNpcsInput!){updateCampaignNpcs(input:$input){id _version}}", "updateCampaignNpcs"),
            "delete": ("mutation M($input:DeleteCampaignNpcsInput!){deleteCampaignNpcs(input:$input){id}}", "deleteCampaignNpcs"),
            "label": "CampaignNpcs",
        },
        "get": ("query Q($id:ID!){getNPC(id:$id){id _version}}", "getNPC"),
        "delete_entity": ("mutation M($input:DeleteNPCInput!){deleteNPC(input:$input){id}}", "deleteNPC"),
    },
}

# Segments are fetched by foreign key with a filtered list query.
_LIST_SEGMENTS = ("query Q($filter:ModelSegmentFilterInput,$limit:Int,$nextToken:String){listSegments(filter:$filter,limit:$limit,nextToken:$nextToken){items{id _version}nextToken}}", "listSegments")
_UPDATE_SEGMENT = ("mutation M($input:UpdateSegmentInput!){updateSegment(input:$input){id _version}}", "updateSegment")


# ---------------------------------------------------------------------------
# Merge steps
# ---------------------------------------------------------------------------

def repoint_segments(segment_fk: str, source_id: str, target_id: str) -> Dict[str, int]:
    """Re-points every Segment whose <segment_fk> == source_id onto target_id."""
    query, key = _LIST_SEGMENTS
    segments = paginate(query, key, {"filter": {segment_fk: {"eq": source_id}}})
    updated, failed = 0, 0
    m, mk = _UPDATE_SEGMENT
    for seg in segments:
        resp = gql(m, {"input": {"id": seg["id"], "_version": seg["_version"], segment_fk: target_id}})
        if (resp.get("data") or {}).get(mk):
            updated += 1
        else:
            print(f"  ⚠️ Failed to re-point Segment {seg['id']}: {resp.get('errors')}")
            failed += 1
    print(f"  Segments ({segment_fk}): re-pointed {updated}, failed {failed}")
    return {"updated": updated, "failed": failed}


def repoint_junctions(jn: Dict[str, Any], source_id: str, target_id: str) -> Dict[str, int]:
    """
    Re-points junction rows from source_id onto target_id.

    To avoid creating a duplicate junction (e.g. two SessionAdventurers rows for the
    same session pointing at the target), any source row whose "other" side already
    has a target row is deleted instead of re-pointed.
    """
    q_query, q_key = jn["by_entity_query"]
    other_fk = jn["other_fk"]
    entity_fk = jn["entity_fk"]

    # Which "other" ids does the target already belong to?
    target_rows = paginate(q_query, q_key, {"id": target_id})
    target_other_ids = {row.get(other_fk) for row in target_rows}

    source_rows = paginate(q_query, q_key, {"id": source_id})

    repointed, deleted, failed = 0, 0, 0
    up_m, up_k = jn["update"]
    del_m, del_k = jn["delete"]

    for row in source_rows:
        other_id = row.get(other_fk)
        if other_id in target_other_ids:
            # Target already linked here — drop the redundant source link.
            resp = gql(del_m, {"input": {"id": row["id"], "_version": row["_version"]}})
            if (resp.get("data") or {}).get(del_k):
                deleted += 1
            else:
                print(f"  ⚠️ Failed to delete duplicate {jn['label']} {row['id']}: {resp.get('errors')}")
                failed += 1
        else:
            resp = gql(up_m, {"input": {"id": row["id"], "_version": row["_version"], entity_fk: target_id}})
            if (resp.get("data") or {}).get(up_k):
                repointed += 1
                target_other_ids.add(other_id)
            else:
                print(f"  ⚠️ Failed to re-point {jn['label']} {row['id']}: {resp.get('errors')}")
                failed += 1

    print(f"  {jn['label']}: re-pointed {repointed}, de-duplicated {deleted}, failed {failed}")
    return {"repointed": repointed, "deleted": deleted, "failed": failed}


def get_entity_version(get_tuple, entity_id: str) -> Optional[int]:
    query, key = get_tuple
    resp = gql(query, {"id": entity_id})
    entity = (resp.get("data") or {}).get(key)
    return entity.get("_version") if entity else None


def merge_entities(source_id: str, target_id: str, entity_type: str) -> Dict[str, Any]:
    cfg = ENTITY_CONFIG[entity_type]
    label = cfg["label"]
    print(f"Merging {label} {source_id} -> {target_id}")

    # Verify both entities exist before mutating anything.
    source_version = get_entity_version(cfg["get"], source_id)
    if source_version is None:
        raise ValueError(f"Source {label} '{source_id}' not found.")
    if get_entity_version(cfg["get"], target_id) is None:
        raise ValueError(f"Target {label} '{target_id}' not found.")

    result: Dict[str, Any] = {"type": label, "sourceId": source_id, "targetId": target_id}

    # 1. Re-point Segment foreign keys.
    result["segments"] = repoint_segments(cfg["segment_fk"], source_id, target_id)

    # 2. Re-point junction rows (session + campaign scoped).
    result["sessionJunctions"] = repoint_junctions(cfg["session_jn"], source_id, target_id)
    result["campaignJunctions"] = repoint_junctions(cfg["campaign_jn"], source_id, target_id)

    total_failed = (
        result["segments"]["failed"]
        + result["sessionJunctions"]["failed"]
        + result["campaignJunctions"]["failed"]
    )
    if total_failed:
        # Do not delete the source while relationships still point at it.
        raise RuntimeError(
            f"{total_failed} relationship(s) failed to re-point; source {label} {source_id} left intact."
        )

    # 3. Delete the (now orphaned) source entity. Re-fetch version in case an
    #    Amplify auto-update bumped it while re-pointing children.
    source_version = get_entity_version(cfg["get"], source_id) or source_version
    del_m, del_k = cfg["delete_entity"]
    del_resp = gql(del_m, {"input": {"id": source_id, "_version": source_version}})
    if not (del_resp.get("data") or {}).get(del_k):
        raise RuntimeError(f"Failed to delete source {label} {source_id}: {del_resp.get('errors')}")
    result["sourceDeleted"] = True

    print(f"Merge complete: {json.dumps(result)}")
    return result


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def _response(status_code: int, body: Dict[str, Any], is_http: bool) -> Dict[str, Any]:
    if is_http:
        return {
            "statusCode": status_code,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,Authorization",
                "Access-Control-Allow-Methods": "OPTIONS,POST",
            },
            "body": json.dumps(body),
        }
    return body


def lambda_handler(event, context):
    """
    Synchronously merges one entity (source) into another (target) of the same type.

    Re-points all Segment foreign keys and junction-table rows from source -> target,
    then deletes the source entity.

    Input (JSON body or direct invoke):
    {
        "sourceId":   "<uuid>",   # entity to merge away (deleted)
        "targetId":   "<uuid>",   # entity to keep
        "entityType": "adventurers" | "locations" | "npcs",
        "sessionId":  "<uuid>",   # scope context (logging)
        "campaignId": "<uuid>"    # scope context (logging)
    }

    Output: { "success": true } or { "success": false, "error": "..." }
    """
    is_http = isinstance(event, dict) and "body" in event
    try:
        if is_http:
            body = json.loads(event["body"]) if isinstance(event["body"], str) else (event["body"] or {})
        else:
            body = event or {}

        source_id = body.get("sourceId")
        target_id = body.get("targetId")
        entity_type = body.get("entityType")
        session_id = body.get("sessionId")
        campaign_id = body.get("campaignId")

        print(f"merge-entities: type={entity_type} source={source_id} target={target_id} "
              f"session={session_id} campaign={campaign_id}")

        if not source_id or not target_id or not entity_type:
            return _response(400, {"success": False, "error": "sourceId, targetId and entityType are required."}, is_http)

        if entity_type not in ENTITY_CONFIG:
            return _response(400, {"success": False,
                                   "error": f"Unknown entityType '{entity_type}'. Must be one of: {list(ENTITY_CONFIG)}"}, is_http)

        if source_id == target_id:
            return _response(400, {"success": False, "error": "sourceId and targetId must differ."}, is_http)

        merge_entities(source_id, target_id, entity_type)
        return _response(200, {"success": True}, is_http)

    except (ValueError, RuntimeError) as e:
        print(f"merge-entities failed: {e}")
        return _response(200, {"success": False, "error": str(e)}, is_http)
    except Exception as e:
        print(f"merge-entities unexpected error: {e}")
        traceback.print_exc()
        return _response(500, {"success": False, "error": str(e)}, is_http)
