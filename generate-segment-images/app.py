# --- Standard Library Imports ---
import os
import json
import base64
import traceback
from typing import List, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- Third-party Library Imports ---
import boto3
import openai
from openai import OpenAI

# --- CONFIGURATION ---
OPENAI_API_KEY_FROM_ENV = os.environ.get('OPENAI_API_KEY')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-2')

# --- VALIDATE ESSENTIAL CONFIGURATION ---
if not OPENAI_API_KEY_FROM_ENV:
    raise ValueError("Environment variable OPENAI_API_KEY not set!")

# --- AWS & OPENAI CLIENTS ---
s3_client = boto3.client("s3", region_name=AWS_REGION)
openai_client = OpenAI(api_key=OPENAI_API_KEY_FROM_ENV)

# --- Image Style Lookup (must match final-summary/app.py exactly) ---
image_format_lookup = {
    "fantasy": {
        "name": "Default",
        "description": "Classic artistic style",
        "longDescription": "A semi-photorealistic fantasy style with bold, directional lighting, rich color saturation, and cinematic composition. Realistic textures, lifelike character detail, and a polished finish create a grounded yet visually striking world with a heightened sense of drama and scale."
    },
    "dark-fantasy": {
        "name": "Dark fantasy",
        "description": "Dark fantasy style",
        "longDescription": "A cinematic stylized realism with rich color depth and dynamic lighting. The palette uses vibrant yet grounded tones with strong value contrast to enhance atmosphere and emotional impact, while preserving detail in shadow and highlight areas. Lighting is volumetric and directional, often cutting through mist, smoke, or haze to reveal depth and form. The overall aesthetic is dark and serious in tone — evoking tension, mystery, and scale — yet maintains enough visibility and texture for every element to feel tangible and alive. The mood is dramatic, immersive, and painterly, blending realistic detail with heightened color and light expression."
    },
    "watercolor": {
        "name": "Watercolor",
        "description": "detailed watercolor style",
        "longDescription": "A refined watercolor style that preserves the medium's softness and translucency while enhancing structure and depth. Colors remain fluid and luminous, but with richer pigment, sharper contrast, and defined brush textures that retain fine detail without losing the organic, hand-painted feel."
    },
    "Sketchbook": {
        "name": "Sketchbook",
        "description": "Sketchbook style",
        "longDescription": "A traditional pen-and-ink illustration style with muted, earthy tones and fine crosshatching, evoking the look of a classic fantasy storybook or vintage map."
    },
    "photo-releastic": {
        "name": "Photo realistic",
        "description": "Photo realistic style",
        "longDescription": "A lifelike, cinematic style with natural lighting, vibrant colors, sharp detail, and dramatic depth of field."
    },
    "cyberpunk": {
        "name": "Cyberpunk",
        "description": "Luminous Cyber Noir",
        "longDescription": "A cinematic, futuristic rendering style defined by luminous contrast and rich neon hues of violet, cyan, and magenta, balanced against cool, atmospheric shadows. Lighting glows through haze and reflection, creating a moody yet clearly legible composition with preserved midtone detail and visible texture. The overall look feels immersive, stylized, and vividly illuminated without becoming overly dark."
    },
    "retro-vibrant": {
        "name": "Retro illustration",
        "description": "Retro illustration style",
        "longDescription": "A bold, 1980s fantasy style with vivid colors, heroic poses, and painterly textures."
    },
    "graphic-novel": {
        "name": "Graphic Novel",
        "description": "Graphic novel style",
        "longDescription": "A clean, inked comic style with vibrant colors, balanced outlines, and cinematic composition."
    },
    "ink-sketch": {
        "name": "B&W ink sketch",
        "description": "B&W ink sketch style",
        "longDescription": "A rough, black-and-white ink style with scratchy lines, heavy cross-hatching, and surreal fantasy elements."
    },
    "retro": {
        "name": "Retro video game",
        "description": "Retro video game style",
        "longDescription": "A pixelated, 8-bit style with chunky forms, limited palettes, and nostalgic charm."
    },
    "3d-animation": {
        "name": "3D Animation",
        "description": "3D animation style",
        "longDescription": "A polished 3D style with stylized characters, expressive faces, and cinematic lighting."
    },
    "anime": {
        "name": "Anime",
        "description": "Anime style",
        "longDescription": "A vibrant, cel-shaded style with dynamic poses, clean lines, and painterly backgrounds."
    },
    "studio-ghibli": {
        "name": "Studio Ghibli",
        "description": "Studio Ghibli style",
        "longDescription": "A Studio Ghibli film scene"
    },
    "painting": {
        "name": "Painterly",
        "description": "Painting style",
        "longDescription": "A painterly, realistic style with warm lighting, rich detail, and heroic figures in vast, mythic landscapes."
    }
}

