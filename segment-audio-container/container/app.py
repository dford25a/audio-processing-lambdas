import os
import json
import urllib.parse
import boto3
from boto3.dynamodb.conditions import Attr
from botocore.config import Config  # Correct import for Config
import math
import tempfile
import subprocess
import shutil
import time
import concurrent.futures
from multiprocessing import cpu_count


DYNAMODB_TABLE_NAME = os.environ.get('DYNAMODB_TABLE')

# Initialize clients - fixed config
s3 = boto3.client("s3", config=Config(max_pool_connections=50))
lambda_client = boto3.client('lambda')

def format_number(number):
    """Format segment number with leading zeros"""
    return f'{number:02}'

def process_segment(segment_info):
    """Process a single segment of audio - used by thread pool"""
    segment_number = segment_info['segment_number']
    total_segments = segment_info['total_segments']
    start_time = segment_info['start_time']
    duration = segment_info['duration']
    input_file = segment_info['input_file']
    temp_dir = segment_info['temp_dir']
    bucket = segment_info['bucket']
    output_key = segment_info['output_key']
    
    # Create output filename
    output_file = os.path.join(temp_dir, f"segment_{segment_number:03d}.aac")
    
    try:
        # Process segment with FFmpeg
        ffmpeg_cmd = [
            'ffmpeg',
            '-ss', str(start_time),
            '-t', str(duration),
            '-i', input_file,
            '-c:a', 'aac',  # Use AAC codec
            '-b:a', '192k',  # Set bitrate for AAC
            '-y', output_file
        ]
        
        # Run FFmpeg
        subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # Upload file to S3
        s3.upload_file(output_file, bucket, output_key)
        
        # Delete the temporary file
        os.remove(output_file)
        
        return {
            'success': True,
            'segment': segment_number,
            'output_key': output_key
        }
    except Exception as e:
        print(f"Error processing segment {segment_number}: {str(e)}")
        return {
            'success': False,
            'segment': segment_number,
            'error': str(e)
        }

