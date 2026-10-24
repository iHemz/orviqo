"""The public web demo: session isolation, the caps, and the HTTP surface."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from orviqo.adapters.audit import InMemoryAuditLog
from orviqo.adapters.debtors import InMemoryDebtorStore
from orviqo.adapters.ledger import InMemoryLedger
from orviqo.adapters.payments import InMemoryPaymentStore
from orviqo.api import webhook
from orviqo.api.site import BUSY_REPLY
from orviqo.config import settings
from orviqo.domain.demo import demo_business_id, is_demo
from orviqo.domain.intake import IntakeAction
from orviqo.services.demo_service import (
    DAILY_LIMIT_REPLY,
    SESSION_LIMIT_REPLY,
    DemoService,
)
from orviqo.services.intake_service import WELCOME, IntakeService

SESSION = "0123456789abcdef0123456789abcdef"
CREATE = IntakeAction(kind="create", debtor_name="Chidi", amount_ngn=150_000, confidence=0.95)


def _demo(agent, audit=None, session_limit=30, daily_limit=300) -> DemoService:
    audit = audit or InMemoryAuditLog()
    intake = IntakeService(
        agent, InMemoryLedger(), audit, InMemoryPaymentStore(), InMemoryDebtorStore()
    )
    return DemoService(intake, audit, session_limit=session_limit, daily_limit=daily_limit)


# --- session ids -------------------------------------------------------------


def test_session_becomes_a_private_demo_business() -> None:
    dashed = "01234567-89ab-cdef-0123-456789abcdef"
    assert demo_business_id(dashed) == "demo:" + SESSION
    assert is_demo(demo_business_id(SESSION))


@pytest.mark.parametrize("bad", ["", "short", "2348031234567", "x" * 32, "../" + "a" * 29])
def test_malformed_sessions_are_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        demo_business_id(bad)


# --- the service --------------------------------------------------------------


async def test_first_message_returns_welcome_then_reply(make_agent) -> None:
    demo = _demo(make_agent(CREATE))

    replies = await demo.chat(demo_business_id(SESSION), "Chidi owes 150k")

    assert replies[0] == WELCOME
    assert replies[1].startswith("Noted:")


async def test_session_cap_stops_before_calling_the_agent(make_agent) -> None:
    agent = make_agent(CREATE)
    demo = _demo(agent, session_limit=2)
    business = demo_business_id(SESSION)
    await demo.chat(business, "one")
    await demo.chat(business, "two")

    agent.seen_history = []  # sentinel: a further call would overwrite it
    assert await demo.chat(business, "three") == [SESSION_LIMIT_REPLY]
    assert agent.seen_history == []  # the agent (and the LLM quota) was never touched


async def test_daily_cap_counts_every_demo_session(make_agent) -> None:
    demo = _demo(make_agent(CREATE), daily_limit=2)
    await demo.chat(demo_business_id("a" * 32), "one")
    await demo.chat(demo_business_id("b" * 32), "two")

    assert await demo.chat(demo_business_id("c" * 32), "three") == [DAILY_LIMIT_REPLY]


# --- HTTP ---------------------------------------------------------------------


class FailingAgent:
    async def decide(self, message, open_invoices, history):
        raise RuntimeError("429 quota exceeded")


def _client(demo: DemoService) -> TestClient:
    app = webhook.create_app()
    app.state.demo = demo  # no lifespan: the demo route only needs this
    return TestClient(app)


def test_landing_page_shows_whatsapp_button_only_when_configured(monkeypatch) -> None:
    client = TestClient(webhook.create_app())

    monkeypatch.setattr(settings, "whatsapp_display_number", "")
    page = client.get("/").text
    assert "Try the live demo" in page and 'href="/start"' not in page

    monkeypatch.setattr(settings, "whatsapp_display_number", "+234 803 123 4567")
    assert 'href="/start"' in client.get("/").text


def test_demo_route_returns_replies(make_agent) -> None:
    client = _client(_demo(make_agent(CREATE)))

    response = client.post("/demo/message", json={"session": SESSION, "text": "Chidi owes 150k"})

    assert response.status_code == 200
    assert response.json()["replies"][0] == WELCOME


def test_demo_route_rejects_a_bad_session(make_agent) -> None:
    client = _client(_demo(make_agent(CREATE)))

    response = client.post("/demo/message", json={"session": "2348031234567", "text": "hi"})

    assert response.status_code == 400


def test_llm_failure_is_a_friendly_503_not_a_crash() -> None:
    client = _client(_demo(FailingAgent()))

    response = client.post("/demo/message", json={"session": SESSION, "text": "hi"})

    assert response.status_code == 503
    assert response.json() == {"replies": [BUSY_REPLY]}


# --- cron ---------------------------------------------------------------------


def test_cron_requires_the_secret(monkeypatch) -> None:
    calls = []

    async def fake_run_once() -> tuple[int, int]:
        calls.append(1)
        return 2, 1

    monkeypatch.setattr(webhook.worker, "run_once", fake_run_once)
    monkeypatch.setattr(settings, "cron_secret", "s3cret-value-1234")
    client = TestClient(webhook.create_app())

    assert client.get("/cron/collections").status_code == 401
    bad = {"Authorization": "Bearer wrong"}
    assert client.get("/cron/collections", headers=bad).status_code == 401
    assert calls == []

    ok = client.get("/cron/collections", headers={"Authorization": "Bearer s3cret-value-1234"})
    assert ok.status_code == 200 and ok.text == "sent 2 digest(s), 1 chase(s)"
    assert calls == [1]


def test_cron_is_off_until_a_secret_is_set(monkeypatch) -> None:
    monkeypatch.setattr(settings, "cron_secret", "")
    client = TestClient(webhook.create_app())

    assert client.get("/cron/collections").status_code == 503
