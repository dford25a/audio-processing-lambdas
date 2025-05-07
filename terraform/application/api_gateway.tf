# API Gateway for Lambda Integration
resource "aws_api_gateway_rest_api" "summary_api" {
  name        = "summary-api-${var.environment}"
  description = "API Gateway for the Summary Chain Lambda"

  tags = {
    Environment = var.environment
  }
}

# Determine Cognito User Pool ID based on environment
locals {
  cognito_user_pool_id = var.environment == "prod" ? "us-east-2_2sxvJnReu" : "us-east-2_p4Mv0gXrW"
}

# Create API Gateway Authorizer using existing Cognito User Pool
resource "aws_api_gateway_authorizer" "cognito_authorizer" {
  name                   = "cognito-authorizer-${var.environment}"
  type                   = "COGNITO_USER_POOLS"
  rest_api_id            = aws_api_gateway_rest_api.summary_api.id
  provider_arns          = ["arn:aws:cognito-idp:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:userpool/${local.cognito_user_pool_id}"]
  identity_source        = "method.request.header.Authorization"
}

# Data sources to get current AWS region and account ID
data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

#################################
# start-summary endpoint
#################################

# API Gateway resource path ("/start-summary")
resource "aws_api_gateway_resource" "start_summary_resource" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id
  parent_id   = aws_api_gateway_rest_api.summary_api.root_resource_id
  path_part   = "start-summary"
}

# API Gateway method (POST) with Cognito authorization
resource "aws_api_gateway_method" "start_summary_post" {
  rest_api_id     = aws_api_gateway_rest_api.summary_api.id
  resource_id     = aws_api_gateway_resource.start_summary_resource.id
  http_method     = "POST"
  authorization   = "COGNITO_USER_POOLS"
  authorizer_id   = aws_api_gateway_authorizer.cognito_authorizer.id
}

# Add OPTIONS method for CORS support
resource "aws_api_gateway_method" "start_summary_options" {
  rest_api_id     = aws_api_gateway_rest_api.summary_api.id
  resource_id     = aws_api_gateway_resource.start_summary_resource.id
  http_method     = "OPTIONS"
  authorization   = "NONE"
}

# API Gateway integration with Lambda
resource "aws_api_gateway_integration" "start_summary_lambda_integration" {
  rest_api_id             = aws_api_gateway_rest_api.summary_api.id
  resource_id             = aws_api_gateway_resource.start_summary_resource.id
  http_method             = aws_api_gateway_method.start_summary_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.start_summary_chain.invoke_arn
}

# OPTIONS method integration for CORS
resource "aws_api_gateway_integration" "start_summary_options_integration" {
  rest_api_id   = aws_api_gateway_rest_api.summary_api.id
  resource_id   = aws_api_gateway_resource.start_summary_resource.id
  http_method   = aws_api_gateway_method.start_summary_options.http_method
  type          = "MOCK"
  
  request_templates = {
    "application/json" = "{\"statusCode\": 200}"
  }
}

# Method response for OPTIONS method
resource "aws_api_gateway_method_response" "start_summary_options_200" {
  rest_api_id   = aws_api_gateway_rest_api.summary_api.id
  resource_id   = aws_api_gateway_resource.start_summary_resource.id
  http_method   = aws_api_gateway_method.start_summary_options.http_method
  status_code   = "200"
  
  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true,
    "method.response.header.Access-Control-Allow-Methods" = true,
    "method.response.header.Access-Control-Allow-Origin"  = true
  }
}

# Integration response for OPTIONS method
resource "aws_api_gateway_integration_response" "start_summary_options_integration_response" {
  rest_api_id   = aws_api_gateway_rest_api.summary_api.id
  resource_id   = aws_api_gateway_resource.start_summary_resource.id
  http_method   = aws_api_gateway_method.start_summary_options.http_method
  status_code   = aws_api_gateway_method_response.start_summary_options_200.status_code
  
  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'",
    "method.response.header.Access-Control-Allow-Methods" = "'GET,POST,OPTIONS'",
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"
  }
}

