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
                "subject": "Your NumaHR Login Code",
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

def send_demo_notification(d):
    to_addr = os.getenv("CONTACT_NOTIFY_EMAIL")
    if not to_addr:
        return False
    try:
        client = EmailClient.from_connection_string(os.getenv("AZURE_EMAIL_CONNECTION_STRING"))
        name = d.name.replace("\n", " ").replace("\r", " ")
        body = (
            f"Name: {name}\n"
            f"Company: {d.company}\n"
            f"Team size: {d.team_size}\n"
            f"Phone: {d.phone}\n"
            f"Email: {d.email}\n\n"
            f"{d.message or '(no message)'}"
        )
        message = {
            "senderAddress": os.getenv("AZURE_EMAIL_SENDER"),
            "recipients": {"to": [{"address": to_addr}]},
            "replyTo": [{"address": d.email, "displayName": name}],
            "content": {
                "subject": f"NumaHr demo request: {name} ({d.company})",
                "plainText": body,
            },
        }
        client.begin_send(message).result()
        return True
    except Exception as ex:
        print(f"Error sending demo email: {ex}")
        return False