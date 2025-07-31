resource "aws_cloudwatch_log_group" "lambda_log_groups" {
  for_each = local.all_lambda_functions

  name              = "/aws/lambda/${each.value.function_name}"
  retention_in_days = 14

  # This ensures the log group exists before we create filters
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_cloudwatch_log_metric_filter" "lambda_error_filters" {
  for_each = local.all_lambda_functions

  name           = "${each.value.function_name}-error-filter"
  log_group_name = aws_cloudwatch_log_group.lambda_log_groups[each.key].name
  pattern        = "ERROR"

  metric_transformation {
    name      = "LambdaErrors-${each.value.function_name}"
    namespace = "CustomLambda"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "lambda_log_error_alarms" {
  for_each = local.all_lambda_functions

  alarm_name          = "${each.value.function_name}-log-errors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = "1"
  metric_name         = "LambdaErrors-${each.value.function_name}"
  namespace           = "CustomLambda"
  period              = "60"
  statistic           = "Sum"
  threshold           = "1"
  alarm_description   = "This metric monitors for ERROR/FATAL messages in the ${each.value.function_name} Lambda function logs."

  alarm_actions = [aws_sns_topic.error_notifications.arn]
}
