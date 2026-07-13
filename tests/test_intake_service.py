"""The intake use-case: create / update / clarify, in conversation context.

The agent's *intelligence* (deciding which action) is the LLM's job and isn't
unit-tested here; these tests pin the service's *execution* of each action and
the rigor gate — and that the conversation context is actually passed along.
"""

from __future__ import annotations

from datetime import date

from orviqo.adapters.audit import InMemoryAuditLog
from orviqo.adapters.ledger import InMemoryLedger
from orviqo.adapters.payments import InMemoryPaymentStore
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
    service = IntakeService(make_agent(action), ledger, audit, InMemoryPaymentStore())

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
    service = IntakeService(make_agent(action), ledger, audit, InMemoryPaymentStore())

    reply = await service.handle_message("biz1", "the debt is for a generator")

    assert reply.text.startswith("Updated:")
    updated = (await ledger.open_invoices("biz1"))[0]
    assert updated.item == "generator"
    assert updated.amount_ngn == 250_000  # untouched fields survive
    assert (await audit.entries("biz1"))[0].decision is Decision.updated


async def test_clarify_asks_and_records_nothing(make_agent) -> None:
    action = IntakeAction(kind="clarify", clarify="Who owes you, and how much?", confidence=0.3)
    ledger, audit = InMemoryLedger(), InMemoryAuditLog()
    service = IntakeService(make_agent(action), ledger, audit, InMemoryPaymentStore())

    reply = await service.handle_message("biz1", "someone owes me")

    assert reply.recorded_invoice_id is None
    assert reply.text == "Who owes you, and how much?"
    assert await ledger.open_invoices("biz1") == []
    assert (await audit.entries("biz1"))[0].decision is Decision.asked


async def test_create_without_amount_is_refused(make_agent) -> None:
    # Rigor gate: a "create" with no amount must fall back to asking, never record.
    action = IntakeAction(kind="create", debtor_name="Tunde", amount_ngn=None, confidence=0.95)
    ledger, audit = InMemoryLedger(), InMemoryAuditLog()
    service = IntakeService(make_agent(action), ledger, audit, InMemoryPaymentStore())

    reply = await service.handle_message("biz1", "Tunde owes me")

    assert reply.recorded_invoice_id is None
    assert await ledger.open_invoices("biz1") == []
    assert (await audit.entries("biz1"))[0].decision is Decision.asked


async def test_update_to_unknown_invoice_falls_back_to_ask(make_agent) -> None:
    action = IntakeAction(kind="update", invoice_id="nonexistent", item="x", confidence=0.9)
    ledger, audit = InMemoryLedger(), InMemoryAuditLog()
    service = IntakeService(make_agent(action), ledger, audit, InMemoryPaymentStore())

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
    service = IntakeService(make_agent(action), ledger, audit, InMemoryPaymentStore())

    reply = await service.handle_message("biz1", "what does Randi owe?")

    assert "Randi owes ₦300,000" in reply.text
    assert reply.recorded_invoice_id is None
    assert (await audit.entries("biz1"))[0].decision is Decision.answered


async def test_query_all_lists_open_debts(make_agent) -> None:
    ledger, audit = InMemoryLedger(), InMemoryAuditLog()
    await ledger.add(ParsedInvoice(debtor_name="Randi", amount_ngn=300_000, confidence=0.98), "b")
    await ledger.add(ParsedInvoice(debtor_name="Chidi", amount_ngn=150_000, confidence=0.98), "b")
    action = IntakeAction(kind="query", confidence=0.9)
    service = IntakeService(make_agent(action), ledger, audit, InMemoryPaymentStore())

    reply = await service.handle_message("b", "who owes me?")

    assert "Randi" in reply.text and "Chidi" in reply.text


async def test_query_unknown_debtor_says_so(make_agent) -> None:
    action = IntakeAction(kind="query", debtor_name="Ghost", confidence=0.9)
    service = IntakeService(
        make_agent(action), InMemoryLedger(), InMemoryAuditLog(), InMemoryPaymentStore()
    )

    reply = await service.handle_message("biz1", "does Ghost owe me?")

    assert "no open debt" in reply.text.lower()


async def test_agent_receives_open_invoices_and_history_as_context(make_agent) -> None:
    # The fix for the re-interrogation bug: on the 2nd message the agent must see
    # the invoice recorded by the 1st, and the 1st exchange.
    action = IntakeAction(
        kind="create", debtor_name="Randi", amount_ngn=250_000, confidence=0.98
    )
    agent = make_agent(action)
    service = IntakeService(agent, InMemoryLedger(), InMemoryAuditLog(), InMemoryPaymentStore())

    await service.handle_message("biz1", "Randi owes 250k, due Friday")
    await service.handle_message("biz1", "the debt is for a generator")

    assert [i.debtor_name for i in agent.seen_open_invoices] == ["Randi"]
    assert agent.seen_history[-1].user == "Randi owes 250k, due Friday"


