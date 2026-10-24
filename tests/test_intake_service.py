"""The intake use-case: create / update / clarify, in conversation context.

The agent's *intelligence* (deciding which action) is the LLM's job and isn't
unit-tested here; these tests pin the service's *execution* of each action and
the rigor gate — and that the conversation context is actually passed along.
"""

from __future__ import annotations

from datetime import date

from orviqo.adapters.audit import InMemoryAuditLog
from orviqo.adapters.debtors import InMemoryDebtorStore
from orviqo.adapters.ledger import InMemoryLedger
from orviqo.adapters.payments import InMemoryPaymentStore
from orviqo.domain.audit import AuditEntry, Decision
from orviqo.domain.intake import IntakeAction
from orviqo.domain.models import ParsedInvoice
from orviqo.services.intake_service import WELCOME, IntakeService


async def test_create_records_and_audits(make_agent) -> None:
    action = IntakeAction(
        kind="create",
        debtor_name="Chidi",
        amount_ngn=150_000,
        item="generator",
        due_date=date(2026, 7, 17),
        confidence=0.98,
    )
    ledger, audit = InMemoryLedger(), InMemoryAuditLog()
    service = IntakeService(
        make_agent(action), ledger, audit, InMemoryPaymentStore(), InMemoryDebtorStore()
    )

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
    service = IntakeService(
        make_agent(action), ledger, audit, InMemoryPaymentStore(), InMemoryDebtorStore()
    )

    reply = await service.handle_message("biz1", "the debt is for a generator")

    assert reply.text.startswith("Updated:")
    updated = (await ledger.open_invoices("biz1"))[0]
    assert updated.item == "generator"
    assert updated.amount_ngn == 250_000  # untouched fields survive
    assert (await audit.entries("biz1"))[0].decision is Decision.updated


async def test_clarify_asks_and_records_nothing(make_agent) -> None:
    action = IntakeAction(kind="clarify", clarify="Who owes you, and how much?", confidence=0.3)
    ledger, audit = InMemoryLedger(), InMemoryAuditLog()
    await audit.record(_prior_turn("biz1"))  # a returning sender, past the welcome
    service = IntakeService(
        make_agent(action), ledger, audit, InMemoryPaymentStore(), InMemoryDebtorStore()
    )

    reply = await service.handle_message("biz1", "someone owes me")

    assert reply.recorded_invoice_id is None
    assert reply.text == "Who owes you, and how much?"
    assert await ledger.open_invoices("biz1") == []
    assert (await audit.entries("biz1"))[-1].decision is Decision.asked


async def test_create_without_amount_is_refused(make_agent) -> None:
    # Rigor gate: a "create" with no amount must fall back to asking, never record.
    action = IntakeAction(kind="create", debtor_name="Tunde", amount_ngn=None, confidence=0.95)
    ledger, audit = InMemoryLedger(), InMemoryAuditLog()
    service = IntakeService(
        make_agent(action), ledger, audit, InMemoryPaymentStore(), InMemoryDebtorStore()
    )

    reply = await service.handle_message("biz1", "Tunde owes me")

    assert reply.recorded_invoice_id is None
    assert await ledger.open_invoices("biz1") == []
    assert (await audit.entries("biz1"))[0].decision is Decision.asked


async def test_update_to_unknown_invoice_falls_back_to_ask(make_agent) -> None:
    action = IntakeAction(kind="update", invoice_id="nonexistent", item="x", confidence=0.9)
    ledger, audit = InMemoryLedger(), InMemoryAuditLog()
    service = IntakeService(
        make_agent(action), ledger, audit, InMemoryPaymentStore(), InMemoryDebtorStore()
    )

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
    service = IntakeService(
        make_agent(action), ledger, audit, InMemoryPaymentStore(), InMemoryDebtorStore()
    )

    reply = await service.handle_message("biz1", "what does Randi owe?")

    assert "Randi owes ₦300,000" in reply.text
    assert reply.recorded_invoice_id is None
    assert (await audit.entries("biz1"))[0].decision is Decision.answered


