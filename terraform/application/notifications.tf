resource "aws_sns_topic" "error_notifications" {
  name = "error-notifications-${var.environment}"
}

resource "aws_ses_email_identity" "error_email" {
  email = "dford25a@gmail.com"
}

resource "aws_iam_role" "error_notifier_lambda_role" {
  name = "error-notifier-lambda-role-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Action = "sts:AssumeRole",
        Effect = "Allow",
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

data "aws_iam_policy_document" "error_notifier_lambda_policy_doc" {
  statement {
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = ["arn:aws:logs:*:*:*"]
  }

  statement {
    effect = "Allow"
    actions = [
      "ses:SendEmail",
      "ses:SendRawEmail"
    ]
    resources = [aws_ses_email_identity.error_email.arn]
  }
}

resource "aws_iam_policy" "error_notifier_lambda_policy" {
  name   = "error-notifier-lambda-policy-${var.environment}"
  policy = data.aws_iam_policy_document.error_notifier_lambda_policy_doc.json
}

resource "aws_iam_role_policy_attachment" "error_notifier_lambda_policy_attachment" {
  role       = aws_iam_role.error_notifier_lambda_role.name
  policy_arn = aws_iam_policy.error_notifier_lambda_policy.arn
}

resource "aws_lambda_function" "error_notifier" {
  function_name = "error-notifier-${var.environment}"
  role          = aws_iam_role.error_notifier_lambda_role.arn
  handler       = "app.lambda_handler"
  runtime       = "python3.9"
  filename      = "error-notifier.zip"
  source_code_hash = filebase64sha256("error-notifier.zip")

  environment {
    variables = {
      DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1400496352105857064/NE3k-euRTeHcnkQwLQlQGqHjFPd0izQYRulCNIMsgsgYXlqyL8cYYcx24r7HfJBJa4_X"
      SENDER_EMAIL_ADDRESS = aws_ses_email_identity.error_email.email
    }
  }
}

resource "aws_sns_topic_subscription" "error_notifier_subscription" {
  topic_arn = aws_sns_topic.error_notifications.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.error_notifier.arn
}

resource "aws_lambda_permission" "allow_sns_to_call_error_notifier" {
  statement_id  = "AllowSNSToCallErrorNotifier"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.error_notifier.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.error_notifications.arn
}
