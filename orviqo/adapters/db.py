"""Database schema and engine — SQLAlchemy 2.0 async Core.

Deliberately Core (a ``Table``), not the ORM: the domain ``Invoice`` stays a
pure Pydantic model, and the adapter translates rows ↔ domain in one place.

The same schema runs on Postgres (prod, ``postgresql+asyncpg://``) and SQLite
(local dev / tests, ``sqlite+aiosqlite://``) — the ledger code doesn't care.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

metadata = MetaData()

# Week-2 invoices table (spec §8). customer_id / source_message_id arrive with
# the WhatsApp send + audit_log work; this is the minimum the ledger needs today.
invoices = Table(
    "invoices",
    metadata,
    Column("id", String, primary_key=True),
    Column("business_id", String, nullable=False, index=True),
    Column("debtor_name", String, nullable=False),
    Column("amount_ngn", Integer, nullable=False),  # only recorded (non-null) invoices land here
    Column("item", String, nullable=True),
    Column("due_date", Date, nullable=True),
    Column("status", String, nullable=False, default="open"),
    Column("confidence", Float, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# Every rigor-gate decision, recorded or refused — the durable trust layer (spec §8).
audit_log = Table(
    "audit_log",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("business_id", String, nullable=False, index=True),
    Column("message", String, nullable=False),  # the citation: what came in
    Column("decision", String, nullable=False),  # "recorded" | "asked"
    Column("confidence", Float, nullable=False),
    Column("reason", String, nullable=False),  # the reply / clarify question
    Column("invoice_id", String, nullable=True, index=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

# One row per payment the owner reports against an invoice (spec §8).
payments = Table(
    "payments",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("invoice_id", String, nullable=False, index=True),
    Column("business_id", String, nullable=False, index=True),
    Column("amount_ngn", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# One row per reminder digest sent to a business owner — used to avoid re-spamming.
reminders = Table(
    "reminders",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("business_id", String, nullable=False, index=True),
    Column("sent_at", DateTime(timezone=True), nullable=False),
)

# One row per inbound WhatsApp message id we've handled — inbound idempotency.
processed_messages = Table(
    "processed_messages",
    metadata,
    Column("message_id", String, primary_key=True),
    Column("processed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# One row per chase sent to a debtor about an invoice — used to avoid re-spamming.
chases = Table(
    "chases",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("invoice_id", String, nullable=False, index=True),
    Column("sent_at", DateTime(timezone=True), nullable=False),
    # The reminder's WhatsApp wamid: a debtor's swipe-reply quotes it.
    Column("message_id", String, nullable=True, index=True),
)

# A debtor's contact + consent state, so the owner can have Orviqo chase them.
# One row per (business, debtor name); `opted_out` is the STOP gate.
debtors = Table(
    "debtors",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("business_id", String, nullable=False, index=True),
    Column("name", String, nullable=False),
    Column("phone", String, nullable=False),
    Column("opted_out", Boolean, nullable=False, default=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


# Hosted MCP OAuth (see orviqo/mcp/oauth.py). Clients register themselves (RFC 7591).
oauth_clients = Table(
    "oauth_clients",
    metadata,
    Column("client_id", String, primary_key=True),
    Column("info", Text, nullable=False),  # OAuthClientInformationFull as JSON
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# A client's connect request, waiting for the owner to sign in (minutes-lived).
oauth_grants = Table(
    "oauth_grants",
    metadata,
    Column("id", String, primary_key=True),
    Column("link_code", String, nullable=False, index=True),
    Column("client_id", String, nullable=False),
    Column("client_name", String, nullable=True),
    Column("redirect_uri", Text, nullable=False),
    Column("redirect_uri_provided_explicitly", Boolean, nullable=False),
    Column("state", Text, nullable=True),
    Column("code_challenge", String, nullable=False),
    Column("scopes", String, nullable=False),  # space-separated
    Column("resource", Text, nullable=True),
    Column("business_id", String, nullable=True),  # set when the owner links
    Column("expires_at", DateTime(timezone=True), nullable=False),
)

# Authorization codes, access and refresh tokens: only their SHA-256 hashes are kept.
oauth_tokens = Table(
    "oauth_tokens",
    metadata,
    Column("token_hash", String, primary_key=True),
    Column("kind", String, nullable=False),  # "code" | "access" | "refresh"
    Column("client_id", String, nullable=False),
    Column("business_id", String, nullable=False, index=True),
    Column("scopes", String, nullable=False),
    Column("resource", Text, nullable=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("code_challenge", String, nullable=True),
    Column("redirect_uri", Text, nullable=True),
    Column("redirect_uri_provided_explicitly", Boolean, nullable=False, default=False),
)


def make_engine(url: str) -> AsyncEngine:
    # pre_ping: a serverless Postgres (Neon) drops idle connections when its compute
    # suspends, so check a pooled connection before use instead of failing on it.
    return create_async_engine(url, pool_pre_ping=True)


async def create_schema(engine: AsyncEngine) -> None:
    """Create tables if absent. Fine for dev/tests; prod uses Alembic migrations."""
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
