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
# AppSync helpers
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


def delete_records(items: List[Dict], mutation: str, mutation_key: str, label: str) -> Dict[str, int]:
    """Deletes a list of records by id + _version. Returns success/failure counts."""
    success, failure = 0, 0
    for item in items:
        resp = gql(mutation, {"input": {"id": item["id"], "_version": item["_version"]}})
        if (resp.get("data") or {}).get(mutation_key):
            success += 1
        else:
            print(f"  ⚠️ Failed to delete {label} {item['id']}: {resp.get('errors')}")
            failure += 1
    if items:
        print(f"  {label}: deleted {success}, failed {failure}")
    return {"success": success, "failure": failure}


def get_entity(get_query: str, get_key: str, entity_id: str) -> Optional[Dict]:
    resp = gql(get_query, {"id": entity_id})
    return (resp.get("data") or {}).get(get_key)


# ---------------------------------------------------------------------------
# GraphQL — junction queries by entity ID
# ---------------------------------------------------------------------------

_SESSION_NPCS_BY_NPC    = ("query Q($nPCId:ID!,$limit:Int,$nextToken:String){sessionNpcsByNPCId(nPCId:$nPCId,limit:$limit,nextToken:$nextToken){items{id _version}nextToken}}", "sessionNpcsByNPCId")
_SESSION_LOCS_BY_LOC    = ("query Q($locationId:ID!,$limit:Int,$nextToken:String){sessionLocationsByLocationId(locationId:$locationId,limit:$limit,nextToken:$nextToken){items{id _version}nextToken}}", "sessionLocationsByLocationId")
_SESSION_ADVS_BY_ADV    = ("query Q($adventurerId:ID!,$limit:Int,$nextToken:String){sessionAdventurersByAdventurerId(adventurerId:$adventurerId,limit:$limit,nextToken:$nextToken){items{id _version}nextToken}}", "sessionAdventurersByAdventurerId")
_SESSION_LOOT_BY_LOOT   = ("query Q($lootItemId:ID!,$limit:Int,$nextToken:String){sessionLootItemsByLootItemId(lootItemId:$lootItemId,limit:$limit,nextToken:$nextToken){items{id _version}nextToken}}", "sessionLootItemsByLootItemId")

_CAMPAIGN_NPCS_BY_NPC   = ("query Q($nPCId:ID!,$limit:Int,$nextToken:String){campaignNpcsByNPCId(nPCId:$nPCId,limit:$limit,nextToken:$nextToken){items{id _version}nextToken}}", "campaignNpcsByNPCId")
_CAMPAIGN_LOCS_BY_LOC   = ("query Q($locationId:ID!,$limit:Int,$nextToken:String){campaignLocationsByLocationId(locationId:$locationId,limit:$limit,nextToken:$nextToken){items{id _version}nextToken}}", "campaignLocationsByLocationId")
_CAMPAIGN_ADVS_BY_ADV   = ("query Q($adventurerId:ID!,$limit:Int,$nextToken:String){campaignAdventurersByAdventurerId(adventurerId:$adventurerId,limit:$limit,nextToken:$nextToken){items{id _version}nextToken}}", "campaignAdventurersByAdventurerId")
_CAMPAIGN_LOOT_BY_LOOT  = ("query Q($lootItemId:ID!,$limit:Int,$nextToken:String){campaignLootItemsByLootItemId(lootItemId:$lootItemId,limit:$limit,nextToken:$nextToken){items{id _version}nextToken}}", "campaignLootItemsByLootItemId")

# ---------------------------------------------------------------------------
# GraphQL — junction queries by session/campaign ID
# ---------------------------------------------------------------------------

