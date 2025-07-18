resource "aws_iam_role" "step_function_exec_role" {
  name = "step-function-exec-role-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Action = "sts:AssumeRole",
        Effect = "Allow",
        Principal = {
          Service = "states.amazonaws.com"
        }
      }
    ]
  })
}

data "aws_iam_policy_document" "step_function_policy_doc" {
  statement {
    effect = "Allow"
    actions = [
      "lambda:InvokeFunction"
    ]
    resources = [
      aws_lambda_function.segment_audio.arn,
      aws_lambda_function.transcribe.arn,
      aws_lambda_function.combine_text_segments.arn,
      aws_lambda_function.final_summary.arn,
      aws_lambda_function.create_campaign_index.arn,
      aws_lambda_function.refund_credits.arn
    ]
  }
}

resource "aws_iam_policy" "step_function_policy" {
  name        = "step-function-policy-${var.environment}"
  description = "IAM policy for the Step Function"
  policy      = data.aws_iam_policy_document.step_function_policy_doc.json
}

resource "aws_iam_role_policy_attachment" "step_function_policy_attachment" {
  role       = aws_iam_role.step_function_exec_role.name
  policy_arn = aws_iam_policy.step_function_policy.arn
}

resource "aws_sfn_state_machine" "audio_processing_state_machine" {
  name     = "audio-processing-state-machine-${var.environment}"
  role_arn = aws_iam_role.step_function_exec_role.arn

  definition = templatefile("${path.module}/step_function_definition.json.tpl", {
    segment_audio_arn = aws_lambda_function.segment_audio.arn,
    transcribe_arn = aws_lambda_function.transcribe.arn,
    combine_text_segments_arn = aws_lambda_function.combine_text_segments.arn,
    final_summary_arn = aws_lambda_function.final_summary.arn,
    create_campaign_index_arn = aws_lambda_function.create_campaign_index.arn,
    refund_credits_arn = aws_lambda_function.refund_credits.arn
  })
}
