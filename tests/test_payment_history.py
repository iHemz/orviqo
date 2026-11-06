"""'How much has Chidi paid?' is answered from the payments, across all his debts."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date

import pytest_asyncio
from orviqo.adapters.audit import InMemoryAuditLog
from orviqo.adapters.db import create_schema, make_engine
from orviqo.adapters.debtors import InMemoryDebtorStore
from orviqo.adapters.ledger import InMemoryLedger
from orviqo.adapters.payments import InMemoryPaymentStore
from orviqo.adapters.sql_ledger import SqlAlchemyLedger
from orviqo.adapters.sql_payments import SqlAlchemyPaymentStore
from orviqo.domain.intake import IntakeAction
from orviqo.domain.models import ParsedInvoice
from orviqo.services.intake_service import IntakeService

OWNER = "2348031234567"


def _debt(name: str, amount: int, item: str) -> ParsedInvoice:
    return ParsedInvoice(
        debtor_name=name, amount_ngn=amount, item=item, due_date=date(2026, 11, 1), confidence=1.0
    )


async def _intake(make_agent, ledger, payments, action: IntakeAction, text: str):
    service = IntakeService(
        make_agent(action), ledger, InMemoryAuditLog(), payments, InMemoryDebtorStore()
    )
    return await service.handle_message(OWNER, text)


async def test_history_lists_each_payment_and_what_is_still_owed(make_agent) -> None:
    ledger, payments = InMemoryLedger(), InMemoryPaymentStore()
    lace = await ledger.add(_debt("Chidi", 100_000, "lace"), OWNER)
    rice = await ledger.add(_debt("Chidi", 30_000, "rice"), OWNER)
    await ledger.add(_debt("Ada", 50_000, "ankara"), OWNER)  # someone else's
    pay_lace = IntakeAction(kind="payment", invoice_id=lace.id, amount_ngn=40_000, confidence=0.9)
    pay_rice = IntakeAction(kind="payment", invoice_id=rice.id, paid_in_full=True, confidence=0.9)
    await _intake(make_agent, ledger, payments, pay_lace, "Chidi paid 40k for the lace")
    await _intake(make_agent, ledger, payments, pay_rice, "Chidi cleared the rice")

    reply = await _intake(
        make_agent,
        ledger,
        payments,
        IntakeAction(kind="history", debtor_name="chidi", confidence=0.9),
        "how much has chidi paid?",
    )

    assert reply.text.startswith("Chidi has paid ₦70,000 in total:")
    assert "₦40,000 for lace\n" in reply.text and "₦30,000 for rice (settled)" in reply.text
    assert reply.text.endswith("Still owed: ₦60,000.")
    assert "ankara" not in reply.text


async def test_history_without_payments_or_debts(make_agent) -> None:
    ledger, payments = InMemoryLedger(), InMemoryPaymentStore()
    await ledger.add(_debt("Chidi", 100_000, "lace"), OWNER)
    ask = IntakeAction(kind="history", debtor_name="Chidi", confidence=0.9)

    none_yet = await _intake(make_agent, ledger, payments, ask, "Chidi's payments?")
    stranger = await _intake(
        make_agent,
        ledger,
        payments,
        IntakeAction(kind="history", debtor_name="Bola", confidence=0.9),
        "Bola's payments?",
    )

    assert none_yet.text == "No payments recorded from Chidi yet. Still owed: ₦100,000."
    assert stranger.text == "You have no debts recorded for Bola."


@pytest_asyncio.fixture
async def engine(tmp_path) -> AsyncIterator:
    engine = make_engine(f"sqlite+aiosqlite:///{(tmp_path / 'p.db').as_posix()}")
    await create_schema(engine)
    try:
        yield engine
    finally:
        await engine.dispose()


async def test_sql_ledger_and_payments_find_a_debtors_history(engine) -> None:
    ledger, payments = SqlAlchemyLedger(engine), SqlAlchemyPaymentStore(engine)
    lace = await ledger.add(_debt("Chidi", 100_000, "lace"), OWNER)
    await ledger.add(_debt("Chidi", 30_000, "rice"), "someone-else")
    await payments.record(lace.id, OWNER, 40_000)

    found = await ledger.for_debtor(OWNER, "CHIDI")
    assert [i.id for i in found] == [lace.id]
    assert [p.amount_ngn for p in await payments.for_invoices([lace.id, "nope"])] == [40_000]
    assert await payments.for_invoices([]) == []
