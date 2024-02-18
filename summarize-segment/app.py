from openai import OpenAI
import os
import urllib3
import urllib.parse
import boto3
import time
import json

s3 = boto3.client("s3")
# bedrock = boto3.client(service_name='bedrock-runtime', region_name='us-east-2')

def lambda_handler(event, context):
    bucket = event["Records"][0]["s3"]["bucket"]["name"]
    key = urllib.parse.unquote_plus(event['Records'][0]['s3']['object']['key'], encoding='utf-8')
    os.makedirs("/tmp/public/transcriptedAudio/", exist_ok=True)
    os.chdir('/tmp/public/transcriptedAudio/')
    out_subdir = 'public/segmentedSummaries/'
    fn = os.path.split(key)[1] #name of just file itself
    num_seg_str = key[-6:-4]
    
    summary=f"/tmp/{key}"
    s3.download_file(bucket, key, summary)
    with open(summary,'r') as f:
        text = f.read()
        
    client = OpenAI(
        api_key='REMOVED',
    )
    
    prefix = key[:-13] #hacky, take the last 10 off, example '_01_of_06.txt'
    uploaded_objs = s3.list_objects(
        Bucket=bucket,
        Prefix=prefix)
    num_uploaded = len(uploaded_objs['Contents'])
    
    previous_summaries = ''
    if key[-10:-6] == '_of_': #this is a split sequence
        previous_summaries += 'The following is a running summary of what has happened so far this session: '
        curr_seg = int(key[-12:-10])
        num_segments = int(key[-6:-4])
        if num_uploaded > 1: #check to see if this is at least the 2nd one so we have stuff to pull from
            for seg in range(num_uploaded-1): #0 based, but getting all existing generated summaries except this one
                seg_str = "{:02d}".format(seg+1) #+1 to make 1 based
                #try to get other summaries
                seg_key = out_subdir+fn[:-12]+seg_str+'_of_'+num_seg_str+'.txt'
                print('current key: '+key)
                try:
                    print('looking for:'+seg_key)
                    data = s3.get_object(
                        Bucket=bucket,
                        Key=seg_key,
                    )
                    contents = data['Body'].read().decode('utf8')
                    previous_summaries = previous_summaries + contents
                except:
                    print('Uh oh, looks like the summary didnt exist yet')
                    # #looks like its not there quite yet, lets try again in 20s
                    # time.sleep(20)
                    # print('looking for:'+seg_key)
                    # data = s3.get_object(
                    #     Bucket=bucket,
                    #     Key=seg_key,
                    # )
                    # contents = data['Body'].read().decode('utf8')
    else:
        #this is an entire recording, proceed normally
        print(key+' only has one segment!')

    def get_completion(prompt, client, model="gpt-3.5-turbo-0125"):
        # body = json.dumps({
        #     "prompt": prompt,
        #     "max_tokens_to_sample": 5000,
        #     "temperature": 0.5,
        #     "top_p": 0.9,
        # })
        
        # accept = 'application/json'
        # contentType = 'application/json'
        
        # response = bedrock.invoke_model(body=body, modelId=model, accept=accept, contentType=contentType)
        # response_body = json.loads(response.get('body').read())
        # text
        messages = [{"role": "user", "content": prompt}]
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.5, # this is the degree of randomness of the model's output
        )
        response_body = response.choices[0].message.content
        return response_body
    
    # super sketchy token limit preventer. Problem with this is tokens aren't always 4chars. Right now this will crop with a slight safety factor
    max_tokens_limit = 16000
    safety_factor = 0.5 # lets max context/prompt at 8k, to allow 8k for previous summaries
    approx_chars_per_token = 4
    max_characters = int(safety_factor*max_tokens_limit*approx_chars_per_token - 500) # arbitrary length of prompt instructions subtracted
    if len(text) > max_characters:
        print('WARNING: MAX CHAR LIMIT HIT FOR CONTEXT. TRUNCATING TO 7500. This is bad for summarization performance. Should probably just error here.')
        text = text[0:max_characters]
        
    if len(previous_summaries) > max_characters:
        print('WARNING: MAX CHAR LIMIT HIT FOR PERVIOUS SUMMARIES. TRUNCATING TO 7500 chars. This is bad for summarization performance. Should probably just error here.')
        previous_summaries = previous_summaries[0:max_characters]
    
    summary=''
    prompt =f"""You are an AI Assistant who is an expert at summarizing text from humans playing role playing games. Your task is to write a summary of a segment of text (delimited with xml tags) of people playing a role playing game. You will extract key details about what the players are doing. 
You may also be provided with a running summary (delimited by xml tags) of the session, if so use this as context for what has occured in this segment.

<running_summary>{previous_summaries}</running_summary>

<segment>{text}</<segment>

Write a 200 word summary of the segment, including events, locations, NPCs, notable scenes, acquired loot, and player character contributions.
"""
    print('prompt length is '+str(len(prompt)))
    response = ''
    try:

        #model = 'anthropic.claude-instant-v1'
        #response = get_completion(prompt, client, model) #experimenting with claude
        response = get_completion(prompt, client)
    except:
        print('ERROR: issues with model call, could be throttling (OpenAI LIMITS to 3 requests per minute in our current paid tier)... trying again after waiting 21s')
        time.sleep(21)
        response = get_completion(prompt, client)   
    
    print(response)
    summary+=response
    

    out_key = out_subdir+fn[:-4]+'.txt'
    object = s3.put_object(Bucket=bucket, Key=out_key, Body=summary)

    return {
        'statusCode': 200,
        'body': response
    }