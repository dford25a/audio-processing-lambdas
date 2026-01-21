"""
Speaker Diarization Lambda

Uses:
- Faster-Whisper (int8): For transcription with word-level timestamps
- Pyannote.audio: For speaker diarization (PyTorch-based, like WhisperX)

Architecture: ARM64 (Graviton2) for cost savings
"""

import os
import json
import signal
import time
from typing import List, Dict, Any, Optional, Tuple

import boto3
import numpy as np
import torch
from faster_whisper import WhisperModel
from pyannote.audio import Pipeline

# --- Environment Setup ---
os.environ.setdefault("HF_HOME", "/opt/models/huggingface")

# --- Global Clients ---
s3 = boto3.client("s3")


# --- Custom Exception and Timeout Context Manager ---
class TimeoutError(Exception):
    """Custom exception to be raised on timeout."""
    pass


class timeout:
    """Context manager to enforce a timeout on a block of code using a signal."""
    
    def __init__(self, seconds: int = 1, error_message: str = 'Function call timed out'):
        self.seconds = seconds
        self.error_message = error_message

    def handle_timeout(self, signum, frame):
        raise TimeoutError(self.error_message)

    def __enter__(self):
        signal.signal(signal.SIGALRM, self.handle_timeout)
        signal.alarm(self.seconds)

    def __exit__(self, type, value, traceback):
        signal.alarm(0)


# --- Model Initialization ---
def initialize_whisper_model() -> WhisperModel:
    """
    Load the Faster-Whisper model from the pre-cached location.
    Uses int8 quantization for efficient CPU inference.
    """
    model_size = "small.en"
    model_cache_dir = os.getenv("FASTER_WHISPER_CACHE_DIR", "/opt/models/faster-whisper")
    
    print(f"Initializing Faster-Whisper model '{model_size}' with int8 quantization")
    print(f"Model cache directory: {model_cache_dir}")
    
    try:
        model = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8",
            download_root=model_cache_dir,
            local_files_only=True
        )
        print("Faster-Whisper model initialized successfully")
        return model
    except Exception as e:
        print(f"Failed to initialize Faster-Whisper model: {e}")
        raise


def initialize_diarization_pipeline() -> Pipeline:
    """
    Initialize the Pyannote speaker diarization pipeline.
    Requires HF_TOKEN environment variable for model access.
    """
    hf_token = os.getenv("HF_TOKEN")
    if not hf_token:
        raise RuntimeError("HF_TOKEN environment variable required for pyannote models")
    
    print("Initializing Pyannote diarization pipeline...")
    
    try:
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token
        )
        # Use CPU
        pipeline.to(torch.device("cpu"))
        print("Pyannote diarization pipeline initialized successfully")
        return pipeline
    except Exception as e:
        print(f"Failed to initialize diarization pipeline: {e}")
        raise


# --- Global Model Instances (loaded once on cold start) ---
print("Loading models at cold start...")
WHISPER_MODEL = initialize_whisper_model()
DIARIZATION_PIPELINE = None  # Lazy load to avoid issues if HF_TOKEN not set


def get_diarization_pipeline() -> Pipeline:
    """Get or initialize the diarization pipeline."""
    global DIARIZATION_PIPELINE
    if DIARIZATION_PIPELINE is None:
        DIARIZATION_PIPELINE = initialize_diarization_pipeline()
    return DIARIZATION_PIPELINE


# --- Audio Processing ---
def load_audio_with_ffmpeg(audio_path: str, target_sample_rate: int = 16000) -> Tuple[np.ndarray, int]:
    """
    Load audio file using ffmpeg subprocess.
    Handles any format ffmpeg supports (AAC, MP3, WAV, etc.)
    """
    import subprocess
    
    print(f"Loading audio with ffmpeg: {audio_path}")
    
    try:
        cmd = [
            "/usr/local/bin/ffmpeg",
            "-i", audio_path,
            "-ar", str(target_sample_rate),
            "-ac", "1",
            "-f", "f32le",
            "-acodec", "pcm_f32le",
            "-"
        ]
        
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        
        if result.returncode != 0:
            stderr = result.stderr.decode('utf-8', errors='replace')
            print(f"ffmpeg stderr: {stderr}")
            raise RuntimeError(f"ffmpeg failed: {stderr}")
        
        audio = np.frombuffer(result.stdout, dtype=np.float32)
        duration = len(audio) / target_sample_rate
        print(f"Loaded audio: {len(audio)} samples at {target_sample_rate}Hz ({duration:.2f}s)")
        
        return audio, target_sample_rate
        
    except subprocess.TimeoutExpired:
        raise RuntimeError("ffmpeg audio loading timed out")
    except FileNotFoundError:
        raise RuntimeError("ffmpeg not found at /usr/local/bin/ffmpeg")


