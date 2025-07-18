aws lambda create-function --region us-east-2 --function-name transcribe \
   --package-type Image  \
   --code ImageUri=006826332261.dkr.ecr.us-east-2.amazonaws.com/whisper:latest   \
   --role  arn:aws:iam::006826332261:role/service-role/lambdas3ddb
