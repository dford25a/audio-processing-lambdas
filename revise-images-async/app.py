# --- Standard Library Imports ---
import os
import json
import base64
import uuid
import traceback
from typing import List, Optional, Dict, Any

# --- Third-party Library Imports ---
import requests
import boto3
import openai
from openai import OpenAI

# --- CONFIGURATION ---
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
APPSYNC_API_URL = os.environ.get('APPSYNC_API_URL')
APPSYNC_API_KEY = os.environ.get('APPSYNC_API_KEY')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-2')
BUCKET_NAME = os.environ.get('BUCKET_NAME')

# Session status written while regeneration runs, and the status restored when it
# finishes. REGENERATING_IMAGES is a valid TranscriptionStatus enum value; keeping
# these overridable via env means the value can change without a code deploy.
REGEN_BUSY_STATUS = os.environ.get('REGEN_BUSY_STATUS', 'REGENERATING_IMAGES')
REGEN_DONE_STATUS = os.environ.get('REGEN_DONE_STATUS', 'READ')

# --- VALIDATE ESSENTIAL CONFIGURATION ---
if not OPENAI_API_KEY:
    raise ValueError("Environment variable OPENAI_API_KEY not set!")
if not APPSYNC_API_URL:
    raise ValueError("Environment variable APPSYNC_API_URL not set!")
if not APPSYNC_API_KEY:
    raise ValueError("Environment variable APPSYNC_API_KEY not set!")
if not BUCKET_NAME:
    raise ValueError("Environment variable BUCKET_NAME not set!")

# --- AWS & OPENAI CLIENTS ---
s3_client = boto3.client("s3", region_name=AWS_REGION)
lambda_client = boto3.client("lambda", region_name=AWS_REGION)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

USER_INSTRUCTIONS_MAX = 4000

# Credit cost is computed on the frontend (from IMAGE_QUALITY_OPTIONS) and passed in
# as `creditsToSpend`, mirroring the initial generation flow (start-summary-chain).
# The lambda only performs the server-side deduction + refund-on-failure; the
# frontend owns pricing and the free-standard regeneration allowance.

# imageQuality label -> OpenAI image quality (matches generate-narrative-summary).
image_quality_lookup = {
    "Low quality": "low",
    "Standard quality": "medium",
    "High quality": "high",
}

# Style key -> longDescription (kept in sync with generate-segment-images / final-summary).
image_format_lookup = {
    "fantasy": "A semi-photorealistic fantasy style with bold, directional lighting, rich color saturation, and cinematic composition. Realistic textures, lifelike character detail, and a polished finish create a grounded yet visually striking world with a heightened sense of drama and scale.",
    "dark-fantasy": "A cinematic stylized realism with rich color depth and dynamic lighting. The palette uses vibrant yet grounded tones with strong value contrast to enhance atmosphere and emotional impact, while preserving detail in shadow and highlight areas. The overall aesthetic is dark and serious in tone yet maintains enough visibility and texture for every element to feel tangible and alive.",
    "watercolor": "A refined watercolor style that preserves the medium's softness and translucency while enhancing structure and depth. Colors remain fluid and luminous, but with richer pigment, sharper contrast, and defined brush textures.",
    "Sketchbook": "A traditional pen-and-ink illustration style with muted, earthy tones and fine crosshatching, evoking a classic fantasy storybook or vintage map.",
    "photo-releastic": "A lifelike, cinematic style with natural lighting, vibrant colors, sharp detail, and dramatic depth of field.",
    "cyberpunk": "A cinematic, futuristic rendering style defined by luminous contrast and rich neon hues of violet, cyan, and magenta, balanced against cool, atmospheric shadows.",
    "retro-vibrant": "A bold, 1980s fantasy style with vivid colors, heroic poses, and painterly textures.",
    "graphic-novel": "A clean, inked comic style with vibrant colors, balanced outlines, and cinematic composition.",
    "ink-sketch": "A rough, black-and-white ink style with scratchy lines, heavy cross-hatching, and surreal fantasy elements.",
    "retro": "A pixelated, 8-bit style with chunky forms, limited palettes, and nostalgic charm.",
    "3d-animation": "A polished 3D style with stylized characters, expressive faces, and cinematic lighting.",
    "anime": "A vibrant, cel-shaded style with dynamic poses, clean lines, and painterly backgrounds.",
    "studio-ghibli": "A Studio Ghibli film scene.",
    "painting": "A painterly, realistic style with warm lighting, rich detail, and heroic figures in vast, mythic landscapes.",
}
DEFAULT_STYLE_PROMPT = image_format_lookup["fantasy"]