def generate_and_upload_image(
    prompt_suffix: str,
    s3_bucket: str,
    s3_base_prefix: str,
    session_id: str,
    segment_index: int,
    image_style_prompt: str,
    image_quality: str,
    debug: bool = False
) -> Optional[str]:
    """
    Generates an image using OpenAI's image model, uploads it to S3,
    and returns the S3 key.
    """
    if not prompt_suffix:
        if debug:
            print("No prompt suffix provided. Skipping.")
        return None
    
    full_prompt = f"{image_style_prompt}. {prompt_suffix}"

    try:
        if debug:
            print(f"Generating image {segment_index + 1}...")
            print(f"  Quality: '{image_quality}'")
            print(f"  Prompt: '{full_prompt[:100]}...'")

        response = openai_client.images.generate(
            model="gpt-image-1-mini",
            prompt=full_prompt,
            n=1,
            size="1536x1024",
            quality=image_quality
        )

        if response.data and response.data[0].b64_json:
            image_data_b64 = response.data[0].b64_json
            image_bytes = base64.b64decode(image_data_b64)

            image_filename = f"{session_id}_segment_{segment_index + 1}.png"
            s3_image_key = f"{s3_base_prefix.rstrip('/')}/{image_filename}"

            if debug:
                print(f"Uploading to S3: {s3_image_key}")

            s3_client.put_object(
                Bucket=s3_bucket,
                Key=s3_image_key,
                Body=image_bytes,
                ContentType='image/png'
            )

            print(f"✅ Image {segment_index + 1} uploaded: {s3_image_key}")
            return s3_image_key
        else:
            print(f"❌ No image data received for segment {segment_index + 1}")
            return None

    except openai.APIError as e:
        print(f"OpenAI API error for segment {segment_index + 1}: {e}")
        return None
    except Exception as e:
        print(f"Error generating image for segment {segment_index + 1}: {e}")
        traceback.print_exc()
        return None


def generate_images_parallel(
    segments: List[Dict],
    s3_bucket: str,
    s3_base_prefix: str,
    session_id: str,
    image_style_prompt: str,
    image_quality: str,
    debug: bool = False,
    max_workers: int = 5
) -> List[Optional[str]]:
    """
    Generates and uploads images for multiple segments in parallel.
    Returns a list of S3 keys in the same order as input segments.
    """
    if not segments:
        return []
    
    print(f"Starting parallel image generation for {len(segments)} segments...")
    
    results = [None] * len(segments)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {}
        
        for idx, segment in enumerate(segments):
            image_prompt = segment.get("image_prompt", "")
            future = executor.submit(
                generate_and_upload_image,
                prompt_suffix=image_prompt,
                s3_bucket=s3_bucket,
                s3_base_prefix=s3_base_prefix,
                session_id=session_id,
                segment_index=idx,
                image_style_prompt=image_style_prompt,
                image_quality=image_quality,
                debug=debug
            )
            future_to_index[future] = idx
        
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            try:
                result = future.result()
                results[index] = result
            except Exception as e:
                print(f"Error in future for segment {index + 1}: {e}")
                results[index] = None
    
    successful = sum(1 for r in results if r is not None)
    print(f"Image generation completed: {successful}/{len(segments)} successful")
    
    return results


