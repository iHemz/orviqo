"""FastAPI WhatsApp webhook — the composition root for the HTTP entry point.

The durable ledger needs an async engine with a real lifecycle, so wiring happens
in a lifespan handler (open engine + ensure schema on startup, dispose on
shutdown) rather than at import. Run with uvicorn factory mode:

    uvicorn --factory orviqo.api.webhook:create_app --reload
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request, Response

from orviqo.adapters.db import make_engine
from orviqo.adapters.sql_audit import SqlAlchemyAuditLog
from orviqo.adapters.sql_debtors import SqlAlchemyDebtorStore
from orviqo.adapters.sql_ledger import SqlAlchemyLedger
from orviqo.adapters.sql_payments import SqlAlchemyPaymentStore
from orviqo.adapters.whatsapp import (
    WhatsAppClient,
    iter_text_messages,
    make_whatsapp_client,
)
from orviqo.agents.intake import PydanticAIIntakeAgent
from orviqo.config import bootstrap, settings
from orviqo.services.debtor_inbox import DebtorInboxService
from orviqo.services.intake_service import IntakeService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    bootstrap()  # fail fast on a missing key; export it for Pydantic AI
    engine = make_engine(settings.database_url)
    # Schema is managed by Alembic — run `uv run alembic upgrade head` before starting.
    debtor_store = SqlAlchemyDebtorStore(engine)
    whatsapp = make_whatsapp_client(settings)
    app.state.service = IntakeService(
        agent=PydanticAIIntakeAgent(),
        ledger=SqlAlchemyLedger(engine),
        audit=SqlAlchemyAuditLog(engine),
        payments=SqlAlchemyPaymentStore(engine),
        debtors=debtor_store,
        confidence_threshold=settings.intake_confidence_threshold,
    )
    app.state.inbox = DebtorInboxService(debtor_store, whatsapp)
    app.state.whatsapp = whatsapp
    try:
        yield
    finally:
        await whatsapp.aclose()
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Orviqo — receivables agent", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict:
        """Liveness check for the platform load balancer (Fly)."""
        return {"status": "ok"}

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
        service: IntakeService = request.app.state.service
        inbox: DebtorInboxService = request.app.state.inbox
        whatsapp: WhatsAppClient = request.app.state.whatsapp
        payload = await request.json()
        for sender, text in iter_text_messages(payload):
            # A known debtor's reply (e.g. STOP) is handled here, not as owner intake.
            debtor_reply = await inbox.handle_if_debtor(sender, text)
            if debtor_reply is not None:
                await whatsapp.send_text(sender, debtor_reply)
                continue
            reply = await service.handle_message(sender, text)
            await whatsapp.send_text(sender, reply.text)
        return {"status": "ok"}

    return app
