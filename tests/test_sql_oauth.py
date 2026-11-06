"""SqlAlchemyOAuthStore and the sandbox clean-up against a real SQLite database."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from orviqo.adapters.db import create_schema, make_engine
from orviqo.adapters.sql_audit import SqlAlchemyAuditLog
from orviqo.adapters.sql_ledger import SqlAlchemyLedger
from orviqo.adapters.sql_oauth import SqlAlchemyOAuthStore
from orviqo.adapters.sql_sandbox import purge_expired_oauth, purge_sandboxes
from orviqo.domain.audit import AuditEntry, Decision
from orviqo.domain.models import ParsedInvoice
from orviqo.domain.oauth import Grant, IssuedToken
from sqlalchemy.ext.asyncio import AsyncEngine

NOW = datetime(2026, 11, 6, 12, tzinfo=UTC)


@pytest_asyncio.fixture
async def engine(tmp_path) -> AsyncIterator[AsyncEngine]:
    engine = make_engine(f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}")
    await create_schema(engine)
    try:
        yield engine
    finally:
        await engine.dispose()


def grant(**kw) -> Grant:
    values = {
        "id": "g1",
        "link_code": "ABCD-2345",
        "client_id": "claude",
        "client_name": "Claude",
        "redirect_uri": "https://claude.ai/cb",
        "redirect_uri_provided_explicitly": True,
        "state": None,
        "code_challenge": "c",
        "scopes": ["ledger"],
        "resource": None,
        "expires_at": NOW + timedelta(minutes=10),
    }
    return Grant(**(values | kw))


def token(**kw) -> IssuedToken:
    values = {
        "token_hash": "h1",
        "kind": "access",
        "client_id": "claude",
        "business_id": "234803",
        "scopes": ["ledger"],
        "resource": None,
        "expires_at": NOW + timedelta(hours=1),
    }
    return IssuedToken(**(values | kw))


async def test_grant_links_once_and_round_trips(engine: AsyncEngine) -> None:
    store = SqlAlchemyOAuthStore(engine)
    await store.add_grant(grant())

    linked = await store.link_grant("ABCD-2345", "234803", NOW)
    again = await store.link_grant("ABCD-2345", "234999", NOW)

    assert linked is not None and linked.business_id == "234803"
    assert again is None  # the first link wins
    stored = await store.get_grant("g1")
    assert stored == grant(business_id="234803")  # incl. a timezone-aware expiry


async def test_expired_grants_cannot_link(engine: AsyncEngine) -> None:
    store = SqlAlchemyOAuthStore(engine)
    await store.add_grant(grant())
    assert await store.link_grant("ABCD-2345", "234803", NOW + timedelta(minutes=11)) is None


async def test_tokens_by_kind_and_session_revocation(engine: AsyncEngine) -> None:
    store = SqlAlchemyOAuthStore(engine)
    await store.add_token(token())
    await store.add_token(token(token_hash="h2", kind="refresh"))
    await store.add_token(token(token_hash="h3", client_id="chatgpt"))

    assert await store.get_token("h1", "access") == token()
    assert await store.get_token("h1", "refresh") is None
    await store.delete_tokens("claude", "234803")
    assert await store.get_token("h2", "refresh") is None
    assert await store.get_token("h3", "access") is not None  # another client's session


async def test_clients_round_trip(engine: AsyncEngine) -> None:
    store = SqlAlchemyOAuthStore(engine)
    await store.save_client("abc", '{"client_id": "abc"}')
    assert await store.get_client("abc") == '{"client_id": "abc"}'
    assert await store.get_client("nope") is None


async def test_purge_removes_old_sandboxes_whole_and_keeps_the_rest(engine: AsyncEngine) -> None:
    audit, ledger = SqlAlchemyAuditLog(engine), SqlAlchemyLedger(engine)
    for business, age in (("demo:mcp-old", 4), ("demo:mcp-new", 1), ("2348031234567", 30)):
        created = NOW - timedelta(days=age)
        await audit.record(_entry(business, created))
        await audit.record(_entry(business, NOW))  # recent activity doesn't extend a sandbox
        await ledger.add(ParsedInvoice(debtor_name="Chidi", amount_ngn=1, confidence=1), business)

    removed = await purge_sandboxes(engine, "demo:mcp-", NOW - timedelta(days=3))

    assert removed == 1
    assert await ledger.open_invoices("demo:mcp-old") == []
    assert await audit.entries("demo:mcp-old") == []
    assert len(await ledger.open_invoices("demo:mcp-new")) == 1
    assert len(await ledger.open_invoices("2348031234567")) == 1  # a real owner, never purged


async def test_purge_expired_oauth(engine: AsyncEngine) -> None:
    store = SqlAlchemyOAuthStore(engine)
    await store.add_grant(grant(expires_at=NOW - timedelta(minutes=1)))
    await store.add_token(token(expires_at=NOW - timedelta(minutes=1)))
    await store.add_token(token(token_hash="live"))

    await purge_expired_oauth(engine, NOW)

    assert await store.get_grant("g1") is None
    assert await store.get_token("h1", "access") is None
    assert await store.get_token("live", "access") is not None


def _entry(business_id: str, at: datetime) -> AuditEntry:
    return AuditEntry(
        business_id=business_id,
        message="seed",
        decision=Decision.recorded,
        confidence=1.0,
        reason="ok",
        created_at=at,
    )
