from openai import OpenAI
import os
import urllib3
import urllib.parse
import boto3

s3 = boto3.client("s3")

def lambda_handler(event, context):
    bucket = event["Records"][0]["s3"]["bucket"]["name"]
    key = urllib.parse.unquote_plus(event['Records'][0]['s3']['object']['key'], encoding='utf-8')
    os.makedirs("/tmp/public/transcriptedAudio/", exist_ok=True)
    os.chdir('/tmp/public/transcriptedAudio/')
    out_subdir = 'public/segmentedSummaries/'
    
    
    summary=f"/tmp/{key}"
    s3.download_file(bucket, key, summary)
    with open(summary,'r') as f:
        text = f.read()
        
    client = OpenAI(
        api_key='REMOVED',
    )
    
    def get_completion(prompt, client, model="gpt-3.5-turbo"):
        messages = [{"role": "user", "content": prompt}]
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1, # this is the degree of randomness of the model's output
        )
        return response.choices[0].message.content
    
    summary=''
    prompt =f"""
    Your task is to extract the key details and write a summary of a segment of a dungeons and dragons session that the people in the text are playing. Please provide a 1000 word summary of the what has happened in this segment of the session, including characters involved, NPCS, key scenes, and key moments.
    Text: ```{text}```
    """
    try:
        response = get_completion(prompt, client)
    except:
        response = ''
    
    print(response)
    summary+=response
    
    fn = os.path.split(key)[1] #name of just file itself
    out_key = out_subdir+fn[:-4]+'.txt'
    object = s3.put_object(Bucket=bucket, Key=out_key, Body=summary)

    return {
        'statusCode': 200,
        'body': response
    }