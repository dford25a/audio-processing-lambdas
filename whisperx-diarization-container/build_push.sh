#!/bin/bash
set -euo pipefail

ENV=${1:-latest}
AWS_REGION=${AWS_REGION:-us-east-2}
AWS_ACCOUNT_ID=${AWS_ACCOUNT_ID:-006826332261}
REPO_NAME=${REPO_NAME:-whisperx-diarization}

ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
ECR_IMAGE="${ECR_REGISTRY}/${REPO_NAME}:${ENV}"

# Get the directory where the script is located and cd into it
SCRIPT_DIR=$(dirname "$0")
cd "$SCRIPT_DIR" || exit

# Build locally
bash ./build.sh

# Ensure AWS creds exist before attempting login (prevents non-TTY login errors later)
aws sts get-caller-identity --region "$AWS_REGION" >/dev/null

# Login to ECR (non-interactive)
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_REGISTRY"

# Tag & push
docker tag dford/whisperx-diarization:latest "$ECR_IMAGE"
docker push "$ECR_IMAGE"

echo "Pushed: $ECR_IMAGE"
