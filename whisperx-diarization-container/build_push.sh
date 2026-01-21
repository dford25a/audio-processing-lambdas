#!/bin/bash
set -euo pipefail

# Build and push Speaker Diarization container to ECR
# Architecture: ARM64 (Graviton2) for cost savings

ENV=${1:-latest}
AWS_REGION=${AWS_REGION:-us-east-2}
AWS_ACCOUNT_ID=${AWS_ACCOUNT_ID:-006826332261}
REPO_NAME=${REPO_NAME:-whisperx-diarization}

ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
ECR_IMAGE="${ECR_REGISTRY}/${REPO_NAME}:${ENV}"

# Get the directory where the script is located
SCRIPT_DIR=$(dirname "$0")
cd "$SCRIPT_DIR" || exit

echo "============================================"
echo "Speaker Diarization Container Build & Push"
echo "============================================"
echo "Environment: ${ENV}"
echo "ECR Image: ${ECR_IMAGE}"
echo "Architecture: ARM64 (Graviton2)"
echo ""

# Ensure AWS creds exist before attempting login
echo "Verifying AWS credentials..."
aws sts get-caller-identity --region "$AWS_REGION" >/dev/null

# Login to ECR
echo "Logging into ECR..."
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_REGISTRY"

# Create ECR repository if it doesn't exist
echo "Ensuring ECR repository exists..."
aws ecr describe-repositories --repository-names "$REPO_NAME" --region "$AWS_REGION" 2>/dev/null || \
    aws ecr create-repository --repository-name "$REPO_NAME" --region "$AWS_REGION"

# Build for ARM64 using buildx
# Note: --provenance=false disables attestation manifests which Lambda doesn't support
echo ""
echo "Building and pushing ARM64 image..."
docker buildx build \
    --platform linux/arm64 \
    --progress=plain \
    --provenance=false \
    --push \
    -t "$ECR_IMAGE" \
    container

echo ""
echo "============================================"
echo "Successfully pushed: $ECR_IMAGE"
echo "============================================"
echo ""
echo "Lambda Configuration:"
echo "  - Architecture: arm64"
echo "  - Memory: 3008-4096 MB (recommended)"
echo "  - Timeout: 900 seconds (15 minutes)"
echo "  - Ephemeral Storage: 512 MB (default is fine)"
echo ""
echo "Example Lambda invocation payload:"
cat << 'EOF'
{
  "bucket": "your-bucket",
  "audio_filename": "path/to/audio.mp3",
  "num_speakers": null,
  "cluster_threshold": 0.5,
  "output_format": "json"
}
EOF