# ---------------------------------------------------------------------------
# AppSync helpers
# ---------------------------------------------------------------------------

def gql(query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    headers = {'Content-Type': 'application/json', 'x-api-key': APPSYNC_API_KEY}
    payload = {"query": query, "variables": variables or {}}
    try:
        r = requests.post(APPSYNC_API_URL, headers=headers, json=payload, timeout=60)
        r.raise_for_status()
        resp = r.json()
        if "errors" in resp:
            print(f"  [GraphQL errors] {json.dumps(resp['errors'])}")
        return resp
    except requests.exceptions.RequestException as e:
        print(f"AppSync request failed: {e}")
        return {"errors": [{"message": str(e)}]}


_GET_SESSION = """
query GetSession($id: ID!) {
  getSession(id: $id) {
    id _version owner transcriptionStatus regenerateImageCount primaryImage images tldr
  }
}
"""

_GET_SEGMENT = """
query GetSegment($id: ID!) {
  getSegment(id: $id) { id _version title description image images index sessionId }
}
"""

_UPDATE_SESSION = """
mutation UpdateSession($input: UpdateSessionInput!) {
  updateSession(input: $input) { id _version transcriptionStatus regenerateImageCount primaryImage images }
}
"""

_UPDATE_SEGMENT = """
mutation UpdateSegment($input: UpdateSegmentInput!) {
  updateSegment(input: $input) { id _version image images }
}
"""

_GET_USER_TRANSACTIONS = """
query GetUserTransactions($id: ID!) {
  getUserTransactions(id: $id) { id creditBalance _version }
}
"""

_UPDATE_USER_TRANSACTIONS = """
mutation UpdateUserTransactions($input: UpdateUserTransactionsInput!) {
  updateUserTransactions(input: $input) { id creditBalance _version }
}
"""

_CREATE_TRANSACTION = """
mutation CreateTransaction($input: CreateTransactionInput!) {
  createTransaction(input: $input) { id }
}
"""


def get_session(session_id: str) -> Optional[Dict]:
    return (gql(_GET_SESSION, {"id": session_id}).get("data") or {}).get("getSession")


def get_segment(segment_id: str) -> Optional[Dict]:
    return (gql(_GET_SEGMENT, {"id": segment_id}).get("data") or {}).get("getSegment")


def get_user_transactions(user_tx_id: str) -> Optional[Dict]:
    return (gql(_GET_USER_TRANSACTIONS, {"id": user_tx_id}).get("data") or {}).get("getUserTransactions")


def update_session(fields: Dict[str, Any]) -> Optional[Dict]:
    return (gql(_UPDATE_SESSION, {"input": fields}).get("data") or {}).get("updateSession")


# ---------------------------------------------------------------------------
# Credit helpers
# ---------------------------------------------------------------------------

def charge_credits(user_tx_id: str, session_id: str, amount: float) -> bool:
    """Deducts `amount` credits and records a SPEND transaction. Returns success."""
    if amount <= 0:
        return True
    user_tx = get_user_transactions(user_tx_id)
    if not user_tx:
        print(f"[ERROR] UserTransactions {user_tx_id} not found; cannot charge.")
        return False
    balance = user_tx.get("creditBalance", 0) or 0
    if balance < amount:
        print(f"[ERROR] Insufficient credits: have {balance}, need {amount}.")
        return False
    upd = gql(_UPDATE_USER_TRANSACTIONS, {"input": {
        "id": user_tx_id, "creditBalance": balance - amount, "_version": user_tx["_version"]}})
    if not (upd.get("data") or {}).get("updateUserTransactions"):
        print(f"[ERROR] Failed to deduct credits: {upd.get('errors')}")
        return False
    gql(_CREATE_TRANSACTION, {"input": {
        "userTransactionsTransactionsId": user_tx_id,
        "quantity": -amount, "amount": 0, "type": "SPEND", "status": "COMPLETED",
        "stripePaymentIntentId": f"regen_images_{session_id}",
        "description": f"Image regeneration for session {session_id}",
    }})
    return True


def refund_credits(user_tx_id: str, session_id: str, amount: float) -> None:
    """Restores `amount` credits (best-effort) and records a refund transaction."""
    if amount <= 0:
        return
    user_tx = get_user_transactions(user_tx_id)
    if not user_tx:
        print(f"[CRITICAL] Could not fetch UserTransactions {user_tx_id} to refund {amount}.")
        return
    balance = user_tx.get("creditBalance", 0) or 0
    upd = gql(_UPDATE_USER_TRANSACTIONS, {"input": {
        "id": user_tx_id, "creditBalance": balance + amount, "_version": user_tx["_version"]}})
    if not (upd.get("data") or {}).get("updateUserTransactions"):
        print(f"[CRITICAL] Failed to refund {amount} credits to {user_tx_id}: {upd.get('errors')}")
        return
    gql(_CREATE_TRANSACTION, {"input": {
        "userTransactionsTransactionsId": user_tx_id,
        "quantity": amount, "amount": 0, "type": "PURCHASE", "status": "COMPLETED",
        "stripePaymentIntentId": f"regen_refund_{session_id}",
        "description": f"Refund for failed image regeneration, session {session_id}",
    }})


def openai_quality_for(image_quality: str) -> str:
    return image_quality_lookup.get(image_quality, "medium")


# ---------------------------------------------------------------------------
# Image generation
# ---------------------------------------------------------------------------

def resolve_style_prompt(selected_style: str) -> str:
    if not selected_style:
        return DEFAULT_STYLE_PROMPT
    if selected_style in image_format_lookup:
        return image_format_lookup[selected_style]
    # Already a longDescription or custom prompt.
    if len(selected_style) > 20:
        return selected_style
    return DEFAULT_STYLE_PROMPT


def generate_and_upload_image(scene_prompt: str, style_prompt: str, image_quality: str,
                              s3_key: str) -> Optional[str]:
    """Generates one image and uploads it to S3 at s3_key. Returns the key or None."""
    if not scene_prompt:
        print("  No scene prompt; skipping.")
        return None
    full_prompt = f"{style_prompt}. {scene_prompt}"
    try:
        response = openai_client.images.generate(
            model="gpt-image-1-mini",
            prompt=full_prompt,
            n=1,
            size="1536x1024",
            quality=openai_quality_for(image_quality),
        )
        if not (response.data and response.data[0].b64_json):
            print(f"  No image data returned for {s3_key}.")
            return None
        image_bytes = base64.b64decode(response.data[0].b64_json)
        s3_client.put_object(Bucket=BUCKET_NAME, Key=s3_key, Body=image_bytes, ContentType='image/png')
        print(f"  ✅ Uploaded {s3_key}")
        return s3_key
    except openai.APIError as e:
        print(f"  OpenAI API error for {s3_key}: {e}")
        return None
    except Exception as e:
        print(f"  Error generating {s3_key}: {e}")
        traceback.print_exc()
        return None


def build_segment_prompt(segment: Dict, user_instructions: str) -> str:
    """Builds a scene prompt for a segment from its stored title/description."""
    title = (segment.get("title") or "").strip()
    desc = segment.get("description") or []
    if isinstance(desc, list):
        desc_text = desc[-1] if desc else ""
    else:
        desc_text = desc or ""
    parts = [p for p in [title, desc_text] if p]
    prompt = ". ".join(parts) if parts else "A scene from this tabletop RPG session."
    if user_instructions:
        prompt = f"{prompt}\n\nAdditional user direction: {user_instructions}"
    return prompt


def build_cover_prompt(session: Dict, user_instructions: str) -> str:
    tldr = session.get("tldr") or []
    tldr_text = (tldr[0] if isinstance(tldr, list) and tldr else (tldr if isinstance(tldr, str) else "")) or ""
    prompt = tldr_text.strip() or "A dramatic cover illustration for this tabletop RPG session."
    if user_instructions:
        prompt = f"{prompt}\n\nAdditional user direction: {user_instructions}"
    return prompt


def _append_history(existing: Optional[List[str]], current_active: Optional[str], new_key: str) -> List[str]:
    """
    Appends new_key to the version-history list, preserving order.

    The initial pipeline (persist-summary-data) only sets the singular image
    field (Segment.image / Session.primaryImage) and never seeds the images
    array, so on the first regeneration we seed history with the existing active
    image. This keeps the original version in the gallery instead of the array
    only ever containing the newest image.
    """
    history = list(existing) if existing else []
    if not history and current_active:
        history.append(current_active)
    history.append(new_key)
    return history


# ---------------------------------------------------------------------------
# Background worker — does the actual regeneration
# ---------------------------------------------------------------------------

def handle_background(payload: Dict[str, Any]) -> None:
    session_id = payload["sessionId"]
    targets = payload.get("targets", {})
    image_instructions = payload.get("image_instructions", {})
    user_instructions = payload.get("userInstructions", "") or ""
    user_tx_id = payload.get("userTransactionsTransactionsId")
    credits_charged = payload.get("creditsCharged", 0) or 0

    style_prompt = resolve_style_prompt(image_instructions.get("selectedStyle"))
    image_quality = image_instructions.get("imageQuality", "Standard quality")

    include_cover = bool(targets.get("includeCover"))
    segment_ids = targets.get("segmentIds") or []

    failed = False
    try:
        # --- Cover -------------------------------------------------------------
        if include_cover:
            session = get_session(session_id)
            if not session:
                raise ValueError(f"Session {session_id} not found for cover regeneration.")
            cover_prompt = build_cover_prompt(session, user_instructions)
            new_key = generate_and_upload_image(
                cover_prompt, style_prompt, image_quality,
                f"public/segment-images/{session_id}_cover_{uuid.uuid4().hex}.png")
            if not new_key:
                raise RuntimeError("Cover image generation failed.")
            updated = update_session({
                "id": session_id,
                "_version": session["_version"],
                "primaryImage": new_key,
                "images": _append_history(session.get("images"), session.get("primaryImage"), new_key),
            })
            if not updated:
                raise RuntimeError("Failed to persist regenerated cover.")
            print(f"Cover regenerated for session {session_id}")

        # --- Segments ----------------------------------------------------------
        for segment_id in segment_ids:
            segment = get_segment(segment_id)
            if not segment:
                raise ValueError(f"Segment {segment_id} not found.")
            if segment.get("sessionId") and segment["sessionId"] != session_id:
                raise ValueError(f"Segment {segment_id} does not belong to session {session_id}.")
            scene_prompt = build_segment_prompt(segment, user_instructions)
            new_key = generate_and_upload_image(
                scene_prompt, style_prompt, image_quality,
                f"public/segment-images/{session_id}_segment_{segment_id}_{uuid.uuid4().hex}.png")
            if not new_key:
                raise RuntimeError(f"Image generation failed for segment {segment_id}.")
            upd = gql(_UPDATE_SEGMENT, {"input": {
                "id": segment_id,
                "_version": segment["_version"],
                "image": new_key,
                "images": _append_history(segment.get("images"), segment.get("image"), new_key),
            }})
            if not (upd.get("data") or {}).get("updateSegment"):
                raise RuntimeError(f"Failed to persist regenerated image for segment {segment_id}.")
            print(f"Segment {segment_id} regenerated")

    except Exception as e:
        failed = True
        print(f"[ERROR] Regeneration failed for session {session_id}: {e}")
        traceback.print_exc()
        if user_tx_id and credits_charged:
            print(f"Refunding {credits_charged} credits to {user_tx_id} after failure.")
            refund_credits(user_tx_id, session_id, credits_charged)

    finally:
        # Always restore the session status so the UI stops showing the spinner.
        restore = get_session(session_id)
        if restore:
            res = update_session({
                "id": session_id,
                "_version": restore["_version"],
                "transcriptionStatus": REGEN_DONE_STATUS,
            })
            if not res:
                print(f"[CRITICAL] Failed to restore status for session {session_id}.")
        print(f"revise-images-async worker finished (failed={failed}) for session {session_id}")


# ---------------------------------------------------------------------------
# Dispatcher — validates, charges, flips status, kicks off the worker, returns fast
# ---------------------------------------------------------------------------

def _http(success: bool, error: str = "", extra: Optional[Dict] = None) -> Dict[str, Any]:
    body = {"success": success, "error": error}
    if extra:
        body.update(extra)
    # Always HTTP 200 even for handled failures — a non-200 triggers the client's blind retry.
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "OPTIONS,POST",
        },
        "body": json.dumps(body),
    }


