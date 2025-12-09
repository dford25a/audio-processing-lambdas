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
      "Next": "GenerateNarrativeSummary",
      "ResultPath": "$.combined_transcript",
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "ResultPath": "$.error",
          "Next": "RefundCredits"
        }
      ]
    },
    "GenerateNarrativeSummary": {
      "Type": "Task",
      "Resource": "${generate_narrative_summary_arn}",
      "Parameters": {
        "bucket.$": "$.bucket",
        "key.$": "$.combined_transcript.key",
        "userTransactionsTransactionsId.$": "$.userTransactionsTransactionsId",
        "sessionId.$": "$.sessionId",
        "creditsToRefund.$": "$.creditsToRefund"
      },
      "ResultPath": "$.narrativeResult",
      "Next": "SummaryProcessingParallel",
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "ResultPath": "$.error",
          "Next": "RefundCredits"
        }
      ]
    },
    "SummaryProcessingParallel": {
      "Type": "Parallel",
      "Branches": [
        {
          "StartAt": "CheckImageEnabled",
          "States": {
            "CheckImageEnabled": {
              "Type": "Choice",
              "Choices": [
                {
                  "Variable": "$.narrativeResult.imageSettings.enabled",
                  "BooleanEquals": true,
                  "Next": "GenerateSegmentImages"
                }
              ],
              "Default": "SkipImages"
            },
            "GenerateSegmentImages": {
              "Type": "Task",
              "Resource": "${generate_segment_images_arn}",
              "Parameters": {
                "bucket.$": "$.narrativeResult.bucket",
                "sessionId.$": "$.narrativeResult.sessionId",
                "narrativeSummaryS3Key.$": "$.narrativeResult.narrativeSummaryS3Key",
                "imageSettings.$": "$.narrativeResult.imageSettings",
                "sessionName.$": "$.narrativeResult.sessionName",
                "campaignId.$": "$.narrativeResult.campaignId",
                "owner.$": "$.narrativeResult.owner",
                "transcriptKey.$": "$.narrativeResult.transcriptKey",
                "generateLore.$": "$.narrativeResult.generateLore",
                "generateName.$": "$.narrativeResult.generateName",
                "entityMentions.$": "$.narrativeResult.entityMentions",
                "userTransactionsTransactionsId.$": "$.narrativeResult.userTransactionsTransactionsId",
                "creditsToRefund.$": "$.narrativeResult.creditsToRefund"
              },
              "End": true
            },
            "SkipImages": {
              "Type": "Pass",
              "Parameters": {
                "imageKeys": [],
                "primaryImage": null,
                "bucket.$": "$.narrativeResult.bucket",
                "sessionId.$": "$.narrativeResult.sessionId",
                "narrativeSummaryS3Key.$": "$.narrativeResult.narrativeSummaryS3Key",
                "sessionName.$": "$.narrativeResult.sessionName",
                "campaignId.$": "$.narrativeResult.campaignId",
                "owner.$": "$.narrativeResult.owner",
                "transcriptKey.$": "$.narrativeResult.transcriptKey",
                "generateLore.$": "$.narrativeResult.generateLore",
                "generateName.$": "$.narrativeResult.generateName",
                "entityMentions.$": "$.narrativeResult.entityMentions",
                "userTransactionsTransactionsId.$": "$.narrativeResult.userTransactionsTransactionsId",
                "creditsToRefund.$": "$.narrativeResult.creditsToRefund"
              },
              "End": true
            }
          }
        },
        {
          "StartAt": "CheckGenerateLore",
          "States": {
            "CheckGenerateLore": {
              "Type": "Choice",
              "Choices": [
                {
                  "Variable": "$.narrativeResult.generateLore",
                  "BooleanEquals": true,
                  "Next": "GenerateEntityLore"
                }
              ],
              "Default": "UpdateEntityDescriptions"
            },
            "GenerateEntityLore": {
              "Type": "Task",
              "Resource": "${generate_entity_lore_arn}",
              "Parameters": {
                "bucket.$": "$.narrativeResult.bucket",
                "sessionId.$": "$.narrativeResult.sessionId",
                "campaignId.$": "$.narrativeResult.campaignId",
                "owner.$": "$.narrativeResult.owner",
                "transcriptKey.$": "$.narrativeResult.transcriptKey",
                "narrativeSummaryS3Key.$": "$.narrativeResult.narrativeSummaryS3Key",
                "entityMentions.$": "$.narrativeResult.entityMentions",
                "generateLore.$": "$.narrativeResult.generateLore",
                "generateName.$": "$.narrativeResult.generateName",
                "sessionName.$": "$.narrativeResult.sessionName",
                "imageSettings.$": "$.narrativeResult.imageSettings",
                "userTransactionsTransactionsId.$": "$.narrativeResult.userTransactionsTransactionsId",
                "creditsToRefund.$": "$.narrativeResult.creditsToRefund"
              },
              "End": true
            },
            "UpdateEntityDescriptions": {
              "Type": "Task",
              "Resource": "${update_entity_descriptions_arn}",
              "Parameters": {
                "bucket.$": "$.narrativeResult.bucket",
                "sessionId.$": "$.narrativeResult.sessionId",
                "campaignId.$": "$.narrativeResult.campaignId",
                "owner.$": "$.narrativeResult.owner",
                "transcriptKey.$": "$.narrativeResult.transcriptKey",
                "narrativeSummaryS3Key.$": "$.narrativeResult.narrativeSummaryS3Key",
                "entityMentions.$": "$.narrativeResult.entityMentions",
                "generateLore.$": "$.narrativeResult.generateLore",
                "generateName.$": "$.narrativeResult.generateName",
                "sessionName.$": "$.narrativeResult.sessionName",
                "imageSettings.$": "$.narrativeResult.imageSettings",
                "userTransactionsTransactionsId.$": "$.narrativeResult.userTransactionsTransactionsId",
                "creditsToRefund.$": "$.narrativeResult.creditsToRefund"
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
                "bucket.$": "$.bucket",
                "key.$": "$.combined_transcript.key",
                "userTransactionsTransactionsId.$": "$.userTransactionsTransactionsId",
                "sessionId.$": "$.sessionId",
                "creditsToRefund.$": "$.creditsToRefund"
              },
              "End": true
            }
          }
        }
      ],
      "ResultPath": "$.parallelResults",
      "Next": "PersistSummaryData",
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "ResultPath": "$.error",
          "Next": "RefundCredits"
        }
      ]
    },
    "PersistSummaryData": {
      "Type": "Task",
      "Resource": "${persist_summary_data_arn}",
      "Parameters": {
        "bucket.$": "$.parallelResults[0].bucket",
        "sessionId.$": "$.parallelResults[0].sessionId",
        "narrativeSummaryS3Key.$": "$.parallelResults[0].narrativeSummaryS3Key",
        "sessionName.$": "$.parallelResults[0].sessionName",
        "campaignId.$": "$.parallelResults[0].campaignId",
        "owner.$": "$.parallelResults[0].owner",
        "imageKeys.$": "$.parallelResults[0].imageKeys",
        "primaryImage.$": "$.parallelResults[0].primaryImage",
        "generateName.$": "$.parallelResults[0].generateName",
        "entityMentions.$": "$.parallelResults[0].entityMentions",
        "userTransactionsTransactionsId.$": "$.parallelResults[0].userTransactionsTransactionsId",
        "creditsToRefund.$": "$.parallelResults[0].creditsToRefund"
      },
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
