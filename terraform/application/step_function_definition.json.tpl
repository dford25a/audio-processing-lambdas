{
  "Comment": "A state machine that processes audio files.",
  "StartAt": "SegmentAudio",
  "States": {
    "SegmentAudio": {
      "Type": "Task",
      "Resource": "${segment_audio_arn}",
      "ResultPath": "$.segments",
      "Next": "CheckSegmentOutputType",
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "ResultPath": "$.error",
          "Next": "RefundCredits"
        }
      ]
    },
    "CheckSegmentOutputType": {
      "Type": "Choice",
      "Choices": [
        {
          "Variable": "$.segments.segments[0]",
          "IsPresent": true,
          "Next": "Transcribe"
        }
      ],
      "Default": "RewriteSegmentsForShortFile"
    },
    "RewriteSegmentsForShortFile": {
      "Type": "Pass",
      "Parameters": {
        "segments": [
          {
            "audio_filename.$": "$.audio_filename"
          }
        ],
        "bucket.$": "$.bucket",
        "userTransactionsTransactionsId.$": "$.userTransactionsTransactionsId",
        "sessionId.$": "$.sessionId",
        "creditsToRefund.$": "$.creditsToRefund"
      },
      "ResultPath": "$.segments",
      "Next": "Transcribe"
    },
    "Transcribe": {
      "Type": "Map",
      "ItemsPath": "$.segments.segments",
      "Parameters": {
        "bucket.$": "$.bucket",
        "audio_filename.$": "$$.Map.Item.Value",
        "userTransactionsTransactionsId.$": "$.userTransactionsTransactionsId",
        "sessionId.$": "$.sessionId",
        "creditsToRefund.$": "$.creditsToRefund"
      },
      "Iterator": {
        "StartAt": "TranscribeSegment",
        "States": {
          "TranscribeSegment": {
            "Type": "Task",
            "Resource": "${transcribe_arn}",
            "ResultSelector": {
              "key.$": "$.key"
            },
            "End": true
          }
        }
      },
      "ResultPath": "$.transcribed_segments",
      "Next": "CombineTextSegments",
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "ResultPath": "$.error",
          "Next": "RefundCredits"
        }
      ]
    },
    "CombineTextSegments": {
      "Type": "Task",
      "Resource": "${combine_text_segments_arn}",
      "Next": "FinalSummaryAndCampaignIndex",
      "ResultPath": "$.combined_transcript",
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "ResultPath": "$.error",
          "Next": "RefundCredits"
        }
      ]
    },
    "FinalSummaryAndCampaignIndex": {
      "Type": "Parallel",
      "Branches": [
        {
          "StartAt": "FinalSummary",
          "States": {
            "FinalSummary": {
              "Type": "Task",
              "Resource": "${final_summary_arn}",
              "Parameters": {
                "bucket.$": "$.bucket",
                "key.$": "$.combined_transcript.key",
                "userTransactionsTransactionsId.$": "$.userTransactionsTransactionsId",
                "sessionId.$": "$.sessionId",
                "creditsToRefund.$": "$.creditsToRefund"
              },
              "End": true
            }
          }
        },
        {
          "StartAt": "CreateCampaignIndex",
          "States": {
            "CreateCampaignIndex": {
              "Type": "Task",
              "Resource": "${create_campaign_index_arn}",
              "Parameters": {
                "userTransactionsTransactionsId.$": "$.userTransactionsTransactionsId",
                "sessionId.$": "$.sessionId",
                "creditsToRefund.$": "$.creditsToRefund"
              },
              "End": true
            }
          }
        }
      ],
      "Next": "Done",
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "ResultPath": "$.error",
          "Next": "RefundCredits"
        }
      ]
    },
    "RefundCredits": {
      "Type": "Task",
      "Resource": "${refund_credits_arn}",
      "Parameters": {
        "Cause.$": "$.error.Cause",
        "Payload.$": "$",
        "userTransactionsTransactionsId.$": "$.userTransactionsTransactionsId",
        "sessionId.$": "$.sessionId",
        "creditsToRefund.$": "$.creditsToRefund"
      },
      "End": true
    },
    "Done": {
      "Type": "Succeed"
    }
  }
}
