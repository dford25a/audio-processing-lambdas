import json
import boto3
import os
import uuid
import base64
from bs4 import BeautifulSoup
import re

s3 = boto3.client('s3')
bucket_name = os.environ.get('S3_BUCKET_NAME')

def embed_s3_images(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    for img in soup.find_all('img'):
        src = img.get('src')
        if src and src.startswith('s3://'):
            try:
                s3_uri_parts = src.replace('s3://', '').split('/', 1)
                image_bucket = s3_uri_parts[0]
                image_key = s3_uri_parts[1]
                
                response = s3.get_object(Bucket=image_bucket, Key=image_key)
                image_data = response['Body'].read()
                
                content_type = response.get('ContentType', 'image/jpeg')
                
                base64_data = base64.b64encode(image_data).decode('utf-8')
                
                img['src'] = f"data:{content_type};base64,{base64_data}"
            except Exception as e:
                print(f"Error processing S3 image {src}: {e}")

    return str(soup)

def handler(event, context):
    try:
        body = json.loads(event['body'])
        html_content = body['html']
        file_id = body['id']
        
        processed_html = embed_s3_images(html_content)
        
        key = f"{file_id}.html"
        
        s3.put_object(
            Bucket=bucket_name,
            Key=key,
            Body=processed_html,
            ContentType='text/html',
            CacheControl='no-cache, no-store, must-revalidate'
        )
        
        public_url = f"https://{bucket_name}.s3.amazonaws.com/{key}"
        
        return {
            'statusCode': 200,
            'body': json.dumps({'public_url': public_url})
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
