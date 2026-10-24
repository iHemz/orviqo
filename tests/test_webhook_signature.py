"""Webhook authenticity: only Meta-signed callbacks reach intake (and the LLM)."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from orviqo.adapters.audit import InMemoryAuditLog
from orviqo.adapters.debtors import InMemoryDebtorStore
from orviqo.adapters.ledger import InMemoryLedger
from orviqo.adapters.payments import InMemoryPaymentStore
from orviqo.adapters.processed import InMemoryProcessedMessageStore
from orviqo.adapters.whatsapp import LoggingWhatsAppClient, valid_signature
from orviqo.api import webhook
from orviqo.config import settings
from orviqo.domain.intake import IntakeAction
from orviqo.services.debtor_inbox import DebtorInboxService
from orviqo.services.intake_service import IntakeService

SECRET = "meta-app-secret"
SENDER = "2348031234567"


def _sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _body(text: str = "Chidi owes 50k") -> bytes:
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": SENDER,
                                    "id": "wamid.1",
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    return json.dumps(payload).encode()


class CapturingCloudClient:
    """Stands in for the real Cloud API client (anything but the logging stub)."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_text(self, to: str, text: str) -> None:
        self.sent.append((to, text))

    async def send_template(self, to: str, name: str, params: list[str], lang: str) -> None:
        raise AssertionError("not used")

    async def aclose(self) -> None:
        return None


class CapturingStub(LoggingWhatsAppClient):
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_text(self, to: str, text: str) -> None:
        self.sent.append((to, text))


def _client(make_agent, whatsapp) -> TestClient:
    action = IntakeAction(kind="create", debtor_name="Chidi", amount_ngn=50_000, confidence=0.95)
    app = webhook.create_app()  # no lifespan: wire the state the route reads
    app.state.service = IntakeService(
        make_agent(action),
        InMemoryLedger(),
        InMemoryAuditLog(),
        InMemoryPaymentStore(),
        InMemoryDebtorStore(),
    )
    app.state.inbox = DebtorInboxService(InMemoryDebtorStore(), whatsapp)
    app.state.processed = InMemoryProcessedMessageStore()
    app.state.whatsapp = whatsapp
    return TestClient(app)


def _post(client: TestClient, body: bytes, signature: str | None):
    headers = {"Content-Type": "application/json"}
    if signature is not None:
        headers["X-Hub-Signature-256"] = signature
    return client.post("/webhook", content=body, headers=headers)


# --- the check itself -----------------------------------------------------------


def test_signature_matches_only_the_exact_body_and_secret() -> None:
    body = _body()
    assert valid_signature(SECRET, body, _sign(body))
    assert not valid_signature(SECRET, body + b" ", _sign(body))  # tampered
    assert not valid_signature(SECRET, body, _sign(body, "other-secret"))
    assert not valid_signature(SECRET, body, _sign(body).removeprefix("sha256="))
    assert not valid_signature("", body, _sign(body, ""))  # no secret, no trust


# --- the route ------------------------------------------------------------------


def test_signed_callback_is_handled(make_agent, monkeypatch) -> None:
    monkeypatch.setattr(settings, "whatsapp_app_secret", SECRET)
    whatsapp = CapturingCloudClient()
    body = _body()

    response = _post(_client(make_agent, whatsapp), body, _sign(body))

    assert response.status_code == 200
    assert [to for to, _ in whatsapp.sent] == [SENDER, SENDER]  # welcome + "Noted"


@pytest.mark.parametrize("signature", [None, "sha256=deadbeef"], ids=["missing", "forged"])
def test_unsigned_or_forged_callback_is_rejected_untouched(
    make_agent, monkeypatch, signature
) -> None:
    monkeypatch.setattr(settings, "whatsapp_app_secret", SECRET)
    whatsapp = CapturingCloudClient()

    response = _post(_client(make_agent, whatsapp), _body(), signature)

    assert response.status_code == 401
    assert whatsapp.sent == []  # nothing processed, nothing sent


def test_real_credentials_without_a_secret_fail_closed(make_agent, monkeypatch) -> None:
    monkeypatch.setattr(settings, "whatsapp_app_secret", "")
    whatsapp = CapturingCloudClient()

    response = _post(_client(make_agent, whatsapp), _body(), None)

    assert response.status_code == 503
    assert whatsapp.sent == []


def test_local_dev_with_the_logging_stub_needs_no_secret(make_agent, monkeypatch) -> None:
    # No WhatsApp credentials = replies are only logged, so nothing can be abused.
    monkeypatch.setattr(settings, "whatsapp_app_secret", "")
    whatsapp = CapturingStub()

    response = _post(_client(make_agent, whatsapp), _body(), None)

    assert response.status_code == 200
    assert len(whatsapp.sent) == 2