_SESSION_NPCS_BY_SESSION = ("query Q($sessionId:ID!,$limit:Int,$nextToken:String){sessionNpcsBySessionId(sessionId:$sessionId,limit:$limit,nextToken:$nextToken){items{id _version}nextToken}}", "sessionNpcsBySessionId")
_SESSION_LOCS_BY_SESSION = ("query Q($sessionId:ID!,$limit:Int,$nextToken:String){sessionLocationsBySessionId(sessionId:$sessionId,limit:$limit,nextToken:$nextToken){items{id _version}nextToken}}", "sessionLocationsBySessionId")
_SESSION_ADVS_BY_SESSION = ("query Q($sessionId:ID!,$limit:Int,$nextToken:String){sessionAdventurersBySessionId(sessionId:$sessionId,limit:$limit,nextToken:$nextToken){items{id _version}nextToken}}", "sessionAdventurersBySessionId")
_SESSION_LOOT_BY_SESSION = ("query Q($sessionId:ID!,$limit:Int,$nextToken:String){sessionLootItemsBySessionId(sessionId:$sessionId,limit:$limit,nextToken:$nextToken){items{id _version}nextToken}}", "sessionLootItemsBySessionId")
_SEGMENTS_BY_SESSION    = ("query Q($sessionSegmentsId:ID!,$limit:Int,$nextToken:String){segmentsBySessionId(sessionSegmentsId:$sessionSegmentsId,limit:$limit,nextToken:$nextToken){items{id _version}nextToken}}", "segmentsBySessionId")
_REMINDERS_BY_SESSION   = ("query Q($limit:Int,$nextToken:String,$filter:ModelSessionReminderFilterInput){listSessionReminders(filter:$filter,limit:$limit,nextToken:$nextToken){items{id _version}nextToken}}", "listSessionReminders")

_CAMPAIGN_NPCS_BY_CAMP  = ("query Q($campaignId:ID!,$limit:Int,$nextToken:String){campaignNpcsByCampaignId(campaignId:$campaignId,limit:$limit,nextToken:$nextToken){items{id _version}nextToken}}", "campaignNpcsByCampaignId")
_CAMPAIGN_LOCS_BY_CAMP  = ("query Q($campaignId:ID!,$limit:Int,$nextToken:String){campaignLocationsByCampaignId(campaignId:$campaignId,limit:$limit,nextToken:$nextToken){items{id _version}nextToken}}", "campaignLocationsByCampaignId")
_CAMPAIGN_ADVS_BY_CAMP  = ("query Q($campaignId:ID!,$limit:Int,$nextToken:String){campaignAdventurersByCampaignId(campaignId:$campaignId,limit:$limit,nextToken:$nextToken){items{id _version}nextToken}}", "campaignAdventurersByCampaignId")
_CAMPAIGN_LOOT_BY_CAMP  = ("query Q($campaignId:ID!,$limit:Int,$nextToken:String){campaignLootItemsByCampaignId(campaignId:$campaignId,limit:$limit,nextToken:$nextToken){items{id _version}nextToken}}", "campaignLootItemsByCampaignId")
_SHARE_LINKS_BY_CAMP    = ("query Q($limit:Int,$nextToken:String,$filter:ModelCampaignShareLinkFilterInput){listCampaignShareLinks(filter:$filter,limit:$limit,nextToken:$nextToken){items{id _version}nextToken}}", "listCampaignShareLinks")
_VIEWERS_BY_CAMP        = ("query Q($limit:Int,$nextToken:String,$filter:ModelCampaignViewerFilterInput){listCampaignViewers(filter:$filter,limit:$limit,nextToken:$nextToken){items{id _version}nextToken}}", "listCampaignViewers")
_SESSIONS_BY_CAMP       = ("query Q($limit:Int,$nextToken:String,$filter:ModelSessionFilterInput){listSessions(filter:$filter,limit:$limit,nextToken:$nextToken){items{id _version}nextToken}}", "listSessions")

# ---------------------------------------------------------------------------
# GraphQL — segments by entity
# ---------------------------------------------------------------------------

_SEGMENTS_BY_FILTER = "query Q($limit:Int,$nextToken:String,$filter:ModelSegmentFilterInput){listSegment(filter:$filter,limit:$limit,nextToken:$nextToken){items{id _version}nextToken}}"

# ---------------------------------------------------------------------------
# GraphQL — delete mutations
# ---------------------------------------------------------------------------

_DEL_SESSION_NPCS  = ("mutation M($input:DeleteSessionNpcsInput!){deleteSessionNpcs(input:$input){id}}", "deleteSessionNpcs")
_DEL_SESSION_LOCS  = ("mutation M($input:DeleteSessionLocationsInput!){deleteSessionLocations(input:$input){id}}", "deleteSessionLocations")
_DEL_SESSION_ADVS  = ("mutation M($input:DeleteSessionAdventurersInput!){deleteSessionAdventurers(input:$input){id}}", "deleteSessionAdventurers")
_DEL_SESSION_LOOT  = ("mutation M($input:DeleteSessionLootItemsInput!){deleteSessionLootItems(input:$input){id}}", "deleteSessionLootItems")
_DEL_REMINDER      = ("mutation M($input:DeleteSessionReminderInput!){deleteSessionReminder(input:$input){id}}", "deleteSessionReminder")
_DEL_SEGMENT       = ("mutation M($input:DeleteSegmentInput!){deleteSegment(input:$input){id}}", "deleteSegment")
_DEL_SESSION       = ("mutation M($input:DeleteSessionInput!){deleteSession(input:$input){id}}", "deleteSession")

