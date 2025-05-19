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
  # Ensure these IDs are correct for your prod and non-prod environments
  cognito_user_pool_id = var.environment == "prod" ? "us-east-2_2sxvJnReu" : "us-east-2_p4Mv0gXrW"
}

# Data sources to get current region and account ID (Ensure these are defined elsewhere or add them)
# data "aws_region" "current" {}
# data "aws_caller_identity" "current" {}

# Create API Gateway Authorizer using existing Cognito User Pool
resource "aws_api_gateway_authorizer" "cognito_authorizer" {
  name                = "cognito-authorizer-${var.environment}"
  type                = "COGNITO_USER_POOLS"
  rest_api_id         = aws_api_gateway_rest_api.summary_api.id
  # Ensure data sources are available or replace with static values if needed
  provider_arns       = ["arn:aws:cognito-idp:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:userpool/${local.cognito_user_pool_id}"]
  identity_source     = "method.request.header.Authorization"
}

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
  rest_api_id   = aws_api_gateway_rest_api.summary_api.id
  resource_id   = aws_api_gateway_resource.start_summary_resource.id
  http_method   = "POST"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito_authorizer.id
  # Optional: Define expected request parameters/models if needed
}

# Add OPTIONS method for CORS support
resource "aws_api_gateway_method" "start_summary_options" {
  rest_api_id   = aws_api_gateway_rest_api.summary_api.id
  resource_id   = aws_api_gateway_resource.start_summary_resource.id
  http_method   = "OPTIONS"
  authorization = "NONE" # OPTIONS for CORS preflight should not require authorization
}

# API Gateway integration with Lambda (AWS_PROXY)
resource "aws_api_gateway_integration" "start_summary_lambda_integration" {
  rest_api_id             = aws_api_gateway_rest_api.summary_api.id
  resource_id             = aws_api_gateway_resource.start_summary_resource.id
  http_method             = aws_api_gateway_method.start_summary_post.http_method
  integration_http_method = "POST" # Must be POST for Lambda proxy integration
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.start_summary_chain.invoke_arn # Ensure this lambda resource exists
}

# OPTIONS method MOCK integration for CORS preflight
resource "aws_api_gateway_integration" "start_summary_options_integration" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id
  resource_id = aws_api_gateway_resource.start_summary_resource.id
  http_method = aws_api_gateway_method.start_summary_options.http_method
  type        = "MOCK"

  # Required for MOCK integration type
  request_templates = {
    "application/json" = "{\"statusCode\": 200}"
  }
  # No backend URI or credentials needed for MOCK
}

# Method response for successful POST (e.g., 200 OK) - Define as needed
# resource "aws_api_gateway_method_response" "start_summary_post_200" {
#   rest_api_id = aws_api_gateway_rest_api.summary_api.id
#   resource_id = aws_api_gateway_resource.start_summary_resource.id
#   http_method = aws_api_gateway_method.start_summary_post.http_method
#   status_code = "200"
#   # Add response models/headers if needed
# }

# Method response for OPTIONS method (200 OK for CORS preflight)
resource "aws_api_gateway_method_response" "start_summary_options_200" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id
  resource_id = aws_api_gateway_resource.start_summary_resource.id
  http_method = aws_api_gateway_method.start_summary_options.http_method
  status_code = "200"

  # Define which headers will be sent in the response (required by API Gateway)
  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true,
    "method.response.header.Access-Control-Allow-Methods" = true,
    "method.response.header.Access-Control-Allow-Origin"  = true
  }
  # No response models needed for OPTIONS
}

# Integration response for OPTIONS method (maps MOCK integration to method response)
resource "aws_api_gateway_integration_response" "start_summary_options_integration_response" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id
  resource_id = aws_api_gateway_resource.start_summary_resource.id
  http_method = aws_api_gateway_method.start_summary_options.http_method
  status_code = aws_api_gateway_method_response.start_summary_options_200.status_code # Match the method response status code

  # Define the actual values for the CORS headers
  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'", # List allowed request headers
    "method.response.header.Access-Control-Allow-Methods" = "'POST,OPTIONS'",                                                       # List allowed methods for the actual request
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"                                                                    # Be specific if possible, e.g., "'https://yourfrontend.com'"
  }

  # ADDED: Empty response template often required for MOCK integration responses
  response_templates = {
    "application/json" = ""
  }

  # ADDED: Explicit dependency to ensure integration exists first
  depends_on = [
    aws_api_gateway_integration.start_summary_options_integration
  ]
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
  rest_api_id   = aws_api_gateway_rest_api.summary_api.id
  resource_id   = aws_api_gateway_resource.revise_summary_resource.id
  http_method   = "POST"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito_authorizer.id
}