def _cognito_sub(event: Dict[str, Any]) -> Optional[str]:
    try:
        claims = event["requestContext"]["authorizer"]["claims"]
        return claims.get("sub")
    except (KeyError, TypeError):
        return None


def handle_dispatch(event, context) -> Dict[str, Any]:
    body_str = event.get("body")
    if not body_str:
        return _http(False, "Missing request body.")
    try:
        body = json.loads(body_str) if isinstance(body_str, str) else body_str
    except json.JSONDecodeError as e:
        return _http(False, f"Invalid JSON body: {e}")

    session_id = body.get("sessionId")
    campaign_id = body.get("campaignId")
    targets = body.get("targets") or {}
    image_instructions = body.get("image_instructions") or {}
    user_instructions = body.get("userInstructions", "") or ""

    if not session_id:
        return _http(False, "sessionId is required.")
    if len(user_instructions) > USER_INSTRUCTIONS_MAX:
        return _http(False, f"userInstructions exceeds {USER_INSTRUCTIONS_MAX} characters.")

    include_cover = bool(targets.get("includeCover"))
    segment_ids = targets.get("segmentIds") or []
    if not include_cover and not segment_ids:
        return _http(False, "No regeneration targets: set includeCover or provide segmentIds.")

    # Credit cost is computed by the frontend (from IMAGE_QUALITY_OPTIONS) and passed
    # in, mirroring the initial generation flow. Deduction happens server-side below.
    credits_to_charge = body.get("creditsToSpend", 0) or 0
    if not isinstance(credits_to_charge, (int, float)) or credits_to_charge < 0:
        return _http(False, "creditsToSpend must be a non-negative number.")

    # Resolve the caller's UserTransactions record. Its id == the Cognito sub
    # (see init-credits). Fall back to an explicit body field for direct invokes/tests.
    user_tx_id = _cognito_sub(event) or body.get("userTransactionsTransactionsId")
    if credits_to_charge > 0 and not user_tx_id:
        return _http(False, "Could not resolve the authenticated user for credit charging.")

    session = get_session(session_id)
    if not session:
        return _http(False, f"Session {session_id} not found.")

    current_regen_count = session.get("regenerateImageCount") or 0

    # Count one per image the user asked to regenerate (cover + each segment).
    images_requested = (1 if include_cover else 0) + len(segment_ids)

    if credits_to_charge > 0:
        if not charge_credits(user_tx_id, session_id, credits_to_charge):
            return _http(False, "Insufficient credits or failed to charge for image regeneration.")

    # Increment the counter by the number of images requested and flip status to the
    # busy state (single write so the frontend subscription fires once).
    updated = update_session({
        "id": session_id,
        "_version": session["_version"],
        "regenerateImageCount": current_regen_count + images_requested,
        "transcriptionStatus": REGEN_BUSY_STATUS,
    })
    if not updated:
        # Roll back the charge so the user isn't billed for a no-op.
        if credits_to_charge > 0:
            refund_credits(user_tx_id, session_id, credits_to_charge)
        return _http(False, "Failed to update session status; please retry.")

    # Kick off the background worker and return immediately.
    worker_payload = {
        "is_background_worker": True,
        "sessionId": session_id,
        "campaignId": campaign_id,
        "targets": {"includeCover": include_cover, "segmentIds": segment_ids},
        "image_instructions": image_instructions,
        "userInstructions": user_instructions,
        "userTransactionsTransactionsId": user_tx_id,
        "creditsCharged": credits_to_charge,
    }
    try:
        lambda_client.invoke(
            FunctionName=context.function_name,
            InvocationType='Event',
            Payload=json.dumps(worker_payload),
        )
    except Exception as e:
        print(f"[ERROR] Failed to invoke background worker: {e}")
        # Best-effort rollback: refund and restore status.
        if credits_to_charge > 0:
            refund_credits(user_tx_id, session_id, credits_to_charge)
        restore = get_session(session_id)
        if restore:
            update_session({"id": session_id, "_version": restore["_version"],
                            "transcriptionStatus": REGEN_DONE_STATUS})
        return _http(False, "Failed to start image regeneration; please retry.")

    return _http(True, "", {"message": "Image regeneration started."})


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------

def lambda_handler(event, context):
    """
    Regenerates selected session images (cover and/or specific segments), appending
    each result to version history. See issue #5.

    Acts as a dispatcher for API Gateway requests (returns immediately after flipping
    the session into REGENERATING_IMAGES) and re-invokes itself as a background worker
    (is_background_worker=True) to do the generation and restore status when done.
    """
    if isinstance(event, dict) and event.get("is_background_worker"):
        handle_background(event)
        return {"statusCode": 200}

    try:
        return handle_dispatch(event, context)
    except Exception as e:
        print(f"[ERROR] revise-images-async dispatch failed: {e}")
        traceback.print_exc()
        return _http(False, "An unexpected error occurred.")
