#!/bin/bash
set -euo pipefail

# Test the speaker diarization container locally
# This script starts the container and provides example curl commands

CONTAINER_NAME="speaker-diarization-test"
PORT=9000

echo "============================================"
echo "Speaker Diarization Local Test"
echo "============================================"
echo ""

# Check if container is already running
if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Container already running. Stopping..."
    docker stop "$CONTAINER_NAME" >/dev/null
fi

# Start the container
echo "Starting container on port ${PORT}..."
docker run -d --rm \
    --name "$CONTAINER_NAME" \
    -p "${PORT}:8080" \
    -e AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-}" \
    -e AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-}" \
    -e AWS_SESSION_TOKEN="${AWS_SESSION_TOKEN:-}" \
    -e AWS_REGION="${AWS_REGION:-us-east-2}" \
    dford/whisperx-diarization:latest

echo "Container started!"
echo ""
echo "Waiting for container to be ready..."
sleep 3

# Check if container is healthy
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "ERROR: Container failed to start. Check logs:"
    docker logs "$CONTAINER_NAME" 2>/dev/null || echo "No logs available"
    exit 1
fi

echo ""
echo "============================================"
echo "Container is ready!"
echo "============================================"
echo ""
echo "Test with curl:"
echo ""
echo "# Basic test (requires S3 access):"
echo 'curl -X POST "http://localhost:9000/2015-03-31/functions/function/invocations" \'
echo '  -H "Content-Type: application/json" \'
echo '  -d '"'"'{"bucket": "your-bucket", "audio_filename": "path/to/audio.mp3"}'"'"
echo ""
echo "# With speaker count hint:"
echo 'curl -X POST "http://localhost:9000/2015-03-31/functions/function/invocations" \'
echo '  -H "Content-Type: application/json" \'
echo '  -d '"'"'{"bucket": "your-bucket", "audio_filename": "path/to/audio.mp3", "num_speakers": 2}'"'"
echo ""
echo "# View container logs:"
echo "docker logs -f $CONTAINER_NAME"
echo ""
echo "# Stop container:"
echo "docker stop $CONTAINER_NAME"
echo ""
