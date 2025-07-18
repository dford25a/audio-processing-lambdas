#!/bin/bash
ENV=${1:-latest}

# Get the directory where the script is located and cd into it
SCRIPT_DIR=$(dirname "$0")
cd "$SCRIPT_DIR" || exit

# Execute build.sh from the script's directory (now the current directory)
bash ./build.sh
aws ecr get-login-password --region us-east-2 | docker login --username AWS --password-stdin 006826332261.dkr.ecr.us-east-2.amazonaws.com
docker tag dford/faster-whisper:latest 006826332261.dkr.ecr.us-east-2.amazonaws.com/faster-whisper:$ENV
docker push 006826332261.dkr.ecr.us-east-2.amazonaws.com/faster-whisper:$ENV