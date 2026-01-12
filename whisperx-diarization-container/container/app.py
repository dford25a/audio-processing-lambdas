import os
import json
import signal
import time
import boto3
import whisperx
import torch

# --- Environment Setup ---
# Ensure ffmpeg is in the PATH. This is required for whisperx/ffmpeg-python to find the binary
# if it is installed in /opt/bin (common with Lambda Layers).
if "/opt/bin" not in os.environ["PATH"]:
    os.environ["PATH"] += os.pathsep + "/opt/bin"

# Set HuggingFace cache to /tmp (writable in Lambda) for any runtime downloads
# The whisper model is pre-cached in the image, but VAD and other models may need /tmp
os.environ["HF_HOME"] = "/tmp/huggingface-cache"

# --- Initialization (Global Scope) ---
# These components are initialized once when the Lambda container starts (cold start).

s3 = boto3.client("s3")

# --- Custom Exception and Timeout Context Manager ---
class TimeoutError(Exception):
    """Custom exception to be raised on timeout."""
    pass

class timeout:
    """
    Context manager to enforce a timeout on a block of code using a signal.
    """
    def __init__(self, seconds=1, error_message='Function call timed out'):
        self.seconds = seconds
        self.error_message = error_message

    def handle_timeout(self, signum, frame):
        """This function is called when the alarm signal is received."""
        raise TimeoutError(self.error_message)

    def __enter__(self):
        """Sets up the signal handler and alarm."""
        signal.signal(signal.SIGALRM, self.handle_timeout)
        signal.alarm(self.seconds)

    def __exit__(self, type, value, traceback):
        """Clears the alarm."""
        signal.alarm(0)


def initialize_whisper_model():
    """
    Loads the whisperx model from the pre-cached location in the Docker image.
    This function is called only once during a cold start.
    
    The faster-whisper model is pre-cached in the image at /usr/local/whisperx-models-cache.
    The VAD model will be downloaded to /tmp at runtime (writable in Lambda).
    """
    from faster_whisper import WhisperModel
    
    model_size = "small"
    model_cache_dir = os.getenv("WHISPERX_CACHE_DIR", "/usr/local/whisperx-models-cache")
    device = "cpu"
    compute_type = "int8"

    print(f"Initializing WhisperX model '{model_size}' on {device} with {compute_type}")
    print(f"Using model cache directory: {model_cache_dir}")
    
    try:
        # Load the faster-whisper model directly with local_files_only=True
        # This prevents any write attempts to the read-only filesystem
        model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            download_root=model_cache_dir,
            local_files_only=True
        )
        print("WhisperX model initialized successfully.")
        return model
    except Exception as e:
        print(f"Failed to initialize WhisperX model: {e}")
        raise e


# Load the whisper model into a global variable
WHISPER_MODEL = initialize_whisper_model()

# Diarization model will be loaded lazily (requires HF token)
DIARIZE_MODEL = None


def get_diarize_model(hf_token):
    """
    Lazily load the diarization model with the provided HuggingFace token.
    """
    global DIARIZE_MODEL
    if DIARIZE_MODEL is None:
        print("Loading diarization model (this may take a while on first run)...")
        start_time = time.time()
        from whisperx.diarize import DiarizationPipeline
        DIARIZE_MODEL = DiarizationPipeline(use_auth_token=hf_token, device="cpu")
        print(f"Diarization model loaded in {time.time() - start_time:.2f}s")
    return DIARIZE_MODEL


def process_audio(audio_path, hf_token, min_speakers=None, max_speakers=None):
    """
    Process audio file with transcription and diarization.
    Returns transcription with speaker labels.
    """
    device = "cpu"
    
    # Step 1: Transcribe with WhisperX
    print("Step 1: Transcribing audio...")
    start_time = time.time()
    audio = whisperx.load_audio(audio_path)
    result = WHISPER_MODEL.transcribe(audio, batch_size=4)  # Smaller batch for CPU
    print(f"Transcription completed in {time.time() - start_time:.2f}s")
    print(f"Detected language: {result.get('language', 'unknown')}")
    
    # Step 2: Align whisper output (for word-level timestamps)
    print("Step 2: Aligning transcription...")
    start_time = time.time()
    model_a, metadata = whisperx.load_align_model(
        language_code=result["language"], 
        device=device
    )
    result = whisperx.align(
        result["segments"], 
        model_a, 
        metadata, 
        audio, 
        device,
        return_char_alignments=False
    )
    print(f"Alignment completed in {time.time() - start_time:.2f}s")
    
    # Step 3: Diarization (speaker identification)
    print("Step 3: Running diarization...")
    start_time = time.time()
    diarize_model = get_diarize_model(hf_token)
    
    diarize_kwargs = {}
    if min_speakers is not None:
        diarize_kwargs["min_speakers"] = min_speakers
    if max_speakers is not None:
        diarize_kwargs["max_speakers"] = max_speakers
    
    diarize_segments = diarize_model(audio, **diarize_kwargs)
    print(f"Diarization completed in {time.time() - start_time:.2f}s")
    
    # Step 4: Assign speaker labels to words
    print("Step 4: Assigning speaker labels...")
    result = whisperx.assign_word_speakers(diarize_segments, result)
    
    return result


