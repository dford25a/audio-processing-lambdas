import json
import boto3
import time
import os

def lambda_handler(event, context):
    """
    AWS Lambda function to save user-specified fields to an S3 bucket as JSON
    and invoke the next Lambda function in the chain (segment-audio).
    
    Can be invoked either directly or through API Gateway.
    
    Parameters when invoked directly:
    - event: Input dictionary containing:
        - "user_specified_fields" (dict): The metadata to save.
        - "audio_filename" (str): The name of the audio file to process.
        
    Parameters when invoked through API Gateway:
    - event: Contains API Gateway proxy integration request info
        - The actual payload is contained in the 'body' field as a JSON string
    """
    try:
        # Get environment variables
        bucket = os.environ.get('BUCKET_NAME')
        
        # Check if the request is coming from API Gateway
        if event.get('httpMethod') == 'POST' and event.get('body'):
            # Parse the JSON body from API Gateway
            payload = json.loads(event.get('body', '{}'))
            user_specified_fields = payload.get("user_specified_fields")
            audio_filename = payload.get("audio_filename")
        else:
            # Direct Lambda invocation
            user_specified_fields = event.get("user_specified_fields")
            audio_filename = event.get("audio_filename")
        
        if not user_specified_fields or not audio_filename:
            error_message = "Parameters 'user_specified_fields' and 'audio_filename' are required."
            print(error_message)
            return format_response(400, {"error": error_message})
            
        # Create S3 client
        s3_client = boto3.client("s3")
        
        # Define the metadata file path and name
        metadata_file_path = "public/session_metadata/"
        metadata_file_name = f"{audio_filename}.metadata.json"
        metadata_s3_key = f"{metadata_file_path}{metadata_file_name}"
        
        # Convert the metadata to JSON
        json_data = json.dumps(user_specified_fields)
        
        # Save the metadata file to S3
        s3_client.put_object(
            Bucket=bucket,
            Key=metadata_s3_key,
            Body=json_data,
            ContentType="application/json"
        )
        
        # Log metadata save success
        print(f"Metadata saved to S3 at s3://{bucket}/{metadata_s3_key}")
        
        # Check for the audio file's upload status
        audio_file_key = f"public/audioUploads/{audio_filename}"
        retries = 10
        wait_time = 10  # seconds
        
        for attempt in range(retries):
            # Check for active multipart uploads
            response = s3_client.list_multipart_uploads(Bucket=bucket)
            uploads = response.get("Uploads", [])
            
            # Check if the audio file is part of any ongoing multipart uploads
            ongoing_upload = any(upload["Key"] == audio_file_key for upload in uploads)
            
            if not ongoing_upload:
                print(f"Audio file '{audio_file_key}' is fully uploaded. Proceeding.")
                break
            else:
                print(f"Audio file '{audio_file_key}' is still being uploaded. Retrying {attempt + 1}/{retries}...")
                time.sleep(wait_time)
        else:
            # If the audio file is still not uploaded after retries
            error_message = f"Audio file '{audio_file_key}' is still being uploaded after {retries} retries."
            print(error_message)
            return format_response(408, {"error": error_message})
        
        # Create Lambda client
        lambda_client = boto3.client("lambda")
        
        # Define payload for the next Lambda function
        next_lambda_payload = {
            "bucket": bucket,  # Include the bucket in the payload for segment-audio
            "audio_filename": audio_file_key
        }
        
        # Invoke the segment-audio Lambda function
        response = lambda_client.invoke(
            FunctionName="segment-audio",
            InvocationType="Event",  # Asynchronous invocation
            Payload=json.dumps(next_lambda_payload)
        )
        
        # Log the response from Lambda invocation
        print(f"Invoked segment-audio Lambda: {response}")
        
        success_message = f"Segment-audio Lambda successfully invoked for file '{audio_filename}'."
        return format_response(200, {"message": success_message})
        
    except Exception as e:
        error_message = f"Error in Lambda function: {str(e)}"
        print(error_message)
        return format_response(500, {"error": error_message})

def format_response(status_code, body):
    """
    Format the response in a way compatible with both direct Lambda invocation
    and API Gateway integration.
    """
    formatted_response = {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",  # Enable CORS for browser requests
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "OPTIONS,POST"
        },
        "body": json.dumps(body)
    }
    
    return formatted_response