_DEL_CAMPAIGN_NPCS = ("mutation M($input:DeleteCampaignNpcsInput!){deleteCampaignNpcs(input:$input){id}}", "deleteCampaignNpcs")
_DEL_CAMPAIGN_LOCS = ("mutation M($input:DeleteCampaignLocationsInput!){deleteCampaignLocations(input:$input){id}}", "deleteCampaignLocations")
_DEL_CAMPAIGN_ADVS = ("mutation M($input:DeleteCampaignAdventurersInput!){deleteCampaignAdventurers(input:$input){id}}", "deleteCampaignAdventurers")
_DEL_CAMPAIGN_LOOT = ("mutation M($input:DeleteCampaignLootItemsInput!){deleteCampaignLootItems(input:$input){id}}", "deleteCampaignLootItems")
_DEL_SHARE_LINK    = ("mutation M($input:DeleteCampaignShareLinkInput!){deleteCampaignShareLink(input:$input){id}}", "deleteCampaignShareLink")
_DEL_VIEWER        = ("mutation M($input:DeleteCampaignViewerInput!){deleteCampaignViewer(input:$input){id}}", "deleteCampaignViewer")
_DEL_CAMPAIGN      = ("mutation M($input:DeleteCampaignInput!){deleteCampaign(input:$input){id}}", "deleteCampaign")

_DEL_NPC           = ("mutation M($input:DeleteNPCInput!){deleteNPC(input:$input){id}}", "deleteNPC")
_DEL_LOCATION      = ("mutation M($input:DeleteLocationInput!){deleteLocation(input:$input){id}}", "deleteLocation")
_DEL_ADVENTURER    = ("mutation M($input:DeleteAdventurerInput!){deleteAdventurer(input:$input){id}}", "deleteAdventurer")
_DEL_LOOT_ITEM     = ("mutation M($input:DeleteLootItemInput!){deleteLootItem(input:$input){id}}", "deleteLootItem")

# ---------------------------------------------------------------------------
# GraphQL — get queries
# ---------------------------------------------------------------------------

_GET_NPC        = ("query Q($id:ID!){getNPC(id:$id){id _version}}", "getNPC")
_GET_LOCATION   = ("query Q($id:ID!){getLocation(id:$id){id _version}}", "getLocation")
_GET_ADVENTURER = ("query Q($id:ID!){getAdventurer(id:$id){id _version}}", "getAdventurer")
_GET_LOOT_ITEM  = ("query Q($id:ID!){getLootItem(id:$id){id _version}}", "getLootItem")
_GET_SESSION    = ("query Q($id:ID!){getSession(id:$id){id _version}}", "getSession")
_GET_CAMPAIGN   = ("query Q($id:ID!){getCampaign(id:$id){id _version}}", "getCampaign")


# ---------------------------------------------------------------------------
# Delete helpers
# ---------------------------------------------------------------------------

def _del(items, mutation_tuple, label):
    if not items:
        return {"success": 0, "failure": 0}
    mutation, key = mutation_tuple
    return delete_records(items, mutation, key, label)


def _page(query_tuple, variables):
    query, key = query_tuple
    return paginate(query, key, variables)


# ---------------------------------------------------------------------------
# Per-entity delete implementations
# ---------------------------------------------------------------------------

def delete_npc(entity_id: str) -> Dict:
    print(f"Deleting NPC {entity_id}")
    results = {"type": "NPC", "id": entity_id, "deleted": {}, "failed": {}}

    counts = _del(_page(_SESSION_NPCS_BY_NPC, {"nPCId": entity_id}), _DEL_SESSION_NPCS, "SessionNpcs")
    counts2 = _del(_page(_CAMPAIGN_NPCS_BY_NPC, {"nPCId": entity_id}), _DEL_CAMPAIGN_NPCS, "CampaignNpcs")
    segments = paginate(_SEGMENTS_BY_FILTER, "listSegment", {"filter": {"nPCSegmentsId": {"eq": entity_id}}})
    counts3 = _del(segments, _DEL_SEGMENT, "Segments")

    results["deleted"] = {"SessionNpcs": counts["success"], "CampaignNpcs": counts2["success"], "Segments": counts3["success"]}
    results["failed"]  = {"SessionNpcs": counts["failure"], "CampaignNpcs": counts2["failure"], "Segments": counts3["failure"]}

    entity = get_entity(*_GET_NPC, entity_id)
    if entity:
        m, k = _DEL_NPC
        resp = gql(m, {"input": {"id": entity_id, "_version": entity["_version"]}})
        results["entity_deleted"] = bool((resp.get("data") or {}).get(k))
    else:
        results["entity_deleted"] = False
        results["entity_not_found"] = True

    return results


