# NEW: SNS Topic to fan-out S3 events to multiple Lambdas
resource "aws_sns_topic" "summary_events_topic" {
  name = "s3-summary-events-topic-${var.environment}"
}

# NEW: Policy to allow S3 to publish events to the SNS Topic
resource "aws_sns_topic_policy" "allow_s3_to_publish" {
  arn    = aws_sns_topic.summary_events_topic.arn
  policy = data.aws_iam_policy_document.sns_topic_policy.json
}

data "aws_iam_policy_document" "sns_topic_policy" {
  statement {
    effect  = "Allow"
    actions = ["SNS:Publish"]
    principals {
      type        = "Service"
      identifiers = ["s3.amazonaws.com"]
    }
    resources = [aws_sns_topic.summary_events_topic.arn]
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = [data.aws_s3_bucket.current_bucket.arn]
    }
  }
}

# NEW: SNS subscription for the final_summary Lambda
resource "aws_sns_topic_subscription" "final_summary_subscription" {
  topic_arn = aws_sns_topic.summary_events_topic.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.final_summary.arn
}

# NEW: SNS subscription for the create_campaign_index Lambda
resource "aws_sns_topic_subscription" "create_campaign_index_subscription" {
  topic_arn = aws_sns_topic.summary_events_topic.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.create_campaign_index.arn
}


# S3 event notification - combined in a single resource
resource "aws_s3_bucket_notification" "bucket_notifications" {
  bucket = data.aws_s3_bucket.current_bucket.id
  
  # Trigger transcribe function when segments are uploaded to audioUploadsSegmented
  lambda_function {
    lambda_function_arn = aws_lambda_function.transcribe.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "public/audioUploadsSegmented/"
    id                  = "transcribe-trigger"
  }
  
  # Trigger combine-text-segments function when transcriptions are uploaded to transcriptedAudio
  lambda_function {
    lambda_function_arn = aws_lambda_function.combine_text_segments.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "public/transcriptedAudio/"
    id                  = "combine-text-segments-trigger"
  }
  
  # MODIFIED: This now sends a single event to an SNS topic for the overlapping prefix
  topic {
    topic_arn     = aws_sns_topic.summary_events_topic.arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "public/segmentedSummaries/"
    id            = "summary-events-sns-trigger"
  }
  
  # This depends_on ensures the S3 notification is created AFTER the permissions for the direct lambda invocations are set.
  # The SNS permission is handled by the aws_sns_topic_policy.
  depends_on = [
    aws_lambda_permission.allow_bucket_to_call_transcribe,
    aws_lambda_permission.allow_bucket_to_call_combine_text
  ]
}