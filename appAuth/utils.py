import os
from azure.communication.email import EmailClient

def send_azure_otp(target_email, otp_code):
    connection_string = os.getenv("AZURE_EMAIL_CONNECTION_STRING")
    try:
        client = EmailClient.from_connection_string(connection_string)
        message = {
            "senderAddress": os.getenv("AZURE_EMAIL_SENDER"),
            "recipients": {"to": [{"address": target_email}]},
            "content": {
                "subject": "Your SkySource HRMS Login Code",
                "plainText": f"Your OTP is {otp_code}. It expires in 5 minutes.",
                "html": f"<html><body><h1>Your code is {otp_code}</h1><p>Expires in 5 minutes.</p></body></html>",
            },
        }
        poller = client.begin_send(message)
        poller.result()
        return True
    except Exception as ex:
        print(f"Error sending email: {ex}")
        return False