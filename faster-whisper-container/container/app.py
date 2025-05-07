import os
import shutil
import json
import urllib3
import urllib.parse
#import whisper
from faster_whisper import WhisperModel
import boto3
#import multiprocessing
import signal
import time

s3 = boto3.client("s3")

def handler(event, context):
    try:
        #print("Received event: " + json.dumps(event, indent=2))
        bucket = event["Records"][0]["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(event['Records'][0]['s3']['object']['key'], encoding='utf-8')
        #print("Bucket:", bucket, "key:", key)
        os.makedirs("/tmp/public/audioUploadsSegmented/", exist_ok=True)
        os.chdir('/tmp/public/audioUploadsSegmented/')
        out_subdir = 'public/transcriptedAudio/'

        audio_file=f"/tmp/{key}"
        # Downloading file to transcribe
        s3.download_file(bucket, key, audio_file)
        fn = os.path.split(key)[1]

        class TimeoutError(Exception):
            pass
        
        class timeout:
            def __init__(self, seconds=1, error_message='Timeout'):
                self.seconds = seconds
                self.error_message = error_message
            def handle_timeout(self, signum, frame):
                print(self.error_message)
            def __enter__(self):
                signal.signal(signal.SIGALRM, self.handle_timeout)
                signal.alarm(self.seconds)
            def __exit__(self, type, value, traceback):
                signal.alarm(0)
        
        def call_model(model_, audio_file_, beam_size_, text_):
            print('preparing to call transcribe.')
            segments, _ = model_.transcribe(audio_file_, beam_size=beam_size_, vad_filter=True, vad_parameters={"max_speech_duration_s": 15})
            segments = list(segments)  # The transcription will actually run here.
            print('transcription complete!')
            for t in segments:
                text_ += t.text 
            return text_

        model_size = "small"
        model = WhisperModel(model_size, device="cpu",  download_root="/tmp", compute_type="int8")
        beam_size = 1
        text = ''
        with timeout(seconds=9*60):
            text = call_model(model, audio_file, beam_size, text)
        
        out_key = out_subdir+fn[:-4]+'.txt'
        object = s3.put_object(Bucket=bucket, Key=out_key, Body=text) 
        
        #clean up tmp
        os.remove(audio_file)

        output = f"Transcribed: {out_key}.txt"
        
        return {
            "statusCode": 200,
            "body": json.dumps(output)
        }
    except Exception as e:
        
        print(e)
        return {
            "statusCode": 500,
            "body": json.dumps("Error processing the file")
        }
