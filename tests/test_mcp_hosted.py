"""The hosted MCP server end to end over HTTP, exactly as claude.ai or ChatGPT drive it.

Discovery → client registration → authorize → sign-in page → WhatsApp link (or a
demo sandbox) → authorization code → token → tool calls. Runs in-process on the
in-memory adapters with the SDK's real OAuth and Streamable HTTP routes.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from orviqo.adapters.audit import InMemoryAuditLog
from orviqo.adapters.debtors import InMemoryDebtorStore
from orviqo.adapters.ledger import InMemoryLedger
from orviqo.adapters.oauth import InMemoryOAuthStore
from orviqo.adapters.payments import InMemoryPaymentStore
from orviqo.domain.models import ParsedInvoice
from orviqo.mcp.hosted import build_hosted_server, hosted_app
from orviqo.mcp.oauth import OrviqoOAuthProvider
from orviqo.mcp.server import Stores

URL = "https://orviqo.test"
CALLBACK = "https://claude.ai/api/mcp/auth_callback"
OWNER = "2348031234567"
OTHER = "2348039999999"


@dataclass
class Hosted:
    http: httpx.AsyncClient
    provider: OrviqoOAuthProvider
    stores: Stores


@asynccontextmanager
async def running(demo_daily_limit: int = 3_000) -> AsyncIterator[Hosted]:
    """The hosted server, live. (A context manager, not a fixture: the session
    manager's task group must open and close in the test's own task.)"""
    stores = Stores(
        InMemoryLedger(), InMemoryPaymentStore(), InMemoryDebtorStore(), InMemoryAuditLog()
    )
    server, provider = build_hosted_server(
        stores,
        InMemoryOAuthStore(),
        public_url=URL,
        display_number="0803 000 0000",
        demo_daily_limit=demo_daily_limit,
    )
    app = hosted_app(server, URL)  # builds the session manager the next line runs
    async with server.session_manager.run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=URL) as http:
            yield Hosted(http, provider, stores)


@dataclass
class Session:
    client_id: str
    verifier: str
    login: str


async def start(h: Hosted) -> Session:
    """Register a client and start authorizing it; return where the owner lands."""
    reg = await h.http.post(
        "/register",
        json={
            "redirect_uris": [CALLBACK],
            "client_name": "Claude",
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )
    assert reg.status_code == 201
    client_id = reg.json()["client_id"]
    verifier = secrets.token_urlsafe(40)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    auth = await h.http.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": CALLBACK,
            "code_challenge": challenge.decode().rstrip("="),
            "code_challenge_method": "S256",
            "state": "st4te",
            "scope": "ledger",
            "resource": f"{URL}/mcp",
        },
    )
    assert auth.status_code == 302
    return Session(client_id, verifier, auth.headers["location"])


async def finish(h: Hosted, s: Session) -> str:
    """Follow "complete" back to the client and swap the code for an access token."""
    done = await h.http.get(f"{s.login}/complete")
    assert done.status_code == 302 and done.headers["location"].startswith(CALLBACK)
    query = parse_qs(urlsplit(done.headers["location"]).query)
    assert query["state"] == ["st4te"]
    token = await h.http.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": query["code"][0],
            "redirect_uri": CALLBACK,
            "client_id": s.client_id,
            "code_verifier": s.verifier,
        },
    )
    assert token.status_code == 200, token.text
    return token.json()["access_token"]


async def sign_in_on_whatsapp(h: Hosted, who: str = OWNER) -> str:
    s = await start(h)
    grant = await h.provider.grant(s.login.rsplit("/", 1)[1])
    assert grant is not None
    assert await h.provider.link_from_message(who, f"LINK {grant.link_code}")
    return await finish(h, s)


async def call(h: Hosted, token: str | None, tool: str, **arguments: Any) -> httpx.Response:
    headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-06-18",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    return await h.http.post("/mcp", headers=headers, json=body)


def structured(response: httpx.Response) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert not result.get("isError"), result
    return result["structuredContent"]


async def test_discovery_points_clients_at_this_server() -> None:
    async with running() as hosted:
        resource = await hosted.http.get("/.well-known/oauth-protected-resource/mcp")
        server = await hosted.http.get("/.well-known/oauth-authorization-server")

        assert resource.json()["authorization_servers"] == [URL]
        meta = server.json()
        assert meta["registration_endpoint"] == f"{URL}/register"
        assert "S256" in meta["code_challenge_methods_supported"]


async def test_mcp_refuses_requests_without_a_token() -> None:
    async with running() as hosted:
        response = await call(hosted, None, "list_open_debts")
        assert response.status_code == 401
        assert "resource_metadata" in response.headers["www-authenticate"]


async def test_sign_in_page_shows_the_code_and_a_prefilled_whatsapp_link() -> None:
    async with running() as hosted:
        s = await start(hosted)
        grant = await hosted.provider.grant(s.login.rsplit("/", 1)[1])
        assert grant is not None

        page = await hosted.http.get(s.login)

        assert page.status_code == 200
        assert f"LINK {grant.link_code}" in page.text
        assert "https://wa.me/2348030000000?text=LINK" in page.text
        assert "Use a demo ledger" in page.text


async def test_completing_before_the_owner_links_goes_back_to_the_page() -> None:
    async with running() as hosted:
        s = await start(hosted)
        response = await hosted.http.get(f"{s.login}/complete")
        assert response.status_code == 303 and response.headers["location"] == s.login


async def test_whatsapp_sign_in_reaches_exactly_that_owners_ledger() -> None:
    async with running() as hosted:
        await hosted.stores.ledger.add(
            ParsedInvoice(debtor_name="Chidi", amount_ngn=150_000, confidence=1), OWNER
        )
        await hosted.stores.ledger.add(
            ParsedInvoice(debtor_name="Stranger", amount_ngn=9_000, confidence=1), OTHER
        )

        token = await sign_in_on_whatsapp(hosted)
        debts = structured(await call(hosted, token, "list_open_debts"))

        assert [d["debtor_name"] for d in debts["debts"]] == ["Chidi"]


async def test_writes_land_in_the_signed_in_ledger_and_audit() -> None:
    async with running() as hosted:
        token = await sign_in_on_whatsapp(hosted)

        result = structured(
            await call(hosted, token, "record_debt", debtor_name="Ada", amount_ngn=45_000)
        )

        assert result["status"] == "recorded"
        assert [i.debtor_name for i in await hosted.stores.ledger.open_invoices(OWNER)] == ["Ada"]
        [entry] = await hosted.stores.audit.entries(OWNER)
        assert entry.message.startswith("mcp:record_debt")


async def test_a_wrong_pkce_verifier_gets_no_token() -> None:
    async with running() as hosted:
        s = await start(hosted)
        grant = await hosted.provider.grant(s.login.rsplit("/", 1)[1])
        assert grant is not None
        await hosted.provider.link(grant.link_code, OWNER)
        done = await hosted.http.get(f"{s.login}/complete")
        code = parse_qs(urlsplit(done.headers["location"]).query)["code"][0]

        token = await hosted.http.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": CALLBACK,
                "client_id": s.client_id,
                "code_verifier": "not-the-verifier-" + "x" * 30,
            },
        )

        assert token.status_code == 400


async def test_demo_sandbox_is_private_seeded_and_not_a_real_owner() -> None:
    async with running() as hosted:
        await hosted.stores.ledger.add(
            ParsedInvoice(debtor_name="Real", amount_ngn=1, confidence=1), OWNER
        )
        s = await start(hosted)

        demo = await hosted.http.post(f"{s.login}/demo")
        assert demo.status_code == 303 and demo.headers["location"] == f"{s.login}/complete"
        token = await finish(hosted, s)
        debts = structured(await call(hosted, token, "list_open_debts"))

        names = sorted(d["debtor_name"] for d in debts["debts"])
        assert names == ["Ada", "Chidi", "Chidi", "Emeka"]
        overdue = structured(await call(hosted, token, "list_overdue"))
        assert {d["debtor_name"] for d in overdue["debts"]} == {"Chidi", "Emeka"}
        ambiguous = structured(
            await call(hosted, token, "record_payment", debtor_name="Chidi", amount_ngn=20_000)
        )
        assert ambiguous["status"] == "ambiguous"


async def test_two_demo_visitors_get_separate_sandboxes() -> None:
    async with running() as hosted:
        tokens = []
        for _ in range(2):
            s = await start(hosted)
            await hosted.http.post(f"{s.login}/demo")
            tokens.append(await finish(hosted, s))

        await call(hosted, tokens[0], "record_debt", debtor_name="Only Mine", amount_ngn=1_000)
        other = structured(
            await call(hosted, tokens[1], "list_open_debts", debtor_name="Only Mine")
        )

        assert other["count"] == 0


async def test_demo_stops_at_the_daily_cap() -> None:
    async with running(demo_daily_limit=4) as h:
        first, second = await start(h), await start(h)
        assert (await h.http.post(f"{first.login}/demo")).status_code == 303  # seeds 4 entries
        assert (await h.http.post(f"{second.login}/demo")).status_code == 429


async def test_unknown_or_expired_sign_in_pages_say_so() -> None:
    async with running() as hosted:
        page = await hosted.http.get("/mcp/login/not-a-grant")
        status = await hosted.http.get("/mcp/login/not-a-grant/status")
        assert page.status_code == 404 and "expired" in page.text
        assert json.loads(status.text) == {"expired": True, "linked": False}


def test_the_app_mounts_hosted_mcp_without_shadowing_its_own_routes(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from orviqo.api import webhook
    from orviqo.config import settings

    monkeypatch.setattr(settings, "orviqo_public_url", URL)
    client = TestClient(webhook.create_app(), base_url=URL)  # no lifespan: routes only

    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/").status_code == 200  # the landing page, not the MCP app
    meta = client.get("/.well-known/oauth-authorization-server")
    assert meta.status_code == 200 and meta.json()["issuer"].rstrip("/") == URL


def test_without_a_public_url_nothing_is_mounted(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from orviqo.api import webhook
    from orviqo.config import settings

    monkeypatch.setattr(settings, "orviqo_public_url", "")
    client = TestClient(webhook.create_app())

    assert client.get("/.well-known/oauth-authorization-server").status_code == 404
