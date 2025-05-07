provider "aws" {
  region = "us-east-2"
}

# Reference the current bucket based on environment
data "aws_s3_bucket" "current_bucket" {
  bucket = local.config.s3_bucket
}

# Reference the current DynamoDB table based on environment
data "aws_dynamodb_table" "current_table" {
  name = local.config.dynamodb_table
}

# IAM Role for Lambda functions
resource "aws_iam_role" "lambda_exec_role" {
  name = "lambda_s3_dynamodb_role_${var.environment}"

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
          "${data.aws_s3_bucket.current_bucket.arn}",
          "${data.aws_s3_bucket.current_bucket.arn}/*"
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
          "${data.aws_dynamodb_table.current_table.arn}"
        ]
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

# IAM Policy for Lambda to invoke other Lambda functions
resource "aws_iam_policy" "lambda_invoke" {
  name        = "lambda_invoke_${var.environment}"
  description = "IAM policy for Lambda to invoke other Lambdas"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "lambda:InvokeFunction"
        ]
        Effect   = "Allow"
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_invoke" {
  role       = aws_iam_role.lambda_exec_role.name
  policy_arn = aws_iam_policy.lambda_invoke.arn
}
