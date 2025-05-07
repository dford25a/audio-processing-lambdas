# Define the path to your local layer zip file
locals {
  openai_layer_zip_path = "${path.module}/openai-layer.zip" # Assuming openai-layer.zip is in the same directory as this lambda.tf
                                                            # Adjust path if it's elsewhere relative to this module.
}

data "aws_ecr_repository" "segment_audio" {
  name = "segment-audio"
}

data "aws_ecr_repository" "faster_whisper" {
  name = "faster-whisper"
}

# 1. Define the Lambda Layer Resource
resource "aws_lambda_layer_version" "openai_layer" {
  filename            = local.openai_layer_zip_path
  source_code_hash    = filebase64sha256(local.openai_layer_zip_path)

  layer_name          = "openai-python-layer-${var.environment}"
  compatible_runtimes = ["python3.10"] # Matches your Lambda runtimes
  description         = "Lambda Layer containing the OpenAI Python library and its dependencies"
}


# Lambda function for start-summary-chain
resource "aws_lambda_function" "start_summary_chain" {
  function_name = "start-summary-chain${local.config.function_suffix}"
  handler       = "app.lambda_handler"
  role          = aws_iam_role.lambda_exec_role.arn
  runtime       = "python3.10"
  timeout       = 30
  memory_size   = 128

  filename         = "${path.module}/start-summary-chain.zip"
  source_code_hash = filebase64sha256("${path.module}/start-summary-chain.zip")

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
    aws_iam_role_policy_attachment.lambda_dynamodb,
    aws_iam_role_policy_attachment.lambda_invoke
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
  image_uri = "${data.aws_ecr_repository.segment_audio.repository_url}:latest"
  
  timeout     = 600  # 10 minutes
  memory_size = 10240  # 10GB
  
  ephemeral_storage {
    size = 5120  # 5GB
  }

  environment {
    variables = {
      BUCKET_NAME = local.config.s3_bucket
      ENVIRONMENT = var.environment
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
  image_uri = "${data.aws_ecr_repository.faster_whisper.repository_url}:latest"
  
  timeout     = 600  # 10 minutes
  memory_size = 5308  # 5GB
  
  ephemeral_storage {
    size = 5120  # 5GB
  }

  environment {
    variables = {
      BUCKET_NAME = local.config.s3_bucket
      ENVIRONMENT = var.environment
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
  runtime       = "python3.10"
  timeout       = 60
  memory_size   = 128
  
  filename      = "${path.module}/combine-text-segments.zip"
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
  runtime       = "python3.10"
  timeout       = 120  # 2 minutes
  memory_size   = 1028

  filename         = "${path.module}/final-summary.zip"
  source_code_hash = filebase64sha256("${path.module}/final-summary.zip")

  ephemeral_storage {
    size = 512
  }

  # ADD THE LAYER HERE
  layers = [
    aws_lambda_layer_version.openai_layer.arn
  ]

  environment {
    variables = {
      BUCKET_NAME    = local.config.s3_bucket
      ENVIRONMENT    = var.environment
      DYNAMODB_TABLE = local.config.dynamodb_table
      OPENAI_API_KEY = var.openai_api_key # This implies it needs the openai library
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

# Lambda function for revise-summary
resource "aws_lambda_function" "revise_summary" {
  function_name = "revise-summary${local.config.function_suffix}"
  handler       = "app.lambda_handler"
  role          = aws_iam_role.lambda_exec_role.arn
  runtime       = "python3.10"
  timeout       = 60
  memory_size   = 128

  filename         = "${path.module}/revise-summary.zip"
  source_code_hash = filebase64sha256("${path.module}/revise-summary.zip")

  # ADD THE LAYER HERE
  layers = [
    aws_lambda_layer_version.openai_layer.arn
  ]

  environment {
    variables = {
      BUCKET_NAME    = local.config.s3_bucket
      ENVIRONMENT    = var.environment
      DYNAMODB_TABLE = local.config.dynamodb_table
      OPENAI_API_KEY = var.openai_api_key # This implies it needs the openai library
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

# Lambda function for session-chat
resource "aws_lambda_function" "session_chat" {
  function_name = "session-chat${local.config.function_suffix}"
  handler       = "app.lambda_handler"
  role          = aws_iam_role.lambda_exec_role.arn
  runtime       = "python3.10"
  timeout       = 60 # Consider increasing if OpenAI calls are slow, e.g., 90 or 120
  memory_size   = 128 # Consider increasing if OpenAI library or processing is memory intensive, e.g., 256 or 512

  filename         = "${path.module}/session-chat.zip"
  source_code_hash = filebase64sha256("${path.module}/session-chat.zip")

  # ADD THE LAYER HERE
  layers = [
    aws_lambda_layer_version.openai_layer.arn
  ]

  environment {
    variables = {
      BUCKET_NAME    = local.config.s3_bucket
      ENVIRONMENT    = var.environment
      DYNAMODB_TABLE = local.config.dynamodb_table
      OPENAI_API_KEY = var.openai_api_key # This implies it needs the openai library
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

# Lambda permissions for S3 triggers
resource "aws_lambda_permission" "allow_bucket_transcribe" {
  statement_id  = "AllowS3Invoke_${var.environment}"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.transcribe.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = "arn:aws:s3:::${local.config.s3_bucket}"
}

resource "aws_lambda_permission" "allow_bucket_combine_text_segments" {
  statement_id  = "AllowS3Invoke_${var.environment}"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.combine_text_segments.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = "arn:aws:s3:::${local.config.s3_bucket}"
}

resource "aws_lambda_permission" "allow_bucket_final_summary" {
  statement_id  = "AllowS3Invoke_${var.environment}"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.final_summary.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = "arn:aws:s3:::${local.config.s3_bucket}"
}