async def test_full_payment_settles_the_invoice(make_agent) -> None:
    ledger, audit, payments = InMemoryLedger(), InMemoryAuditLog(), InMemoryPaymentStore()
    inv = await ledger.add(
        ParsedInvoice(debtor_name="Randi", amount_ngn=250_000, confidence=1.0), "b"
    )
    action = IntakeAction(kind="payment", invoice_id=inv.id, paid_in_full=True, confidence=0.95)
    service = IntakeService(make_agent(action), ledger, audit, payments)

    reply = await service.handle_message("b", "Randi cleared her debt")

    assert "fully paid" in reply.text
    assert await ledger.open_invoices("b") == []  # settled -> off the open list
    assert (await payments.for_invoice(inv.id))[0].amount_ngn == 250_000
    assert (await audit.entries("b"))[0].decision is Decision.reconciled


async def test_partial_payment_reduces_outstanding(make_agent) -> None:
    ledger, audit, payments = InMemoryLedger(), InMemoryAuditLog(), InMemoryPaymentStore()
    inv = await ledger.add(
        ParsedInvoice(debtor_name="Chidi", amount_ngn=80_000, confidence=1.0), "b"
    )
    action = IntakeAction(kind="payment", invoice_id=inv.id, amount_ngn=50_000, confidence=0.95)
    service = IntakeService(make_agent(action), ledger, audit, payments)

    reply = await service.handle_message("b", "Chidi paid 50k")

    assert "30,000 still outstanding" in reply.text
    [remaining] = await ledger.open_invoices("b")
    assert remaining.amount_ngn == 30_000
    assert (await payments.for_invoice(inv.id))[0].amount_ngn == 50_000


async def test_payment_tolerates_hash_prefixed_invoice_id(make_agent) -> None:
    # The agent often copies the "#" from the "[#id]" it sees in context.
    ledger, audit, payments = InMemoryLedger(), InMemoryAuditLog(), InMemoryPaymentStore()
    inv = await ledger.add(
        ParsedInvoice(debtor_name="Randi", amount_ngn=250_000, confidence=1.0), "b"
    )
    action = IntakeAction(
        kind="payment", invoice_id=f"#{inv.id}", paid_in_full=True, confidence=0.95
    )
    service = IntakeService(make_agent(action), ledger, audit, payments)

    reply = await service.handle_message("b", "Randi paid in full")

    assert "fully paid" in reply.text
    assert await ledger.open_invoices("b") == []


async def test_ambiguous_debtor_payment_asks_which(make_agent) -> None:
    # Two open debts for the same debtor: never guess which one the money clears.
    ledger, audit, payments = InMemoryLedger(), InMemoryAuditLog(), InMemoryPaymentStore()
    for item in ("rice", "generator"):
        await ledger.add(
            ParsedInvoice(debtor_name="Chidi", amount_ngn=50_000, item=item, confidence=1.0), "b"
        )
    action = IntakeAction(kind="payment", debtor_name="Chidi", amount_ngn=50_000, confidence=0.95)
    service = IntakeService(make_agent(action), ledger, audit, payments)

    reply = await service.handle_message("b", "Chidi paid 50k")

    assert "which one" in reply.text.lower()
    assert "rice" in reply.text and "generator" in reply.text
    assert await payments.for_invoice("") == []  # nothing recorded
    assert len(await ledger.open_invoices("b")) == 2  # both untouched
    assert (await audit.entries("b"))[0].decision is Decision.asked


async def test_overpayment_settles_and_flags_the_excess(make_agent) -> None:
    ledger, audit, payments = InMemoryLedger(), InMemoryAuditLog(), InMemoryPaymentStore()
    inv = await ledger.add(ParsedInvoice(debtor_name="Ada", amount_ngn=40_000, confidence=1.0), "b")
    action = IntakeAction(kind="payment", invoice_id=inv.id, amount_ngn=50_000, confidence=0.95)
    service = IntakeService(make_agent(action), ledger, audit, payments)

    reply = await service.handle_message("b", "Ada paid 50k")

    assert "overpaid" in reply.text.lower()
    assert "10,000" in reply.text
    assert await ledger.open_invoices("b") == []  # still settled
    assert (await payments.for_invoice(inv.id))[0].amount_ngn == 50_000  # actual amount kept


async def test_payment_without_amount_asks(make_agent) -> None:
    ledger, audit, payments = InMemoryLedger(), InMemoryAuditLog(), InMemoryPaymentStore()
    inv = await ledger.add(ParsedInvoice(debtor_name="Ada", amount_ngn=40_000, confidence=1.0), "b")
    action = IntakeAction(kind="payment", invoice_id=inv.id, confidence=0.9)
    service = IntakeService(make_agent(action), ledger, audit, payments)

    reply = await service.handle_message("b", "Ada paid")

    assert "How much" in reply.text
    assert await payments.for_invoice(inv.id) == []  # nothing recorded until we know


async def test_payment_for_unknown_debtor_asks(make_agent) -> None:
    audit = InMemoryAuditLog()
    action = IntakeAction(kind="payment", debtor_name="Ghost", amount_ngn=10_000, confidence=0.9)
    service = IntakeService(make_agent(action), InMemoryLedger(), audit, InMemoryPaymentStore())

    reply = await service.handle_message("b", "Ghost paid 10k")

    assert reply.recorded_invoice_id is None
    assert (await audit.entries("b"))[0].decision is Decision.asked
