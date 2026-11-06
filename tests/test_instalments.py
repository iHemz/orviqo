"""Instalments: "Chidi will pay 20k every Friday".

The debt's due date is always the next instalment's, so a missed instalment is
just an overdue debt: chased for the instalment, not the whole balance. Each
payment moves it on one period per full instalment paid.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from orviqo.adapters.audit import InMemoryAuditLog
from orviqo.adapters.chases import InMemoryChaseStore
from orviqo.adapters.db import create_schema, make_engine
from orviqo.adapters.debtors import InMemoryDebtorStore
from orviqo.adapters.ledger import InMemoryLedger
from orviqo.adapters.payments import InMemoryPaymentStore
from orviqo.adapters.plans import InMemoryPlanStore
from orviqo.adapters.sql_plans import SqlAlchemyPlanStore
from orviqo.domain.intake import IntakeAction
from orviqo.domain.models import Invoice, ParsedInvoice, PaymentPlan
from orviqo.services.chase_service import ChaseService
from orviqo.services.intake_service import IntakeService

OWNER = "2348031234567"
TODAY = date(2026, 11, 6)  # a Friday
FRIDAY = date(2026, 11, 13)


@pytest.mark.parametrize(
    ("every", "due", "periods", "expected"),
    [
        ("week", FRIDAY, 1, date(2026, 11, 20)),
        ("week", FRIDAY, 0, FRIDAY),
        ("month", date(2026, 1, 31), 1, date(2026, 2, 28)),  # no 31 Feb
        ("month", date(2026, 11, 15), 3, date(2027, 2, 15)),  # across the year
    ],
)
def test_advance(every, due, periods, expected) -> None:
    plan = PaymentPlan(invoice_id="i", amount_ngn=20_000, every=every)
    assert plan.advance(due, periods) == expected


class _World:
    def __init__(self, make_agent) -> None:
        self.make_agent = make_agent
        self.ledger, self.payments = InMemoryLedger(), InMemoryPaymentStore()
        self.plans, self.audit = InMemoryPlanStore(), InMemoryAuditLog()

    async def say(self, action: IntakeAction, text: str = "…"):
        service = IntakeService(
            self.make_agent(action),
            self.ledger,
            self.audit,
            self.payments,
            InMemoryDebtorStore(),
            plans=self.plans,
            today=lambda: TODAY,
        )
        return await service.handle_message(OWNER, text)

    async def debt(self) -> Invoice:
        return await self.ledger.add(
            ParsedInvoice(
                debtor_name="Chidi",
                amount_ngn=100_000,
                item="lace",
                due_date=date(2026, 11, 1),
                confidence=1.0,
            ),
            OWNER,
        )

    async def invoice(self, invoice_id: str) -> Invoice:
        return next(i for i in await self.ledger.open_invoices(OWNER) if i.id == invoice_id)


def _plan(**fields) -> IntakeAction:
    return IntakeAction(kind="plan", debtor_name="Chidi", confidence=0.9, **fields)


def _paid(invoice_id: str, amount: int) -> IntakeAction:
    return IntakeAction(kind="payment", invoice_id=invoice_id, amount_ngn=amount, confidence=0.9)


async def test_a_plan_sets_the_next_due_date_and_shows_in_lists(make_agent) -> None:
    w = _World(make_agent)
    debt = await w.debt()

    reply = await w.say(
        _plan(amount_ngn=20_000, plan_every="week", due_date=FRIDAY), "20k every Friday"
    )

    assert "₦20,000 weekly, first on Fri 13 Nov" in reply.text and "(5 instalments)" in reply.text
    assert (await w.invoice(debt.id)).due_date == FRIDAY
    listed = await w.say(IntakeAction(kind="query", confidence=0.9), "who owes me?")
    assert "next ₦20,000 due 2026-11-13, paying ₦20,000 weekly" in listed.text


async def test_payments_move_the_plan_on_per_full_instalment(make_agent) -> None:
    w = _World(make_agent)
    debt = await w.debt()
    await w.say(_plan(amount_ngn=20_000, plan_every="week", due_date=FRIDAY))

    two = await w.say(_paid(debt.id, 40_000), "Chidi paid 40k")
    assert "Next instalment: ₦20,000 due Fri 27 Nov" in two.text
    assert (await w.invoice(debt.id)).due_date == date(2026, 11, 27)

    short = await w.say(_paid(debt.id, 5_000), "Chidi paid 5k")
    assert "less than the ₦20,000 instalment" in short.text and "Fri 27 Nov" in short.text

    rest = await w.say(_paid(debt.id, 55_000), "Chidi paid the rest")
    assert rest.text.startswith("Settled") and await w.plans.get(debt.id) is None


async def test_a_plan_asks_for_what_it_is_missing(make_agent) -> None:
    w = _World(make_agent)
    await w.debt()

    how = await w.say(_plan(due_date=FRIDAY), "Chidi will pay in instalments")
    when = await w.say(_plan(amount_ngn=20_000, plan_every="week"), "Chidi will pay 20k weekly")

    assert how.text == "How much will Chidi pay each time, and how often: weekly or monthly?"
    assert when.text == "When is Chidi's first instalment of ₦20,000?"
    assert await w.plans.for_invoices([i.id for i in await w.ledger.open_invoices(OWNER)]) == {}


async def test_a_missed_instalment_is_chased_for_the_instalment() -> None:
    class Capturing:
        params: list[str] = []

        async def send_template(self, to: str, name: str, params: list[str], lang: str) -> str:
            Capturing.params = params
            return "wamid.1"

    ledger, debtors, plans = InMemoryLedger(), InMemoryDebtorStore(), InMemoryPlanStore()
    debt = await ledger.add(
        ParsedInvoice(
            debtor_name="Chidi", amount_ngn=15_000, item="lace", due_date=FRIDAY, confidence=1.0
        ),
        OWNER,
    )
    await debtors.upsert(OWNER, "Chidi", "2348070000009")
    await plans.set(PaymentPlan(invoice_id=debt.id, amount_ngn=20_000, every="week"))
    service = ChaseService(
        ledger,
        debtors,
        InMemoryChaseStore(),
        Capturing(),  # type: ignore[arg-type]
        template_name="reminder",
        plans=plans,
    )

    assert await service.run(datetime(2026, 11, 13, 9, tzinfo=UTC)) == 0  # not missed yet
    assert await service.run(datetime(2026, 11, 14, 9, tzinfo=UTC)) == 1
    assert Capturing.params[2] == "₦15,000"  # the last instalment is what's left


@pytest_asyncio.fixture
async def sql_plans(tmp_path) -> AsyncIterator[SqlAlchemyPlanStore]:
    engine = make_engine(f"sqlite+aiosqlite:///{(tmp_path / 'pl.db').as_posix()}")
    await create_schema(engine)
    try:
        yield SqlAlchemyPlanStore(engine)
    finally:
        await engine.dispose()


async def test_sql_plans(sql_plans: SqlAlchemyPlanStore) -> None:
    assert await sql_plans.get("i1") is None and await sql_plans.for_invoices([]) == {}
    await sql_plans.set(PaymentPlan(invoice_id="i1", amount_ngn=20_000, every="week"))
    await sql_plans.set(PaymentPlan(invoice_id="i1", amount_ngn=50_000, every="month"))

    plan = await sql_plans.get("i1")
    assert plan is not None and (plan.amount_ngn, plan.every) == (50_000, "month")
    await sql_plans.remove("i1")
    assert await sql_plans.get("i1") is None
