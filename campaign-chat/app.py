# --- Standard Library Imports ---
import json
import os
import traceback
from typing import List, Dict, Optional, Any

# --- Third-party Library Imports ---
import boto3
import numpy as np
import faiss  # Requires faiss-cpu to be in the Lambda Layer
import requests # Requires requests to be in the Lambda Layer
from openai import OpenAI

# --- CONFIGURATION ---
S3_BUCKET_NAME = os.environ.get('BUCKET_NAME')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-2')
INDEX_SOURCE_PREFIX = os.environ.get('INDEX_SOURCE_PREFIX', 'private/campaign-indexes/') # Note: Changed from public to private
APPSYNC_API_URL = os.environ.get('APPSYNC_API_URL')
APPSYNC_API_KEY_FROM_ENV = os.environ.get('APPSYNC_API_KEY')

EMBEDDING_MODEL_ID = 'amazon.titan-embed-text-v2:0'
# GENERATION_MODEL_ID = 'us.anthropic.claude-3-haiku-20240307-v1:0'
OPENAI_API_KEY_FROM_ENV = os.environ.get('OPENAI_API_KEY')
if not OPENAI_API_KEY_FROM_ENV:
    raise ValueError("Environment variable OPENAI_API_KEY not set!")

# --- VALIDATE ESSENTIAL CONFIGURATION ---
if not S3_BUCKET_NAME: raise ValueError("Environment variable BUCKET_NAME not set!")
if not APPSYNC_API_URL: raise ValueError("Environment variable APPSYNC_API_URL not set!")
if not APPSYNC_API_KEY_FROM_ENV: raise ValueError("Environment variable APPSYNC_API_KEY not set!")

# --- AWS & AppSync CLIENTS ---
s3_client = boto3.client('s3', region_name=AWS_REGION)
bedrock_runtime = boto3.client(service_name='bedrock-runtime', region_name=AWS_REGION)
openai_client = OpenAI(api_key=OPENAI_API_KEY_FROM_ENV)

# --- GLOBAL CACHE ---
cache = {}

# --- GraphQL Query ---
LIST_ACTIVE_SESSIONS_QUERY = """
query ListSessions($campaignId: ID!, $limit: Int, $nextToken: String) {
  listSessions(
    filter: {
      campaignSessionsId: { eq: $campaignId },
      _deleted: { ne: true }
    },
    limit: $limit,
    nextToken: $nextToken
  ) {
    items {
      id
    }
    nextToken
  }
}
"""

# --- HELPER FUNCTIONS ---
def normalize_message_content(messages: List[Dict]) -> List[Dict]:
    """
    Ensures the 'content' field of each message is a flat string.
    This handles cases where content might be a list of strings.
    """
    normalized_messages = []
    for msg in messages:
        # Make a copy to avoid modifying the original dict in place
        new_msg = msg.copy()
        content = new_msg.get('content')
        
        if isinstance(content, list):
            # If content is a list, join its elements into a single string
            new_msg['content'] = " ".join(map(str, content))
        elif not isinstance(content, str):
            # If it's some other non-string type, convert it safely
            new_msg['content'] = str(content)
            
        normalized_messages.append(new_msg)
        
    return normalized_messages


