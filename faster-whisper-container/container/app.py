import os
import json
import urllib.parse
import signal
import boto3
from faster_whisper import WhisperModel

# --- Initialization (Global Scope) ---
# These components are initialized once when the Lambda container starts (cold start).
# They are reused across subsequent invocations (warm starts) for high performance.

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

def initialize_model():
    """
    Loads the faster-whisper model from the pre-cached location in the Docker image.
    This function is called only once during a cold start.
    """
    model_size = "small"
    # This must match the directory set in the Dockerfile
    model_cache_dir = os.getenv("FASTER_WHISPER_CACHE_DIR", "/tmp/faster-whisper-cache")

    print(f"Initializing model '{model_size}' from cache: {model_cache_dir}")
    try:
        model = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8",
            download_root=model_cache_dir,
            # --- THIS IS THE FIX ---
            # This flag prevents the library from trying to write to the read-only filesystem.
            local_files_only=True
        )
        print("Model initialized successfully.")
        return model
    except Exception as e:
        print(f"Failed to initialize model: {e}")
        # If the model can't be loaded, the Lambda function is not viable.
        # Raising an exception here will cause the container initialization to fail.
        raise e

# Load the model into a global variable.
GLOBAL_MODEL = initialize_model()

def call_model(model, audio_path, beam_size=1):
    """
    Calls the transcription model and returns the full transcribed text.
    """
    print(f"Starting transcription for: {audio_path}")
    # vad_filter helps remove long periods of silence for cleaner output
    segments, _ = model.transcribe(
        audio_path,
        beam_size=beam_size,
        vad_filter=True,
        vad_parameters={"max_speech_duration_s": 20}
    )

    # list() consumes the generator, running the actual transcription
    transcribed_segments = list(segments)
    full_text = "".join(segment.text for segment in transcribed_segments)
    print("Transcription complete.")
    return full_text

# --- Lambda Handler ---
def handler(event, context):
    """
    Main Lambda function handler. Triggered by a Step Function.
    """
    local_audio_path = None
    try:
        # 1. Get Bucket and Key from Step Function event
        bucket = event["bucket"]
        key = event["audio_filename"]
        print(f"Processing s3://{bucket}/{key}")

        # 2. Prepare local file path safely
        # Use only the base filename to avoid creating nested directories in /tmp
        filename = os.path.basename(key)
        local_audio_path = f"/tmp/{filename}"
        
        # 3. Download audio file from S3
        print(f"Downloading file to {local_audio_path}...")
        s3.download_file(bucket, key, local_audio_path)
        print("Download complete.")

        # 4. Transcribe with timeout
        # Lambda has a max timeout of 15 mins. We set ours to 14 mins (840s)
        # to ensure we have time to clean up and respond.
        transcribed_text = ''
        try:
            with timeout(seconds=840):
                transcribed_text = call_model(GLOBAL_MODEL, local_audio_path)
        except TimeoutError as e:
            print(f"ERROR: Transcription process timed out: {e}")
            # Raise the error to be caught by the main exception handler
            raise

        # 5. Prepare and upload transcript segment to S3
        # Use os.path.splitext for robustly handling file extensions
        fn_without_ext, _ = os.path.splitext(filename)
        output_key = f"public/transcripts/segments/{fn_without_ext}.txt"

        print(f"Uploading transcript segment to s3://{bucket}/{output_key}")
        s3.put_object(Bucket=bucket, Key=output_key, Body=transcribed_text)
        print("Upload complete.")

        return {
            "bucket": bucket,
            "key": output_key
        }

    except Exception as e:
        # Catch-all for any errors during execution
        error_message = f"Error processing file. Exception: {str(e)}"
        print(f"FATAL: {error_message}")
        # Re-raise the exception to allow the Step Function's error handling
        # (Catch/Retry) to take over. This is a more robust pattern for
        # state machine integrations than returning a success code with an error body.
        raise e

    finally:
        # 6. Cleanup: Ensure the temporary file is always deleted
        if local_audio_path and os.path.exists(local_audio_path):
            print(f"Cleaning up local file: {local_audio_path}")
            os.remove(local_audio_path)
