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
  cognito_user_pool_id = var.environment == "prod" ? "us-east-2_2sxvJnReu" : "us-east-2_N5trdtp4e"
}

# Data sources to get current region and account ID (Ensure these are defined elsewhere or add them)
# data "aws_region" "current" {}
# data "aws_caller_identity" "current" {}

# Create API Gateway Authorizer using existing Cognito User Pool
resource "aws_api_gateway_authorizer" "cognito_authorizer" {
  name              = "cognito-authorizer-${var.environment}"
  type              = "COGNITO_USER_POOLS"
  rest_api_id       = aws_api_gateway_rest_api.summary_api.id
  # Ensure data sources are available or replace with static values if needed
  provider_arns     = ["arn:aws:cognito-idp:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:userpool/${local.cognito_user_pool_id}"]
  identity_source   = "method.request.header.Authorization"
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
}

# Add OPTIONS method for CORS support
resource "aws_api_gateway_method" "start_summary_options" {
  rest_api_id   = aws_api_gateway_rest_api.summary_api.id
  resource_id   = aws_api_gateway_resource.start_summary_resource.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

# API Gateway integration with Lambda (AWS_PROXY)
resource "aws_api_gateway_integration" "start_summary_lambda_integration" {
  rest_api_id             = aws_api_gateway_rest_api.summary_api.id
  resource_id             = aws_api_gateway_resource.start_summary_resource.id
  http_method             = aws_api_gateway_method.start_summary_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.start_summary_chain.invoke_arn # Ensure this lambda resource exists
}

# OPTIONS method MOCK integration for CORS preflight
resource "aws_api_gateway_integration" "start_summary_options_integration" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id
  resource_id = aws_api_gateway_resource.start_summary_resource.id
  http_method = aws_api_gateway_method.start_summary_options.http_method
  type        = "MOCK"

  request_templates = {
    "application/json" = "{\"statusCode\": 200}"
  }
}

# Method response for OPTIONS method (200 OK for CORS preflight)
resource "aws_api_gateway_method_response" "start_summary_options_200" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id
  resource_id = aws_api_gateway_resource.start_summary_resource.id
  http_method = aws_api_gateway_method.start_summary_options.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true,
    "method.response.header.Access-Control-Allow-Methods" = true,
    "method.response.header.Access-Control-Allow-Origin"  = true
  }
}

# Integration response for OPTIONS method (maps MOCK integration to method response)
resource "aws_api_gateway_integration_response" "start_summary_options_integration_response" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id
  resource_id = aws_api_gateway_resource.start_summary_resource.id
  http_method = aws_api_gateway_method.start_summary_options.http_method
  status_code = aws_api_gateway_method_response.start_summary_options_200.status_code

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'",
    "method.response.header.Access-Control-Allow-Methods" = "'POST,OPTIONS'",
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"
  }

  response_templates = {
    "application/json" = ""
  }

  depends_on = [
    aws_api_gateway_integration.start_summary_options_integration
  ]
}

#################################
# NEW: stripe-webhook endpoint
#################################

# API Gateway resource path ("/stripe-webhook")
resource "aws_api_gateway_resource" "stripe_webhook_resource" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id
  parent_id   = aws_api_gateway_rest_api.summary_api.root_resource_id
  path_part   = "stripe-webhook"
}

# API Gateway method (POST) - NO authorization for webhooks
resource "aws_api_gateway_method" "stripe_webhook_post" {
  rest_api_id   = aws_api_gateway_rest_api.summary_api.id
  resource_id   = aws_api_gateway_resource.stripe_webhook_resource.id
  http_method   = "POST"
  authorization = "NONE" # Stripe needs to call this endpoint without credentials
}

# API Gateway integration with the stripeWebhook Lambda
resource "aws_api_gateway_integration" "stripe_webhook_lambda_integration" {
  rest_api_id             = aws_api_gateway_rest_api.summary_api.id
  resource_id             = aws_api_gateway_resource.stripe_webhook_resource.id
  http_method             = aws_api_gateway_method.stripe_webhook_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.stripe_webhook.invoke_arn
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
    "method.response.header.Access-Control-Allow-Methods" = "'POST,OPTIONS'",
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"
  }

  response_templates = {
    "application/json" = ""
  }

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
    "method.response.header.Access-Control-Allow-Methods" = "'POST,OPTIONS'",
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"
  }

  response_templates = {
    "application/json" = ""
  }

  depends_on = [
    aws_api_gateway_integration.session_chat_options_integration
  ]
}

