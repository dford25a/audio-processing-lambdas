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
  
  # Trigger final-summary function when combined text is uploaded to segmentedSummaries
  lambda_function {
    lambda_function_arn = aws_lambda_function.final_summary.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "public/segmentedSummaries/"
    id                  = "final-summary-trigger"
  }
  
  depends_on = [
    aws_lambda_permission.allow_bucket_transcribe,
    aws_lambda_permission.allow_bucket_combine_text_segments,
    aws_lambda_permission.allow_bucket_final_summary
  ]
}