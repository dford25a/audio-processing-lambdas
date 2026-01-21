# Speaker Diarization Lambda Container

Lightweight speaker diarization for AWS Lambda using **Faster-Whisper** and **Sherpa-ONNX**. Runs entirely on CPU without GPU requirements.

## Architecture

- **Base Image**: `public.ecr.aws/lambda/python:3.10-arm64`
- **Architecture**: ARM64 (Graviton2) - ~20% cheaper than x86
- **Runtime**: ONNX Runtime (CPU)
- **No GPU Required**: All inference runs on CPU with int8 quantization

## Components

| Component | Library | Model | Size |
|-----------|---------|-------|------|
| Transcription | Faster-Whisper | small.en (int8) | ~250MB |
| Segmentation | Sherpa-ONNX | Pyannote 3.0 | ~6MB |
| Speaker Embedding | Sherpa-ONNX | 3dspeaker | ~25MB |

## How It Works

1. **Transcription**: Faster-Whisper transcribes audio with word-level timestamps
2. **Diarization**: Sherpa-ONNX segments audio and clusters speakers
3. **Merging**: Words are assigned to speakers based on timestamp overlap
4. **Output**: JSON or text format with speaker-labeled segments

## Lambda Configuration

| Setting | Recommended Value |
|---------|-------------------|
| Architecture | `arm64` |
| Memory | 3008-4096 MB |
| Timeout | 900 seconds (15 min) |
| Ephemeral Storage | 512 MB (default) |

> **Note**: Higher memory = more CPU power in Lambda. 4GB RAM processes audio ~2x faster than 2GB.

## Input Event Format

```json
{
  "bucket": "your-s3-bucket",
  "audio_filename": "path/to/audio.mp3",
  "num_speakers": null,
  "cluster_threshold": 0.5,
  "output_format": "json"
}
```

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `bucket` | string | Yes | - | S3 bucket name |
| `audio_filename` | string | Yes | - | S3 key to audio file |
| `num_speakers` | int | No | null | Known number of speakers (null = auto-detect) |
| `cluster_threshold` | float | No | 0.5 | Clustering sensitivity (lower = more speakers) |
| `output_format` | string | No | "json" | Output format: "json" or "text" |

## Output Format

### JSON Output

```json
{
  "language": "en",
  "num_speakers": 2,
  "segments": [
    {
      "speaker": "SPEAKER_00",
      "start": 0.5,
      "end": 3.2,
      "text": "Hello, how are you today?",
      "words": [
        {"word": "Hello,", "start": 0.5, "end": 0.8, "speaker": "SPEAKER_00"},
        {"word": "how", "start": 0.9, "end": 1.1, "speaker": "SPEAKER_00"}
      ]
    },
    {
      "speaker": "SPEAKER_01",
      "start": 3.5,
      "end": 5.8,
      "text": "I'm doing great, thanks!",
      "words": [...]
    }
  ]
}
```

### Text Output

```
[0.50s - 3.20s] SPEAKER_00: Hello, how are you today?
[3.50s - 5.80s] SPEAKER_01: I'm doing great, thanks!
```

## Building

### Local Build (for testing)

```bash
./build.sh
```

### Build and Push to ECR

```bash
# Push to ECR with 'latest' tag
./build_push.sh

# Push with specific environment tag
./build_push.sh prod
```

## Testing Locally

```bash
# Start the container
docker run --rm -p 9000:8080 dford/speaker-diarization:latest

# In another terminal, invoke the function
curl -X POST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -d '{"bucket": "test-bucket", "audio_filename": "test.mp3"}'
```

## Performance Expectations

| Audio Duration | Processing Time (4GB RAM) | Processing Time (2GB RAM) |
|----------------|---------------------------|---------------------------|
| 1 minute | ~30-45 seconds | ~60-90 seconds |
| 5 minutes | ~2-3 minutes | ~4-6 minutes |
| 10 minutes | ~5-7 minutes | ~10-14 minutes |

> **Note**: First invocation (cold start) adds ~30-60 seconds for model loading.

## Limitations

- **Max Audio Duration**: ~10-12 minutes per Lambda invocation (15 min timeout)
- **Longer Audio**: Split into chunks using Step Functions Map state
- **Language**: Optimized for English (small.en model). For multilingual, change to `small` model.

## Cost Optimization Tips

1. **Use ARM64**: ~20% cheaper than x86 for same performance
2. **Right-size Memory**: Start with 3GB, increase if timeouts occur
3. **Batch Processing**: Process multiple short files in parallel
4. **Provisioned Concurrency**: Eliminate cold starts for latency-sensitive workloads

## Troubleshooting

### Out of Memory
- Increase Lambda memory to 4096 MB
- For very long audio, split into smaller chunks

### Timeout
- Increase Lambda timeout to 900 seconds (max)
- Split audio longer than 10 minutes

### Poor Speaker Detection
- Adjust `cluster_threshold` (lower = more speakers detected)
- Provide `num_speakers` if known

## Dependencies

- `faster-whisper>=1.0.0` - Transcription with CTranslate2
- `sherpa-onnx>=1.10.0` - Speaker diarization with ONNX Runtime
- `soundfile>=0.12.0` - Audio file I/O
- `numpy<2.0` - Numerical operations
- `boto3>=1.34.0` - AWS SDK

## References

- [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper)
- [Sherpa-ONNX](https://github.com/k2-fsa/sherpa-onnx)
- [Pyannote Segmentation Model](https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-segmentation-models)