#################################
# revise-summary endpoint
#################################

# API Gateway resource path ("/revise-summary")
resource "aws_api_gateway_resource" "revise_summary_resource" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id
  parent_id   = aws_api_gateway_rest_api.summary_api.root_resource_id
  path_part   = "revise-summary"
}

# API Gateway method (POST) with Cognito authorization
resource "aws_api_gateway_method" "revise_summary_post" {
  rest_api_id     = aws_api_gateway_rest_api.summary_api.id
  resource_id     = aws_api_gateway_resource.revise_summary_resource.id
  http_method     = "POST"
  authorization   = "COGNITO_USER_POOLS"
  authorizer_id   = aws_api_gateway_authorizer.cognito_authorizer.id
}

# Add OPTIONS method for CORS support
resource "aws_api_gateway_method" "revise_summary_options" {
  rest_api_id     = aws_api_gateway_rest_api.summary_api.id
  resource_id     = aws_api_gateway_resource.revise_summary_resource.id
  http_method     = "OPTIONS"
  authorization   = "NONE"
}

# API Gateway integration with Lambda
resource "aws_api_gateway_integration" "revise_summary_lambda_integration" {
  rest_api_id             = aws_api_gateway_rest_api.summary_api.id
  resource_id             = aws_api_gateway_resource.revise_summary_resource.id
  http_method             = aws_api_gateway_method.revise_summary_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.revise_summary.invoke_arn
}

# OPTIONS method integration for CORS
resource "aws_api_gateway_integration" "revise_summary_options_integration" {
  rest_api_id   = aws_api_gateway_rest_api.summary_api.id
  resource_id   = aws_api_gateway_resource.revise_summary_resource.id
  http_method   = aws_api_gateway_method.revise_summary_options.http_method
  type          = "MOCK"
  
  request_templates = {
    "application/json" = "{\"statusCode\": 200}"
  }
}

# Method response for OPTIONS method
resource "aws_api_gateway_method_response" "revise_summary_options_200" {
  rest_api_id   = aws_api_gateway_rest_api.summary_api.id
  resource_id   = aws_api_gateway_resource.revise_summary_resource.id
  http_method   = aws_api_gateway_method.revise_summary_options.http_method
  status_code   = "200"
  
  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true,
    "method.response.header.Access-Control-Allow-Methods" = true,
    "method.response.header.Access-Control-Allow-Origin"  = true
  }
}

# Integration response for OPTIONS method
resource "aws_api_gateway_integration_response" "revise_summary_options_integration_response" {
  rest_api_id   = aws_api_gateway_rest_api.summary_api.id
  resource_id   = aws_api_gateway_resource.revise_summary_resource.id
  http_method   = aws_api_gateway_method.revise_summary_options.http_method
  status_code   = aws_api_gateway_method_response.revise_summary_options_200.status_code
  
  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'",
    "method.response.header.Access-Control-Allow-Methods" = "'GET,POST,OPTIONS'",
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"
  }
}

#################################
# session-chat endpoint
#################################

# API Gateway resource path ("/session-chat")
resource "aws_api_gateway_resource" "session_chat_resource" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id
  parent_id   = aws_api_gateway_rest_api.summary_api.root_resource_id
  path_part   = "session-chat"
}

# API Gateway method (POST) with Cognito authorization
resource "aws_api_gateway_method" "session_chat_post" {
  rest_api_id     = aws_api_gateway_rest_api.summary_api.id
  resource_id     = aws_api_gateway_resource.session_chat_resource.id
  http_method     = "POST"
  authorization   = "COGNITO_USER_POOLS"
  authorizer_id   = aws_api_gateway_authorizer.cognito_authorizer.id
}

# Add OPTIONS method for CORS support
resource "aws_api_gateway_method" "session_chat_options" {
  rest_api_id     = aws_api_gateway_rest_api.summary_api.id
  resource_id     = aws_api_gateway_resource.session_chat_resource.id
  http_method     = "OPTIONS"
  authorization   = "NONE"
}