def execute_graphql_request(query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Executes a GraphQL request against the AppSync endpoint using an API Key."""
    headers = {'Content-Type': 'application/json', 'x-api-key': APPSYNC_API_KEY_FROM_ENV}
    payload = {"query": query, "variables": variables or {}}
    try:
        response = requests.post(APPSYNC_API_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        response_json = response.json()
        if "errors" in response_json:
            print(f"GraphQL Error: {json.dumps(response_json['errors'], indent=2)}")
        return response_json
    except requests.exceptions.RequestException as e:
        print(f"Error making AppSync request: {e}")
        return {"errors": [{"message": f"RequestException: {e}"}]}

def get_active_session_ids(campaign_id: str) -> List[str]:
    """Paginates through AppSync to get all non-deleted session IDs for a campaign."""
    active_ids = []
    next_token = None
    while True:
        variables = {"campaignId": campaign_id, "limit": 100, "nextToken": next_token}
        response = execute_graphql_request(LIST_ACTIVE_SESSIONS_QUERY, variables)
        
        data = response.get("data", {}).get("listSessions", {})
        if not data or response.get("errors"):
            print("Failed to fetch sessions from AppSync or received an error.")
            break
            
        items = data.get("items", [])
        for item in items:
            active_ids.append(item['id'])
            
        next_token = data.get("nextToken")
        if not next_token:
            break
    print(f"Found {len(active_ids)} active sessions for campaign {campaign_id}.")
    return active_ids

def load_index_from_s3(campaign_id: str) -> tuple:
    if campaign_id in cache:
        print(f"Using cached index for campaign: {campaign_id}")
        return cache[campaign_id]

    print(f"Loading index from S3 for campaign: {campaign_id}")
    index_s3_key = f"{INDEX_SOURCE_PREFIX}{campaign_id}.index"
    mapping_s3_key = f"{INDEX_SOURCE_PREFIX}{campaign_id}.json"
    local_index_path, local_mapping_path = f"/tmp/{campaign_id}.index", f"/tmp/{campaign_id}.json"
    
    try:
        s3_client.download_file(S3_BUCKET_NAME, index_s3_key, local_index_path)
        s3_client.download_file(S3_BUCKET_NAME, mapping_s3_key, local_mapping_path)
        index = faiss.read_index(local_index_path)
        with open(local_mapping_path, 'r') as f:
            mapping = json.load(f)
        cache[campaign_id] = (index, mapping)
        return index, mapping
    except s3_client.exceptions.NoSuchKey:
        print(f"Index or mapping file not found for campaign {campaign_id}")
        return None, None
    except Exception as e:
        print(f"Error loading index from S3: {e}")
        return None, None

def get_embedding_for_query(query_text: str) -> np.ndarray:
    body = json.dumps({"inputText": query_text})
    response = bedrock_runtime.invoke_model(
        body=body, modelId=EMBEDDING_MODEL_ID, accept='application/json', contentType='application/json'
    )
    response_body = json.loads(response.get('body').read())
    return np.array([response_body.get('embedding')], dtype='float32')

def get_openai_response(prompt: str, messages: List[Dict[str, str]], debug: bool = True) -> str:
    if debug: print(f"Sending prompt to OpenAI. System Prompt Length: {len(prompt)}, Messages Count: {len(messages)}")
    try:
        full_messages = [{"role": "system", "content": prompt}] + messages
        completion = openai_client.chat.completions.create(
            model="gpt-4.1-nano",
            messages=full_messages,
            stream=False
        )
        if completion.choices and completion.choices[0].message and completion.choices[0].message.content:
            response_content = completion.choices[0].message.content
            if debug: print(f"OpenAI response content (first 300 chars): {response_content[:300]}...")
            return response_content
        else:
            if debug: print("OpenAI response lacked content or choices.")
            return "I'm sorry, I couldn't generate a response at this time."
    except Exception as e:
        if debug: print(f"Error calling OpenAI: {e}"); traceback.print_exc()
        return "There was an error communicating with the AI. Please try again."

# --- MAIN LAMBDA HANDLER ---
def lambda_handler(event, context):
    debug = True
    if debug: print(f"Received event: {json.dumps(event)}")
    
    try:
        body = json.loads(event['body'])
        campaign_id = body.get('campaignId')
        # The incoming messages from the client
        original_messages = body.get('messages')

        if not campaign_id or not original_messages or not isinstance(original_messages, list):
            return {'statusCode': 400, 'headers': {'Access-Control-Allow-Origin': '*'}, 'body': json.dumps({'error': 'Missing or invalid fields'})}

        # --- START: NEW AND IMPROVED MESSAGE PARSING ---
        # This comprehension iterates through your original messages and rebuilds them
        # in the correct format for the Bedrock Claude 3 model.
        # 1. It extracts the 'text' from the 'content' list.
        # 2. It only includes the 'role' and 'content' keys, dropping the 'id'.
        user_chat_messages = [
            {
                "role": msg["role"],
                "content": msg["content"][0]["text"] 
            }
            for msg in original_messages
            if msg.get("content") and isinstance(msg.get("content"), list) and msg["content"][0].get("type") == "text"
        ]
        # --- END: NEW AND IMPROVED MESSAGE PARSING ---

        # You no longer need the normalize_message_content function call.
        # user_chat_messages = normalize_message_content(body.get('messages')) # <--- DELETE THIS LINE

        if not user_chat_messages:
             return {'statusCode': 400, 'headers': {'Access-Control-Allow-Origin': '*'}, 'body': json.dumps({'error': 'Message list is empty or invalid format after parsing.'})}

        # 1. **NEW**: Get a list of all active (not deleted) session IDs for this campaign.
        active_session_ids = get_active_session_ids(campaign_id)
        if not active_session_ids:
             return {'statusCode': 404, 'headers': {'Access-Control-Allow-Origin': '*'}, 'body': json.dumps({'error': f'No active sessions found for campaign {campaign_id}.'})}
        # Normalize session IDs by stripping "Session" prefix if present
        def normalize_session_id(sid):
            return sid[len("Session"):] if isinstance(sid, str) and sid.startswith("Session") else sid
        active_session_ids_set = set(normalize_session_id(sid) for sid in active_session_ids)

        # 2. Load FAISS index and mapping from S3
        index, mapping = load_index_from_s3(campaign_id)
        if index is None:
            return {'statusCode': 404, 'headers': {'Access-Control-Allow-Origin': '*'}, 'body': json.dumps({'error': f'No index found for campaign {campaign_id}.'})}

        # 3. Embed the latest user query
        latest_query = user_chat_messages[-1]['content']
        query_embedding = get_embedding_for_query(latest_query)

        # 4. Search the index for relevant context
        k = 5 # Retrieve more results initially to allow for filtering
        distances, indices = index.search(query_embedding, k)
        if debug:
            print(f"FAISS search returned indices: {indices[0].tolist()}")
            print(f"FAISS search returned distances: {distances[0].tolist()}")

        # 5. **NEW**: Filter the retrieved chunks to include only those from active sessions.
        relevant_chunks = []
        retrieved_chunk_infos = []
        if debug:
            print(f"Raw FAISS indices: {indices[0].tolist()}")
            print(f"Active session IDs: {active_session_ids_set}")
        for i in indices[0]:
            if i == -1:
                if debug:
                    print("Skipping FAISS index -1 (no neighbor found).")
                continue
            chunk_info = mapping[i]
            retrieved_chunk_infos.append(chunk_info)
            session_id = chunk_info.get("session_id")
            # Normalize: strip "Session" prefix if present
            normalized_session_id = session_id
            if session_id and session_id.startswith("Session"):
                normalized_session_id = session_id[len("Session"):]
            if normalized_session_id in active_session_ids_set:
                relevant_chunks.append(chunk_info['text'])
                if debug:
                    print(f"INCLUDED chunk from session_id: {session_id} (normalized: {normalized_session_id})")
            else:
                if debug:
                    print(f"FILTERED OUT chunk from session_id: {session_id} (normalized: {normalized_session_id}) (not in active_session_ids)")
        if debug:
            print(f"Processed {len(retrieved_chunk_infos)} chunk_info objects (pre-filter):")
            for info in retrieved_chunk_infos:
                print(json.dumps(info, indent=2))
            print(f"Filtered {len(relevant_chunks)} relevant_chunks (text only):")
            for chunk in relevant_chunks:
                print(chunk)

        if not relevant_chunks:
            # Handle case where no relevant context is found in active sessions
            relevant_chunks.append("No specific context was found in the active session transcripts for this query.")

        context_str = "\n\n---\n\n".join(relevant_chunks)
        if debug: print(f"Retrieved {len(relevant_chunks)} relevant, filtered chunks from index.")
        
        # 6. Construct System Prompt and call OpenAI
        system_prompt = f"""You are Scribe, an AI chat assistant for a TTRPG campaign. Your goal is to answer questions based on the provided chunks of context from TTRPG transcripts. Do your best to answer the questions given the context below. 

<context>
{context_str}
</context>
"""
        ai_response_content = get_openai_response(system_prompt, user_chat_messages, debug=debug)

        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'},
            'body': json.dumps({'message': ai_response_content})
        }

    except Exception as e:
        if debug: print(f"General unhandled error in lambda_handler: {str(e)}"); traceback.print_exc()
        return {'statusCode': 500, 'headers': {'Access-Control-Allow-Origin': '*'}, 'body': json.dumps({'error': f'An unexpected internal server error occurred: {str(e)}'})}
