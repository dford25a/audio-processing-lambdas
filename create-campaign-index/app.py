# --- Standard Library Imports ---
import json
import os
import re
import traceback
from typing import List, Dict, Tuple, Optional

# --- Third-party Library Imports ---
import boto3
import numpy as np
import faiss  # Requires faiss-cpu to be in the Lambda Layer

# --- CONFIGURATION ---
# It's recommended to retrieve these from environment variables for security and flexibility.
S3_BUCKET_NAME = os.environ.get('BUCKET_NAME')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-2')
SOURCE_PREFIX = os.environ.get('SOURCE_TRANSCRIPT_PREFIX', 'public/segmentedSummaries/')
INDEX_DESTINATION_PREFIX = os.environ.get('INDEX_DESTINATION_PREFIX', 'private/campaign-indexes/')
EMBEDDING_MODEL_ID = 'amazon.titan-embed-text-v2:0'

# --- VALIDATE ESSENTIAL CONFIGURATION ---
if not S3_BUCKET_NAME:
    raise ValueError("FATAL: Environment variable BUCKET_NAME not set!")

# --- AWS CLIENTS ---
# Initialize clients once to be reused across invocations.
s3_client = boto3.client('s3', region_name=AWS_REGION)
bedrock_runtime = boto3.client(service_name='bedrock-runtime', region_name=AWS_REGION)

# --- HELPER FUNCTIONS ---

