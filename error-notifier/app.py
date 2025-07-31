import boto3
import json
import os
import requests

ses_client = boto3.client('ses')
DISCORD_WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK_URL')
SENDER_EMAIL_ADDRESS = os.environ.get('SENDER_EMAIL_ADDRESS')

def lambda_handler(event, context):
    for record in event['Records']:
        sns_message_str = record['Sns']['Message']
        sns_message = json.loads(sns_message_str)

        # Default subject and bodies
        subject = "New SNS Notification"
        body_html = f"<pre>{json.dumps(sns_message, indent=2)}</pre>"
        discord_message = {"content": f"```json\n{json.dumps(sns_message, indent=2)}\n```"}

        # Check if the message is from a CloudWatch Alarm
        if sns_message.get('AlarmName'):
            alarm_name = sns_message['AlarmName']
            new_state_reason = sns_message['NewStateReason']
            metric_name = sns_message['Trigger']['MetricName']
            # Extract function name from alarm name since dimensions were removed
            function_name = alarm_name.replace('-log-errors', '') if '-log-errors' in alarm_name else 'N/A'

            subject = f"ALARM: \"{alarm_name}\" in {sns_message['AWSAccountId']}"
            
            body_html = f"""
            <html>
            <head></head>
            <body>
              <h1>CloudWatch Alarm: {alarm_name}</h1>
              <p><b>Function Name:</b> {function_name}</p>
              <p><b>Reason:</b> {new_state_reason}</p>
              <p><b>Metric:</b> {metric_name}</p>
              <p><b>Account ID:</b> {sns_message['AWSAccountId']}</p>
              <p><b>Region:</b> {sns_message['Region']}</p>
            </body>
            </html>
            """

            discord_message = {
                "content": f"🔥 **CloudWatch Alarm Triggered** 🔥\n"
                           f"**Alarm Name:** `{alarm_name}`\n"
                           f"**Function Name:** `{function_name}`\n"
                           f"**Reason:** {new_state_reason}"
            }

        # Send Email
        if SENDER_EMAIL_ADDRESS:
            try:
                ses_client.send_email(
                    Source=SENDER_EMAIL_ADDRESS,
                    Destination={'ToAddresses': [SENDER_EMAIL_ADDRESS]},
                    Message={
                        'Subject': {'Data': subject},
                        'Body': {'Html': {'Data': body_html}}
                    }
                )
            except Exception as e:
                print(f"Error sending email: {e}")

        # Send Discord Notification
        if DISCORD_WEBHOOK_URL:
            try:
                requests.post(DISCORD_WEBHOOK_URL, json=discord_message)
            except Exception as e:
                print(f"Error sending Discord notification: {e}")

    return {
        'statusCode': 200,
        'body': json.dumps('Notifications processed successfully!')
    }