def format_output(result):
    """
    Format the diarized transcription result into a readable format.
    """
    output_lines = []
    
    for segment in result.get("segments", []):
        speaker = segment.get("speaker", "UNKNOWN")
        start = segment.get("start", 0)
        end = segment.get("end", 0)
        text = segment.get("text", "").strip()
        
        output_lines.append(f"[{start:.2f}s - {end:.2f}s] {speaker}: {text}")
    
    return "\n".join(output_lines)


def format_json_output(result):
    """
    Format the result as JSON with speaker information.
    """
    segments = []
    for segment in result.get("segments", []):
        segments.append({
            "speaker": segment.get("speaker", "UNKNOWN"),
            "start": segment.get("start", 0),
            "end": segment.get("end", 0),
            "text": segment.get("text", "").strip(),
            "words": segment.get("words", [])
        })
    
    return {
        "language": result.get("language", "unknown"),
        "segments": segments
    }


# --- Lambda Handler ---
def handler(event, context):
    """
    Main Lambda function handler. Triggered by a Step Function or direct invocation.
    
    Expected event format:
    {
        "bucket": "your-bucket-name",
        "audio_filename": "path/to/audio.mp3",
        "hf_token": "your-huggingface-token",  # Required for diarization
        "min_speakers": 2,  # Optional
        "max_speakers": 5,  # Optional
        "output_format": "json"  # Optional: "json" or "text" (default: "json")
    }
    """
    local_audio_path = None
    total_start_time = time.time()
    
    try:
        # 1. Get parameters from event
        bucket = event["bucket"]
        key = event["audio_filename"]
        hf_token = event.get("hf_token") or os.environ.get("HF_TOKEN")
        min_speakers = event.get("min_speakers")
        max_speakers = event.get("max_speakers")
        output_format = event.get("output_format", "json")
        
        if not hf_token:
            raise ValueError("HuggingFace token is required for diarization. "
                           "Provide 'hf_token' in event or set HF_TOKEN environment variable.")
        
        print(f"Processing s3://{bucket}/{key}")
        print(f"Min speakers: {min_speakers}, Max speakers: {max_speakers}")

        # 2. Prepare local file path
        filename = os.path.basename(key)
        local_audio_path = f"/tmp/{filename}"
        
        # 3. Download audio file from S3
        print(f"Downloading file to {local_audio_path}...")
        download_start = time.time()
        s3.download_file(bucket, key, local_audio_path)
        print(f"Download complete in {time.time() - download_start:.2f}s")

        # 4. Process with timeout (13 minutes to leave buffer for cleanup)
        result = None
        try:
            with timeout(seconds=780):  # 13 minutes
                result = process_audio(
                    local_audio_path, 
                    hf_token,
                    min_speakers=min_speakers,
                    max_speakers=max_speakers
                )
        except TimeoutError as e:
            print(f"ERROR: Processing timed out: {e}")
            raise

        # 5. Format output
        if output_format == "text":
            output_content = format_output(result)
            output_extension = ".txt"
            content_type = "text/plain"
        else:
            output_content = json.dumps(format_json_output(result), indent=2)
            output_extension = ".json"
            content_type = "application/json"

        # 6. Upload result to S3
        fn_without_ext, _ = os.path.splitext(filename)
        output_key = f"public/transcripts/diarized/{fn_without_ext}{output_extension}"

        print(f"Uploading diarized transcript to s3://{bucket}/{output_key}")
        s3.put_object(
            Bucket=bucket, 
            Key=output_key, 
            Body=output_content,
            ContentType=content_type
        )
        print("Upload complete.")

        total_time = time.time() - total_start_time
        print(f"Total processing time: {total_time:.2f}s")

        return {
            "bucket": bucket,
            "key": output_key,
            "processing_time_seconds": round(total_time, 2),
            "language": result.get("language", "unknown"),
            "num_segments": len(result.get("segments", []))
        }

    except Exception as e:
        error_message = f"Error processing file. Exception: {str(e)}"
        print(f"FATAL: {error_message}")
        raise e

    finally:
        # Cleanup: Ensure the temporary file is always deleted
        if local_audio_path and os.path.exists(local_audio_path):
            print(f"Cleaning up local file: {local_audio_path}")
            os.remove(local_audio_path)
