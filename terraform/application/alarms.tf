locals {
  all_lambda_functions = {
    "start_summary_chain"       = aws_lambda_function.start_summary_chain,
    "post_cognito_confirmation" = aws_lambda_function.post_cognito_confirmation,
    "init_credits"              = aws_lambda_function.init_credits,
    "refund_credits"            = aws_lambda_function.refund_credits,
    "segment_audio"             = aws_lambda_function.segment_audio,
    "transcribe"                = aws_lambda_function.transcribe,
    "combine_text_segments"     = aws_lambda_function.combine_text_segments,
    "final_summary"             = aws_lambda_function.final_summary,
    "revise_summary"            = aws_lambda_function.revise_summary,
    "session_chat"              = aws_lambda_function.session_chat,
    "create_campaign_index"     = aws_lambda_function.create_campaign_index,
    "stripe_webhook"            = aws_lambda_function.stripe_webhook,
    "campaign_chat"             = aws_lambda_function.campaign_chat,
    "spend_credits"             = aws_lambda_function.spend_credits,
    "html_to_url"               = aws_lambda_function.html_to_url
  }
}

resource "aws_cloudwatch_metric_alarm" "lambda_error_alarms" {
  for_each = local.all_lambda_functions

  alarm_name          = "${each.value.function_name}-errors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = "1"
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = "60"
  statistic           = "Sum"
  threshold           = "1"
  alarm_description   = "This metric monitors for errors in the ${each.value.function_name} Lambda function."

  dimensions = {
    FunctionName = each.value.function_name
  }

  alarm_actions = [aws_sns_topic.error_notifications.arn]
}
