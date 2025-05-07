import json
import boto3
from openai import OpenAI
import os # <--- Import the 'os' module
from boto3.dynamodb.conditions import Attr

# --- CONFIGURATION ---
# Read from environment variables set by Terraform
# These are available when the Lambda execution environment initializes
DYNAMODB_TABLE_NAME = os.environ.get('DYNAMODB_TABLE')
S3_BUCKET_NAME = os.environ.get('BUCKET_NAME')
OPENAI_API_KEY_FROM_ENV = os.environ.get('OPENAI_API_KEY')

# --- VALIDATE ESSENTIAL CONFIGURATION ---
# It's good practice to check if these are set, especially during Lambda cold starts
if not DYNAMODB_TABLE_NAME:
    # This will cause the Lambda invocation to fail if the env var is missing,
    # which is often desired as the function cannot operate without it.
    # CloudWatch Logs will show this error.
    raise ValueError("Environment variable DYNAMODB_TABLE not set!")
if not S3_BUCKET_NAME:
    raise ValueError("Environment variable BUCKET_NAME not set!")
if not OPENAI_API_KEY_FROM_ENV:
    raise ValueError("Environment variable OPENAI_API_KEY not set!")

# --- AWS CLIENTS ---
# Initialize outside the handler for better performance (reused across invocations)
s3 = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
# Use the DYNAMODB_TABLE_NAME from environment variable
table = dynamodb.Table(DYNAMODB_TABLE_NAME)

# --- OPENAI CLIENT ---
# Initialize outside the handler
client = OpenAI(api_key=OPENAI_API_KEY_FROM_ENV) # <--- Use the key from environment

def get_openai_response(prompt, messages):
    """ Calls OpenAI's API and gets the full completion response. """
    response = client.chat.completions.create(
        model="gpt-4.1-nano", # Consider making model configurable via env var too
        messages=[{"role": "system", "content": prompt}] + messages,
        stream=False
    )
    return response.choices[0].message.content if response.choices else ""

def lambda_handler(event, context):
    """ AWS Lambda Handler for retrieving OpenAI responses. """
    try:
        # Log the received event for debugging
        print(f"Received event: {json.dumps(event)}")
        print(f"Using DynamoDB table: {DYNAMODB_TABLE_NAME}") # For verification
        print(f"Using S3 bucket: {S3_BUCKET_NAME}")         # For verification

        # --- CORRECTED INPUT PARSING ---
        if not event.get('body'):
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing request body'})
            }
        try:
            body = json.loads(event['body'])
        except json.JSONDecodeError:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Invalid JSON in request body'})
            }

        session_id = body.get('sessionId')
        campaign_id = body.get('campaignId')
        messages = body.get('messages')
        # --- END CORRECTION ---

        if not session_id or not campaign_id or not messages:
            return {
                'statusCode': 400,
                'headers': {
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token',
                    'Access-Control-Allow-Methods': 'POST,OPTIONS'
                },
                'body': json.dumps({'error': 'Missing required fields in body: sessionId, campaignId, or messages'})
            }

        # DynamoDB table is already initialized globally using DYNAMODB_TABLE_NAME
        # table = dynamodb.Table(DYNAMODB_TABLE_NAME) # This line is now redundant here, using global `table`

        scan_filter = Attr('audioFile').contains(f"campaign{campaign_id}Session{session_id}")
        resp = table.scan(FilterExpression=scan_filter) # Now uses the dynamically set table

        if not resp['Items']:
            return {
                'statusCode': 404,
                'headers': {
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token',
                    'Access-Control-Allow-Methods': 'POST,OPTIONS'
                },
                'body': json.dumps({'error': f'No item found for campaignId={campaign_id}, sessionId={session_id}'})
            }

        item = resp['Items'][0]
        audio_key = item['audioFile']
        original_summary = item.get('description', '')

        # S3_BUCKET_NAME is already initialized globally
        # bucket = S3_BUCKET_NAME # This line is now redundant here, using global S3_BUCKET_NAME
        folder_path = "public/transcriptedAudio/"
        file_name_without_extension = audio_key.rsplit('.', 1)[0]
        prefix = f"{folder_path}{file_name_without_extension}"

        # Use the S3_BUCKET_NAME from environment variable
        uploaded_objs = s3.list_objects_v2(Bucket=S3_BUCKET_NAME, Prefix=prefix)
        text = ''
        if 'Contents' not in uploaded_objs or not uploaded_objs['Contents']:
             print(f"No objects found in S3 with prefix: {prefix} in bucket {S3_BUCKET_NAME}")
        else: # Ensure else block to avoid iterating if 'Contents' is missing
            for obj in uploaded_objs.get('Contents', []): # .get is safer
                data = s3.get_object(Bucket=S3_BUCKET_NAME, Key=obj['Key']) # Use S3_BUCKET_NAME
                contents = data['Body'].read().decode('utf8')
                text += contents

    except Exception as e:
        print(f"Error during data retrieval or setup: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'headers': {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token',
                'Access-Control-Allow-Methods': 'POST,OPTIONS'
            },
            'body': json.dumps({'error': f"Internal server error: {str(e)}"})
        }

    system_prompt = f"""
    You are an AI assistant for a campaign conversation. You have access to the session summary and transcript. Use this context:

    - **Campaign Session Summary:** {original_summary}
    - **Session Transcript from S3:** {text if text else "No transcript available."}

    Your goal is to provide relevant responses in the campaign's tone, continuing the conversation naturally.
    """

    try:
        ai_response = get_openai_response(system_prompt, messages)

        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token',
                'Access-Control-Allow-Methods': 'POST,OPTIONS'
            },
            'body': json.dumps({'message': ai_response})
        }
    except Exception as e:
        print(f"Error during OpenAI call: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 502,
            'headers': {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token',
                'Access-Control-Allow-Methods': 'POST,OPTIONS'
            },
            'body': json.dumps({'error': f"Error communicating with AI service: {str(e)}"})
        }