import json
import boto3
import time
import os

def lambda_handler(event, context):
    """
    AWS Lambda function to save user-specified fields to an S3 bucket as JSON
    and invoke the next Lambda function in the chain (segment-audio-dev or segment-audio-prod).

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
        environment = os.environ.get('ENVIRONMENT') # Get the ENVIRONMENT variable

        # Determine the target Lambda function name based on the environment
        if environment == "dev":
            target_lambda_function_name = "segment-audio-dev"
        elif environment == "prod":
            target_lambda_function_name = "segment-audio-prod"
        else:
            # Fallback or error if ENVIRONMENT is not set or invalid
            error_message = "ENVIRONMENT variable is not set or is invalid. Expected 'dev' or 'prod'."
            print(f"[ERROR] {error_message}")
            return format_response(500, {"error": error_message})

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
            print(f"[ERROR] {error_message}")
            return format_response(400, {"error": error_message})

        # Create S3 client
        s3_client = boto3.client("s3")

        # Define the metadata file path and name
        metadata_file_path = "public/session_metadata/"
        audio_filename_stem = os.path.splitext(audio_filename)[0]
        metadata_file_name = f"{audio_filename_stem}.metadata.json"
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
            # Note: list_multipart_uploads might require specific permissions.
            # Consider checking object existence as an alternative if multipart is not always used or permissions are an issue.
            try:
                s3_client.head_object(Bucket=bucket, Key=audio_file_key)
                print(f"Audio file '{audio_file_key}' found. Checking if it's part of an ongoing multipart upload.")
                # Listing multipart uploads is a good check, but ensure permissions are set.
                # If head_object confirms presence, and no multipart is listed for it, it's likely complete.
                response_multipart = s3_client.list_multipart_uploads(Bucket=bucket, Prefix=audio_file_key) # Filter by prefix for efficiency
                uploads = response_multipart.get("Uploads", [])

                ongoing_upload_for_specific_key = any(upload["Key"] == audio_file_key for upload in uploads)

                if not ongoing_upload_for_specific_key:
                    print(f"Audio file '{audio_file_key}' is fully uploaded or not part of a multipart upload. Proceeding.")
                    break
                else:
                    print(f"Audio file '{audio_file_key}' is still being uploaded (multipart). Retrying {attempt + 1}/{retries}...")
                    time.sleep(wait_time)

            except s3_client.exceptions.ClientError as e:
                if e.response['Error']['Code'] == '404': # Not Found
                    print(f"Audio file '{audio_file_key}' not found yet. Retrying {attempt + 1}/{retries}...")
                    time.sleep(wait_time)
                else:
                    # Handle other S3 errors
                    error_message = f"S3 error checking audio file '{audio_file_key}': {str(e)}"
                    print(f"[ERROR] {error_message}")
                    return format_response(500, {"error": error_message})
        else:
            # If the audio file is still not uploaded/found after retries
            error_message = f"Audio file '{audio_file_key}' issues after {retries} retries (either not found or still uploading)."
            print(f"[ERROR] {error_message}")
            return format_response(408, {"error": error_message})

        # Create Lambda client
        lambda_client = boto3.client("lambda")

        # Define payload for the next Lambda function
        next_lambda_payload = {
            "bucket": bucket,  # Include the bucket in the payload
            "audio_filename": audio_file_key # Pass the full S3 key
        }

        # Invoke the target Lambda function
        print(f"Invoking Lambda function: {target_lambda_function_name} with payload: {json.dumps(next_lambda_payload)}")
        response = lambda_client.invoke(
            FunctionName=target_lambda_function_name, # Use the dynamically determined function name
            InvocationType="Event",  # Asynchronous invocation
            Payload=json.dumps(next_lambda_payload)
        )

        # Log the response from Lambda invocation
        # For "Event" invocation, response.Payload will be empty, StatusCode is 202 if successful.
        print(f"Invoked {target_lambda_function_name} Lambda. Status Code: {response.get('StatusCode')}")

        success_message = f"{target_lambda_function_name} Lambda successfully invoked for file '{audio_filename}'."
        return format_response(200, {"message": success_message, "invoked_function": target_lambda_function_name})

    except Exception as e:
        error_message = f"Error in Lambda function: {str(e)}"
        import traceback
        print(f"[ERROR] {error_message}\n{traceback.format_exc()}") # Print full traceback for debugging
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