async def test_query_for_debtor_shows_payment_progress(make_agent) -> None:
    # After a partial payment, asking about the debtor shows how far they've got.
    ledger, audit, payments = InMemoryLedger(), InMemoryAuditLog(), InMemoryPaymentStore()
    inv = await ledger.add(
        ParsedInvoice(debtor_name="Chidi", amount_ngn=30_000, item="rice", confidence=1.0), "b"
    )
    await payments.record(inv.id, "b", 50_000)  # ₦30k left of an ₦80k original
    action = IntakeAction(kind="query", debtor_name="Chidi", confidence=0.9)
    service = IntakeService(make_agent(action), ledger, audit, payments, InMemoryDebtorStore())

    reply = await service.handle_message("b", "what does Chidi owe?")

    assert "₦30,000" in reply.text  # still outstanding
    assert "₦50,000 of ₦80,000 paid" in reply.text  # progress


async def test_query_all_lists_open_debts(make_agent) -> None:
    ledger, audit = InMemoryLedger(), InMemoryAuditLog()
    await ledger.add(ParsedInvoice(debtor_name="Randi", amount_ngn=300_000, confidence=0.98), "b")
    await ledger.add(ParsedInvoice(debtor_name="Chidi", amount_ngn=150_000, confidence=0.98), "b")
    action = IntakeAction(kind="query", confidence=0.9)
    service = IntakeService(
        make_agent(action), ledger, audit, InMemoryPaymentStore(), InMemoryDebtorStore()
    )

    reply = await service.handle_message("b", "who owes me?")

    assert "Randi" in reply.text and "Chidi" in reply.text


async def test_query_unknown_debtor_says_so(make_agent) -> None:
    action = IntakeAction(kind="query", debtor_name="Ghost", confidence=0.9)
    service = IntakeService(
        make_agent(action),
        InMemoryLedger(),
        InMemoryAuditLog(),
        InMemoryPaymentStore(),
        InMemoryDebtorStore(),
    )

    reply = await service.handle_message("biz1", "does Ghost owe me?")

    assert "no open debt" in reply.text.lower()


async def test_agent_receives_open_invoices_and_history_as_context(make_agent) -> None:
    # The fix for the re-interrogation bug: on the 2nd message the agent must see
    # the invoice recorded by the 1st, and the 1st exchange.
    action = IntakeAction(kind="create", debtor_name="Randi", amount_ngn=250_000, confidence=0.98)
    agent = make_agent(action)
    service = IntakeService(
        agent, InMemoryLedger(), InMemoryAuditLog(), InMemoryPaymentStore(), InMemoryDebtorStore()
    )

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
    service = IntakeService(make_agent(action), ledger, audit, payments, InMemoryDebtorStore())

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
    service = IntakeService(make_agent(action), ledger, audit, payments, InMemoryDebtorStore())

    reply = await service.handle_message("b", "Chidi paid 50k")

    assert "₦50,000 of ₦80,000 paid" in reply.text  # running balance
    assert "₦30,000 still outstanding" in reply.text
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
    service = IntakeService(make_agent(action), ledger, audit, payments, InMemoryDebtorStore())

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
    service = IntakeService(make_agent(action), ledger, audit, payments, InMemoryDebtorStore())

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
    service = IntakeService(make_agent(action), ledger, audit, payments, InMemoryDebtorStore())

    reply = await service.handle_message("b", "Ada paid 50k")

    assert "overpaid" in reply.text.lower()
    assert "10,000" in reply.text
    assert await ledger.open_invoices("b") == []  # still settled
    assert (await payments.for_invoice(inv.id))[0].amount_ngn == 50_000  # actual amount kept


async def test_payment_without_amount_asks(make_agent) -> None:
    ledger, audit, payments = InMemoryLedger(), InMemoryAuditLog(), InMemoryPaymentStore()
    inv = await ledger.add(ParsedInvoice(debtor_name="Ada", amount_ngn=40_000, confidence=1.0), "b")
    action = IntakeAction(kind="payment", invoice_id=inv.id, confidence=0.9)
    service = IntakeService(make_agent(action), ledger, audit, payments, InMemoryDebtorStore())

    reply = await service.handle_message("b", "Ada paid")

    assert "How much" in reply.text
    assert await payments.for_invoice(inv.id) == []  # nothing recorded until we know


