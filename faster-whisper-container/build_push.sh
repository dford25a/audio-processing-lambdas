#!/bin/bash
ENV=${1:-latest}
bash build.sh
aws ecr get-login-password --region us-east-2 | docker login --username AWS --password-stdin 006826332261.dkr.ecr.us-east-2.amazonaws.com
docker tag dford/faster-whisper:latest 006826332261.dkr.ecr.us-east-2.amazonaws.com/faster-whisper:$ENV
docker push 006826332261.dkr.ecr.us-east-2.amazonaws.com/faster-whisper:$ENV