"""Simulate a WhatsApp inbound message by POSTing a Cloud API payload to the webhook.

Exercises the whole pipeline — parse → rigor gate → ledger → audit → reply —
without waiting on Meta to deliver real webhooks (blocked until the app is
published). Point it at local or the deployed app.

    uv run python tools/simulate_inbound.py "Chidi owes 150k, due Friday"
    uv run python tools/simulate_inbound.py "..." --url https://orviqo.fly.dev/webhook
    uv run python tools/simulate_inbound.py "..." --from 2348164443163   # who gets the reply

Requests are signed like Meta's (``X-Hub-Signature-256``) with WHATSAPP_APP_SECRET
from the environment / ``.env``, so they pass the webhook's verification.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json

import httpx
from orviqo.config import settings


def build_payload(text: str, sender: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "0",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "0", "phone_number_id": "0"},
                            "contacts": [{"profile": {"name": "Simulated"}, "wa_id": sender}],
                            "messages": [
                                {
                                    "from": sender,
                                    "id": "wamid.SIM",
                                    "timestamp": "0",
                                    "text": {"body": text},
                                    "type": "text",
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate an inbound WhatsApp message.")
    parser.add_argument("message", help="The debt message to send.")
    parser.add_argument("--url", default="http://localhost:8000/webhook", help="Webhook URL.")
    parser.add_argument(
        "--from", dest="sender", default="2340000000000", help="Sender number (receives the reply)."
    )
    args = parser.parse_args()

    body = json.dumps(build_payload(args.message, args.sender)).encode()
    headers = {"Content-Type": "application/json"}
    if settings.whatsapp_app_secret:
        digest = hmac.new(settings.whatsapp_app_secret.encode(), body, hashlib.sha256)
        headers["X-Hub-Signature-256"] = "sha256=" + digest.hexdigest()
    response = httpx.post(args.url, content=body, headers=headers, timeout=30)
    print("HTTP", response.status_code, response.text)


if __name__ == "__main__":
    main()
