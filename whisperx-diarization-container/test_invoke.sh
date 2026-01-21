#!/usr/bin/env bash
set -euo pipefail

# Invoke the Speaker Diarization Lambda with a test event.
#
# Usage:
#   AWS_PROFILE=scribe ./test_invoke.sh
#
# Optional env vars:
#   AWS_REGION=us-east-2
#   FUNCTION_ARN=arn:aws:lambda:us-east-2:006826332261:function:whisperx-diarization-dev
#   BUCKET=...
#   AUDIO_KEY=...
#   OUTPUT_FORMAT=json|text
#   NUM_SPEAKERS=2  (optional - auto-detect if not set)

AWS_REGION=${AWS_REGION:-us-east-2}
FUNCTION_ARN=${FUNCTION_ARN:-arn:aws:lambda:us-east-2:006826332261:function:whisperx-diarization-dev}

BUCKET=${BUCKET:-scribe8a8fcf3f6cb14734bce4bd48352f8043acdd4-devsort}
AUDIO_KEY=${AUDIO_KEY:-public/audio-segments/campaign529b5d65-832c-44fd-a5bd-602d7359f127Session236d44c4-f2bc-4fc0-9233-3899982be591_01_of_26.aac}
OUTPUT_FORMAT=${OUTPUT_FORMAT:-json}
NUM_SPEAKERS=${NUM_SPEAKERS:-}
CLUSTER_THRESHOLD=${CLUSTER_THRESHOLD:-0.5}

OUT_FILE=${OUT_FILE:-/tmp/speaker-diarization-response.json}

if [[ -z "${AWS_PROFILE:-}" ]]; then
  echo "ERROR: AWS_PROFILE is not set. Example: AWS_PROFILE=scribe $0" >&2
  exit 1
fi

echo "============================================"
echo "Speaker Diarization Lambda Test"
echo "============================================"
echo "AWS_PROFILE: $AWS_PROFILE"
echo "Function: $FUNCTION_ARN"
echo "Region: $AWS_REGION"
echo "Input: s3://$BUCKET/$AUDIO_KEY"
echo "Output format: $OUTPUT_FORMAT"
echo "Num speakers: ${NUM_SPEAKERS:-auto-detect}"
echo "Cluster threshold: $CLUSTER_THRESHOLD"
echo "Output file: $OUT_FILE"
echo ""

# Build payload - include num_speakers only if set
if [[ -n "$NUM_SPEAKERS" ]]; then
  PAYLOAD=$(cat <<JSON
{"bucket":"$BUCKET","audio_filename":"$AUDIO_KEY","output_format":"$OUTPUT_FORMAT","num_speakers":$NUM_SPEAKERS,"cluster_threshold":$CLUSTER_THRESHOLD}
JSON
)
else
  PAYLOAD=$(cat <<JSON
{"bucket":"$BUCKET","audio_filename":"$AUDIO_KEY","output_format":"$OUTPUT_FORMAT","cluster_threshold":$CLUSTER_THRESHOLD}
JSON
)
fi

echo "Payload: $PAYLOAD"
echo ""
echo "Invoking Lambda (this may take several minutes for diarization)..."
echo ""

# Invoke and capture both the invoke metadata and the function payload.
INVOKE_START=$(date +%s)

aws lambda invoke \
  --region "$AWS_REGION" \
  --function-name "$FUNCTION_ARN" \
  --cli-binary-format raw-in-base64-out \
  --payload "$PAYLOAD" \
  --log-type Tail \
  "$OUT_FILE" \
  | tee /tmp/speaker-diarization-invoke-metadata.json

INVOKE_END=$(date +%s)
INVOKE_DURATION=$((INVOKE_END - INVOKE_START))

echo ""
echo "============================================"
echo "Invocation completed in ${INVOKE_DURATION}s"
echo "============================================"
echo ""

# Check for errors in metadata
if grep -q '"FunctionError"' /tmp/speaker-diarization-invoke-metadata.json 2>/dev/null; then
  echo "ERROR: Lambda function returned an error!"
  echo ""
  echo "--- Error Response ---"
  cat "$OUT_FILE"
  echo ""
  
  # Decode and show logs if available
  LOG_RESULT=$(jq -r '.LogResult // empty' /tmp/speaker-diarization-invoke-metadata.json 2>/dev/null || true)
  if [[ -n "$LOG_RESULT" ]]; then
    echo "--- CloudWatch Logs (last 4KB) ---"
    echo "$LOG_RESULT" | base64 -d
    echo ""
  fi
  exit 1
fi

echo "--- Response Payload ---"
cat "$OUT_FILE"
echo ""
echo ""

# Pretty print if jq is available and output is JSON
if command -v jq &> /dev/null && [[ "$OUTPUT_FORMAT" == "json" ]]; then
  echo "--- Formatted Response ---"
  jq '.' "$OUT_FILE" 2>/dev/null || cat "$OUT_FILE"
  echo ""
fi

# Show logs if available
LOG_RESULT=$(jq -r '.LogResult // empty' /tmp/speaker-diarization-invoke-metadata.json 2>/dev/null || true)
if [[ -n "$LOG_RESULT" ]]; then
  echo "--- CloudWatch Logs (last 4KB) ---"
  echo "$LOG_RESULT" | base64 -d
  echo ""
fi

echo "Full response saved to: $OUT_FILE"
