"""Through the real webhook route: a trader who owes someone runs their own ledger too.

The reported case: a wholesaler saved a retailer's number and Orviqo chased it.
The retailer can still record their own debtor at once, and an answer to the
reminder reaches the wholesaler, because the intake agent reads the reminder as
context and decides which one a message is.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from orviqo.adapters.audit import InMemoryAuditLog
from orviqo.adapters.chases import InMemoryChaseStore
from orviqo.adapters.debtors import InMemoryDebtorStore
from orviqo.adapters.ledger import InMemoryLedger
from orviqo.adapters.payments import InMemoryPaymentStore
from orviqo.adapters.processed import InMemoryProcessedMessageStore
from orviqo.agents.intake import _format_context
from orviqo.api import webhook
from orviqo.config import settings
from orviqo.domain.intake import IntakeAction
from orviqo.domain.models import ParsedInvoice
from orviqo.services.debtor_inbox import DebtorInboxService
from orviqo.services.intake_service import IntakeService

from test_webhook_signature import SECRET, SENDER, CapturingCloudClient, _body, _post, _sign

WHOLESALER = "2348070000001"


async def _client(
    action: IntakeAction, make_agent
) -> tuple[TestClient, CapturingCloudClient, InMemoryLedger]:
    whatsapp, ledger, debtors, chases = (
        CapturingCloudClient(),
        InMemoryLedger(),
        InMemoryDebtorStore(),
        InMemoryChaseStore(),
    )
    # The wholesaler saved the sender (the retailer) and Orviqo chased them today.
    await debtors.upsert(WHOLESALER, "Chidi", SENDER)
    owed = await ledger.add(
        ParsedInvoice(debtor_name="Chidi", amount_ngn=50_000, item="rice", confidence=1), WHOLESALER
    )
    await chases.record(owed.id, datetime.now(UTC))
    app = webhook.create_app()
    app.state.service = IntakeService(
        make_agent(action), ledger, InMemoryAuditLog(), InMemoryPaymentStore(), debtors
    )
    app.state.inbox = DebtorInboxService(debtors, whatsapp, ledger=ledger, chases=chases)
    app.state.processed = InMemoryProcessedMessageStore()
    app.state.whatsapp = whatsapp
    return TestClient(app), whatsapp, ledger


async def test_chased_retailer_records_their_own_debtor_straight_away(
    make_agent, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "whatsapp_app_secret", SECRET)
    action = IntakeAction(kind="create", debtor_name="Ada", amount_ngn=20_000, confidence=0.95)
    client, whatsapp, ledger = await _client(action, make_agent)

    body = _body("Ada owes me 20k")
    assert _post(client, body, _sign(body)).status_code == 200

    assert [i.debtor_name for i in await ledger.open_invoices(SENDER)] == ["Ada"]
    assert all(to == SENDER for to, _ in whatsapp.sent)  # nothing went to the wholesaler


async def test_an_answer_to_the_reminder_reaches_the_wholesaler(make_agent, monkeypatch) -> None:
    monkeypatch.setattr(settings, "whatsapp_app_secret", SECRET)
    action = IntakeAction(kind="reminder_reply", confidence=0.9)  # the only reminder on file
    client, whatsapp, ledger = await _client(action, make_agent)

    body = _body("I'll pay on Friday")
    assert _post(client, body, _sign(body)).status_code == 200

    acks = [text for to, text in whatsapp.sent if to == SENDER]
    assert any("reminded you about ₦50,000 for rice" in text for text in acks)
    assert (
        WHOLESALER,
        'Chidi replied to your reminder about ₦50,000 for rice: "I\'ll pay on Friday"',
    ) in whatsapp.sent
    assert await ledger.open_invoices(SENDER) == []


def test_the_agent_sees_reminders_apart_from_the_senders_own_ledger() -> None:
    from orviqo.domain.intake import Reminder

    reminder = Reminder(
        invoice_id="inv9",
        business_id=WHOLESALER,
        debtor_name="Chidi",
        amount_ngn=50_000,
        item="rice",
        due_date=None,
        reminded_at=datetime(2026, 11, 6, tzinfo=UTC),
    )

    context = _format_context([], [], [reminder])

    assert "Reminders this sender received" in context
    assert "reminder #inv9 · they owe a business ₦50,000 for rice" in context
    assert WHOLESALER not in context  # the creditor's number is none of the model's business


def test_the_agent_is_told_which_reminder_was_quoted() -> None:
    from orviqo.domain.intake import Reminder

    reminder = Reminder(
        invoice_id="inv9",
        business_id=WHOLESALER,
        debtor_name="Chidi",
        amount_ngn=50_000,
        item="rice",
        due_date=None,
        reminded_at=datetime(2026, 11, 6, tzinfo=UTC),
        quoted=True,
    )

    assert "QUOTED: the new message is a WhatsApp reply to this reminder" in _format_context(
        [], [], [reminder]
    )


async def test_a_swipe_reply_reaches_the_agent_marked_quoted(make_agent, monkeypatch) -> None:
    import json

    monkeypatch.setattr(settings, "whatsapp_app_secret", SECRET)
    action = IntakeAction(kind="reminder_reply", confidence=0.9)
    client, whatsapp, ledger = await _client(action, make_agent)
    # The chase above was sent before ids were kept; this one carries its wamid.
    chases = client.app.state.inbox._chases  # type: ignore[attr-defined]
    [owed] = await ledger.open_invoices(WHOLESALER)
    await chases.record(owed.id, datetime.now(UTC), "wamid.reminder")
    message = {
        "from": SENDER,
        "id": "wamid.in",
        "type": "text",
        "text": {"body": "Paid 20k"},
        "context": {"from": "2348000000000", "id": "wamid.reminder"},
    }
    body = json.dumps({"entry": [{"changes": [{"value": {"messages": [message]}}]}]}).encode()

    assert _post(client, body, _sign(body)).status_code == 200

    agent = client.app.state.service._agent  # type: ignore[attr-defined]
    assert [r.quoted for r in agent.seen_reminders] == [True]
    assert any(to == WHOLESALER and '"Paid 20k"' in text for to, text in whatsapp.sent)


async def test_the_webhook_notes_the_senders_whatsapp_name(make_agent, monkeypatch) -> None:
    import json

    from orviqo.adapters.businesses import InMemoryBusinessStore

    monkeypatch.setattr(settings, "whatsapp_app_secret", SECRET)
    client, _, _ = await _client(IntakeAction(kind="greeting", confidence=0.9), make_agent)
    businesses = InMemoryBusinessStore()
    client.app.state.businesses = businesses  # type: ignore[attr-defined]
    value = {
        "contacts": [{"profile": {"name": "Chidi Traders"}, "wa_id": SENDER}],
        "messages": [{"from": SENDER, "id": "w9", "type": "text", "text": {"body": "hi"}}],
    }
    body = json.dumps({"entry": [{"changes": [{"value": value}]}]}).encode()

    assert _post(client, body, _sign(body)).status_code == 200

    profile = await businesses.get(SENDER)
    assert profile is not None and profile.whatsapp_name == "Chidi Traders"
