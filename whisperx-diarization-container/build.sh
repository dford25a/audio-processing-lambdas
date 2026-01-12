#!/bin/bash
set -euo pipefail

# Build the WhisperX diarization container
# NOTE: build can take several minutes due to large ML dependencies.
# Use --no-cache to ensure app.py changes are always picked up (Docker can cache the COPY layer)
docker build --progress=plain --rm=true --force-rm=true --no-cache -t dford/whisperx-diarization container
