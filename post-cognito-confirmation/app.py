from __future__ import print_function
import time
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from pprint import pprint
import os

def handler(event, context):
    print(event)

    user_attributes = event['request']['userAttributes']
    email = user_attributes.get('email')
    username = event['userName']

    if not email:
        print("Email not found in user attributes")
        return event

    # Configure API key authorization: api-key
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key['api-key'] = os.environ['BREVO_API_KEY']

    # create an instance of the API class
    api_instance = sib_api_v3_sdk.ContactsApi(sib_api_v3_sdk.ApiClient(configuration))
    create_contact = sib_api_v3_sdk.CreateContact(
      email=email,
      attributes={"USERNAME": username},
      list_ids=[16],
      update_enabled=False
    ) # CreateContact | Values to create a contact

    try:
        # Create a contact
        api_response = api_instance.create_contact(create_contact)
        pprint(api_response)
    except ApiException as e:
        print("Exception when calling ContactsApi->create_contact: %s\n" % e)


    return event
