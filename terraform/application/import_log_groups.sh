#!/bin/bash

# Script to import existing CloudWatch Log Groups into Terraform state

cd "$(dirname "$0")"

# Array of log groups to import (terraform_key:aws_log_group_name)
declare -a log_groups=(
    "refund_credits:/aws/lambda/refund-credits-prod"
    "segment_audio:/aws/lambda/segment-audio-prod"
    "spend_credits:/aws/lambda/spend-credits-prod"
    "html_to_url:/aws/lambda/html-to-url-prod"
    "campaign_chat:/aws/lambda/campaign-chat-prod"
    "create_campaign_index:/aws/lambda/create-campaign-index-prod"
    "transcribe:/aws/lambda/transcribe-prod"
    "revise_summary:/aws/lambda/revise-summary-prod"
    "post_cognito_confirmation:/aws/lambda/post-cognito-confirmation-prod"
    "init_credits:/aws/lambda/init-credits-prod"
    "combine_text_segments:/aws/lambda/combine-text-segments-prod"
    "start_summary_chain:/aws/lambda/start-summary-chain-prod"
)

echo "Importing CloudWatch Log Groups into Terraform state..."

for log_group in "${log_groups[@]}"; do
    IFS=':' read -r terraform_key aws_name <<< "$log_group"
    echo "Importing $terraform_key -> $aws_name"
    
    AWS_PROFILE=scribe terraform import -var-file="prod.tfvars" \
        "aws_cloudwatch_log_group.lambda_log_groups[\"$terraform_key\"]" \
        "$aws_name"
    
    if [ $? -eq 0 ]; then
        echo "✅ Successfully imported $terraform_key"
    else
        echo "❌ Failed to import $terraform_key"
    fi
    echo "---"
done

echo "Import process completed!"
