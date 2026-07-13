"""The intake use-case: create / update / clarify, in conversation context.

The agent's *intelligence* (deciding which action) is the LLM's job and isn't
unit-tested here; these tests pin the service's *execution* of each action and
the rigor gate — and that the conversation context is actually passed along.
"""

from __future__ import annotations

from datetime import date

from orviqo.adapters.audit import InMemoryAuditLog
from orviqo.adapters.ledger import InMemoryLedger
from orviqo.domain.audit import Decision
from orviqo.domain.intake import IntakeAction
from orviqo.domain.models import ParsedInvoice
from orviqo.services.intake_service import IntakeService


async def test_create_records_and_audits(make_agent) -> None:
    action = IntakeAction(
        kind="create", debtor_name="Chidi", amount_ngn=150_000, item="generator",
        due_date=date(2026, 7, 17), confidence=0.98,
    )
    ledger, audit = InMemoryLedger(), InMemoryAuditLog()
    service = IntakeService(make_agent(action), ledger, audit)

    reply = await service.handle_message("biz1", "Chidi owes 150k for generator, due Friday")

    assert reply.recorded_invoice_id is not None
    assert reply.text.startswith("Noted:")
    assert (await ledger.open_invoices("biz1"))[0].debtor_name == "Chidi"
    assert (await audit.entries("biz1"))[0].decision is Decision.recorded


async def test_update_modifies_existing_invoice(make_agent) -> None:
    ledger, audit = InMemoryLedger(), InMemoryAuditLog()
    existing = await ledger.add(
        ParsedInvoice(debtor_name="Randi", amount_ngn=250_000, confidence=0.98), "biz1"
    )
    action = IntakeAction(kind="update", invoice_id=existing.id, item="generator", confidence=0.95)
    service = IntakeService(make_agent(action), ledger, audit)

    reply = await service.handle_message("biz1", "the debt is for a generator")

    assert reply.text.startswith("Updated:")
    updated = (await ledger.open_invoices("biz1"))[0]
    assert updated.item == "generator"
    assert updated.amount_ngn == 250_000  # untouched fields survive
    assert (await audit.entries("biz1"))[0].decision is Decision.updated


async def test_clarify_asks_and_records_nothing(make_agent) -> None:
    action = IntakeAction(kind="clarify", clarify="Who owes you, and how much?", confidence=0.3)
    ledger, audit = InMemoryLedger(), InMemoryAuditLog()
    service = IntakeService(make_agent(action), ledger, audit)

    reply = await service.handle_message("biz1", "someone owes me")

    assert reply.recorded_invoice_id is None
    assert reply.text == "Who owes you, and how much?"
    assert await ledger.open_invoices("biz1") == []
    assert (await audit.entries("biz1"))[0].decision is Decision.asked


async def test_create_without_amount_is_refused(make_agent) -> None:
    # Rigor gate: a "create" with no amount must fall back to asking, never record.
    action = IntakeAction(kind="create", debtor_name="Tunde", amount_ngn=None, confidence=0.95)
    ledger, audit = InMemoryLedger(), InMemoryAuditLog()
    service = IntakeService(make_agent(action), ledger, audit)

    reply = await service.handle_message("biz1", "Tunde owes me")

    assert reply.recorded_invoice_id is None
    assert await ledger.open_invoices("biz1") == []
    assert (await audit.entries("biz1"))[0].decision is Decision.asked


async def test_update_to_unknown_invoice_falls_back_to_ask(make_agent) -> None:
    action = IntakeAction(kind="update", invoice_id="nonexistent", item="x", confidence=0.9)
    ledger, audit = InMemoryLedger(), InMemoryAuditLog()
    service = IntakeService(make_agent(action), ledger, audit)

    reply = await service.handle_message("biz1", "for the generator")

    assert reply.recorded_invoice_id is None
    assert (await audit.entries("biz1"))[0].decision is Decision.asked


async def test_query_answers_a_specific_debtor_from_the_ledger(make_agent) -> None:
    ledger, audit = InMemoryLedger(), InMemoryAuditLog()
    await ledger.add(
        ParsedInvoice(debtor_name="Randi", amount_ngn=300_000, item="generator", confidence=0.98),
        "biz1",
    )
    action = IntakeAction(kind="query", debtor_name="Randi", confidence=0.9)
    service = IntakeService(make_agent(action), ledger, audit)

    reply = await service.handle_message("biz1", "what does Randi owe?")

    assert "Randi owes ₦300,000" in reply.text
    assert reply.recorded_invoice_id is None
    assert (await audit.entries("biz1"))[0].decision is Decision.answered


async def test_query_all_lists_open_debts(make_agent) -> None:
    ledger, audit = InMemoryLedger(), InMemoryAuditLog()
    await ledger.add(ParsedInvoice(debtor_name="Randi", amount_ngn=300_000, confidence=0.98), "b")
    await ledger.add(ParsedInvoice(debtor_name="Chidi", amount_ngn=150_000, confidence=0.98), "b")
    action = IntakeAction(kind="query", confidence=0.9)
    service = IntakeService(make_agent(action), ledger, audit)

    reply = await service.handle_message("b", "who owes me?")

    assert "Randi" in reply.text and "Chidi" in reply.text


async def test_query_unknown_debtor_says_so(make_agent) -> None:
    action = IntakeAction(kind="query", debtor_name="Ghost", confidence=0.9)
    service = IntakeService(make_agent(action), InMemoryLedger(), InMemoryAuditLog())

    reply = await service.handle_message("biz1", "does Ghost owe me?")

    assert "no open debt" in reply.text.lower()


async def test_agent_receives_open_invoices_and_history_as_context(make_agent) -> None:
    # The fix for the re-interrogation bug: on the 2nd message the agent must see
    # the invoice recorded by the 1st, and the 1st exchange.
    action = IntakeAction(
        kind="create", debtor_name="Randi", amount_ngn=250_000, confidence=0.98
    )
    agent = make_agent(action)
    service = IntakeService(agent, InMemoryLedger(), InMemoryAuditLog())

    await service.handle_message("biz1", "Randi owes 250k, due Friday")
    await service.handle_message("biz1", "the debt is for a generator")

    assert [i.debtor_name for i in agent.seen_open_invoices] == ["Randi"]
    assert agent.seen_history[-1].user == "Randi owes 250k, due Friday"