#################################
# NEW: campaign-chat endpoint
#################################

# API Gateway resource path ("/campaign-chat")
resource "aws_api_gateway_resource" "campaign_chat_resource" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id
  parent_id   = aws_api_gateway_rest_api.summary_api.root_resource_id
  path_part   = "campaign-chat"
}

# API Gateway method (POST) with Cognito authorization
resource "aws_api_gateway_method" "campaign_chat_post" {
  rest_api_id   = aws_api_gateway_rest_api.summary_api.id
  resource_id   = aws_api_gateway_resource.campaign_chat_resource.id
  http_method   = "POST"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito_authorizer.id
}

# Add OPTIONS method for CORS support
resource "aws_api_gateway_method" "campaign_chat_options" {
  rest_api_id   = aws_api_gateway_rest_api.summary_api.id
  resource_id   = aws_api_gateway_resource.campaign_chat_resource.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

# API Gateway integration with the new campaign-chat Lambda
resource "aws_api_gateway_integration" "campaign_chat_lambda_integration" {
  rest_api_id             = aws_api_gateway_rest_api.summary_api.id
  resource_id             = aws_api_gateway_resource.campaign_chat_resource.id
  http_method             = aws_api_gateway_method.campaign_chat_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.campaign_chat.invoke_arn # Points to the campaign_chat lambda
}

# OPTIONS method integration for CORS
resource "aws_api_gateway_integration" "campaign_chat_options_integration" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id
  resource_id = aws_api_gateway_resource.campaign_chat_resource.id
  http_method = aws_api_gateway_method.campaign_chat_options.http_method
  type        = "MOCK"

  request_templates = {
    "application/json" = "{\"statusCode\": 200}"
  }
}

# Method response for OPTIONS method
resource "aws_api_gateway_method_response" "campaign_chat_options_200" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id
  resource_id = aws_api_gateway_resource.campaign_chat_resource.id
  http_method = aws_api_gateway_method.campaign_chat_options.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true,
    "method.response.header.Access-Control-Allow-Methods" = true,
    "method.response.header.Access-Control-Allow-Origin"  = true
  }
}

# Integration response for OPTIONS method
resource "aws_api_gateway_integration_response" "campaign_chat_options_integration_response" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id
  resource_id = aws_api_gateway_resource.campaign_chat_resource.id
  http_method = aws_api_gateway_method.campaign_chat_options.http_method
  status_code = aws_api_gateway_method_response.campaign_chat_options_200.status_code

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'",
    "method.response.header.Access-Control-Allow-Methods" = "'POST,OPTIONS'",
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"
  }

  response_templates = {
    "application/json" = ""
  }

  depends_on = [
    aws_api_gateway_integration.campaign_chat_options_integration
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
  source_arn    = "${aws_api_gateway_rest_api.summary_api.execution_arn}/*/${aws_api_gateway_method.start_summary_post.http_method}${aws_api_gateway_resource.start_summary_resource.path}"
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

# NEW: Allow API Gateway to invoke the campaign-chat Lambda function
resource "aws_lambda_permission" "api_gateway_campaign_chat_lambda" {
  statement_id  = "AllowExecutionFromAPIGateway_CampaignChat"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.campaign_chat.function_name # Points to the campaign_chat lambda
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.summary_api.execution_arn}/*/${aws_api_gateway_method.campaign_chat_post.http_method}${aws_api_gateway_resource.campaign_chat_resource.path}"
}

# NEW: Allow API Gateway to invoke the stripe-webhook Lambda function
resource "aws_lambda_permission" "api_gateway_stripe_webhook_lambda" {
  statement_id  = "AllowExecutionFromAPIGateway_StripeWebhook"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.stripe_webhook.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.summary_api.execution_arn}/*/${aws_api_gateway_method.stripe_webhook_post.http_method}${aws_api_gateway_resource.stripe_webhook_resource.path}"
}


#################################
# spend-credits endpoint
#################################

# API Gateway resource path ("/spend-credits")
resource "aws_api_gateway_resource" "spend_credits_resource" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id
  parent_id   = aws_api_gateway_rest_api.summary_api.root_resource_id
  path_part   = "spend-credits"
}

# API Gateway method (POST) with Cognito authorization
resource "aws_api_gateway_method" "spend_credits_post" {
  rest_api_id   = aws_api_gateway_rest_api.summary_api.id
  resource_id   = aws_api_gateway_resource.spend_credits_resource.id
  http_method   = "POST"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito_authorizer.id
}

