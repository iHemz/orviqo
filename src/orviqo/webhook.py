"""FastAPI WhatsApp webhook.

Week 1: the verification handshake is implemented; the inbound-message handler
parses text into an invoice and stores it. Sending the reply back over the
WhatsApp Cloud API is stubbed (logged) — wire it in Week 2 once you have
WhatsApp credentials.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Query, Request, Response

from .agents.intake import parse_message
from .config import settings
from .store import add_invoice

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("orviqo.webhook")

app = FastAPI(title="Orviqo — receivables agent")


@app.get("/webhook")
def verify(
    mode: str = Query("", alias="hub.mode"),
    token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
) -> Response:
    """WhatsApp Cloud API verification handshake."""
    if mode == "subscribe" and token == settings.whatsapp_verify_token:
        return Response(content=challenge, media_type="text/plain")
    return Response(status_code=403)


@app.post("/webhook")
async def inbound(request: Request) -> dict:
    """Handle an inbound WhatsApp message: parse -> store -> (stub) reply."""
    payload = await request.json()
    for wa_from, text in _iter_text_messages(payload):
        parsed = await parse_message(text)
        reply = _handle(wa_from, parsed)
        # Week 2: send `reply` back via the WhatsApp Cloud API.
        log.info("would reply to %s: %s", wa_from, reply)
    return {"status": "ok"}


def _handle(wa_from: str, parsed) -> str:
    """Apply the rigor gate: only record when confident, else ask."""
    if parsed.confidence < 0.9 or parsed.clarify:
        return parsed.clarify or "Sorry, I didn't fully get that — can you rephrase?"
    invoice = add_invoice(parsed, business_id=wa_from)
    due = invoice.due_date.isoformat() if invoice.due_date else "no due date"
    return (
        f"Noted: {invoice.debtor_name} owes ₦{invoice.amount_ngn:,} "
        f"for {invoice.item or 'unspecified'} ({due}). [#{invoice.id}]"
    )


def _iter_text_messages(payload: dict):
    """Yield (from, text) pairs from a WhatsApp Cloud API webhook payload."""
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []):
                if msg.get("type") == "text":
                    yield msg.get("from", ""), msg["text"]["body"]
