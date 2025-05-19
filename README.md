# Audio Processing Infrastructure

This repository contains Terraform code to set up the AWS infrastructure for an audio processing pipeline. It includes Lambda functions, ECR repositories, IAM roles, and S3 event triggers.

## Components

- **start-summary-chain**: Lambda function to initiate the audio processing pipeline
- **segment-audio**: Container-based Lambda function to segment uploaded audio files
- **transcribe**: Container-based Lambda function using faster-whisper for audio transcription
- **combine-text-segments**: Lambda function to combine transcription segments
- **final-summary**: Lambda function to generate summaries from transcriptions
- **revise-summary**: Lambda function to revise summaries based on user feedback
- **session-chat**: Lambda function for an AI-powered chat interface

## Prerequisites

- Terraform v1.0+
- AWS CLI configured with appropriate credentials
- Docker for building container images

## Environment Configuration

This infrastructure supports both development and production deployments. The environment is controlled via command line arguments when running Terraform commands.

## Deployment Instructions

### 1. Build the Lambda ZIP files

```bash
./build_lambdas.sh
2. Build and push container images
# For development environment
cd segment-audio-container 
./build_push.sh dev
cd ../faster-whisper-container 
./build_push.sh dev
cd ..

# For production environment
cd segment-audio-container 
./build_push.sh prod
cd ../faster-whisper-container 
./build_push.sh prod
cd ..
3. Initialize Terraform
terraform init
4. Development Deployment
# Plan the infrastructure changes for development
terraform plan -var="environment=dev" -var="openai_api_key=your-openai-api-key"

# Apply the infrastructure for development
terraform apply -var="environment=dev" -var="openai_api_key=your-openai-api-key"
5. Production Deployment
# Plan the infrastructure changes for production
terraform plan -var="environment=prod" -var="openai_api_key=your-prod-openai-api-key"

# Apply the infrastructure for production
terraform apply -var="environment=prod" -var="openai_api_key=your-prod-openai-api-key"
6. Using a separate workspace for production (recommended)
# Create and switch to a production workspace
terraform workspace new prod

# Use production configuration
terraform plan -var="environment=prod" -var="openai_api_key=your-prod-api-key"
terraform apply -var="environment=prod" -var="openai_api_key=your-prod-api-key"

# Switch back to default (dev) workspace
terraform workspace select default
Resource Naming Convention
The infrastructure uses the following naming conventions:

Development: Resources include a -dev suffix (e.g., segment-audio-dev)
Production: Resources use the base name without a suffix (e.g., segment-audio)
Important Notes
The S3 buckets and DynamoDB tables should be created before deploying this infrastructure.
For production deployments, consider using AWS Secrets Manager or Parameter Store for sensitive values like the OpenAI API key.
Ensure your AWS credentials have the necessary permissions to create and manage all the required resources.
Cleaning Up Resources
To remove all created resources:

# For development environment
terraform destroy -var="environment=dev" -var="openai_api_key=your-openai-api-key"

# For production environment
terraform destroy -var="environment=prod" -var="openai_api_key=your-prod-openai-api-key"

# If using workspaces, ensure you're in the right workspace before destroying
terraform workspace select prod  # or default for dev
terraform destroy -var="environment=prod" -var="openai_api_key=your-prod-api-key"
Monitoring and Troubleshooting
Check CloudWatch Logs for Lambda execution logs
Monitor S3 event notifications in the CloudWatch Events console
View Lambda metrics in the AWS Lambda console