async def test_payment_for_unknown_debtor_asks(make_agent) -> None:
    audit = InMemoryAuditLog()
    action = IntakeAction(kind="payment", debtor_name="Ghost", amount_ngn=10_000, confidence=0.9)
    service = IntakeService(
        make_agent(action), InMemoryLedger(), audit, InMemoryPaymentStore(), InMemoryDebtorStore()
    )

    reply = await service.handle_message("b", "Ghost paid 10k")

    assert reply.recorded_invoice_id is None
    assert (await audit.entries("b"))[0].decision is Decision.asked


async def test_contact_saves_the_debtors_number(make_agent) -> None:
    debtors, audit = InMemoryDebtorStore(), InMemoryAuditLog()
    action = IntakeAction(kind="contact", debtor_name="Chidi", phone="08031234567", confidence=0.95)
    service = IntakeService(
        make_agent(action), InMemoryLedger(), audit, InMemoryPaymentStore(), debtors
    )

    reply = await service.handle_message("b", "Chidi's number is 08031234567")

    assert "2348031234567" in reply.text  # stored + shown in canonical wa_id form
    saved = await debtors.find("b", "chidi")  # case-insensitive lookup
    assert saved is not None and saved.phone == "2348031234567"
    assert (await audit.entries("b"))[0].decision is Decision.noted


async def test_contact_without_a_number_asks(make_agent) -> None:
    debtors, audit = InMemoryDebtorStore(), InMemoryAuditLog()
    action = IntakeAction(kind="contact", debtor_name="Chidi", confidence=0.9)
    service = IntakeService(
        make_agent(action), InMemoryLedger(), audit, InMemoryPaymentStore(), debtors
    )

    reply = await service.handle_message("b", "save Chidi's contact")

    assert "number" in reply.text.lower()
    assert await debtors.find("b", "Chidi") is None  # nothing saved without a phone
    assert (await audit.entries("b"))[0].decision is Decision.asked


async def test_first_message_from_new_sender_gets_welcome(make_agent) -> None:
    # First contact: welcome the owner, but still act on the message itself.
    action = IntakeAction(
        kind="create", debtor_name="Chidi", amount_ngn=50_000, item="rice", confidence=0.95
    )
    ledger, audit = InMemoryLedger(), InMemoryAuditLog()
    service = IntakeService(
        make_agent(action), ledger, audit, InMemoryPaymentStore(), InMemoryDebtorStore()
    )

    reply = await service.handle_message("new-owner", "Chidi owes 50k for rice")

    assert reply.welcome == WELCOME
    assert reply.text.startswith("Noted:")
    assert len(await ledger.open_invoices("new-owner")) == 1


def _service(agent, audit=None) -> IntakeService:
    return IntakeService(
        agent,
        InMemoryLedger(),
        audit or InMemoryAuditLog(),
        InMemoryPaymentStore(),
        InMemoryDebtorStore(),
    )


async def test_first_greeting_gets_the_welcome_alone(make_agent) -> None:
    # "Hi" has nothing to act on, and the welcome already says what to send, so it
    # is the whole reply. Later greetings get a short nudge, not the welcome again.
    audit = InMemoryAuditLog()
    service = _service(make_agent(IntakeAction(kind="greeting", confidence=0.9)), audit)

    first = await service.handle_message("biz1", "Hi Orviqo")
    second = await service.handle_message("biz1", "good morning")

    assert (first.text, first.welcome) == (WELCOME, None)
    assert second.welcome is None and second.text.startswith("Hi! Tell me about a debt")
    assert [e.decision for e in await audit.entries("biz1")] == [Decision.answered] * 2


async def test_first_vague_debt_gets_the_welcome_and_the_question(make_agent) -> None:
    # "Mama Nkechi never paid" as a first message: welcome them, AND ask how much,
    # so the rigor gate is visible from the very first exchange.
    action = IntakeAction(
        kind="clarify", clarify="How much does Mama Nkechi owe you?", confidence=0.4
    )
    service = _service(make_agent(action))

    reply = await service.handle_message("biz1", "Mama Nkechi never paid")

    assert reply.welcome == WELCOME
    assert reply.text == "How much does Mama Nkechi owe you?"


def _prior_turn(business_id: str) -> AuditEntry:
    return AuditEntry(
        business_id=business_id,
        message="Hi",
        decision=Decision.asked,
        confidence=0.3,
        reason=WELCOME,
    )