def delete_location(entity_id: str) -> Dict:
    print(f"Deleting Location {entity_id}")
    results = {"type": "Location", "id": entity_id, "deleted": {}, "failed": {}}

    counts  = _del(_page(_SESSION_LOCS_BY_LOC, {"locationId": entity_id}), _DEL_SESSION_LOCS, "SessionLocations")
    counts2 = _del(_page(_CAMPAIGN_LOCS_BY_LOC, {"locationId": entity_id}), _DEL_CAMPAIGN_LOCS, "CampaignLocations")
    segments = paginate(_SEGMENTS_BY_FILTER, "listSegment", {"filter": {"locationSegmentsId": {"eq": entity_id}}})
    counts3 = _del(segments, _DEL_SEGMENT, "Segments")

    results["deleted"] = {"SessionLocations": counts["success"], "CampaignLocations": counts2["success"], "Segments": counts3["success"]}
    results["failed"]  = {"SessionLocations": counts["failure"], "CampaignLocations": counts2["failure"], "Segments": counts3["failure"]}

    entity = get_entity(*_GET_LOCATION, entity_id)
    if entity:
        m, k = _DEL_LOCATION
        resp = gql(m, {"input": {"id": entity_id, "_version": entity["_version"]}})
        results["entity_deleted"] = bool((resp.get("data") or {}).get(k))
    else:
        results["entity_deleted"] = False
        results["entity_not_found"] = True

    return results


def delete_adventurer(entity_id: str) -> Dict:
    print(f"Deleting Adventurer {entity_id}")
    results = {"type": "Adventurer", "id": entity_id, "deleted": {}, "failed": {}}

    counts  = _del(_page(_SESSION_ADVS_BY_ADV, {"adventurerId": entity_id}), _DEL_SESSION_ADVS, "SessionAdventurers")
    counts2 = _del(_page(_CAMPAIGN_ADVS_BY_ADV, {"adventurerId": entity_id}), _DEL_CAMPAIGN_ADVS, "CampaignAdventurers")
    segments = paginate(_SEGMENTS_BY_FILTER, "listSegment", {"filter": {"adventurerSegmentsId": {"eq": entity_id}}})
    counts3 = _del(segments, _DEL_SEGMENT, "Segments")

    results["deleted"] = {"SessionAdventurers": counts["success"], "CampaignAdventurers": counts2["success"], "Segments": counts3["success"]}
    results["failed"]  = {"SessionAdventurers": counts["failure"], "CampaignAdventurers": counts2["failure"], "Segments": counts3["failure"]}

    entity = get_entity(*_GET_ADVENTURER, entity_id)
    if entity:
        m, k = _DEL_ADVENTURER
        resp = gql(m, {"input": {"id": entity_id, "_version": entity["_version"]}})
        results["entity_deleted"] = bool((resp.get("data") or {}).get(k))
    else:
        results["entity_deleted"] = False
        results["entity_not_found"] = True

    return results