def handler(event, context):
    """Lambda handler for audio segmentation"""
    # Create temporary working directory
    temp_dir = tempfile.mkdtemp(dir='/tmp')
    
    try:
        # Parse event to get bucket and key
        if "bucket" in event and "audio_filename" in event:
            bucket = event["bucket"]
            key = urllib.parse.unquote_plus(event["audio_filename"], encoding='utf-8')
        elif "Records" in event and len(event["Records"]) > 0 and "s3" in event["Records"][0]:
            bucket = event["Records"][0]["s3"]["bucket"]["name"]
            key = urllib.parse.unquote_plus(event["Records"][0]["s3"]["object"]["key"], encoding='utf-8')
        else:
            raise ValueError("Invalid event structure")
        
        # Parse filename components
        fn = os.path.split(key)[1]
        base_name = os.path.splitext(fn)[0]
        input_ext = os.path.splitext(fn)[1].lower().lstrip('.')
        output_ext = 'aac'
        out_subdir = 'public/audio-segments/'
        
        print(f"Processing file: {fn} from bucket: {bucket}")
        
        # Set paths
        input_file = os.path.join(temp_dir, f"input.{input_ext}")
        
        # Update DynamoDB session to PROCESSING
        try:
            dynamodb = boto3.resource('dynamodb')
            table = dynamodb.Table(DYNAMODB_TABLE_NAME)
            
            response = table.scan(FilterExpression=Attr('audioFile').eq(fn))
            items = response['Items']
            if items:
                item = items[0]
                item['transcriptionStatus'] = 'PROCESSING'
                table.put_item(Item=item)
                print(f"Updated DynamoDB status to PROCESSING for {fn}")
            else:
                print(f"Warning: No matching item found in DynamoDB for audioFile: {fn}")
        except Exception as db_err:
            print(f"Warning: Could not update DynamoDB status: {db_err}")
        
        # Download the file
        print(f"Downloading {key} from {bucket}")
        s3.download_file(bucket, key, input_file)
        
        # Get audio duration using ffprobe
        duration_cmd = [
            'ffprobe', 
            '-v', 'error', 
            '-show_entries', 'format=duration', 
            '-of', 'default=noprint_wrappers=1:nokey=1', 
            input_file
        ]
        
        try:
            duration_output = subprocess.check_output(duration_cmd, stderr=subprocess.STDOUT)
            duration_seconds = float(duration_output.decode('utf-8').strip())
            print(f"Audio duration: {duration_seconds:.2f} seconds ({duration_seconds/60:.2f} minutes)")
        except subprocess.CalledProcessError as e:
            print(f"Error getting duration, using file size estimate instead: {e}")
            file_size = os.path.getsize(input_file)
            duration_seconds = (file_size / 1024 / 1024) * 60  # Rough estimate
            print(f"Estimated duration from file size: {duration_seconds:.2f} seconds")
        
        # Calculate segments
        segment_length_sec = 300  # 5 minutes
        
        # If the audio is shorter than the segment length, no need to segment
        if duration_seconds <= segment_length_sec:
            print("Audio is shorter than segment length, skipping segmentation.")
            return {
                "bucket": bucket,
                "segments": [key],
                "userTransactionsTransactionsId": event.get("userTransactionsTransactionsId"),
                "sessionId": event.get("sessionId"),
                "creditsToRefund": event.get("creditsToRefund")
            }

        num_segments = math.ceil(duration_seconds / segment_length_sec)
        print(f"File will be split into {num_segments} segments of {segment_length_sec} seconds each")
        
        # Determine optimal number of concurrent processors
        # Balancing between parallelism and memory usage
        total_cores = min(16, cpu_count() * 2)  # Use at most 16 threads
        max_concurrent = min(num_segments, max(4, min(12, total_cores)))  # Limit to 12 for 5GB memory
        print(f"Using up to {max_concurrent} concurrent processes")
        
        # Prepare segments for processing
        segments = []
        for i in range(num_segments):
            start_time = i * segment_length_sec
            duration = min(segment_length_sec, duration_seconds - start_time)
            
            segment_number = i + 1
            output_key = f"{out_subdir}{base_name}_{format_number(segment_number)}_of_{format_number(num_segments)}.{output_ext}"
            
            segments.append({
                'segment_number': segment_number,
                'total_segments': num_segments,
                'start_time': start_time,
                'duration': duration,
                'input_file': input_file,
                'temp_dir': temp_dir,
                'bucket': bucket,
                'output_key': output_key
            })
        
        # Process segments using a thread pool
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            futures = {executor.submit(process_segment, segment): segment for segment in segments}
            
            for future in concurrent.futures.as_completed(futures):
                segment = futures[future]
                try:
                    result = future.result()
                    if result['success']:
                        print(f"Successfully processed segment {result['segment']}/{num_segments}")
                    else:
                        print(f"Failed to process segment {result['segment']}: {result.get('error', 'Unknown error')}")
                    results.append(result)
                except Exception as exc:
                    print(f"Segment {segment['segment_number']} generated an exception: {exc}")
                    results.append({
                        'success': False,
                        'segment': segment['segment_number'],
                        'error': str(exc)
                    })
        
        # Check if all segments were processed successfully and construct the output
        processed_segments = [result for result in results if result['success']]
        failed_segments = [result for result in results if not result['success']]

        # Update DynamoDB status
        try:
            if items:
                item = items[0]
                if failed_segments:
                    item['transcriptionStatus'] = 'ERROR'
                else:
                    item['transcriptionStatus'] = 'PROCESSING'
                table.put_item(Item=item)
                print(f"Updated DynamoDB status to {'ERROR' if failed_segments else 'PROCESSING'} for {fn}")
        except Exception as db_err:
            print(f"Warning: Could not update DynamoDB completion status: {db_err}")

        if failed_segments:
            # If any segment failed, raise an exception to be caught by the Step Function
            error_details = ", ".join([f"Segment {s['segment']}: {s.get('error', 'Unknown')}" for s in failed_segments])
            raise Exception(f"{len(failed_segments)} segment(s) failed to process: {error_details}")
        
        # If all segments succeeded, return the payload directly for the Map state
        print("All segments processed successfully.")
        output_keys = [result["output_key"] for result in processed_segments]
        
        return {
            "bucket": bucket,
            "segments": output_keys,
            "userTransactionsTransactionsId": event.get("userTransactionsTransactionsId"),
            "sessionId": event.get("sessionId"),
            "creditsToRefund": event.get("creditsToRefund")
        }
        # If all segments succeeded, return the payload directly for the Map state
        print("All segments processed successfully.")
        output_keys = [result["output_key"] for result in processed_segments]
        
        return {
            "bucket": bucket,
            "segments": output_keys,
            "userTransactionsTransactionsId": event.get("userTransactionsTransactionsId"),
            "sessionId": event.get("sessionId"),
            "creditsToRefund": event.get("creditsToRefund")
        }
    
    except Exception as e:
        print(f"FATAL: Error processing audio: {str(e)}")
        
        # Update DynamoDB with error status
        try:
            fn = os.path.split(key)[1] if 'key' in locals() else "unknown"
            dynamodb = boto3.resource('dynamodb')
            table = dynamodb.Table(DYNAMODB_TABLE_NAME)
            response = table.scan(FilterExpression=Attr('audioFile').eq(fn))
            items = response['Items']
            if items:
                item = items[0]
                item['transcriptionStatus'] = 'ERROR'
                table.put_item(Item=item)
        except Exception as inner_e:
            print(f"Error updating DynamoDB error status: {str(inner_e)}")
        
        # Re-raise the exception to allow the Step Function's Catch block to handle it.
        raise e
    
    finally:
        # Clean up temp directory
        try:
            shutil.rmtree(temp_dir)
            print(f"Cleaned up temporary directory: {temp_dir}")
        except Exception as cleanup_err:
            print(f"Warning: Failed to clean up temp directory: {str(cleanup_err)}")