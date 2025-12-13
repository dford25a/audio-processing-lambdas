provider "aws" {
  profile = var.aws_profile
  region  = "us-east-2"
}

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

data "aws_s3_bucket" "current_bucket" {
  bucket = local.config.s3_bucket
}

data "aws_dynamodb_table" "current_table" {
  name = local.config.dynamodb_table
}

data "aws_dynamodb_table" "user_transactions_table" {
  name = local.config.user_transactions_table_name
}

# Linker tables for entity relationships
data "aws_dynamodb_table" "campaign_npcs_table" {
  name = local.config.campaign_npcs_table
}

data "aws_dynamodb_table" "campaign_locations_table" {
  name = local.config.campaign_locations_table
}

data "aws_dynamodb_table" "campaign_adventurers_table" {
  name = local.config.campaign_adventurers_table
}

data "aws_dynamodb_table" "session_npcs_table" {
  name = local.config.session_npcs_table
}

data "aws_dynamodb_table" "session_locations_table" {
  name = local.config.session_locations_table
}

data "aws_dynamodb_table" "session_adventurers_table" {
  name = local.config.session_adventurers_table
}

resource "aws_iam_role" "lambda_exec_role" {
  name = "lambda_s3_dynamodb_appsync_role_${var.environment}"

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

data "aws_iam_policy_document" "lambda_combined_policy_doc" {
  statement {
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    effect    = "Allow"
    resources = ["arn:aws:logs:*:*:*"]
  }

  statement {
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:PutObjectAcl",
      "s3:ListBucket",
      "s3:ListMultipartUploadParts",
      "s3:ListBucketMultipartUploads"
    ]
    effect    = "Allow"
    resources = [
      data.aws_s3_bucket.current_bucket.arn,
      "${data.aws_s3_bucket.current_bucket.arn}/*",
      aws_s3_bucket.html_bucket.arn,
      "${aws_s3_bucket.html_bucket.arn}/*"
    ]
  }

  statement {
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:Query",
      "dynamodb:Scan"
    ]
    effect    = "Allow"
    resources = [
      data.aws_dynamodb_table.current_table.arn,
      "${data.aws_dynamodb_table.current_table.arn}/index/*",
      data.aws_dynamodb_table.user_transactions_table.arn,
      "${data.aws_dynamodb_table.user_transactions_table.arn}/index/*",
      # Linker tables for entity relationships
      data.aws_dynamodb_table.campaign_npcs_table.arn,
      data.aws_dynamodb_table.campaign_locations_table.arn,
      data.aws_dynamodb_table.campaign_adventurers_table.arn,
      data.aws_dynamodb_table.session_npcs_table.arn,
      data.aws_dynamodb_table.session_locations_table.arn,
      data.aws_dynamodb_table.session_adventurers_table.arn
    ]
  }

  statement {
    actions   = ["lambda:InvokeFunction"]
    effect    = "Allow"
    resources = ["*"]
  }

  statement {
    actions = ["appsync:GraphQL"]
    effect  = "Allow"
    resources = [
      "arn:aws:appsync:${data.aws_region.current.id}:${data.aws_caller_identity.current.account_id}:apis/${var.appsync_api_id}/*"
    ]
  }

  statement {
    actions   = ["bedrock:InvokeModel"]
    effect    = "Allow"
    resources = ["arn:aws:bedrock:${data.aws_region.current.id}::foundation-model/amazon.titan-embed-text-v2:0"]
  }

  statement {
    actions = ["ssm:GetParameters"]
    effect  = "Allow"
    resources = [
      "arn:aws:ssm:${data.aws_region.current.id}:${data.aws_caller_identity.current.account_id}:parameter${var.stripe_secret_key}",
      "arn:aws:ssm:${data.aws_region.current.id}:${data.aws_caller_identity.current.account_id}:parameter${var.stripe_webhook_secret}"
    ]
  }

  statement {
    actions = ["states:StartExecution"]
    effect  = "Allow"
    resources = [aws_sfn_state_machine.audio_processing_state_machine.arn]
  }
}

resource "aws_iam_policy" "lambda_combined_policy" {
  name_prefix = "lambda_combined_policy_${var.environment}"
  description = "Combined IAM policy for Lambda functions"
  policy      = data.aws_iam_policy_document.lambda_combined_policy_doc.json
}

resource "aws_iam_role_policy_attachment" "lambda_combined_policy_attachment" {
  role       = aws_iam_role.lambda_exec_role.name
  policy_arn = aws_iam_policy.lambda_combined_policy.arn
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