# API Gateway integration with Lambda
resource "aws_api_gateway_integration" "session_chat_lambda_integration" {
  rest_api_id             = aws_api_gateway_rest_api.summary_api.id
  resource_id             = aws_api_gateway_resource.session_chat_resource.id
  http_method             = aws_api_gateway_method.session_chat_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.session_chat.invoke_arn
}

# OPTIONS method integration for CORS
resource "aws_api_gateway_integration" "session_chat_options_integration" {
  rest_api_id   = aws_api_gateway_rest_api.summary_api.id
  resource_id   = aws_api_gateway_resource.session_chat_resource.id
  http_method   = aws_api_gateway_method.session_chat_options.http_method
  type          = "MOCK"
  
  request_templates = {
    "application/json" = "{\"statusCode\": 200}"
  }
}

# Method response for OPTIONS method
resource "aws_api_gateway_method_response" "session_chat_options_200" {
  rest_api_id   = aws_api_gateway_rest_api.summary_api.id
  resource_id   = aws_api_gateway_resource.session_chat_resource.id
  http_method   = aws_api_gateway_method.session_chat_options.http_method
  status_code   = "200"
  
  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true,
    "method.response.header.Access-Control-Allow-Methods" = true,
    "method.response.header.Access-Control-Allow-Origin"  = true
  }
}

# Integration response for OPTIONS method
resource "aws_api_gateway_integration_response" "session_chat_options_integration_response" {
  rest_api_id   = aws_api_gateway_rest_api.summary_api.id
  resource_id   = aws_api_gateway_resource.session_chat_resource.id
  http_method   = aws_api_gateway_method.session_chat_options.http_method
  status_code   = aws_api_gateway_method_response.session_chat_options_200.status_code
  
  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'",
    "method.response.header.Access-Control-Allow-Methods" = "'GET,POST,OPTIONS'",
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"
  }
}

#################################
# Lambda Permissions for API Gateway
#################################

# Allow API Gateway to invoke the start-summary-chain Lambda function
resource "aws_lambda_permission" "api_gateway_start_summary_lambda" {
  statement_id  = "AllowExecutionFromAPIGateway_StartSummary"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.start_summary_chain.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.summary_api.execution_arn}/*/*/start-summary"
}

# Allow API Gateway to invoke the revise-summary Lambda function
resource "aws_lambda_permission" "api_gateway_revise_summary_lambda" {
  statement_id  = "AllowExecutionFromAPIGateway_ReviseSummary"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.revise_summary.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.summary_api.execution_arn}/*/*/revise-summary"
}

# Allow API Gateway to invoke the session-chat Lambda function
resource "aws_lambda_permission" "api_gateway_session_chat_lambda" {
  statement_id  = "AllowExecutionFromAPIGateway_SessionChat"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.session_chat.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.summary_api.execution_arn}/*/*/session-chat"
}

#################################
# API Gateway Deployment and Stage
#################################

