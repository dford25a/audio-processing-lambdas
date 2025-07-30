provider "aws" {
  profile = var.aws_profile
  region  = "us-east-2" # As per your dev.tfvars and api_gateway.tf
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

data "aws_dynamodb_table" "user_transactions_table" {
  name = local.config.user_transactions_table_name
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

resource "aws_iam_policy" "lambda_ssm_access" {
  name        = "lambda_ssm_access_${var.environment}"
  description = "IAM policy for SSM Parameter Store access from Lambda"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "ssm:GetParameters"
        ]
        Effect   = "Allow"
        # Scope this down to the specific parameter paths for better security
        Resource = [
          "arn:aws:ssm:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:parameter${var.stripe_secret_key}",
          "arn:aws:ssm:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:parameter${var.stripe_webhook_secret}"
        ]
      }
    ]
  })
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
          "s3:PutObjectAcl",
          "s3:ListBucket",
          "s3:ListMultipartUploadParts",
          "s3:ListBucketMultipartUploads"
        ]
        Effect   = "Allow"
        Resource = [
          data.aws_s3_bucket.current_bucket.arn, # Bucket level permissions (e.g., for ListBucket)
          "${data.aws_s3_bucket.current_bucket.arn}/*", # Object level permissions
          aws_s3_bucket.html_bucket.arn,
          "${aws_s3_bucket.html_bucket.arn}/*"
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
          "${data.aws_dynamodb_table.current_table.arn}/index/*", # If you have GSIs
          data.aws_dynamodb_table.user_transactions_table.arn,
          "${data.aws_dynamodb_table.user_transactions_table.arn}/index/*"
        ]
      }
    ]
  })
}

# IAM Policy for Lambda to access DynamoDB Streams
resource "aws_iam_policy" "lambda_dynamodb_streams" {
  name        = "lambda_dynamodb_streams_access_${var.environment}"
  description = "IAM policy for DynamoDB Streams access from Lambda"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "dynamodb:DescribeStream",
          "dynamodb:GetRecords",
          "dynamodb:GetShardIterator",
          "dynamodb:ListStreams"
        ]
        Effect   = "Allow"
        Resource = [
          var.user_transactions_table_stream_arn
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

resource "aws_iam_role_policy_attachment" "lambda_dynamodb_streams" {
  role       = aws_iam_role.lambda_exec_role.name
  policy_arn = aws_iam_policy.lambda_dynamodb_streams.arn
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

resource "aws_iam_role_policy_attachment" "lambda_ssm_access" {
  role       = aws_iam_role.lambda_exec_role.name
  policy_arn = aws_iam_policy.lambda_ssm_access.arn
}

resource "aws_iam_policy" "step_function_start_execution_policy" {
  name        = "step_function_start_execution_policy_${var.environment}"
  description = "Policy to allow lambda to start step function execution"

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "states:StartExecution"
        ],
        Resource = aws_sfn_state_machine.audio_processing_state_machine.arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_step_function_start_execution" {
  role       = aws_iam_role.lambda_exec_role.name
  policy_arn = aws_iam_policy.step_function_start_execution_policy.arn
}

resource "aws_s3_bucket" "html_bucket" {
  bucket = local.config.html_s3_bucket

  tags = {
    Environment = var.environment
    Name        = "HTML Storage Bucket"
  }
}

resource "aws_s3_bucket_public_access_block" "html_bucket_public_access" {
  bucket = aws_s3_bucket.html_bucket.id

  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket_policy" "html_bucket_policy" {
  bucket = aws_s3_bucket.html_bucket.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = "*"
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.html_bucket.arn}/*"
      }
    ]
  })
}