def lambda_handler(event, context):
    """
    Generate segment images from narrative summary.
    
    Input: {
        narrativeSummaryS3Key, sessionId, bucket, imageSettings,
        userTransactionsTransactionsId, creditsToRefund, ...
    }
    
    Output: {
        imageKeys: [...], primaryImage: "...", ...passthrough fields
    }
    """
    debug = False
    
    try:
        print("Starting generate-segment-images")
        
        # Extract input
        s3_bucket = event["bucket"]
        session_id = event["sessionId"]
        narrative_summary_key = event["narrativeSummaryS3Key"]
        image_settings = event.get("imageSettings", {})
        
        # Check if images are enabled
        img_enabled = image_settings.get("enabled", True)
        if not img_enabled:
            print("Image generation disabled. Skipping.")
            return {
                "statusCode": 200,
                "imageKeys": [],
                "primaryImage": None,
                # Passthrough all input fields
                **{k: v for k, v in event.items() if k not in ["imageSettings"]}
            }
        
        img_quality = image_settings.get("quality", "medium")

        # Style can be either a key (e.g., "cyberpunk") or the full longDescription text
        style_input = image_settings.get("stylePrompt")
        if not style_input:
            raise ValueError("imageSettings.stylePrompt is required but was not provided")

        # Check if it's a known key first
        if style_input in image_format_lookup:
            img_style_prompt = image_format_lookup[style_input]["longDescription"]
        else:
            # Check if it matches any longDescription value (sent by generate-narrative-summary)
            matched = False
            for style_data in image_format_lookup.values():
                if style_input == style_data["longDescription"]:
                    img_style_prompt = style_input
                    matched = True
                    break

            if not matched:
                # Use as-is if it looks like a valid prompt (reasonably long text)
                if len(style_input) > 20:
                    print(f"Using custom style prompt: {style_input[:50]}...")
                    img_style_prompt = style_input
                else:
                    raise ValueError(f"Invalid stylePrompt '{style_input}'. Must be a valid style key or description.")
        
        # Read narrative summary from S3
        print(f"Reading narrative summary: {narrative_summary_key}")
        summary_obj = s3_client.get_object(Bucket=s3_bucket, Key=narrative_summary_key)
        summary_content = json.loads(summary_obj['Body'].read().decode('utf-8'))
        
        segments = summary_content.get("sessionSegments", [])
        if not segments:
            print("No segments found in summary. Skipping image generation.")
            return {
                "statusCode": 200,
                "imageKeys": [],
                "primaryImage": None,
                **{k: v for k, v in event.items() if k not in ["imageSettings"]}
            }
        
        print(f"Found {len(segments)} segments to generate images for")
        
        # Generate images in parallel
        s3_image_prefix = "public/segment-images/"
        image_keys = generate_images_parallel(
            segments=segments,
            s3_bucket=s3_bucket,
            s3_base_prefix=s3_image_prefix,
            session_id=session_id,
            image_style_prompt=img_style_prompt,
            image_quality=img_quality,
            debug=debug,
            max_workers=5
        )
        
        # First successful image becomes the primary image
        primary_image = next((key for key in image_keys if key is not None), None)
        
        print(f"generate-segment-images completed. Primary image: {primary_image}")
        
        # Build output - passthrough all input fields plus new image data
        output = {
            "statusCode": 200,
            "imageKeys": image_keys,
            "primaryImage": primary_image,
            # Passthrough fields from input
            "narrativeSummaryS3Key": narrative_summary_key,
            "sessionId": session_id,
            "sessionName": event.get("sessionName"),
            "campaignId": event.get("campaignId"),
            "owner": event.get("owner"),
            "bucket": s3_bucket,
            "transcriptKey": event.get("transcriptKey"),
            "generateLore": event.get("generateLore"),
            "generateName": event.get("generateName"),
            "entityMentions": event.get("entityMentions"),
            "userTransactionsTransactionsId": event.get("userTransactionsTransactionsId"),
            "creditsToRefund": event.get("creditsToRefund")
        }
        
        return output

    except Exception as e:
        error_message = str(e)
        print(f"ERROR: {error_message}")
        traceback.print_exc()

        # Re-raise the exception so Step Functions catches it and routes to error handler
        raise
