provider "aws" {
  region = "us-east-2" # As per your dev.tfvars and api_gateway.tf
}

# Data sources to get current AWS region and account ID
# (These might also be in your api_gateway.tf, ensure they are accessible or define them here)
data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

# Reference the current bucket based on environment
data "aws_s3_bucket" "current_bucket" {
  bucket = local.config.s3_bucket
}

# Reference the current DynamoDB table based on environment
data "aws_dynamodb_table" "current_table" {
  name = local.config.dynamodb_table
}

# IAM Role for Lambda functions (shared role)
resource "aws_iam_role" "lambda_exec_role" {
  name = "lambda_s3_dynamodb_appsync_role_${var.environment}" # Updated name to reflect AppSync

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      },
    ]
  })

  tags = {
    Environment = var.environment
  }
}

# IAM Policy for Lambda to access CloudWatch Logs
resource "aws_iam_policy" "lambda_logging" {
  name        = "lambda_logging_${var.environment}"
  description = "IAM policy for logging from Lambda"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Effect   = "Allow"
        # It's good practice to scope this more tightly if possible, 
        # but "*" is common for general logging.
        # For tighter scope: "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/*${local.config.function_suffix}:*"
        Resource = "arn:aws:logs:*:*:*" 
      }
    ]
  })
}

# IAM Policy for Lambda to access S3
resource "aws_iam_policy" "lambda_s3" {
  name        = "lambda_s3_access_${var.environment}"
  description = "IAM policy for S3 access from Lambda"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket",
          "s3:ListMultipartUploadParts",
          "s3:ListBucketMultipartUploads"
        ]
        Effect   = "Allow"
        Resource = [
          data.aws_s3_bucket.current_bucket.arn, # Bucket level permissions (e.g., for ListBucket)
          "${data.aws_s3_bucket.current_bucket.arn}/*" # Object level permissions
        ]
      }
    ]
  })
}

# IAM Policy for Lambda to access DynamoDB
resource "aws_iam_policy" "lambda_dynamodb" {
  name        = "lambda_dynamodb_access_${var.environment}"
  description = "IAM policy for DynamoDB access from Lambda"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
          "dynamodb:Scan"
        ]
        Effect   = "Allow"
        Resource = [
          data.aws_dynamodb_table.current_table.arn,
          "${data.aws_dynamodb_table.current_table.arn}/index/*" # If you have GSIs
        ]
      }
    ]
  })
}

# IAM Policy for Lambda to invoke other Lambda functions
resource "aws_iam_policy" "lambda_invoke" {
  name        = "lambda_invoke_${var.environment}"
  description = "IAM policy for Lambda to invoke other Lambdas"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action   = ["lambda:InvokeFunction"]
        Effect   = "Allow"
        Resource = "*" # Consider scoping this down if possible to specific Lambda ARNs
      }
    ]
  })
}

# IAM Policy for Lambda to access AppSync
resource "aws_iam_policy" "lambda_appsync" {
  name        = "lambda_appsync_access_${var.environment}"
  description = "IAM policy for AppSync GraphQL access from Lambda"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "appsync:GraphQL"
        Effect = "Allow"
        Resource = [
          # Specific permissions for the queries/mutations the final_summary Lambda will use
          "arn:aws:appsync:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:apis/${var.appsync_api_id}/*"
        ]
      }
    ]
  })
}

# --- NEW: IAM Policy for Lambda to access Bedrock ---
resource "aws_iam_policy" "lambda_bedrock" {
  name        = "lambda_bedrock_access_${var.environment}"
  description = "IAM policy for Bedrock access from Lambda"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action   = "bedrock:InvokeModel"
        Effect   = "Allow"
        # This ARN is specific to the Titan embedding model used in the Python script.
        Resource = "arn:aws:bedrock:${data.aws_region.current.name}::foundation-model/amazon.titan-embed-text-v2:0"
      }
    ]
  })
}

# Attach policies to role
resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda_exec_role.name
  policy_arn = aws_iam_policy.lambda_logging.arn
}

resource "aws_iam_role_policy_attachment" "lambda_s3" {
  role       = aws_iam_role.lambda_exec_role.name
  policy_arn = aws_iam_policy.lambda_s3.arn
}

resource "aws_iam_role_policy_attachment" "lambda_dynamodb" {
  role       = aws_iam_role.lambda_exec_role.name
  policy_arn = aws_iam_policy.lambda_dynamodb.arn
}

resource "aws_iam_role_policy_attachment" "lambda_invoke" {
  role       = aws_iam_role.lambda_exec_role.name
  policy_arn = aws_iam_policy.lambda_invoke.arn
}

resource "aws_iam_role_policy_attachment" "lambda_appsync_attachment" {
  role       = aws_iam_role.lambda_exec_role.name
  policy_arn = aws_iam_policy.lambda_appsync.arn
}

# --- NEW: Attach Bedrock policy to role ---
resource "aws_iam_role_policy_attachment" "lambda_bedrock_attachment" {
  role       = aws_iam_role.lambda_exec_role.name
  policy_arn = aws_iam_policy.lambda_bedrock.arn
}