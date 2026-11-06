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
from contextlib import asynccontextmanager, nullcontext

from fastapi import FastAPI, Header, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from mcp.server.mcpserver import MCPServer
from sqlalchemy.ext.asyncio import AsyncEngine

from orviqo import worker
from orviqo.adapters.db import make_engine
from orviqo.adapters.debtors import InMemoryDebtorStore
from orviqo.adapters.processed import ProcessedMessageStore
from orviqo.adapters.sql_audit import SqlAlchemyAuditLog
from orviqo.adapters.sql_chases import SqlAlchemyChaseStore
from orviqo.adapters.sql_debtors import SqlAlchemyDebtorStore
from orviqo.adapters.sql_ledger import SqlAlchemyLedger
from orviqo.adapters.sql_oauth import SqlAlchemyOAuthStore
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
from orviqo.mcp.hosted import build_hosted_server, hosted_app
from orviqo.mcp.oauth import OrviqoOAuthProvider
from orviqo.mcp.server import Stores
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
    engine = app.state.engine
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
    app.state.inbox = DebtorInboxService(
        debtor_store,
        whatsapp,
        ledger=ledger,
        chases=SqlAlchemyChaseStore(engine),
        audit=audit,
    )
    app.state.processed = SqlAlchemyProcessedMessageStore(engine)
    app.state.whatsapp = whatsapp
    mcp = app.state.mcp
    try:
        # A mounted app's lifespan never runs, so the hosted MCP server's runs here.
        async with mcp.session_manager.run() if mcp else nullcontext():
            yield
    finally:
        await whatsapp.aclose()
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Orviqo — receivables agent", lifespan=lifespan)
    app.include_router(site_router)
    # Lazy: nothing connects until the first query, so building it here is free.
    app.state.engine = make_engine(settings.database_url)
    app.state.mcp, app.state.oauth = None, None
    if settings.orviqo_public_url:
        app.state.mcp, app.state.oauth = _hosted_mcp(app.state.engine)

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
                # Meta signs with the app secret: a mismatch here means WHATSAPP_APP_SECRET
                # differs from the Meta app's (or the caller isn't Meta).
                log.warning(
                    "webhook rejected: X-Hub-Signature-256 %s", "bad" if signature else "missing"
                )
                return Response(status_code=401)
        elif not isinstance(whatsapp, LoggingWhatsAppClient):
            # Real credentials but no way to verify callers: refuse, never fail open.
            log.error("WHATSAPP_APP_SECRET is not set; refusing unverified webhook")
            return Response("Webhook verification is not configured.", status_code=503)
        oauth: OrviqoOAuthProvider | None = request.app.state.oauth
        payload = json.loads(body)
        messages = list(iter_text_messages(payload))
        log.info("webhook: %d text message(s)", len(messages))  # never the content
        for msg in messages:
            if await processed.seen(msg.id):
                continue  # redelivered webhook — already handled
            # "LINK ABCD-2345" from the hosted MCP sign-in page: the sender's number
            # proves which ledger is theirs. No intake, so no LLM call.
            link_reply = await oauth.link_from_message(msg.sender, msg.text) if oauth else None
            # A known debtor's reply (e.g. STOP) is handled here, not as owner intake.
            debtor_reply = None
            if link_reply is None:
                debtor_reply = await inbox.handle_if_debtor(msg.sender, msg.text)
            if link_reply is not None:
                # Already linked: a failed confirmation mustn't make WhatsApp redeliver.
                try:
                    await whatsapp.send_text(msg.sender, link_reply)
                except Exception:
                    log.exception("couldn't send the link confirmation")
            elif debtor_reply is not None:
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

    if app.state.mcp is not None:
        # Last, at the root: OAuth endpoints (/.well-known/*, /authorize, /token,
        # /register, /revoke), /mcp and the sign-in pages. Routes above win first.
        app.mount("/", hosted_app(app.state.mcp, settings.orviqo_public_url))
    return app


def _hosted_mcp(engine: AsyncEngine) -> tuple[MCPServer, OrviqoOAuthProvider]:
    stores = Stores(
        ledger=SqlAlchemyLedger(engine),
        payments=SqlAlchemyPaymentStore(engine),
        debtors=SqlAlchemyDebtorStore(engine),
        audit=SqlAlchemyAuditLog(engine),
    )
    return build_hosted_server(
        stores,
        SqlAlchemyOAuthStore(engine),
        public_url=settings.orviqo_public_url,
        display_number=settings.whatsapp_display_number,
        demo_daily_limit=settings.mcp_demo_daily_limit,
    )


app = create_app()
