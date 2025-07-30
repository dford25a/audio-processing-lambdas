# Audio Processing Infrastructure

This repository contains AWS infrastructure and Lambda functions for a comprehensive audio processing pipeline with AI-powered features, user management, and payment processing capabilities.

## Architecture Overview

The system consists of Lambda functions, containerized applications, Step Functions, API Gateway endpoints, and supporting infrastructure deployed via Terraform.

## Lambda Functions

### Core Audio Processing
- **start-summary-chain**: Initiates the audio processing pipeline
- **segment-audio-container**: Container-based Lambda for segmenting uploaded audio files
- **faster-whisper-container**: Container-based Lambda using faster-whisper for audio transcription
- **combine-text-segments**: Combines transcription segments into cohesive text
- **final-summary**: Generates AI-powered summaries from transcriptions
- **revise-summary**: Revises summaries based on user feedback

### Chat & AI Interface
- **session-chat**: AI-powered chat interface for user interactions
- **campaign-chat**: Campaign-specific chat functionality

### User & Credit Management
- **init-credits**: Initializes user credit accounts
- **spend-credits**: Handles credit spending transactions
- **refund-credits**: Processes credit refunds

### Campaign & Index Management
- **create-campaign-index**: Creates and manages campaign indices

### Utility Functions
- **html-to-url**: Converts HTML content to accessible URLs
- **stripeWebhook**: Handles Stripe payment webhook events

## Additional Components

- **migrate-historical-segments.py**: Migration script for historical data segments
- **Layer Building Scripts**: Automated scripts for building Lambda layers
  - `build_layer.sh`: General Lambda layer builder
  - `build_html_layer.sh`: HTML processing layer builder  
  - `build_stripe_layer.sh`: Stripe integration layer builder

## Prerequisites

- **Terraform** v1.0+
- **AWS CLI** configured with appropriate credentials
- **Docker** for building container images
- **Python 3.9+** for Lambda functions
- **Node.js** (if applicable for certain layers)

## Project Structure

```
audio-processing-lambdas/
├── terraform/
│   ├── application/          # Main application infrastructure
│   └── shared/              # Shared resources (ECR, etc.)
├── [function-name]/         # Individual Lambda function directories
│   └── app.py              # Lambda handler code
├── [container-name]/        # Container-based Lambda directories
│   ├── container/
│   │   ├── app.py
│   │   └── Dockerfile
│   ├── build.sh
│   └── build_push.sh
└── build_*.sh              # Layer building scripts
```

## Deployment Instructions

### 1. Build Lambda Layers

```bash
# Build general layer
./build_layer.sh

# Build HTML processing layer
./build_html_layer.sh

# Build Stripe integration layer
./build_stripe_layer.sh
```

### 2. Build Lambda ZIP Files

```bash
cd terraform/application
./build_lambdas.sh
```

### 3. Build and Push Container Images

```bash
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
```

### 4. Deploy Infrastructure

#### Initialize Terraform
```bash
cd terraform/application
terraform init
```

#### Development Deployment
```bash
# Plan the infrastructure changes for development
terraform plan -var-file="dev.tfvars"

# Apply the infrastructure for development
terraform apply -var-file="dev.tfvars"
```

#### Production Deployment
```bash
# Plan the infrastructure changes for production
terraform plan -var-file="prod.tfvars"

# Apply the infrastructure for production
terraform apply -var-file="prod.tfvars"
```

#### Using Terraform Workspaces (Recommended)
```bash
# Create and switch to a production workspace
terraform workspace new prod

# Use production configuration
terraform plan -var-file="prod.tfvars"
terraform apply -var-file="prod.tfvars"

# Switch back to default (dev) workspace
terraform workspace select default
```

## Environment Configuration

The infrastructure supports multiple environments through `.tfvars` files:
- `dev.tfvars`: Development environment configuration
- `prod.tfvars`: Production environment configuration

## Resource Naming Convention

- **Development**: Resources include a `-dev` suffix (e.g., `audio-processor-dev`)
- **Production**: Resources use the base name without suffix (e.g., `audio-processor`)

## Important Notes

- **Prerequisites**: S3 buckets and DynamoDB tables should be created before deploying this infrastructure
- **Security**: For production deployments, use AWS Secrets Manager or Parameter Store for sensitive values
- **Permissions**: Ensure your AWS credentials have necessary permissions for all required resources
- **Container Registry**: ECR repositories are managed in the `terraform/shared/` directory
- **API Integration**: Stripe webhook integration requires proper endpoint configuration

## Monitoring and Troubleshooting

- **CloudWatch Logs**: Check Lambda execution logs for debugging
- **Step Functions**: Monitor workflow execution in AWS Step Functions console
- **API Gateway**: Review API logs and metrics for endpoint performance
- **Lambda Metrics**: View function metrics in the AWS Lambda console
- **Container Logs**: Monitor containerized Lambda logs for processing issues

## Cleanup

To remove all created resources:

```bash
cd terraform/application

# For development environment
terraform destroy -var-file="dev.tfvars"

# For production environment  
terraform destroy -var-file="prod.tfvars"

# If using workspaces
terraform workspace select [workspace-name]
terraform destroy -var-file="[environment].tfvars"
```

## Contributing

1. Follow the established Lambda function structure
2. Update Terraform configurations for new resources
3. Test deployments in development environment first
4. Update this README when adding new components

## License

See `LICENSE` file for details.
