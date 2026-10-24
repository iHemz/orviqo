"""FastAPI app: the WhatsApp webhook, the public site, and the cron trigger.

This is the composition root for the HTTP entry point. The durable ledger needs
an async engine with a real lifecycle, so wiring happens in a lifespan handler
(open engine on startup, dispose on shutdown) rather than at import. Run locally
with uvicorn factory mode:

    uvicorn --factory orviqo.api.webhook:create_app --reload

``app`` (bottom) is the module-level instance a serverless host imports (Vercel
looks for ``app`` at the entrypoint set in pyproject ``[tool.vercel]``).
"""

from __future__ import annotations

import json
import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from orviqo import worker
from orviqo.adapters.db import make_engine
from orviqo.adapters.debtors import InMemoryDebtorStore
from orviqo.adapters.processed import ProcessedMessageStore
from orviqo.adapters.sql_audit import SqlAlchemyAuditLog
from orviqo.adapters.sql_debtors import SqlAlchemyDebtorStore
from orviqo.adapters.sql_ledger import SqlAlchemyLedger
from orviqo.adapters.sql_payments import SqlAlchemyPaymentStore
from orviqo.adapters.sql_processed import SqlAlchemyProcessedMessageStore
from orviqo.adapters.whatsapp import (
    LoggingWhatsAppClient,
    WhatsAppClient,
    iter_text_messages,
    make_whatsapp_client,
    valid_signature,
)
from orviqo.agents.intake import PydanticAIIntakeAgent
from orviqo.api.site import router as site_router
from orviqo.config import bootstrap, settings
from orviqo.domain.entry import whatsapp_link
from orviqo.services.debtor_inbox import DebtorInboxService
from orviqo.services.demo_service import DemoService
from orviqo.services.intake_service import IntakeService

log = logging.getLogger("orviqo.webhook")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    bootstrap()  # fail fast on a missing key; export it for Pydantic AI
    # Our INFO lines (e.g. which model answered) belong in the platform's logs too.
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("orviqo").setLevel(logging.INFO)
    engine = make_engine(settings.database_url)
    # Schema is managed by Alembic — run `uv run alembic upgrade head` before starting.
    debtor_store = SqlAlchemyDebtorStore(engine)
    whatsapp = make_whatsapp_client(settings)
    agent = PydanticAIIntakeAgent()
    ledger = SqlAlchemyLedger(engine)
    audit = SqlAlchemyAuditLog(engine)
    payments = SqlAlchemyPaymentStore(engine)
    app.state.service = IntakeService(
        agent=agent,
        ledger=ledger,
        audit=audit,
        payments=payments,
        debtors=debtor_store,
        confidence_threshold=settings.intake_confidence_threshold,
    )
    # The web demo runs the same intake, except a debtor number typed into it is
    # held in memory only: never stored, so never chased or routed as a real debtor.
    app.state.demo = DemoService(
        intake=IntakeService(
            agent=agent,
            ledger=ledger,
            audit=audit,
            payments=payments,
            debtors=InMemoryDebtorStore(),
            confidence_threshold=settings.intake_confidence_threshold,
        ),
        audit=audit,
        session_limit=settings.demo_session_limit,
        daily_limit=settings.demo_daily_limit,
    )
    app.state.inbox = DebtorInboxService(debtor_store, whatsapp)
    app.state.processed = SqlAlchemyProcessedMessageStore(engine)
    app.state.whatsapp = whatsapp
    try:
        yield
    finally:
        await whatsapp.aclose()
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Orviqo — receivables agent", lifespan=lifespan)
    app.include_router(site_router)

    @app.get("/health")
    def health() -> dict:
        """Liveness check for the platform's health checks."""
        return {"status": "ok"}

    @app.get("/cron/collections")
    async def collections(authorization: str = Header("")) -> Response:
        """One collections pass (owner digests + debtor chases), for a daily scheduler.

        Vercel Cron calls this with ``Authorization: Bearer <CRON_SECRET>``; anything
        else is refused, so the public can't trigger WhatsApp sends.
        """
        if not settings.cron_secret:
            return Response("Cron is not configured.", status_code=503)
        if not secrets.compare_digest(authorization, f"Bearer {settings.cron_secret}"):
            return Response(status_code=401)
        reminded, chased = await worker.run_once()
        return Response(f"sent {reminded} digest(s), {chased} chase(s)", media_type="text/plain")

    @app.get("/start")
    def start() -> Response:
        """The shareable entry point: redirect to a WhatsApp chat with Orviqo.

        Share this URL (and its QR code) rather than a raw wa.me link, so the
        business number can change without reprinting anything.
        """
        if not settings.whatsapp_display_number:
            return Response("Orviqo isn't open for new chats yet.", status_code=503)
        return RedirectResponse(whatsapp_link(settings.whatsapp_display_number), 302)

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
    async def inbound(request: Request) -> Response:
        service: IntakeService = request.app.state.service
        inbox: DebtorInboxService = request.app.state.inbox
        processed: ProcessedMessageStore = request.app.state.processed
        whatsapp: WhatsAppClient = request.app.state.whatsapp
        body = await request.body()
        # Anyone can POST here, and each message costs an LLM call and may send a
        # WhatsApp reply to whatever number the payload claims, so only Meta's
        # signed callbacks get through.
        if settings.whatsapp_app_secret:
            signature = request.headers.get("X-Hub-Signature-256", "")
            if not valid_signature(settings.whatsapp_app_secret, body, signature):
                return Response(status_code=401)
        elif not isinstance(whatsapp, LoggingWhatsAppClient):
            # Real credentials but no way to verify callers: refuse, never fail open.
            log.error("WHATSAPP_APP_SECRET is not set; refusing unverified webhook")
            return Response("Webhook verification is not configured.", status_code=503)
        payload = json.loads(body)
        for msg in iter_text_messages(payload):
            if await processed.seen(msg.id):
                continue  # redelivered webhook — already handled
            # A known debtor's reply (e.g. STOP) is handled here, not as owner intake.
            debtor_reply = await inbox.handle_if_debtor(msg.sender, msg.text)
            if debtor_reply is not None:
                await whatsapp.send_text(msg.sender, debtor_reply)
            else:
                reply = await service.handle_message(msg.sender, msg.text)
                if reply.welcome:
                    await whatsapp.send_text(msg.sender, reply.welcome)
                await whatsapp.send_text(msg.sender, reply.text)
            # Mark only after a clean handle: a failure above leaves it unmarked so
            # WhatsApp's retry reprocesses it, rather than dropping the message.
            await processed.mark(msg.id)
        return JSONResponse({"status": "ok"})

    return app


app = create_app()