# Add OPTIONS method for CORS support
resource "aws_api_gateway_method" "spend_credits_options" {
  rest_api_id   = aws_api_gateway_rest_api.summary_api.id
  resource_id   = aws_api_gateway_resource.spend_credits_resource.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

# API Gateway integration with the spend_credits Lambda
resource "aws_api_gateway_integration" "spend_credits_lambda_integration" {
  rest_api_id             = aws_api_gateway_rest_api.summary_api.id
  resource_id             = aws_api_gateway_resource.spend_credits_resource.id
  http_method             = aws_api_gateway_method.spend_credits_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.spend_credits.invoke_arn
}

# OPTIONS method MOCK integration for CORS preflight
resource "aws_api_gateway_integration" "spend_credits_options_integration" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id
  resource_id = aws_api_gateway_resource.spend_credits_resource.id
  http_method = aws_api_gateway_method.spend_credits_options.http_method
  type        = "MOCK"

  request_templates = {
    "application/json" = "{\"statusCode\": 200}"
  }
}

# Method response for OPTIONS method (200 OK for CORS preflight)
resource "aws_api_gateway_method_response" "spend_credits_options_200" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id
  resource_id = aws_api_gateway_resource.spend_credits_resource.id
  http_method = aws_api_gateway_method.spend_credits_options.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true,
    "method.response.header.Access-Control-Allow-Methods" = true,
    "method.response.header.Access-Control-Allow-Origin"  = true
  }
}

# Integration response for OPTIONS method
resource "aws_api_gateway_integration_response" "spend_credits_options_integration_response" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id
  resource_id = aws_api_gateway_resource.spend_credits_resource.id
  http_method = aws_api_gateway_method.spend_credits_options.http_method
  status_code = aws_api_gateway_method_response.spend_credits_options_200.status_code

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'",
    "method.response.header.Access-Control-Allow-Methods" = "'POST,OPTIONS'",
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"
  }

  response_templates = {
    "application/json" = ""
  }

  depends_on = [
    aws_api_gateway_integration.spend_credits_options_integration
  ]
}

# Allow API Gateway to invoke the spend-credits Lambda function
resource "aws_lambda_permission" "api_gateway_spend_credits_lambda" {
  statement_id  = "AllowExecutionFromAPIGateway_SpendCredits"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.spend_credits.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.summary_api.execution_arn}/*/${aws_api_gateway_method.spend_credits_post.http_method}${aws_api_gateway_resource.spend_credits_resource.path}"
}

#################################
# html-to-url endpoint
#################################

# API Gateway resource path ("/html-to-url")
resource "aws_api_gateway_resource" "html_to_url_resource" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id
  parent_id   = aws_api_gateway_rest_api.summary_api.root_resource_id
  path_part   = "html-to-url"
}

# API Gateway method (POST) with Cognito authorization
resource "aws_api_gateway_method" "html_to_url_post" {
  rest_api_id   = aws_api_gateway_rest_api.summary_api.id
  resource_id   = aws_api_gateway_resource.html_to_url_resource.id
  http_method   = "POST"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito_authorizer.id
}

# Add OPTIONS method for CORS support
resource "aws_api_gateway_method" "html_to_url_options" {
  rest_api_id   = aws_api_gateway_rest_api.summary_api.id
  resource_id   = aws_api_gateway_resource.html_to_url_resource.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

# API Gateway integration with Lambda
resource "aws_api_gateway_integration" "html_to_url_lambda_integration" {
  rest_api_id             = aws_api_gateway_rest_api.summary_api.id
  resource_id             = aws_api_gateway_resource.html_to_url_resource.id
  http_method             = aws_api_gateway_method.html_to_url_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.html_to_url.invoke_arn
}

# OPTIONS method integration for CORS
resource "aws_api_gateway_integration" "html_to_url_options_integration" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id
  resource_id = aws_api_gateway_resource.html_to_url_resource.id
  http_method = aws_api_gateway_method.html_to_url_options.http_method
  type        = "MOCK"

  request_templates = {
    "application/json" = "{\"statusCode\": 200}"
  }
}

# Method response for OPTIONS method
resource "aws_api_gateway_method_response" "html_to_url_options_200" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id
  resource_id = aws_api_gateway_resource.html_to_url_resource.id
  http_method = aws_api_gateway_method.html_to_url_options.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true,
    "method.response.header.Access-Control-Allow-Methods" = true,
    "method.response.header.Access-Control-Allow-Origin"  = true
  }
}

# Integration response for OPTIONS method
resource "aws_api_gateway_integration_response" "html_to_url_options_integration_response" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id
  resource_id = aws_api_gateway_resource.html_to_url_resource.id
  http_method = aws_api_gateway_method.html_to_url_options.http_method
  status_code = aws_api_gateway_method_response.html_to_url_options_200.status_code

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'",
    "method.response.header.Access-Control-Allow-Methods" = "'POST,OPTIONS'",
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"
  }

  response_templates = {
    "application/json" = ""
  }

  depends_on = [
    aws_api_gateway_integration.html_to_url_options_integration
  ]
}

# Allow API Gateway to invoke the html-to-url Lambda function
resource "aws_lambda_permission" "api_gateway_html_to_url_lambda" {
  statement_id  = "AllowExecutionFromAPIGateway_HtmlToUrl"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.html_to_url.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.summary_api.execution_arn}/*/${aws_api_gateway_method.html_to_url_post.http_method}${aws_api_gateway_resource.html_to_url_resource.path}"
}