def get_ids_from_key(key: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extracts campaign and session IDs from the S3 object key using regex.
    Example key format: '.../campaignUUIDSessionUUID.txt'
    Returns: A tuple containing (campaign_id, session_id).
    """
    # Regex to find 'campaign' followed by a UUID and 'Session' followed by a UUID.
    match = re.search(r'campaign([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})Session([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})', key)
    if match:
        campaign_uuid = match.group(1)
        session_uuid = match.group(2)
        # Reconstruct the full IDs as they might appear elsewhere.
        campaign_id = f"campaign{campaign_uuid}"
        session_id = f"Session{session_uuid}"
        return campaign_id, session_id
    return None, None

def split_text_into_chunks(text: str, chunk_size: int = 400, chunk_overlap: int = 50) -> List[str]:
    """Splits a long text into overlapping chunks of words."""
    if not text:
        return []
    
    words = text.split()
    if not words:
        return []

    chunks = []
    current_pos = 0
    while current_pos < len(words):
        end_pos = current_pos + chunk_size
        chunk_words = words[current_pos:end_pos]
        chunks.append(" ".join(chunk_words))
        
        # Move the window forward, ensuring overlap.
        current_pos += (chunk_size - chunk_overlap)
        
    return chunks

def generate_embeddings(chunks: List[str]) -> Optional[np.ndarray]:
    """Generates embeddings for a list of text chunks using Amazon Bedrock."""
    if not chunks:
        return None

    embeddings = []
    for chunk in chunks:
        body = json.dumps({"inputText": chunk})
        try:
            response = bedrock_runtime.invoke_model(
                body=body,
                modelId=EMBEDDING_MODEL_ID,
                accept='application/json',
                contentType='application/json'
            )
            response_body = json.loads(response.get('body').read())
            embedding = response_body.get('embedding')
            if embedding:
                embeddings.append(embedding)
        except Exception as e:
            # Log the error but continue processing other chunks.
            print(f"Error generating embedding for chunk: '{chunk[:50]}...'. Error: {e}")
            continue
    
    if not embeddings:
        return None
        
    return np.array(embeddings, dtype='float32')

# --- MAIN LAMBDA HANDLER ---

def lambda_handler(event, context):
    """
    Triggered by SNS or S3 directly. Reads all transcripts for a campaign, 
    generates embeddings, creates a FAISS index, and saves the index and a metadata 
    mapping file back to S3.
    """
    debug = True
    if debug: print(f"Received raw event: {json.dumps(event)}")

    try:
        # --- FIX: HANDLE BOTH SNS AND DIRECT S3 TRIGGERS ---
        # Check if the event is from SNS.
        if 'Sns' in event['Records'][0]:
            if debug: print("Event is from SNS. Parsing message...")
            sns_message_str = event['Records'][0]['Sns']['Message']
            s3_event = json.loads(sns_message_str)
            s3_record = s3_event['Records'][0]['s3']
        # Otherwise, assume it's a direct S3 event.
        else:
            if debug: print("Event is a direct S3 trigger.")
            s3_record = event['Records'][0]['s3']
        # --- END FIX ---
        
        bucket_name = s3_record['bucket']['name']
        triggered_key = s3_record['object']['key']

        if not triggered_key.startswith(SOURCE_PREFIX):
            if debug: print(f"Object {triggered_key} is not in the source prefix {SOURCE_PREFIX}. Skipping.")
            return {'statusCode': 200, 'body': 'Not a target object, skipping.'}

        campaign_id, _ = get_ids_from_key(triggered_key)
        if not campaign_id:
            print(f"Could not determine campaign ID from key: {triggered_key}. Aborting.")
            return {'statusCode': 400, 'body': f'Could not determine campaign ID from key: {triggered_key}'}
        
        if debug: print(f"Processing for Campaign ID: {campaign_id}")

        all_chunks_with_source = []
        
        directory_of_trigger_file = os.path.dirname(triggered_key)
        campaign_transcript_prefix = f"{directory_of_trigger_file}/{campaign_id}"
        if debug: print(f"Constructed campaign listing prefix: {campaign_transcript_prefix}")
        
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=bucket_name, Prefix=campaign_transcript_prefix)

        for page in pages:
            for obj in page.get('Contents', []):
                transcript_key = obj['Key']
                _, transcript_session_id = get_ids_from_key(transcript_key)
                if not transcript_session_id:
                    print(f"Skipping file, could not parse session ID from key: {transcript_key}")
                    continue

                if debug: print(f"Reading transcript: {transcript_key} for Session ID: {transcript_session_id}")
                
                s3_object = s3_client.get_object(Bucket=bucket_name, Key=transcript_key)
                transcript_text = s3_object['Body'].read().decode('utf-8')
                
                chunks = split_text_into_chunks(transcript_text)
                
                for chunk_text in chunks:
                    all_chunks_with_source.append({
                        "source_file": transcript_key,
                        "session_id": transcript_session_id,
                        "text": chunk_text
                    })

        if not all_chunks_with_source:
            print(f"No text chunks found for campaign {campaign_id}. Nothing to index.")
            return {'statusCode': 200, 'body': 'No content to index.'}

        if debug: print(f"Total chunks from all transcripts for campaign {campaign_id}: {len(all_chunks_with_source)}")
        
        all_texts = [item['text'] for item in all_chunks_with_source]
        embeddings = generate_embeddings(all_texts)
        
        if embeddings is None or embeddings.shape[0] == 0:
            print("Failed to generate any embeddings. Aborting.")
            return {'statusCode': 500, 'body': 'Embedding generation failed.'}
            
        if debug: print(f"Generated {embeddings.shape[0]} embeddings of dimension {embeddings.shape[1]}")

        dimension = embeddings.shape[1]
        index = faiss.IndexFlatL2(dimension)
        index.add(embeddings)
        
        if debug: print(f"FAISS index created successfully. Total vectors in index: {index.ntotal}")

        local_index_path = f"/tmp/{campaign_id}.index"
        local_mapping_path = f"/tmp/{campaign_id}.json"
        
        faiss.write_index(index, local_index_path)
        with open(local_mapping_path, 'w') as f:
            json.dump(all_chunks_with_source, f, indent=2)

        s3_index_key = f"{INDEX_DESTINATION_PREFIX}{campaign_id}.index"
        s3_mapping_key = f"{INDEX_DESTINATION_PREFIX}{campaign_id}.json"
        
        s3_client.upload_file(local_index_path, bucket_name, s3_index_key)
        s3_client.upload_file(local_mapping_path, bucket_name, s3_mapping_key)
        
        if debug: print(f"Successfully uploaded index to s3://{bucket_name}/{s3_index_key}")
        if debug: print(f"Successfully uploaded mapping to s3://{bucket_name}/{s3_mapping_key}")

        return {
            'statusCode': 200, 
            'body': json.dumps(f'Successfully created/updated index for campaign {campaign_id}')
        }

    except Exception as e:
        print(f"General unhandled error in lambda_handler: {str(e)}")
        traceback.print_exc()
        return {
            'statusCode': 500, 
            'body': json.dumps({'error': f'An unexpected internal server error occurred: {str(e)}'})
        }