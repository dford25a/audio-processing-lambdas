# The S3 triggers and SNS topic are no longer needed, as the Step Function will handle the workflow.

# Data source to get the existing user pool
data "aws_cognito_user_pool" "existing" {
  user_pool_id = var.environment == "prod" ? "us-east-2_2sxvJnReu" : "us-east-2_N5trdtp4e"
}

# Grant Cognito permission to invoke the Lambda function
resource "aws_lambda_permission" "cognito_invoke_init_credits" {
  statement_id  = "AllowExecutionFromCognito"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.init_credits.function_name
  principal     = "cognito-idp.amazonaws.com"
  source_arn    = data.aws_cognito_user_pool.existing.arn
}

# Configure the Lambda trigger on the existing User Pool using AWS CLI
resource "null_resource" "configure_cognito_trigger" {
  # This will run whenever the Lambda function changes
  triggers = {
    lambda_function_arn = aws_lambda_function.init_credits.arn
  }

  provisioner "local-exec" {
    command = "echo 'MANUAL STEP REQUIRED: Add post-confirmation Lambda trigger to Cognito User Pool ${data.aws_cognito_user_pool.existing.id} with Lambda ARN: ${aws_lambda_function.init_credits.arn}'"
  }

  depends_on = [
    aws_lambda_function.init_credits,
    aws_lambda_permission.cognito_invoke_init_credits
  ]
}
