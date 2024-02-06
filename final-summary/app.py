from openai import OpenAI
import os
import urllib3
import urllib.parse
import boto3

s3 = boto3.client("s3")

def lambda_handler(event, context):
    bucket = event["Records"][0]["s3"]["bucket"]["name"]
    key = urllib.parse.unquote_plus(event['Records'][0]['s3']['object']['key'], encoding='utf-8')
    os.makedirs("/tmp/public/segmentedSummaries/", exist_ok=True)
    os.chdir('/tmp/public/segmentedSummaries/')
    out_subdir = 'public/transcriptedSummary/'
    
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
                contents = data['Body'].read()
                text = text + contents
    for obj in uploaded_objs['Contents']:
        data = s3.get_object(Bucket=bucket, Key=obj['Key'])
        contents = data['Body'].read().decode('utf8')
        text = text + contents
        
    client = OpenAI(
        # This is the default and can be omitted
        api_key='REMOVED',
    )
    
    def get_completion(prompt, client, model="gpt-3.5-turbo-1106"):
        messages = [{"role": "user", "content": prompt}]
        response = client.chat.completions.create(
            model=model,
            response_format={ "type": "json_object" },
            messages=messages,
            temperature=0.1, # this is the degree of randomness of the model's output
        )
        return response.choices[0].message.content
    
    summary=''
    prompt =f"""You are Scribe, an AI-powered assistant that summarizes DnD sessions to compile a knowledge base of information for the dungeon master and players to reference throughout the campaign.

You will be provided with a list of correct player character names. You should match and replace the names generated in overview with these correct names because the overview may not have generated them accurately. 

Here are the player names:
```Titus, Aximus, Lulu, King Anax, Queen Cymede, Zeke, Ezekiel, Karthel, Kosher, Rhordon, Borren, Gary, Traxigor, Yulag```

Your deliverables for each session are the following, these MUST be in JSON format:
Full summary - A detailed account of the session around 1,250 words long. 
TLDR - A brief summary around 250 words long.
NPCs - Characters that appear in the campaign but are not the players. Each NPC should have a name of 1-3 words and a description of 2-3 sentences. 
Locations - 3-5 main settings of the session. Each location should have a name of 1-3 words and a description of 2-3 sentences. 
Scenes - 3-5 key scenes from the session that would make for good paintings. These should be written in the format of Dall-e prompts with a consistent fantasy-themed aesthetic. 
Quests - A bulleted list of 1-3 quests that the party is working toward within the session and beyond. Each quest should be limited to 5-20 words. 
Player Character summaries - A bullet list of 2-3 key contributions that each player character made to the session.
```{text}```
"""
    response = get_completion(prompt, client)
    #print(response)
    
    fn = os.path.split(key)[1] #name of just file itself
    if key[-9:-5] == '_of_':
        out_key = out_subdir+fn[:-11]+'.json'
    else:
        out_key = out_subdir+fn[:-4]+'.json'
    object = s3.put_object(Bucket=bucket, Key=out_key, Body=response)

    return {
        'statusCode': 200,
        'body': response['choices'][0]['text']
    }