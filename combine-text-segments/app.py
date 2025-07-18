import os, json
import urllib.parse
import boto3
import re

s3 = boto3.client("s3")

def lambda_handler(event, context):
    # The 'bucket' is at the top level of the event, passed through from the start.
    bucket = event["bucket"]
    # The 'transcribed_segments' is an array of results from the Map state.
    transcribed_segments = event["transcribed_segments"]

    if not transcribed_segments:
        raise ValueError("Input 'transcribed_segments' is empty.")

    combined_text = ""
    for segment in transcribed_segments:
        # Validate that the segment data is a valid result from the Transcribe lambda.
        # If 'key' is missing, it means a transcription task failed and returned an error object.
        if "key" not in segment:
            error_message = f"Invalid segment found in input. A transcription task likely failed. Segment data: {segment}"
            print(f"ERROR: {error_message}")
            # Raise an exception to trigger the Step Function's Catch block.
            raise Exception(error_message)

        try:
            segment_key = segment["key"]
            segment_obj = s3.get_object(Bucket=bucket, Key=segment_key)
            segment_text = segment_obj['Body'].read().decode('utf-8')
            combined_text += segment_text
        except Exception as e:
            # This will now catch errors related to S3 access, etc.
            error_message = f"Error fetching S3 object for segment data: {segment}. Exception: {str(e)}"
            print(error_message)
            raise Exception(error_message)

    # The base filename is the first part of the key of the first segment, with segment info and extension stripped
    first_segment_key = os.path.basename(transcribed_segments[0]["key"])
    # Remove _XX_of_YY and .txt/.json extensions
    base_filename = re.sub(r'(_\d+_of_\d+)?(\.txt|\.json)+$', '', first_segment_key)
    final_filename = f"{base_filename}.txt"

    # Upload the combined file back to S3
    try:
        output_key = f"public/transcripts/full/{final_filename}"
        s3.put_object(Bucket=bucket, Key=output_key, Body=combined_text)
    except Exception as e:
        error_message = f"Error uploading combined file {final_filename}: {str(e)}"
        print(error_message)
        raise Exception(error_message)

    return {
        "bucket": bucket,
        "key": output_key,
        "userTransactionsTransactionsId": event.get("userTransactionsTransactionsId"),
        "sessionId": event.get("sessionId"),
        "creditsToRefund": event.get("creditsToRefund")
    }