# Deploy the API Gateway
resource "aws_api_gateway_deployment" "summary_api_deployment" {
  # depends_on can still be useful for initial creation order clarity,
  # but triggers will handle the re-deployment on changes.
  depends_on = [
    # Start Summary dependencies
    aws_api_gateway_integration.start_summary_lambda_integration,
    aws_api_gateway_integration.start_summary_options_integration,
    aws_api_gateway_method_response.start_summary_options_200, # Added for completeness, though integration_response is more critical for deployment
    aws_api_gateway_integration_response.start_summary_options_integration_response,
    aws_api_gateway_method.start_summary_post, # Add methods too
    aws_api_gateway_method.start_summary_options,

    # Revise Summary dependencies
    aws_api_gateway_integration.revise_summary_lambda_integration,
    aws_api_gateway_integration.revise_summary_options_integration,
    aws_api_gateway_method_response.revise_summary_options_200,
    aws_api_gateway_integration_response.revise_summary_options_integration_response,
    aws_api_gateway_method.revise_summary_post,
    aws_api_gateway_method.revise_summary_options,

    # Session Chat dependencies
    aws_api_gateway_integration.session_chat_lambda_integration,
    aws_api_gateway_integration.session_chat_options_integration,
    aws_api_gateway_method_response.session_chat_options_200,
    aws_api_gateway_integration_response.session_chat_options_integration_response,
    aws_api_gateway_method.session_chat_post,
    aws_api_gateway_method.session_chat_options,

    # Also depend on the authorizer if it changes
    aws_api_gateway_authorizer.cognito_authorizer
  ]

  rest_api_id = aws_api_gateway_rest_api.summary_api.id

  # THIS IS THE KEY PART:
  triggers = {
    redeployment = sha1(jsonencode([
      # Include IDs or ARNs of all resources that define your API structure
      aws_api_gateway_rest_api.summary_api.id, # Though changing this already triggers a new deployment
      aws_api_gateway_authorizer.cognito_authorizer.id,

      # Start Summary
      aws_api_gateway_resource.start_summary_resource.id,
      aws_api_gateway_method.start_summary_post.id,
      aws_api_gateway_method.start_summary_options.id,
      aws_api_gateway_integration.start_summary_lambda_integration.id,
      aws_api_gateway_integration.start_summary_options_integration.id,
      aws_api_gateway_method_response.start_summary_options_200.id,
      aws_api_gateway_integration_response.start_summary_options_integration_response.id,
      # Consider adding the Lambda ARNs if changes to them should trigger a new deployment
      # aws_lambda_function.start_summary_chain.invoke_arn,

      # Revise Summary
      aws_api_gateway_resource.revise_summary_resource.id,
      aws_api_gateway_method.revise_summary_post.id,
      aws_api_gateway_method.revise_summary_options.id,
      aws_api_gateway_integration.revise_summary_lambda_integration.id,
      aws_api_gateway_integration.revise_summary_options_integration.id,
      aws_api_gateway_method_response.revise_summary_options_200.id,
      aws_api_gateway_integration_response.revise_summary_options_integration_response.id,
      # aws_lambda_function.revise_summary.invoke_arn,

      # Session Chat
      aws_api_gateway_resource.session_chat_resource.id,
      aws_api_gateway_method.session_chat_post.id,
      aws_api_gateway_method.session_chat_options.id,
      aws_api_gateway_integration.session_chat_lambda_integration.id,
      aws_api_gateway_integration.session_chat_options_integration.id,
      aws_api_gateway_method_response.session_chat_options_200.id,
      aws_api_gateway_integration_response.session_chat_options_integration_response.id
      # aws_lambda_function.session_chat.invoke_arn,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Create a dedicated API Gateway Stage
resource "aws_api_gateway_stage" "api_stage" {
  deployment_id = aws_api_gateway_deployment.summary_api_deployment.id
  rest_api_id   = aws_api_gateway_rest_api.summary_api.id
  stage_name    = var.environment

  # Optional: If you want to automatically redeploy when the stage's configuration changes (e.g., logging, throttling)
  # but NOT for API definition changes (that's handled by the deployment's triggers).
  # For most cases, you don't need triggers here if the deployment handles API changes.
  # triggers = {
  #   stage_config_change = timestamp() # or hash of stage-specific settings
  # }
}
#################################
# API Outputs
#################################

# Output the API Gateway URLs
output "start_summary_api_url" {
  value = "${aws_api_gateway_stage.api_stage.invoke_url}/start-summary"
  description = "URL for invoking the start-summary-chain Lambda function"
}

output "revise_summary_api_url" {
  value = "${aws_api_gateway_stage.api_stage.invoke_url}/revise-summary"
  description = "URL for invoking the revise-summary Lambda function"
}

output "session_chat_api_url" {
  value = "${aws_api_gateway_stage.api_stage.invoke_url}/session-chat"
  description = "URL for invoking the session-chat Lambda function"
}