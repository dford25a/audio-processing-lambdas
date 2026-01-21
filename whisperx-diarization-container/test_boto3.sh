#!/bin/bash
cd "$(dirname "$0")"
docker run --rm --entrypoint python dford/whisperx-diarization:latest -c "import sys; import boto3; print('boto3 ok', boto3.__version__); print('python', sys.executable)"
