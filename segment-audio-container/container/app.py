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
import uuid
from botocore.exceptions import ClientError


DYNAMODB_TABLE_NAME = os.environ.get('DYNAMODB_TABLE')

# Initialize clients - fixed config
s3 = boto3.client("s3", config=Config(max_pool_connections=50))
lambda_client = boto3.client('lambda')

def get_audio_metadata_streaming(bucket, key):
    """Get audio duration using streaming approach with minimal data transfer"""
    try:
        # Download first 256KB for metadata extraction (covers most audio formats)
        response = s3.get_object(Bucket=bucket, Key=key, Range='bytes=0-262143')
        header_data = response['Body'].read()
        
        # Write header to temp file for ffprobe
        temp_header = f"/tmp/header_{uuid.uuid4().hex}.tmp"
        with open(temp_header, 'wb') as f:
            f.write(header_data)
        
        # Extract duration using ffprobe on header
        duration_cmd = [
            'ffprobe', 
            '-v', 'error', 
            '-show_entries', 'format=duration', 
            '-of', 'default=noprint_wrappers=1:nokey=1', 
            temp_header
        ]
        
        try:
            duration_output = subprocess.check_output(duration_cmd, stderr=subprocess.PIPE)
            duration_seconds = float(duration_output.decode('utf-8').strip())
            print(f"Extracted duration from header: {duration_seconds:.2f} seconds")
            os.remove(temp_header)
            return duration_seconds
        except (subprocess.CalledProcessError, ValueError) as e:
            print(f"Could not extract duration from header: {e}")
            os.remove(temp_header)
            return None
            
    except Exception as e:
        print(f"Error in streaming metadata extraction: {e}")
        return None

def calculate_segment_ranges(file_size, duration_seconds, segment_length_sec=300):
    """Calculate byte ranges for streaming segmentation"""
    if duration_seconds <= 0:
        return []
    
    bytes_per_second = file_size / duration_seconds
    segments = []
    
    for i in range(math.ceil(duration_seconds / segment_length_sec)):
        start_time = i * segment_length_sec
        end_time = min((i + 1) * segment_length_sec, duration_seconds)
        
        # Calculate byte ranges with padding for format overhead
        # Use conservative approach to ensure we get complete audio frames
        start_byte = max(0, int(start_time * bytes_per_second * 0.85))  # Start earlier
        end_byte = min(file_size - 1, int(end_time * bytes_per_second * 1.15))  # End later
        
        segments.append({
            'segment_number': i + 1,
            'start_time': start_time,
            'duration': end_time - start_time,
            'byte_range': f'bytes={start_byte}-{end_byte}',
            'start_byte': start_byte,
            'end_byte': end_byte
        })
    
    return segments

