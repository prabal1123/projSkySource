import requests
from django.conf import settings

def send_whatsapp_message(to_number, message_text):
    url = f"https://graph.facebook.com/v20.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": message_text},
    }
    response = requests.post(url, headers=headers, json=payload)

    if response.status_code != 200:
        print(f"WhatsApp send failed ({response.status_code}): {response.json()}")

    return response.status_code, response.json()

def send_whatsapp_otp(to_number, otp):
    """
    Sends a login OTP via an approved WhatsApp Authentication template.
    Unlike send_whatsapp_message(), this canNOT send free-text — Meta
    requires business-initiated messages like OTPs to use a pre-approved
    template, regardless of whether the user has messaged you recently.
    """
    url = f"https://graph.facebook.com/v20.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "template",
        "template": {
            "name": "login_otp",  # must exactly match the approved template name
            "language": {"code": "en"},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": otp}],
                },
                {
                    "type": "button",
                    "sub_type": "url",
                    "index": "0",
                    "parameters": [{"type": "text", "text": otp}],
                },
            ],
        },
    }
    response = requests.post(url, headers=headers, json=payload)

    if response.status_code != 200:
        print(f"WhatsApp OTP send failed ({response.status_code}): {response.json()}")

    return response.status_code, response.json()
