from openai import OpenAI
import os
import json
import urllib3
import urllib.parse
import boto3
from boto3.dynamodb.conditions import Key, Attr

s3 = boto3.client("s3")

def lambda_handler(event, context):
    try:
        bucket = event["Records"][0]["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(event['Records'][0]['s3']['object']['key'], encoding='utf-8')
        os.makedirs("/tmp/public/segmentedSummaries/", exist_ok=True)
        os.chdir('/tmp/public/segmentedSummaries/')
        out_subdir = 'public/transcriptedSummary/'
        
        item = []
        
        #first we check if all items are there
        prefix = key[:-13] #hacky, take the last 10 off, example '_01_of_06.txt'
        uploaded_objs = s3.list_objects(
            Bucket=bucket,
            Prefix=prefix)
        text = ''
        print(key)
        print(key[-10:-6])
        if key[-10:-6] == '_of_': #this is a split sequence
            num_segments = int(key[-6:-4])
            if len(uploaded_objs['Contents']) != num_segments:
                print('Stopping, not all segments are present in s3.')
                print('Expected: '+str(num_segments)+' only '+str(len(uploaded_objs['Contents']))+ 'currrent uplodaded')
                exit()
            else:
                print('All segments present!')
                for obj in uploaded_objs['Contents']:
                    data = s3.get_object(Bucket=bucket, Key=obj['Key'])
                    contents = data['Body'].read().decode('utf8')
                    text = text + contents
        else:
            for obj in uploaded_objs['Contents']:
                data = s3.get_object(Bucket=bucket, Key=obj['Key'])
                contents = data['Body'].read().decode('utf8')
                text = text + contents
            
        client = OpenAI(
            # This is the default and can be omitted
            #ryans key 'REMOVED'
            api_key='REMOVED',
        )
        
        def get_completion(prompt, client, model="gpt-3.5-turbo-1106"):
            messages = [{"role": "user", "content": prompt}]
            response = client.chat.completions.create(
                model=model,
                response_format={ "type": "json_object" },
                messages=messages,
                temperature=0.3, # this is the degree of randomness of the model's output
            )
            return response.choices[0].message.content
        
        prompt =f"""You are Scribe, an AI-powered assistant that summarizes role playing game sessions to compile a knowledge base of information for players to reference.

Here is a list of correct player character names (in xml tags as player_names) that may not have been spelled correctly in the session_summary so please swap out names that are close with these.
<player_names>Titus, Zeke, Karthel, Kosher, Rhordon, Borren, Gary<player_names>

Here is a list of characters the players may interact with in the game (delimitted in xml as npc_names), otherwise known as non-playable chacters or NPCs. These may not have been spelled correctly so please swap out names that are close with these.
<npc_names>Aximus, Lulu, King Anax, Queen Cymede, Traxigor</npc_names>

<session_summary>{text}</session_summary>

Based on the above session summary generate the following in JSON format:

Full summary - A detailed account of the session around 1,250 words long. 
TLDR - A brief summary around 250 words long.
NPCs - Characters that appear in the session but are not the players. Each NPC should have a name of 1-3 words and a description of 2-3 sentences. 
Locations - A bulleted list of locations of the session with a short description.
Scenes - Key scenes from the session that would make for good paintings. These should be written in the format of Dall-e prompts with a consistent fantasy-themed aesthetic. 
Quests - A bulleted list of 1-3 quests that the party is working toward within the session and beyond. 
Player Character summaries - A bullet list of 2-3 key contributions that each player character made to the session.
"""
        response = get_completion(prompt, client)
        #print(response)
        
        fn = os.path.split(key)[1] #name of just file itself
        if key[-10:-6] == '_of_':
            out_key = out_subdir+fn[:-13]+'.json'
            db_key = fn[:-13]+'.m4a'
        else:
            out_key = out_subdir+fn[:-4]+'.json'
            db_key = fn[:-4]+'.m4a'
        object = s3.put_object(Bucket=bucket, Key=out_key, Body=response)
        
        # update session to PROCESSING
        table = boto3.resource('dynamodb').Table('Session-ejphalvgizhdjbbzuj2vahx7ii-dev')
        resp = table.scan(
            FilterExpression=Attr('audioFile').eq(db_key)
        )

        items = resp['Items']
        item = items[0]
        
        print(response)
        response = json.loads(response)
        if 'TLDR' in response:
            item['tldr'] = [response['TLDR']]
        if 'Full summary' in response:
            item['description'] = response['Full summary']
        item['transcriptionStatus'] = 'READ'
        table.put_item(Item=item)
        return {
            'statusCode': 200,
            'body': json.dumps("Processed successfully")
        }
    except Exception as e:
        print(e)
        if item:
            item['transcriptionStatus'] = 'ERROR'
            table.put_item(Item=item)
            return {
                "statusCode": 500,
                "body": json.dumps("Error processing the file")
            }