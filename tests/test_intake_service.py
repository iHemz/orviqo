"""The rigor gate is the product's core promise — so it's the core test."""

from __future__ import annotations

from datetime import date

from orviqo.adapters.ledger import InMemoryLedger
from orviqo.domain.models import ParsedInvoice
from orviqo.services.intake_service import IntakeService


async def test_confident_message_is_recorded(make_parser) -> None:
    parsed = ParsedInvoice(
        debtor_name="Chidi",
        amount_ngn=150_000,
        item="generator",
        due_date=date(2026, 7, 17),
        confidence=0.98,
    )
    ledger = InMemoryLedger()
    service = IntakeService(make_parser(parsed), ledger)

    reply = await service.handle_message("biz1", "Chidi owes 150k...")

    assert reply.recorded_invoice_id is not None
    assert "150,000" in reply.text
    assert (await ledger.open_invoices("biz1"))[0].debtor_name == "Chidi"


async def test_low_confidence_asks_and_records_nothing(make_parser) -> None:
    parsed = ParsedInvoice(
        debtor_name="Mama Nkechi",
        amount_ngn=None,
        confidence=0.4,
        clarify="How much does she owe you?",
    )
    ledger = InMemoryLedger()
    service = IntakeService(make_parser(parsed), ledger)

    reply = await service.handle_message("biz1", "Mama Nkechi never paid")

    assert reply.recorded_invoice_id is None
    assert reply.text == "How much does she owe you?"
    assert await ledger.open_invoices("biz1") == []


async def test_missing_amount_is_never_recorded_even_when_confident(make_parser) -> None:
    # The boundary guard: high confidence must not override a null amount.
    parsed = ParsedInvoice(debtor_name="Tunde", amount_ngn=None, confidence=0.95)
    ledger = InMemoryLedger()
    service = IntakeService(make_parser(parsed), ledger)

    reply = await service.handle_message("biz1", "Tunde owes me")

    assert reply.recorded_invoice_id is None
    assert await ledger.open_invoices("biz1") == []
