# Define the path to your local layer zip file
locals {
  python_dependencies_layer_zip_path = "${path.module}/python_dependencies_layer.zip"
}

data "aws_ecr_repository" "segment_audio" {
  name = "segment-audio"
}

data "aws_ecr_repository" "faster_whisper" {
  name = "faster-whisper"
}

# 1. Define the new combined Lambda Layer Resource
resource "aws_lambda_layer_version" "python_dependencies_layer" {
  filename            = local.python_dependencies_layer_zip_path
  source_code_hash    = filebase64sha256(local.python_dependencies_layer_zip_path)

  layer_name          = "python-dependencies-layer-${var.environment}"
  compatible_runtimes = ["python3.10", "python3.11"] # Ensure this covers all your Lambda runtimes
  description         = "Lambda Layer containing common Python dependencies (Pydantic, OpenAI, Requests, etc.)"
}

# Lambda function for start-summary-chain
resource "aws_lambda_function" "start_summary_chain" {
  function_name = "start-summary-chain${local.config.function_suffix}"
  handler       = "app.lambda_handler"
  role          = aws_iam_role.lambda_exec_role.arn
  runtime       = "python3.11"
  timeout       = 30
  memory_size   = 128

  filename         = "${path.module}/start-summary-chain.zip"
  source_code_hash = filebase64sha256("${path.module}/start-summary-chain.zip")

  environment {
    variables = {
      BUCKET_NAME    = local.config.s3_bucket
      ENVIRONMENT    = var.environment
      DYNAMODB_TABLE = local.config.dynamodb_table # Still here if this Lambda uses it directly
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_logs,
    aws_iam_role_policy_attachment.lambda_s3,
    aws_iam_role_policy_attachment.lambda_dynamodb,
    aws_iam_role_policy_attachment.lambda_invoke
    # Add aws_iam_role_policy_attachment.lambda_appsync_attachment if this lambda also needs AppSync
  ]

  tags = {
    Environment = var.environment
  }
}

# Lambda function for segment-audio (container)
resource "aws_lambda_function" "segment_audio" {
  function_name = "segment-audio${local.config.function_suffix}"
  role          = aws_iam_role.lambda_exec_role.arn
  package_type  = "Image"
  image_uri     = "${data.aws_ecr_repository.segment_audio.repository_url}:${var.environment}"
  
  timeout     = 600 
  memory_size = 10240
  
  ephemeral_storage {
    size = 5120
  }

  environment {
    variables = {
      BUCKET_NAME    = local.config.s3_bucket
      ENVIRONMENT    = var.environment
      DYNAMODB_TABLE = local.config.dynamodb_table
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_logs,
    aws_iam_role_policy_attachment.lambda_s3,
    aws_iam_role_policy_attachment.lambda_dynamodb
  ]
  
  tags = {
    Environment = var.environment
  }
}

# Lambda function for transcribe (faster-whisper container)
resource "aws_lambda_function" "transcribe" {
  function_name = "transcribe${local.config.function_suffix}"
  role          = aws_iam_role.lambda_exec_role.arn
  package_type  = "Image"
  image_uri     = "${data.aws_ecr_repository.faster_whisper.repository_url}:${var.environment}"
  
  timeout     = 600
  memory_size = 5308
  
  ephemeral_storage {
    size = 5120
  }

  environment {
    variables = {
      BUCKET_NAME    = local.config.s3_bucket
      ENVIRONMENT    = var.environment
      DYNAMODB_TABLE = local.config.dynamodb_table
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_logs,
    aws_iam_role_policy_attachment.lambda_s3,
    aws_iam_role_policy_attachment.lambda_dynamodb
  ]
  
  tags = {
    Environment = var.environment
  }
}

# Lambda function for combine-text-segments
resource "aws_lambda_function" "combine_text_segments" {
  function_name = "combine-text-segments${local.config.function_suffix}"
  handler       = "app.lambda_handler"
  role          = aws_iam_role.lambda_exec_role.arn
  runtime       = "python3.11"
  timeout       = 60
  memory_size   = 128
  
  filename         = "${path.module}/combine-text-segments.zip"
  source_code_hash = filebase64sha256("${path.module}/combine-text-segments.zip")

  environment {
    variables = {
      BUCKET_NAME = local.config.s3_bucket
      ENVIRONMENT = var.environment
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_logs,
    aws_iam_role_policy_attachment.lambda_s3
  ]
  
  tags = {
    Environment = var.environment
  }
}

# Lambda function for final-summary
resource "aws_lambda_function" "final_summary" {
  function_name = "final-summary${local.config.function_suffix}"
  handler       = "app.lambda_handler"
  role          = aws_iam_role.lambda_exec_role.arn
  runtime       = "python3.11"
  timeout       = 300
  memory_size   = 512

  filename         = "${path.module}/final-summary.zip"
  source_code_hash = filebase64sha256("${path.module}/final-summary.zip")

  ephemeral_storage {
    size = 512
  }

  layers = [
    aws_lambda_layer_version.python_dependencies_layer.arn
  ]

  environment {
    variables = {
      BUCKET_NAME      = local.config.s3_bucket
      ENVIRONMENT      = var.environment
      OPENAI_API_KEY   = var.openai_api_key
      APPSYNC_API_URL  = var.appsync_api_url
      APPSYNC_API_KEY  = var.appsync_api_key
      DYNAMODB_TABLE   = local.config.dynamodb_table
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_logs,
    aws_iam_role_policy_attachment.lambda_s3,
    aws_iam_role_policy_attachment.lambda_appsync_attachment
  ]

  tags = {
    Environment = var.environment
  }
}

# Lambda function for revise-summary
resource "aws_lambda_function" "revise_summary" {
  function_name = "revise-summary${local.config.function_suffix}"
  handler       = "app.lambda_handler"
  role          = aws_iam_role.lambda_exec_role.arn
  runtime       = "python3.11"
  timeout       = 60
  memory_size   = 128

  filename         = "${path.module}/revise-summary.zip"
  source_code_hash = filebase64sha256("${path.module}/revise-summary.zip")

  layers = [
    aws_lambda_layer_version.python_dependencies_layer.arn
  ]

  environment {
    variables = {
      BUCKET_NAME     = local.config.s3_bucket
      ENVIRONMENT     = var.environment
      DYNAMODB_TABLE  = local.config.dynamodb_table
      OPENAI_API_KEY  = var.openai_api_key
      APPSYNC_API_URL = var.appsync_api_url
      APPSYNC_API_KEY = var.appsync_api_key
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_logs,
    aws_iam_role_policy_attachment.lambda_s3,
    aws_iam_role_policy_attachment.lambda_dynamodb,
    aws_iam_role_policy_attachment.lambda_appsync_attachment
  ]

  tags = {
    Environment = var.environment
  }
}

# Lambda function for session-chat
resource "aws_lambda_function" "session_chat" {
  function_name = "session-chat${local.config.function_suffix}"
  handler       = "app.lambda_handler"
  role          = aws_iam_role.lambda_exec_role.arn
  runtime       = "python3.11"
  timeout       = 60 
  memory_size   = 128

  filename         = "${path.module}/session-chat.zip"
  source_code_hash = filebase64sha256("${path.module}/session-chat.zip")

  layers = [
    aws_lambda_layer_version.python_dependencies_layer.arn
  ]

  environment {
    variables = {
      BUCKET_NAME     = local.config.s3_bucket
      ENVIRONMENT     = var.environment
      DYNAMODB_TABLE  = local.config.dynamodb_table
      OPENAI_API_KEY  = var.openai_api_key
      APPSYNC_API_URL = var.appsync_api_url
      APPSYNC_API_KEY = var.appsync_api_key
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_logs,
    aws_iam_role_policy_attachment.lambda_s3,
    aws_iam_role_policy_attachment.lambda_dynamodb,
    aws_iam_role_policy_attachment.lambda_appsync_attachment
  ]

  tags = {
    Environment = var.environment
  }
}

# =========================================================================
# NEW LAMBDA FUNCTION: create-campaign-index
# =========================================================================
resource "aws_lambda_function" "create_campaign_index" {
  function_name = "create-campaign-index${local.config.function_suffix}"
  handler       = "app.lambda_handler"
  role          = aws_iam_role.lambda_exec_role.arn
  runtime       = "python3.11"
  timeout       = 600
  memory_size   = 1024

  filename         = "${path.module}/create-campaign-index.zip"
  source_code_hash = filebase64sha256("${path.module}/create-campaign-index.zip")

  layers = [
    aws_lambda_layer_version.python_dependencies_layer.arn
  ]

  environment {
    variables = {
      BUCKET_NAME                = local.config.s3_bucket
      ENVIRONMENT                = var.environment
      SOURCE_TRANSCRIPT_PREFIX   = "public/segmentedSummaries/"
      INDEX_DESTINATION_PREFIX   = "private/campaign-indexes/"
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_logs,
    aws_iam_role_policy_attachment.lambda_s3,
    aws_iam_role_policy_attachment.lambda_bedrock_access 
  ]

  tags = {
    Environment = var.environment
  }
}

# =========================================================================
# NEW LAMBDA FUNCTION: campaign-chat
# =========================================================================
resource "aws_lambda_function" "campaign_chat" {
  function_name = "campaign-chat${local.config.function_suffix}"
  handler       = "app.lambda_handler"
  role          = aws_iam_role.lambda_exec_role.arn
  runtime       = "python3.11"
  timeout       = 60
  memory_size   = 1024

  filename         = "${path.module}/campaign-chat.zip"
  source_code_hash = filebase64sha256("${path.module}/campaign-chat.zip")

  layers = [
    aws_lambda_layer_version.python_dependencies_layer.arn
  ]

  environment {
    variables = {
      BUCKET_NAME           = local.config.s3_bucket
      ENVIRONMENT           = var.environment
      INDEX_SOURCE_PREFIX   = "private/campaign-indexes/"
      APPSYNC_API_URL       = var.appsync_api_url
      APPSYNC_API_KEY       = var.appsync_api_key
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_logs,
    aws_iam_role_policy_attachment.lambda_s3,
    aws_iam_role_policy_attachment.lambda_bedrock_access,
    aws_iam_role_policy_attachment.lambda_appsync_attachment
  ]

  tags = {
    Environment = var.environment
  }
}

resource "aws_lambda_permission" "allow_bucket_to_call_transcribe" {
  statement_id  = "AllowS3InvokeTranscribe_${var.environment}"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.transcribe.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = data.aws_s3_bucket.current_bucket.arn
  source_account = data.aws_caller_identity.current.account_id
}

resource "aws_lambda_permission" "allow_bucket_to_call_combine_text" {
  statement_id  = "AllowS3InvokeCombineText_${var.environment}"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.combine_text_segments.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = data.aws_s3_bucket.current_bucket.arn
  source_account = data.aws_caller_identity.current.account_id
}

resource "aws_lambda_permission" "allow_sns_to_call_final_summary" {
  statement_id  = "AllowSNSInvokeFinalSummary"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.final_summary.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.summary_events_topic.arn
}

resource "aws_lambda_permission" "allow_sns_to_call_indexing_lambda" {
  statement_id  = "AllowSNSInvokeCampaignIndex"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.create_campaign_index.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.summary_events_topic.arn
}

# REMOVED: The problematic "renamed" permissions are no longer needed.
# By removing them, Terraform will see they exist in the state but not in the code,
# and will plan to destroy them using the default provider, resolving the error.

# IAM POLICY FOR BEDROCK 
resource "aws_iam_policy" "bedrock_access_policy" {
  name        = "BedrockAccessPolicy-${var.environment}"
  description = "Allows invoking Bedrock models for embeddings and generation."

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect   = "Allow",
        Action   = "bedrock:*",
        Resource = [
          "*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_bedrock_access" {
  role       = aws_iam_role.lambda_exec_role.name
  policy_arn = aws_iam_policy.bedrock_access_policy.arn
}
