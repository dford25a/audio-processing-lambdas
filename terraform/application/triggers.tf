# The S3 triggers and SNS topic are no longer needed, as the Step Function will handle the workflow.

resource "aws_lambda_event_source_mapping" "init_credits_trigger" {
  event_source_arn = var.user_transactions_table_stream_arn
  function_name    = aws_lambda_function.init_credits.arn
  starting_position = "LATEST"
}
