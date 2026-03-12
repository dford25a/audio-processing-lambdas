"""
cleanup_orphaned_junctions.py

Scans all six junction tables for orphaned records — those where the
referenced entity no longer exists — and deletes them via AppSync.

Strategy: query junction tables for FK fields only (avoids NON_NULL GraphQL
errors), load all valid entity IDs separately, then delete any junction record
whose FK has no matching entity.

Usage:
    export APPSYNC_API_URL="https://..."
    export APPSYNC_API_KEY="da2-..."
    python scripts/cleanup_orphaned_junctions.py [--dry-run] [--table TABLE]

Options:
    --dry-run       Print what would be deleted without actually deleting.
    --table TABLE   Only process one table (e.g. CampaignNpcs).
"""

import os
import sys
import json
import argparse
import requests
from typing import Optional, Dict, Any, List, Set

APPSYNC_API_URL = os.environ.get("APPSYNC_API_URL")
APPSYNC_API_KEY = os.environ.get("APPSYNC_API_KEY")


# ---------------------------------------------------------------------------
# GraphQL helpers
# ---------------------------------------------------------------------------

def gql(query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not APPSYNC_API_URL or not APPSYNC_API_KEY:
        raise EnvironmentError("APPSYNC_API_URL and APPSYNC_API_KEY must be set.")
    headers = {"Content-Type": "application/json", "x-api-key": APPSYNC_API_KEY}
    r = requests.post(APPSYNC_API_URL, headers=headers, json={"query": query, "variables": variables or {}}, timeout=30)
    r.raise_for_status()
    resp = r.json()
    if "errors" in resp:
        print(f"  [GraphQL error] {json.dumps(resp['errors'])}")
    return resp


def paginate(query: str, data_key: str, variables: Dict[str, Any] = None) -> List[Dict]:
    items, next_token = [], None
    while True:
        vars_page = {**(variables or {}), "nextToken": next_token, "limit": 200}
        resp = gql(query, vars_page)
        page = (resp.get("data") or {}).get(data_key) or {}
        batch = page.get("items") or []
        # Filter out None items (AppSync nulls items with NON_NULL violations)
        items.extend(item for item in batch if item is not None)
        next_token = page.get("nextToken")
        if not next_token:
            break
    return items


# ---------------------------------------------------------------------------
# Entity ID loaders  (fetch all valid IDs for each entity type)
# ---------------------------------------------------------------------------

_LIST_NPC_IDS = """
query ListNPCs($limit: Int, $nextToken: String) {
  listNPCS(limit: $limit, nextToken: $nextToken) {
    items { id }
    nextToken
  }
}"""

_LIST_LOCATION_IDS = """
query ListLocations($limit: Int, $nextToken: String) {
  listLocations(limit: $limit, nextToken: $nextToken) {
    items { id }
    nextToken
  }
}"""

_LIST_ADVENTURER_IDS = """
query ListAdventurers($limit: Int, $nextToken: String) {
  listAdventurers(limit: $limit, nextToken: $nextToken) {
    items { id }
    nextToken
  }
}"""


def load_entity_ids(entity_type: str) -> Set[str]:
    """Loads all valid entity IDs for the given type into a set."""
    configs = {
        "NPC":       (_LIST_NPC_IDS, "listNPCS"),
        "Location":  (_LIST_LOCATION_IDS, "listLocations"),
        "Adventurer": (_LIST_ADVENTURER_IDS, "listAdventurers"),
    }
    query, data_key = configs[entity_type]
    print(f"  Loading all {entity_type} IDs...")
    items = paginate(query, data_key)
    ids = {item["id"] for item in items if item}
    print(f"  Found {len(ids)} valid {entity_type}(s)")
    return ids


# ---------------------------------------------------------------------------
# Junction table definitions  (no nested entity fields — just FK)
# ---------------------------------------------------------------------------

JUNCTION_CONFIGS = {
    "CampaignNpcs": {
        "list_query": """
query ListCampaignNpcs($limit: Int, $nextToken: String) {
  listCampaignNpcs(filter: {_deleted: {ne: true}}, limit: $limit, nextToken: $nextToken) {
    items { id _version nPCId }
    nextToken
  }
}""",
        "list_data_key": "listCampaignNpcs",
        "fk_field": "nPCId",
        "entity_type": "NPC",
        "delete_mutation": """
mutation DeleteCampaignNpcs($input: DeleteCampaignNpcsInput!) {
  deleteCampaignNpcs(input: $input) { id }
}""",
        "delete_data_key": "deleteCampaignNpcs",
    },
    "CampaignLocations": {
        "list_query": """
query ListCampaignLocations($limit: Int, $nextToken: String) {
  listCampaignLocations(filter: {_deleted: {ne: true}}, limit: $limit, nextToken: $nextToken) {
    items { id _version locationId }
    nextToken
  }
}""",
        "list_data_key": "listCampaignLocations",
        "fk_field": "locationId",
        "entity_type": "Location",
        "delete_mutation": """
mutation DeleteCampaignLocations($input: DeleteCampaignLocationsInput!) {
  deleteCampaignLocations(input: $input) { id }
}""",
        "delete_data_key": "deleteCampaignLocations",
    },
    "CampaignAdventurers": {
        "list_query": """
query ListCampaignAdventurers($limit: Int, $nextToken: String) {
  listCampaignAdventurers(filter: {_deleted: {ne: true}}, limit: $limit, nextToken: $nextToken) {
    items { id _version adventurerId }
    nextToken
  }
}""",
        "list_data_key": "listCampaignAdventurers",
        "fk_field": "adventurerId",
        "entity_type": "Adventurer",
        "delete_mutation": """
mutation DeleteCampaignAdventurers($input: DeleteCampaignAdventurersInput!) {
  deleteCampaignAdventurers(input: $input) { id }
}""",
        "delete_data_key": "deleteCampaignAdventurers",
    },
    "SessionNpcs": {
        "list_query": """
query ListSessionNpcs($limit: Int, $nextToken: String) {
  listSessionNpcs(filter: {_deleted: {ne: true}}, limit: $limit, nextToken: $nextToken) {
    items { id _version nPCId }
    nextToken
  }
}""",
        "list_data_key": "listSessionNpcs",
        "fk_field": "nPCId",
        "entity_type": "NPC",
        "delete_mutation": """
mutation DeleteSessionNpcs($input: DeleteSessionNpcsInput!) {
  deleteSessionNpcs(input: $input) { id }
}""",
        "delete_data_key": "deleteSessionNpcs",
    },
    "SessionLocations": {
        "list_query": """
query ListSessionLocations($limit: Int, $nextToken: String) {
  listSessionLocations(filter: {_deleted: {ne: true}}, limit: $limit, nextToken: $nextToken) {
    items { id _version locationId }
    nextToken
  }
}""",
        "list_data_key": "listSessionLocations",
        "fk_field": "locationId",
        "entity_type": "Location",
        "delete_mutation": """
mutation DeleteSessionLocations($input: DeleteSessionLocationsInput!) {
  deleteSessionLocations(input: $input) { id }
}""",
        "delete_data_key": "deleteSessionLocations",
    },
    "SessionAdventurers": {
        "list_query": """
query ListSessionAdventurers($limit: Int, $nextToken: String) {
  listSessionAdventurers(filter: {_deleted: {ne: true}}, limit: $limit, nextToken: $nextToken) {
    items { id _version adventurerId }
    nextToken
  }
}""",
        "list_data_key": "listSessionAdventurers",
        "fk_field": "adventurerId",
        "entity_type": "Adventurer",
        "delete_mutation": """
mutation DeleteSessionAdventurers($input: DeleteSessionAdventurersInput!) {
  deleteSessionAdventurers(input: $input) { id }
}""",
        "delete_data_key": "deleteSessionAdventurers",
    },
}


# ---------------------------------------------------------------------------
# Core scan-and-delete logic
# ---------------------------------------------------------------------------

def cleanup_table(table_name: str, config: Dict, entity_ids: Set[str], dry_run: bool) -> Dict[str, int]:
    print(f"\n{'[DRY RUN] ' if dry_run else ''}Scanning {table_name}...")

    all_items = paginate(config["list_query"], config["list_data_key"])
    print(f"  Total records: {len(all_items)}")

    fk_field = config["fk_field"]
    orphans = [item for item in all_items if item.get(fk_field) not in entity_ids]
    print(f"  Orphaned records (FK not in {config['entity_type']} table): {len(orphans)}")

    if not orphans:
        return {"scanned": len(all_items), "orphaned": 0, "deleted": 0, "failed": 0}

    deleted, failed = 0, 0
    for item in orphans:
        fk_val = item.get(fk_field, "unknown")
        print(f"  {'[DRY RUN] Would delete' if dry_run else 'Deleting'} junction {item['id']} — {fk_field}={fk_val} not found")

        if dry_run:
            deleted += 1
            continue

        resp = gql(config["delete_mutation"], {"input": {"id": item["id"], "_version": item["_version"]}})
        if resp.get("data", {}).get(config["delete_data_key"]):
            print(f"    ✅ Deleted {item['id']}")
            deleted += 1
        else:
            print(f"    ❌ Failed to delete {item['id']}: {resp.get('errors')}")
            failed += 1

    return {"scanned": len(all_items), "orphaned": len(orphans), "deleted": deleted, "failed": failed}


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Clean up orphaned junction table records.")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be deleted without deleting.")
    parser.add_argument("--table", choices=list(JUNCTION_CONFIGS.keys()), help="Only process this table.")
    args = parser.parse_args()

    if not APPSYNC_API_URL or not APPSYNC_API_KEY:
        print("ERROR: Set APPSYNC_API_URL and APPSYNC_API_KEY environment variables.")
        sys.exit(1)

    tables_to_process = {args.table: JUNCTION_CONFIGS[args.table]} if args.table else JUNCTION_CONFIGS

    # Determine which entity types are needed and load them once each
    needed_entity_types = {cfg["entity_type"] for cfg in tables_to_process.values()}
    print("Loading entity ID sets...")
    entity_id_sets: Dict[str, Set[str]] = {et: load_entity_ids(et) for et in needed_entity_types}

    totals = {"scanned": 0, "orphaned": 0, "deleted": 0, "failed": 0}
    for table_name, config in tables_to_process.items():
        entity_ids = entity_id_sets[config["entity_type"]]
        counts = cleanup_table(table_name, config, entity_ids, dry_run=args.dry_run)
        for k in totals:
            totals[k] += counts[k]

    print(f"\n{'=' * 50}")
    print(f"{'[DRY RUN] ' if args.dry_run else ''}Summary:")
    print(f"  Tables processed : {len(tables_to_process)}")
    print(f"  Records scanned  : {totals['scanned']}")
    print(f"  Orphans found    : {totals['orphaned']}")
    print(f"  {'Would delete' if args.dry_run else 'Deleted'}     : {totals['deleted']}")
    if not args.dry_run:
        print(f"  Failed           : {totals['failed']}")


if __name__ == "__main__":
    main()
