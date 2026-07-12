"""FastAPI WhatsApp webhook — the composition root for the HTTP entry point.

``create_app()`` wires the concrete adapters into the service (dependency
injection by hand — no framework magic). Run it with uvicorn's factory mode so
nothing is constructed at import time:

    uvicorn --factory orviqo.api.webhook:create_app --reload
"""

from __future__ import annotations

from fastapi import FastAPI, Query, Request, Response

from orviqo.adapters.ledger import InMemoryLedger
from orviqo.adapters.whatsapp import LoggingWhatsAppClient, iter_text_messages
from orviqo.agents.intake import PydanticAIIntakeParser
from orviqo.config import bootstrap
from orviqo.services.intake_service import IntakeService


def create_app() -> FastAPI:
    settings = bootstrap()
    service = IntakeService(
        parser=PydanticAIIntakeParser(),
        ledger=InMemoryLedger(),
        confidence_threshold=settings.intake_confidence_threshold,
    )
    whatsapp = LoggingWhatsAppClient()

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
        payload = await request.json()
        for sender, text in iter_text_messages(payload):
            reply = await service.handle_message(sender, text)
            await whatsapp.send_text(sender, reply.text)
        return {"status": "ok"}

    return app