def process_segment_streaming(segment_info):
    """Process a single segment using streaming approach"""
    segment_number = segment_info['segment_number']
    bucket = segment_info['bucket']
    key = segment_info['key']
    byte_range = segment_info['byte_range']
    start_time = segment_info['start_time']
    duration = segment_info['duration']
    output_key = segment_info['output_key']
    temp_dir = segment_info['temp_dir']
    
    temp_chunk = None
    output_file = None
    
    try:
        print(f"Processing segment {segment_number} with range {byte_range}")
        
        # Stream the specific byte range from S3
        response = s3.get_object(Bucket=bucket, Key=key, Range=byte_range)
        audio_chunk = response['Body'].read()
        
        # Write chunk to temp file
        temp_chunk = os.path.join(temp_dir, f"chunk_{segment_number}_{uuid.uuid4().hex}.tmp")
        with open(temp_chunk, 'wb') as f:
            f.write(audio_chunk)
        
        # Create output filename
        output_file = os.path.join(temp_dir, f"segment_{segment_number:03d}.aac")
        
        # Use FFmpeg to extract the precise time segment from the chunk
        # Use lower bitrate optimized for transcription
        ffmpeg_cmd = [
            'ffmpeg',
            '-ss', str(start_time),
            '-t', str(duration),
            '-i', temp_chunk,
            '-c:a', 'aac',
            '-b:a', '128k',  # Reduced bitrate for transcription
            '-ar', '16000',  # Sample rate optimized for Whisper
            '-ac', '1',      # Mono audio for transcription
            '-y', output_file
        ]
        
        # Run FFmpeg
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"FFmpeg stderr for segment {segment_number}: {result.stderr}")
            # If precise timing fails, try without timing constraints
            fallback_cmd = [
                'ffmpeg',
                '-i', temp_chunk,
                '-c:a', 'aac',
                '-b:a', '128k',
                '-ar', '16000',
                '-ac', '1',
                '-y', output_file
            ]
            result = subprocess.run(fallback_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception(f"FFmpeg failed: {result.stderr}")
        
        # Upload file to S3
        s3.upload_file(output_file, bucket, output_key)
        
        return {
            'success': True,
            'segment': segment_number,
            'output_key': output_key
        }
        
    except Exception as e:
        print(f"Error processing streaming segment {segment_number}: {str(e)}")
        return {
            'success': False,
            'segment': segment_number,
            'error': str(e)
        }
    finally:
        # Clean up temp files
        if temp_chunk and os.path.exists(temp_chunk):
            os.remove(temp_chunk)
        if output_file and os.path.exists(output_file):
            os.remove(output_file)

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
        
        # Try streaming approach first
        print("Attempting streaming segmentation approach...")
        duration_seconds = get_audio_metadata_streaming(bucket, key)
        use_streaming = False
        file_size = 0
        
        if duration_seconds is not None:
            # Get file size for streaming approach
            try:
                head_response = s3.head_object(Bucket=bucket, Key=key)
                file_size = head_response['ContentLength']
                print(f"File size: {file_size} bytes ({file_size/1024/1024:.2f} MB)")
                print(f"Streaming metadata extraction successful: {duration_seconds:.2f} seconds ({duration_seconds/60:.2f} minutes)")
                use_streaming = True
            except Exception as e:
                print(f"Could not get file size for streaming: {e}")
                duration_seconds = None
        
        if not use_streaming:
            print("Falling back to traditional approach...")
            # Download the file for traditional approach
            print(f"Downloading {key} from {bucket}")
            s3.download_file(bucket, key, input_file)
            
            # Get audio duration using ffprobe on downloaded file
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
        # With streaming approach, we can use more concurrent processes since memory usage is lower
        total_cores = min(20, cpu_count() * 2)  # Increased from 16 to 20
        if use_streaming:
            max_concurrent = min(num_segments, max(6, min(20, total_cores)))  # Up to 20 for streaming
            print(f"Using streaming approach with up to {max_concurrent} concurrent processes")
        else:
            max_concurrent = min(num_segments, max(4, min(12, total_cores)))  # Keep 12 for traditional
            print(f"Using traditional approach with up to {max_concurrent} concurrent processes")
        
        # Prepare segments for processing
        if use_streaming:
            # Calculate byte ranges for streaming segmentation
            segment_ranges = calculate_segment_ranges(file_size, duration_seconds, segment_length_sec)
            segments = []
            
            for segment_range in segment_ranges:
                segment_number = segment_range['segment_number']
                output_key = f"{out_subdir}{base_name}_{format_number(segment_number)}_of_{format_number(num_segments)}.{output_ext}"
                
                segments.append({
                    'segment_number': segment_number,
                    'bucket': bucket,
                    'key': key,
                    'byte_range': segment_range['byte_range'],
                    'start_time': segment_range['start_time'],
                    'duration': segment_range['duration'],
                    'output_key': output_key,
                    'temp_dir': temp_dir
                })
        else:
            # Traditional approach - use full file
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
            if use_streaming:
                futures = {executor.submit(process_segment_streaming, segment): segment for segment in segments}
            else:
                futures = {executor.submit(process_segment, segment): segment for segment in segments}
            
            for future in concurrent.futures.as_completed(futures):
                segment = futures[future]
                try:
                    result = future.result()
                    if result['success']:
                        approach = "streaming" if use_streaming else "traditional"
                        print(f"Successfully processed segment {result['segment']}/{num_segments} using {approach} approach")
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
        approach = "streaming" if use_streaming else "traditional"
        print(f"All segments processed successfully using {approach} approach.")
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
