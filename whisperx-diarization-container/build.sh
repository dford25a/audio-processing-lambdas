#!/bin/bash
set -euo pipefail

# Build the Speaker Diarization container for ARM64
# Uses Faster-Whisper + Sherpa-ONNX for lightweight CPU-only diarization

SCRIPT_DIR=$(dirname "$0")
cd "$SCRIPT_DIR" || exit

echo "Building speaker diarization container (ARM64)..."
echo "This may take several minutes due to model downloads."

# Build for ARM64 architecture (Graviton2)
# Use buildx for cross-platform builds if not on ARM
if [[ "$(uname -m)" == "aarch64" ]] || [[ "$(uname -m)" == "arm64" ]]; then
    # Native ARM build
    docker build \
        --progress=plain \
        --rm=true \
        --force-rm=true \
        --no-cache \
        -t dford/whisperx-diarization:latest \
        container
else
    # Cross-platform build using buildx
    echo "Cross-compiling for ARM64 from $(uname -m)..."
    docker buildx build \
        --platform linux/arm64 \
        --progress=plain \
        --rm=true \
        --load \
        -t dford/whisperx-diarization:latest \
        container
fi

echo ""
echo "Build complete!"
echo "Image: dford/whisperx-diarization:latest"
echo ""
echo "To test locally (on ARM64):"
echo "  docker run --rm -p 9000:8080 dford/whisperx-diarization:latest"
echo ""
echo "To push to ECR:"
echo "  ./build_push.sh [environment]"
