import json
import boto3
import openai
import os
from boto3.dynamodb.conditions import Attr
from openai import OpenAI

s3 = boto3.client("s3")

OPENAI_API_KEY_FROM_ENV = os.environ.get('OPENAI_API_KEY')
S3_BUCKET_NAME = os.environ.get('BUCKET_NAME')
DYNAMODB_TABLE_NAME = os.environ.get('DYNAMODB_TABLE')

# Helper function to get OpenAI completion
def get_completion(prompt, client, model="gpt-4.1-mini"):
    print("Sending prompt to OpenAI...")
    messages = [{"role": "user", "content": prompt}]
    response = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=messages,
        temperature=0.1,
    )
    print("OpenAI response received")
    return response.choices[0].message.content

def lambda_handler(event, context):
    try:
        print(f"Event received: {json.dumps(event)}")

        session_id = event['sessionId']
        campaign_id = event['campaignId']
        user_revisions = event['userRevisions']
        print(f"Parameters: sessionId={session_id}, campaignId={campaign_id}, userRevisions={user_revisions}")

        # DynamoDB table
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table(DYNAMODB_TABLE_NAME)

        # Query for matching item using campaignId and sessionId as substrings in the audioFile name
        scan_filter = Attr('audioFile').contains(f"campaign{campaign_id}Session{session_id}")
        print(f"Querying DynamoDB with audioFile contains: campaign{campaign_id}Session{session_id}")
        resp = table.scan(FilterExpression=scan_filter)
        print(f"DynamoDB query response: {resp}")

        if not resp['Items']:
            print("No matching items found in DynamoDB")
            return {
                'statusCode': 404,
                'body': json.dumps({'error': 'No matching item found in DynamoDB'})
            }

        item = resp['Items'][0]
        audio_key = item['audioFile']
        original_summary = item.get('description', '')
        original_tldr = item.get('tldr', '')

        # Fetch transcription from S3
        folder_path = "public/transcriptedAudio/"
        prefix = f"{folder_path}{audio_key.rsplit('.', 1)[0]}"  # Strip extension for the prefix

        print(f"Fetching objects from S3 with prefix: {prefix}")
        uploaded_objs = s3.list_objects(Bucket=S3_BUCKET_NAME, Prefix=prefix)
        text = ''
        for obj in uploaded_objs.get('Contents', []):
            print(f"Reading object: {obj['Key']}")
            data = s3.get_object(Bucket=S3_BUCKET_NAME, Key=obj['Key'])
            contents = data['Body'].read().decode('utf8')
            text += contents

        # OpenAI client
        client = OpenAI(api_key=OPENAI_API_KEY_FROM_ENV)

        prompt = f"""Please refine the following tldr and summary based on the user's revision requests. You will be provided with the original transcipted text that was turned into the tldr/summary, the original tldr and summary that was created, and the users requested revisions/changes. Please try to maintain similar tone and structure, but please modify as much as needed to satisfy the user's requests.
        
        Original text that was transcripted to the original summary:
        {text}

        Original TLDR:
        {original_tldr}

        Original Summary:
        {original_summary}
        
        User's Revision Requests:
        {user_revisions}
        
        Please provide both the refined tldr and refined summary in a JSON format with the following two keys. 'refined_tldr' and 'refined_summary' containing the updated text."""

        # Get refined summary
        try:
            refined_summary = get_completion(prompt, client)
            print(f"Refined summary from OpenAI: {refined_summary}")
            refined_summary_json = json.loads(refined_summary)

            item['description'] = refined_summary_json['refined_summary']
            item['tldr'] = [refined_summary_json['refined_tldr']]

            print("Updating item in DynamoDB")
            table.put_item(Item=item)
            print("Successfully updated item in DynamoDB")

            return {
                'statusCode': 200,
                'body': json.dumps({'message': 'Summary updated successfully'})
            }

        except Exception as e:
            print(f"Error during OpenAI API call: {e}")
            return {
                'statusCode': 500,
                'body': json.dumps({'error': f'OpenAI API error: {str(e)}'})
            }

    except Exception as e:
        print(f"General error: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': f'General error: {str(e)}'})
        }