def delete_session(session_id: str) -> Dict:
    print(f"Deleting Session {session_id}")
    results = {"type": "Session", "id": session_id, "deleted": {}, "failed": {}}

    c1 = _del(_page(_SESSION_NPCS_BY_SESSION,  {"sessionId": session_id}), _DEL_SESSION_NPCS,  "SessionNpcs")
    c2 = _del(_page(_SESSION_LOCS_BY_SESSION,  {"sessionId": session_id}), _DEL_SESSION_LOCS,  "SessionLocations")
    c3 = _del(_page(_SESSION_ADVS_BY_SESSION,  {"sessionId": session_id}), _DEL_SESSION_ADVS,  "SessionAdventurers")
    c4 = _del(_page(_SESSION_LOOT_BY_SESSION,  {"sessionId": session_id}), _DEL_SESSION_LOOT,  "SessionLootItems")
    c5 = _del(_page(_SEGMENTS_BY_SESSION,      {"sessionSegmentsId": session_id}), _DEL_SEGMENT, "Segments")
    reminders = paginate(*_REMINDERS_BY_SESSION, {"filter": {"sessionRemindersId": {"eq": session_id}}})
    c6 = _del(reminders, _DEL_REMINDER, "SessionReminders")

    results["deleted"] = {
        "SessionNpcs": c1["success"], "SessionLocations": c2["success"],
        "SessionAdventurers": c3["success"], "SessionLootItems": c4["success"],
        "Segments": c5["success"], "SessionReminders": c6["success"],
    }
    results["failed"] = {
        "SessionNpcs": c1["failure"], "SessionLocations": c2["failure"],
        "SessionAdventurers": c3["failure"], "SessionLootItems": c4["failure"],
        "Segments": c5["failure"], "SessionReminders": c6["failure"],
    }

    entity = get_entity(*_GET_SESSION, session_id)
    if entity:
        m, k = _DEL_SESSION
        resp = gql(m, {"input": {"id": session_id, "_version": entity["_version"]}})
        results["entity_deleted"] = bool((resp.get("data") or {}).get(k))
        if not results["entity_deleted"]:
            print(f"  ❌ Failed to delete Session {session_id}: {resp.get('errors')}")
    else:
        results["entity_deleted"] = False
        results["entity_not_found"] = True

    return results


def delete_campaign(campaign_id: str, cascade_sessions: bool = False) -> Dict:
    """
    Deletes a campaign and all its junction/related records.

    cascade_sessions=True will also delete every session belonging to the campaign
    (including all their own child records). This is highly destructive and must be
    explicitly opted into.
    """
    print(f"Deleting Campaign {campaign_id} (cascade_sessions={cascade_sessions})")
    results = {"type": "Campaign", "id": campaign_id, "deleted": {}, "failed": {}}

    c1 = _del(_page(_CAMPAIGN_NPCS_BY_CAMP,  {"campaignId": campaign_id}), _DEL_CAMPAIGN_NPCS,  "CampaignNpcs")
    c2 = _del(_page(_CAMPAIGN_LOCS_BY_CAMP,  {"campaignId": campaign_id}), _DEL_CAMPAIGN_LOCS,  "CampaignLocations")
    c3 = _del(_page(_CAMPAIGN_ADVS_BY_CAMP,  {"campaignId": campaign_id}), _DEL_CAMPAIGN_ADVS,  "CampaignAdventurers")
    c4 = _del(_page(_CAMPAIGN_LOOT_BY_CAMP,  {"campaignId": campaign_id}), _DEL_CAMPAIGN_LOOT,  "CampaignLootItems")
    share_links = paginate(*_SHARE_LINKS_BY_CAMP, {"filter": {"campaignShareLinksId": {"eq": campaign_id}}})
    c5 = _del(share_links, _DEL_SHARE_LINK, "CampaignShareLinks")
    viewers = paginate(*_VIEWERS_BY_CAMP, {"filter": {"campaignShareViewersId": {"eq": campaign_id}}})
    c6 = _del(viewers, _DEL_VIEWER, "CampaignViewers")

    results["deleted"] = {
        "CampaignNpcs": c1["success"], "CampaignLocations": c2["success"],
        "CampaignAdventurers": c3["success"], "CampaignLootItems": c4["success"],
        "CampaignShareLinks": c5["success"], "CampaignViewers": c6["success"],
    }
    results["failed"] = {
        "CampaignNpcs": c1["failure"], "CampaignLocations": c2["failure"],
        "CampaignAdventurers": c3["failure"], "CampaignLootItems": c4["failure"],
        "CampaignShareLinks": c5["failure"], "CampaignViewers": c6["failure"],
    }

    # Optionally cascade into sessions
    if cascade_sessions:
        sessions = paginate(*_SESSIONS_BY_CAMP, {"filter": {"campaignSessionsId": {"eq": campaign_id}}})
        print(f"  Cascading into {len(sessions)} session(s)...")
        session_results = []
        for s in sessions:
            session_results.append(delete_session(s["id"]))
        results["sessions_deleted"] = sum(1 for r in session_results if r.get("entity_deleted"))
        results["sessions_failed"]  = sum(1 for r in session_results if not r.get("entity_deleted"))
    else:
        results["sessions_skipped"] = "Pass cascade_sessions=true to also delete sessions"

    entity = get_entity(*_GET_CAMPAIGN, campaign_id)
    if entity:
        m, k = _DEL_CAMPAIGN
        resp = gql(m, {"input": {"id": campaign_id, "_version": entity["_version"]}})
        results["entity_deleted"] = bool((resp.get("data") or {}).get(k))
        if not results["entity_deleted"]:
            print(f"  ❌ Failed to delete Campaign {campaign_id}: {resp.get('errors')}")
    else:
        results["entity_deleted"] = False
        results["entity_not_found"] = True

    return results