# Add OPTIONS method for CORS support
resource "aws_api_gateway_method" "revise_summary_options" {
  rest_api_id   = aws_api_gateway_rest_api.summary_api.id
  resource_id   = aws_api_gateway_resource.revise_summary_resource.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

# API Gateway integration with Lambda
resource "aws_api_gateway_integration" "revise_summary_lambda_integration" {
  rest_api_id             = aws_api_gateway_rest_api.summary_api.id
  resource_id             = aws_api_gateway_resource.revise_summary_resource.id
  http_method             = aws_api_gateway_method.revise_summary_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.revise_summary.invoke_arn # Ensure this lambda resource exists
}

# OPTIONS method integration for CORS
resource "aws_api_gateway_integration" "revise_summary_options_integration" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id
  resource_id = aws_api_gateway_resource.revise_summary_resource.id
  http_method = aws_api_gateway_method.revise_summary_options.http_method
  type        = "MOCK"

  request_templates = {
    "application/json" = "{\"statusCode\": 200}"
  }
}

# Method response for OPTIONS method
resource "aws_api_gateway_method_response" "revise_summary_options_200" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id
  resource_id = aws_api_gateway_resource.revise_summary_resource.id
  http_method = aws_api_gateway_method.revise_summary_options.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true,
    "method.response.header.Access-Control-Allow-Methods" = true,
    "method.response.header.Access-Control-Allow-Origin"  = true
  }
}

# Integration response for OPTIONS method
resource "aws_api_gateway_integration_response" "revise_summary_options_integration_response" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id
  resource_id = aws_api_gateway_resource.revise_summary_resource.id
  http_method = aws_api_gateway_method.revise_summary_options.http_method
  status_code = aws_api_gateway_method_response.revise_summary_options_200.status_code

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'",
    "method.response.header.Access-Control-Allow-Methods" = "'POST,OPTIONS'", # Only allow POST and OPTIONS
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"
  }

  # ADDED: Empty response template often required for MOCK integration responses
  response_templates = {
    "application/json" = ""
  }

  # ADDED: Explicit dependency to ensure integration exists first
  depends_on = [
    aws_api_gateway_integration.revise_summary_options_integration
  ]
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
  rest_api_id   = aws_api_gateway_rest_api.summary_api.id
  resource_id   = aws_api_gateway_resource.session_chat_resource.id
  http_method   = "POST"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito_authorizer.id
}

# Add OPTIONS method for CORS support
resource "aws_api_gateway_method" "session_chat_options" {
  rest_api_id   = aws_api_gateway_rest_api.summary_api.id
  resource_id   = aws_api_gateway_resource.session_chat_resource.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

# API Gateway integration with Lambda
resource "aws_api_gateway_integration" "session_chat_lambda_integration" {
  rest_api_id             = aws_api_gateway_rest_api.summary_api.id
  resource_id             = aws_api_gateway_resource.session_chat_resource.id
  http_method             = aws_api_gateway_method.session_chat_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.session_chat.invoke_arn # Ensure this lambda resource exists
}

# OPTIONS method integration for CORS
resource "aws_api_gateway_integration" "session_chat_options_integration" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id
  resource_id = aws_api_gateway_resource.session_chat_resource.id
  http_method = aws_api_gateway_method.session_chat_options.http_method
  type        = "MOCK"

  request_templates = {
    "application/json" = "{\"statusCode\": 200}"
  }
}

# Method response for OPTIONS method
resource "aws_api_gateway_method_response" "session_chat_options_200" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id
  resource_id = aws_api_gateway_resource.session_chat_resource.id
  http_method = aws_api_gateway_method.session_chat_options.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true,
    "method.response.header.Access-Control-Allow-Methods" = true,
    "method.response.header.Access-Control-Allow-Origin"  = true
  }
}

# Integration response for OPTIONS method
resource "aws_api_gateway_integration_response" "session_chat_options_integration_response" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id
  resource_id = aws_api_gateway_resource.session_chat_resource.id
  http_method = aws_api_gateway_method.session_chat_options.http_method
  status_code = aws_api_gateway_method_response.session_chat_options_200.status_code

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'",
    "method.response.header.Access-Control-Allow-Methods" = "'POST,OPTIONS'", # Only allow POST and OPTIONS
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"
  }

  # ADDED: Empty response template often required for MOCK integration responses
  response_templates = {
    "application/json" = ""
  }

  # ADDED: Explicit dependency to ensure integration exists first
  depends_on = [
    aws_api_gateway_integration.session_chat_options_integration
  ]
}


#################################
# Lambda Permissions for API Gateway
#################################

# Allow API Gateway to invoke the start-summary-chain Lambda function
resource "aws_lambda_permission" "api_gateway_start_summary_lambda" {
  statement_id  = "AllowExecutionFromAPIGateway_StartSummary"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.start_summary_chain.function_name # Ensure this lambda resource exists
  principal     = "apigateway.amazonaws.com"
  # Use execution_arn for source_arn for more robust permission scoping
  source_arn    = "${aws_api_gateway_rest_api.summary_api.execution_arn}/*/${aws_api_gateway_method.start_summary_post.http_method}${aws_api_gateway_resource.start_summary_resource.path}"
  # Example if path is /start-summary: "${aws_api_gateway_rest_api.summary_api.execution_arn}/*/POST/start-summary"
}

