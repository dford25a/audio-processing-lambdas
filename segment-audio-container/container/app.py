import os
import shutil
import json
import urllib3
import urllib.parse
import boto3
import math
from pydub import AudioSegment

s3 = boto3.client("s3")

def handler(event, context):
    try:
        #print("Received event: " + json.dumps(event, indent=2))
        bucket = event["Records"][0]["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(event['Records'][0]['s3']['object']['key'], encoding='utf-8')
        #print("Bucket:", bucket, "key:", key)
        os.makedirs("/tmp/public/audioUploads/", exist_ok=True)
        os.chdir('/tmp/public/audioUploads/')
        out_subdir = 'public/audioUploadsSegmented/'
        
        audio_file=f"/tmp/{key}"
        fn = os.path.split(key)[1] #name of just file itself
        
        # Downloading file to split
        s3.download_file(bucket, key, audio_file)
        
        myaudio = AudioSegment.from_file(audio_file)
        audio_length = len(myaudio)
        print('length of audio: '+str(audio_length))
        segment_length = 1200000 # 20 min
        num_segments = math.ceil(audio_length/segment_length)
        
        def format_number(number):
            formatted_number = str(number)
            if number < 10:
                formatted_number = '0'+str(number)
            return formatted_number
        
        if num_segments == 1:
            out_fn = audio_file[:-4]+'.m4a'
            myaudio.export(out_fn, format="ipod")
            out_key = out_subdir+fn[:-4]+'.m4a'
            #s3.put_object(Bucket=bucket, Key=out_key, Body=text)
            print('uploading: '+out_fn+' to bucket: '+bucket+' and key: '+out_key)
            s3.upload_file(Filename=out_fn, Bucket=bucket, Key=out_key)
        else:
            for i in range(num_segments-1):
                start_idx = (i)*segment_length
                stop_idx = (i+1)*segment_length
                print('splitting audio at:'+str(start_idx)+' '+str(stop_idx))
                if stop_idx > audio_length:
                    stop_idx = audio_length
                chunk_data = myaudio[start_idx:stop_idx]
                out_fn = audio_file[:-4]+'_'+format_number(i+1)+'_of_'+format_number(num_segments-1)+'.m4a'
                print('exporting:' +out_fn)
                chunk_data.export(out_fn, format="ipod")
            
                out_key = out_subdir+fn[:-4]+'_'+format_number(i+1)+'_of_'+format_number(num_segments-1)+'.m4a'
                #s3.put_object(Bucket=bucket, Key=out_key, Body=text)
                print('uploading: '+out_fn+' to bucket: '+bucket+' and key: '+out_key)
                s3.upload_file(Filename=out_fn, Bucket=bucket, Key=out_key)
            

        return {
            "statusCode": 200,
            "body": json.dumps(num_segments)
        }
    except Exception as e:
        print(e)
        return {
            "statusCode": 500,
            "body": json.dumps("Error processing the file")
        }
