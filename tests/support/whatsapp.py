"""Payloads shaped the way Meta actually sends them."""

import hashlib
import hmac
import json
from typing import Any

PHONE_NUMBER_ID = "109876543210987"
BUSINESS_ACCOUNT_ID = "102290129340398"


def inbound_payload(
    *,
    message_id: str = "wamid.INBOUND1",
    from_number: str = "923001234567",
    text: str = "Do you have this in medium?",
    timestamp: str = "1735689600",
    profile_name: str | None = "Ayesha",
    phone_number_id: str = PHONE_NUMBER_ID,
) -> dict[str, Any]:
    contacts = (
        [{"profile": {"name": profile_name}, "wa_id": from_number}]
        if profile_name is not None
        else []
    )

    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": BUSINESS_ACCOUNT_ID,
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550001111",
                                "phone_number_id": phone_number_id,
                            },
                            "contacts": contacts,
                            "messages": [
                                {
                                    "from": from_number,
                                    "id": message_id,
                                    "timestamp": timestamp,
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def status_payload(
    *,
    message_id: str = "wamid.OUTBOUND1",
    status: str = "delivered",
    timestamp: str = "1735689700",
    phone_number_id: str = PHONE_NUMBER_ID,
) -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": BUSINESS_ACCOUNT_ID,
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550001111",
                                "phone_number_id": phone_number_id,
                            },
                            "statuses": [
                                {
                                    "id": message_id,
                                    "status": status,
                                    "timestamp": timestamp,
                                    "recipient_id": "923001234567",
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def media_payload(phone_number_id: str = PHONE_NUMBER_ID) -> dict[str, Any]:
    """An image, which the MVP does not carry."""
    payload = inbound_payload(phone_number_id=phone_number_id)
    message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    message.pop("text")
    message["type"] = "image"
    message["image"] = {"id": "media-1", "mime_type": "image/jpeg"}

    return payload


def sign(payload: dict[str, Any], secret: str) -> tuple[bytes, str]:
    """The exact bytes Meta would send, and the header it would send them
    under."""
    body = json.dumps(payload).encode()
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    return body, f"sha256={digest}"
