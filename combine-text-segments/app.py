import os, json
import urllib.parse
import boto3

s3 = boto3.client("s3")

def lambda_handler(event, context):
    bucket = event["Records"][0]["s3"]["bucket"]["name"]
    key = urllib.parse.unquote_plus(event["Records"][0]["s3"]["object"]["key"], encoding="utf-8")

    # Assuming the segment naming follows the pattern: `filename_01_of_03.txt`, etc.
    base_filename = key[:-13]  # Remove '_01_of_03.txt' part
    total_segments = int(key[-6:-4])  # '03' in '_01_of_03.txt'
    
    # List all objects with the same base filename (i.e., all segments)
    uploaded_objs = s3.list_objects_v2(Bucket=bucket, Prefix=base_filename)
    uploaded_keys = [obj['Key'] for obj in uploaded_objs.get('Contents', [])]

    # Check if all segments exist
    expected_files = [f"{base_filename}_{i:02d}_of_{total_segments:02d}.txt" for i in range(1, total_segments + 1)]
    missing_files = [file for file in expected_files if file not in uploaded_keys]

    if missing_files:
        print(f"Missing segments: {missing_files}")
        return {
            'statusCode': 400,
            'body': json.dumps(f"Missing segments: {missing_files}")
        }
    else:
        print(f"all segments present - should write file {base_filename}")
    
    # Combine the contents of all segments in order
    combined_text = ""
    for i in range(1, total_segments + 1):
        segment_key = f"{base_filename}_{i:02d}_of_{total_segments:02d}.txt"
        
        # Fetch each segment from S3 using s3.get_object
        try:
            segment_obj = s3.get_object(Bucket=bucket, Key=segment_key)
            segment_text = segment_obj['Body'].read().decode('utf-8')
            combined_text += segment_text
        except Exception as e:
            print(f"Error fetching segment {segment_key}: {str(e)}")
            return {
                'statusCode': 500,
                'body': json.dumps(f"Error fetching segment {segment_key}: {str(e)}")
            }
    
    # Remove '_of_03' from the filename and save the combined content
    final_filename = f"{base_filename}.txt"

    # Upload the combined file back to S3
    try:
        s3.put_object(Bucket=bucket, Key=f"public/segmentedSummaries/{final_filename}", Body=combined_text)
    except Exception as e:
        print(f"Error uploading combined file {final_filename}: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps(f"Error uploading combined file {final_filename}: {str(e)}")
        }

    return {
        'statusCode': 200,
        'body': json.dumps(f"Combined file {final_filename} successfully created.")
    }