# Allow API Gateway to invoke the revise-summary Lambda function
resource "aws_lambda_permission" "api_gateway_revise_summary_lambda" {
  statement_id  = "AllowExecutionFromAPIGateway_ReviseSummary"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.revise_summary.function_name # Ensure this lambda resource exists
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.summary_api.execution_arn}/*/${aws_api_gateway_method.revise_summary_post.http_method}${aws_api_gateway_resource.revise_summary_resource.path}"
}

# Allow API Gateway to invoke the session-chat Lambda function
resource "aws_lambda_permission" "api_gateway_session_chat_lambda" {
  statement_id  = "AllowExecutionFromAPIGateway_SessionChat"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.session_chat.function_name # Ensure this lambda resource exists
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.summary_api.execution_arn}/*/${aws_api_gateway_method.session_chat_post.http_method}${aws_api_gateway_resource.session_chat_resource.path}"
}

#################################
# API Gateway Deployment and Stage
#################################

# Deploy the API Gateway
resource "aws_api_gateway_deployment" "summary_api_deployment" {
  # Removed explicit depends_on as triggers handle the necessary dependencies for redeployment.
  # Terraform's graph handles initial creation order.

  rest_api_id = aws_api_gateway_rest_api.summary_api.id

  # Trigger redeployment when any relevant API Gateway component changes.
  triggers = {
    redeployment = sha1(jsonencode([
      # Include IDs or relevant attributes of all resources defining the API structure.
      aws_api_gateway_rest_api.summary_api.id,
      aws_api_gateway_authorizer.cognito_authorizer.id,

      # Start Summary Resources
      aws_api_gateway_resource.start_summary_resource.id,
      aws_api_gateway_method.start_summary_post.id,
      aws_api_gateway_method.start_summary_options.id,
      aws_api_gateway_integration.start_summary_lambda_integration.id,
      aws_api_gateway_integration.start_summary_options_integration.id,
      aws_api_gateway_method_response.start_summary_options_200.id,
      aws_api_gateway_integration_response.start_summary_options_integration_response.id,
      # Add method responses for POST if defined, e.g., aws_api_gateway_method_response.start_summary_post_200.id

      # Revise Summary Resources
      aws_api_gateway_resource.revise_summary_resource.id,
      aws_api_gateway_method.revise_summary_post.id,
      aws_api_gateway_method.revise_summary_options.id,
      aws_api_gateway_integration.revise_summary_lambda_integration.id,
      aws_api_gateway_integration.revise_summary_options_integration.id,
      aws_api_gateway_method_response.revise_summary_options_200.id,
      aws_api_gateway_integration_response.revise_summary_options_integration_response.id,

      # Session Chat Resources
      aws_api_gateway_resource.session_chat_resource.id,
      aws_api_gateway_method.session_chat_post.id,
      aws_api_gateway_method.session_chat_options.id,
      aws_api_gateway_integration.session_chat_lambda_integration.id,
      aws_api_gateway_integration.session_chat_options_integration.id,
      aws_api_gateway_method_response.session_chat_options_200.id,
      aws_api_gateway_integration_response.session_chat_options_integration_response.id,

      # Include Lambda function ARNs if changes to the function itself should trigger API redeployment
      # aws_lambda_function.start_summary_chain.arn,
      # aws_lambda_function.revise_summary.arn,
      # aws_lambda_function.session_chat.arn,
    ]))
  }

  # Ensures a new deployment is created before the old one is destroyed,
  # minimizing downtime during updates.
  lifecycle {
    create_before_destroy = true
  }
}

# Create a dedicated API Gateway Stage pointing to the latest deployment
resource "aws_api_gateway_stage" "api_stage" {
  deployment_id = aws_api_gateway_deployment.summary_api_deployment.id
  rest_api_id   = aws_api_gateway_rest_api.summary_api.id
  stage_name    = var.environment # Use variable for stage name (e.g., "dev", "prod")

  # Optional: Add stage-specific settings like logging, throttling, variables etc.
  # access_log_settings { ... }
  # variables = { ... }
}

#################################
# API Outputs
#################################

# Output the base invoke URL for the stage
output "api_invoke_url" {
  value       = aws_api_gateway_stage.api_stage.invoke_url
  description = "Base invoke URL for the API stage"
}

# Output the specific endpoint URLs
output "start_summary_api_url" {
  value       = "${aws_api_gateway_stage.api_stage.invoke_url}${aws_api_gateway_resource.start_summary_resource.path}"
  description = "URL for invoking the start-summary endpoint"
}

output "revise_summary_api_url" {
  value       = "${aws_api_gateway_stage.api_stage.invoke_url}${aws_api_gateway_resource.revise_summary_resource.path}"
  description = "URL for invoking the revise-summary endpoint"
}

output "session_chat_api_url" {
  value       = "${aws_api_gateway_stage.api_stage.invoke_url}${aws_api_gateway_resource.session_chat_resource.path}"
  description = "URL for invoking the session-chat endpoint"
}