def delete_loot_item(entity_id: str) -> Dict:
    print(f"Deleting LootItem {entity_id}")
    results = {"type": "LootItem", "id": entity_id, "deleted": {}, "failed": {}}

    counts  = _del(_page(_SESSION_LOOT_BY_LOOT,  {"lootItemId": entity_id}), _DEL_SESSION_LOOT,  "SessionLootItems")
    counts2 = _del(_page(_CAMPAIGN_LOOT_BY_LOOT,  {"lootItemId": entity_id}), _DEL_CAMPAIGN_LOOT, "CampaignLootItems")

    results["deleted"] = {"SessionLootItems": counts["success"], "CampaignLootItems": counts2["success"]}
    results["failed"]  = {"SessionLootItems": counts["failure"], "CampaignLootItems": counts2["failure"]}

    entity = get_entity(*_GET_LOOT_ITEM, entity_id)
    if entity:
        m, k = _DEL_LOOT_ITEM
        resp = gql(m, {"input": {"id": entity_id, "_version": entity["_version"]}})
        results["entity_deleted"] = bool((resp.get("data") or {}).get(k))
    else:
        results["entity_deleted"] = False
        results["entity_not_found"] = True

    return results


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

ENTITY_HANDLERS = {
    "NPC":        delete_npc,
    "Location":   delete_location,
    "Adventurer": delete_adventurer,
    "LootItem":   delete_loot_item,
    "Session":    delete_session,
    "Campaign":   delete_campaign,
}


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def lambda_handler(event, context):
    """
    Cascade-deletes an entity and all its related records.

    Accepts both direct Lambda invocation and API Gateway proxy events.

    Input:
    {
        "entity_type": "NPC" | "Location" | "Adventurer" | "LootItem" | "Session" | "Campaign",
        "entity_id":   "<uuid>",
        "cascade_sessions": false   // Campaign only — also delete all child sessions
    }

    Output:
    {
        "statusCode": 200,
        "type": "...",
        "id": "...",
        "deleted": { ... counts per table ... },
        "failed":  { ... counts per table ... },
        "entity_deleted": true/false
    }
    """
    try:
        if "body" in event:
            body = json.loads(event["body"]) if isinstance(event["body"], str) else event["body"]
        else:
            body = event

        entity_type = body.get("entity_type")
        entity_id   = body.get("entity_id")

        if not entity_type or not entity_id:
            resp = {"statusCode": 400, "error": "entity_type and entity_id are required"}
            if "body" in event:
                return {"statusCode": 400, "headers": {"Content-Type": "application/json"}, "body": json.dumps(resp)}
            return resp

        handler = ENTITY_HANDLERS.get(entity_type)
        if not handler:
            resp = {"statusCode": 400, "error": f"Unknown entity_type '{entity_type}'. Must be one of: {list(ENTITY_HANDLERS)}"}
            if "body" in event:
                return {"statusCode": 400, "headers": {"Content-Type": "application/json"}, "body": json.dumps(resp)}
            return resp

        # Build kwargs for handlers that accept extra options
        kwargs = {}
        if entity_type == "Campaign":
            kwargs["cascade_sessions"] = bool(body.get("cascade_sessions", False))

        print(f"cascade-delete: {entity_type} {entity_id} kwargs={kwargs}")
        result = handler(entity_id, **kwargs)
        result["statusCode"] = 200
        print(f"cascade-delete complete: {result}")

        if "body" in event:
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
                "body": json.dumps(result)
            }
        return result

    except Exception as e:
        print(f"ERROR in cascade-delete: {e}")
        traceback.print_exc()
        error_resp = {"statusCode": 500, "error": str(e)}
        if "body" in event:
            return {
                "statusCode": 500,
                "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
                "body": json.dumps(error_resp)
            }
        return error_resp
