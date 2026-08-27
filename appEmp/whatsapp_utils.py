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