def transcribe_audio(audio_path: str) -> Tuple[List[Dict[str, Any]], str]:
    """
    Transcribe audio using Faster-Whisper with word-level timestamps.
    """
    print("Starting transcription with Faster-Whisper...")
    start_time = time.time()
    
    segments, info = WHISPER_MODEL.transcribe(
        audio_path,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500}
    )
    
    words = []
    for segment in segments:
        if segment.words:
            for word in segment.words:
                words.append({
                    "word": word.word.strip(),
                    "start": word.start,
                    "end": word.end,
                    "probability": word.probability
                })
    
    elapsed = time.time() - start_time
    print(f"Transcription complete: {len(words)} words in {elapsed:.2f}s")
    print(f"Detected language: {info.language} (probability: {info.language_probability:.2f})")
    
    return words, info.language


def diarize_audio(
    audio_path: str,
    num_speakers: Optional[int] = None,
    min_speakers: Optional[int] = None,
    max_speakers: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Perform speaker diarization using Pyannote.
    """
    print("Starting speaker diarization with Pyannote...")
    start_time = time.time()
    
    pipeline = get_diarization_pipeline()
    
    # Run diarization
    diarization_params = {}
    if num_speakers is not None:
        diarization_params["num_speakers"] = num_speakers
    if min_speakers is not None:
        diarization_params["min_speakers"] = min_speakers
    if max_speakers is not None:
        diarization_params["max_speakers"] = max_speakers
    
    diarization = pipeline(audio_path, **diarization_params)
    
    # Convert to list of dicts
    speaker_segments = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        speaker_segments.append({
            "start": turn.start,
            "end": turn.end,
            "speaker": speaker
        })
    
    elapsed = time.time() - start_time
    unique_speakers = len(set(s["speaker"] for s in speaker_segments))
    print(f"Diarization complete: {len(speaker_segments)} segments, {unique_speakers} speakers in {elapsed:.2f}s")
    
    return speaker_segments


def assign_speakers_to_words(
    words: List[Dict[str, Any]],
    speaker_segments: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Assign speaker labels to words based on timestamp overlap.
    """
    print("Assigning speakers to words...")
    
    for word in words:
        word_start = word["start"]
        word_end = word["end"]
        
        best_speaker = "UNKNOWN"
        best_overlap = 0.0
        
        for segment in speaker_segments:
            overlap_start = max(word_start, segment["start"])
            overlap_end = min(word_end, segment["end"])
            overlap = max(0, overlap_end - overlap_start)
            
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = segment["speaker"]
        
        word["speaker"] = best_speaker
    
    return words


def merge_words_into_segments(words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merge consecutive words from the same speaker into segments.
    """
    if not words:
        return []
    
    segments = []
    current_segment = {
        "speaker": words[0]["speaker"],
        "start": words[0]["start"],
        "end": words[0]["end"],
        "text": words[0]["word"],
        "words": [words[0]]
    }
    
    for word in words[1:]:
        time_gap = word["start"] - current_segment["end"]
        
        if word["speaker"] == current_segment["speaker"] and time_gap < 1.0:
            current_segment["end"] = word["end"]
            current_segment["text"] += " " + word["word"]
            current_segment["words"].append(word)
        else:
            segments.append(current_segment)
            current_segment = {
                "speaker": word["speaker"],
                "start": word["start"],
                "end": word["end"],
                "text": word["word"],
                "words": [word]
            }
    
    segments.append(current_segment)
    return segments


def process_audio(
    audio_path: str,
    num_speakers: Optional[int] = None,
    min_speakers: Optional[int] = None,
    max_speakers: Optional[int] = None
) -> Dict[str, Any]:
    """
    Full processing pipeline: transcription + diarization + merging.
    """
    # Step 1: Transcribe with word timestamps
    words, language = transcribe_audio(audio_path)
    
    if not words:
        print("Warning: No words transcribed")
        return {
            "language": language,
            "segments": [],
            "num_speakers": 0
        }
    
    # Step 2: Diarize to get speaker segments
    speaker_segments = diarize_audio(
        audio_path,
        num_speakers=num_speakers,
        min_speakers=min_speakers,
        max_speakers=max_speakers
    )
    
    # Step 3: Assign speakers to words
    words_with_speakers = assign_speakers_to_words(words, speaker_segments)
    
    # Step 4: Merge into speaker-labeled segments
    segments = merge_words_into_segments(words_with_speakers)
    
    # Count unique speakers
    unique_speakers = len(set(s["speaker"] for s in segments if s["speaker"] != "UNKNOWN"))
    
    return {
        "language": language,
        "segments": segments,
        "num_speakers": unique_speakers
    }


def format_json_output(result: Dict[str, Any]) -> Dict[str, Any]:
    """Format the result for JSON output."""
    segments = []
    for segment in result.get("segments", []):
        segments.append({
            "speaker": segment.get("speaker", "UNKNOWN"),
            "start": round(segment.get("start", 0), 3),
            "end": round(segment.get("end", 0), 3),
            "text": segment.get("text", "").strip(),
            "words": [
                {
                    "word": w["word"],
                    "start": round(w["start"], 3),
                    "end": round(w["end"], 3),
                    "speaker": w.get("speaker", "UNKNOWN")
                }
                for w in segment.get("words", [])
            ]
        })
    
    return {
        "language": result.get("language", "unknown"),
        "num_speakers": result.get("num_speakers", 0),
        "segments": segments
    }


def format_text_output(result: Dict[str, Any]) -> str:
    """Format the result as human-readable text."""
    lines = []
    for segment in result.get("segments", []):
        speaker = segment.get("speaker", "UNKNOWN")
        start = segment.get("start", 0)
        end = segment.get("end", 0)
        text = segment.get("text", "").strip()
        lines.append(f"[{start:.2f}s - {end:.2f}s] {speaker}: {text}")
    
    return "\n".join(lines)


# --- Lambda Handler ---
def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda function handler.
    
    Expected event format:
    {
        "bucket": "your-bucket-name",
        "audio_filename": "path/to/audio.mp3",
        "num_speakers": 2,  # Optional: exact number of speakers
        "min_speakers": 1,  # Optional: minimum speakers
        "max_speakers": 5,  # Optional: maximum speakers
        "output_format": "json"  # Optional: "json" or "text"
    }
    """
    local_audio_path = None
    total_start_time = time.time()
    
    try:
        # 1. Parse event parameters
        bucket = event["bucket"]
        key = event["audio_filename"]
        num_speakers = event.get("num_speakers")
        min_speakers = event.get("min_speakers")
        max_speakers = event.get("max_speakers")
        output_format = event.get("output_format", "json")
        
        print(f"Processing s3://{bucket}/{key}")
        print(f"Parameters: num_speakers={num_speakers}, min={min_speakers}, max={max_speakers}")
        
        # 2. Prepare local file path
        filename = os.path.basename(key)
        local_audio_path = f"/tmp/{filename}"
        
        # 3. Download audio from S3
        print(f"Downloading to {local_audio_path}...")
        download_start = time.time()
        s3.download_file(bucket, key, local_audio_path)
        print(f"Download complete in {time.time() - download_start:.2f}s")
        
        # 4. Process with timeout (13 minutes to leave buffer)
        result = None
        try:
            with timeout(seconds=780):
                result = process_audio(
                    local_audio_path,
                    num_speakers=num_speakers,
                    min_speakers=min_speakers,
                    max_speakers=max_speakers
                )
        except TimeoutError as e:
            print(f"ERROR: Processing timed out: {e}")
            raise
        
        # 5. Format output
        if output_format == "text":
            output_content = format_text_output(result)
            output_extension = ".txt"
            content_type = "text/plain"
        else:
            output_content = json.dumps(format_json_output(result), indent=2)
            output_extension = ".json"
            content_type = "application/json"
        
        # 6. Upload result to S3
        fn_without_ext, _ = os.path.splitext(filename)
        output_key = f"public/transcripts/diarized/{fn_without_ext}{output_extension}"
        
        print(f"Uploading to s3://{bucket}/{output_key}")
        s3.put_object(
            Bucket=bucket,
            Key=output_key,
            Body=output_content,
            ContentType=content_type
        )
        print("Upload complete")
        
        total_time = time.time() - total_start_time
        print(f"Total processing time: {total_time:.2f}s")
        
        return {
            "bucket": bucket,
            "key": output_key,
            "processing_time_seconds": round(total_time, 2),
            "language": result.get("language", "unknown"),
            "num_segments": len(result.get("segments", [])),
            "num_speakers": result.get("num_speakers", 0)
        }
    
    except Exception as e:
        error_message = f"Error processing file: {str(e)}"
        print(f"FATAL: {error_message}")
        raise
    
    finally:
        if local_audio_path and os.path.exists(local_audio_path):
            print(f"Cleaning up: {local_audio_path}")
            os.remove(local_audio_path)