#################################
# API Gateway Deployment and Stage
#################################

# Deploy the API Gateway
resource "aws_api_gateway_deployment" "summary_api_deployment" {
  rest_api_id = aws_api_gateway_rest_api.summary_api.id

  triggers = {
    redeployment = sha1(jsonencode([
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
      
      # NEW: Campaign Chat Resources
      aws_api_gateway_resource.campaign_chat_resource.id,
      aws_api_gateway_method.campaign_chat_post.id,
      aws_api_gateway_method.campaign_chat_options.id,
      aws_api_gateway_integration.campaign_chat_lambda_integration.id,
      aws_api_gateway_integration.campaign_chat_options_integration.id,
      aws_api_gateway_method_response.campaign_chat_options_200.id,
      aws_api_gateway_integration_response.campaign_chat_options_integration_response.id,
      
      # Stripe Webhook Resources
      aws_api_gateway_resource.stripe_webhook_resource.id,
      aws_api_gateway_method.stripe_webhook_post.id,
      aws_api_gateway_integration.stripe_webhook_lambda_integration.id,
      
      # Spend Credits Resources
      aws_api_gateway_resource.spend_credits_resource.id,
      aws_api_gateway_method.spend_credits_post.id,
      aws_api_gateway_method.spend_credits_options.id,
      aws_api_gateway_integration.spend_credits_lambda_integration.id,
      aws_api_gateway_integration.spend_credits_options_integration.id,
      aws_api_gateway_method_response.spend_credits_options_200.id,
      aws_api_gateway_integration_response.spend_credits_options_integration_response.id,

      # Html To Url Resources
      aws_api_gateway_resource.html_to_url_resource.id,
      aws_api_gateway_method.html_to_url_post.id,
      aws_api_gateway_method.html_to_url_options.id,
      aws_api_gateway_integration.html_to_url_lambda_integration.id,
      aws_api_gateway_integration.html_to_url_options_integration.id,
      aws_api_gateway_method_response.html_to_url_options_200.id,
      aws_api_gateway_integration_response.html_to_url_options_integration_response.id,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Create a dedicated API Gateway Stage pointing to the latest deployment
resource "aws_api_gateway_stage" "api_stage" {
  deployment_id = aws_api_gateway_deployment.summary_api_deployment.id
  rest_api_id   = aws_api_gateway_rest_api.summary_api.id
  stage_name    = var.environment
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

output "campaign_chat_api_url" {
  value       = "${aws_api_gateway_stage.api_stage.invoke_url}${aws_api_gateway_resource.campaign_chat_resource.path}"
  description = "URL for invoking the campaign-chat endpoint"
}

output "stripe_webhook_api_url" {
  value       = "${aws_api_gateway_stage.api_stage.invoke_url}${aws_api_gateway_resource.stripe_webhook_resource.path}"
  description = "URL for the Stripe Webhook. Register this URL in your Stripe dashboard."
}

output "spend_credits_api_url" {
  value       = "${aws_api_gateway_stage.api_stage.invoke_url}${aws_api_gateway_resource.spend_credits_resource.path}"
  description = "URL for invoking the spend-credits endpoint"
}

output "html_to_url_api_url" {
  value       = "${aws_api_gateway_stage.api_stage.invoke_url}${aws_api_gateway_resource.html_to_url_resource.path}"
  description = "URL for invoking the html-to-url endpoint"
}
