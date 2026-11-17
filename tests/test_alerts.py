"""Operator alerts: errors and the daily run reach ntfy, never with user data in them."""

from __future__ import annotations

import httpx
from fastapi.testclient import TestClient
from orviqo.adapters.alerts import NtfyAlerter, describe
from orviqo.api import webhook
from orviqo.config import settings


class Recording:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, bool]] = []

    async def alert(self, title: str, body: str, *, urgent: bool = True) -> None:
        self.sent.append((title, body, urgent))


async def test_ntfy_posts_once_per_alert_per_ten_minutes() -> None:
    posts: list[httpx.Request] = []
    transport = httpx.MockTransport(lambda r: posts.append(r) or httpx.Response(200))
    now = [1000.0]
    alerter = NtfyAlerter(
        "orviqo-x7k2", client=httpx.AsyncClient(transport=transport), clock=lambda: now[0]
    )

    await alerter.alert("Orviqo error on /webhook", "RuntimeError")
    await alerter.alert("Orviqo error on /webhook", "RuntimeError")  # Meta retrying
    now[0] += 601
    await alerter.alert("Orviqo error on /webhook", "RuntimeError")

    assert len(posts) == 2
    assert str(posts[0].url) == "https://ntfy.sh/orviqo-x7k2"
    assert posts[0].headers["Title"] == "Orviqo error on /webhook"
    assert posts[0].headers["Priority"] == "high"


async def test_a_failing_alert_never_raises() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("ntfy is down")

    alerter = NtfyAlerter("t", client=httpx.AsyncClient(transport=httpx.MockTransport(refuse)))
    await alerter.alert("Orviqo error on /webhook", "RuntimeError")  # no exception


def test_alerts_name_the_error_never_its_message() -> None:
    assert describe(ValueError("Chidi 08031234567 owes 50k")) == "ValueError"
    request = httpx.Request("POST", "https://graph.facebook.com/v21.0/123/messages")
    refused = httpx.HTTPStatusError("401", request=request, response=httpx.Response(401))
    assert describe(refused) == "HTTPStatusError 401 from graph.facebook.com"


def test_a_failing_request_alerts_and_still_fails(monkeypatch) -> None:
    async def broken() -> tuple[int, int]:
        raise RuntimeError("database unreachable")

    monkeypatch.setattr(webhook.worker, "run_once", broken)
    monkeypatch.setattr(settings, "cron_secret", "s3cret-value-1234")
    app = webhook.create_app()
    app.state.alerter = recording = Recording()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get(
        "/cron/collections", headers={"Authorization": "Bearer s3cret-value-1234"}
    )

    assert response.status_code == 500
    assert recording.sent == [("Orviqo error on /cron/collections", "RuntimeError", True)]


def test_the_daily_run_sends_a_quiet_summary(monkeypatch) -> None:
    async def ran() -> tuple[int, int]:
        return 3, 1

    monkeypatch.setattr(webhook.worker, "run_once", ran)
    monkeypatch.setattr(settings, "cron_secret", "s3cret-value-1234")
    app = webhook.create_app()
    app.state.alerter = recording = Recording()

    TestClient(app).get("/cron/collections", headers={"Authorization": "Bearer s3cret-value-1234"})

    assert recording.sent == [("Orviqo daily run", "Sent 3 digest(s), 1 chase(s).", False)]


def test_requests_that_succeed_alert_nothing() -> None:
    app = webhook.create_app()
    app.state.alerter = recording = Recording()

    assert TestClient(app).get("/health").status_code == 200
    assert recording.sent == []
