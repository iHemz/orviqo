"""ChaseService — chase debtors directly for overdue debts, with fakes.

Covers the consent gates (opt-out, no contact, template off) and dedup, so the
rules that decide *whether* to message a debtor are pinned without WhatsApp or a DB.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from orviqo.adapters.chases import InMemoryChaseStore
from orviqo.adapters.debtors import InMemoryDebtorStore
from orviqo.adapters.ledger import InMemoryLedger
from orviqo.domain.models import ParsedInvoice
from orviqo.services.chase_service import ChaseService

NOW = datetime(2026, 7, 20, 9, 0, tzinfo=UTC)
TEMPLATE = "orviqo_debt_reminder"


class CapturingWhatsApp:
    def __init__(self) -> None:
        self.templates: list[tuple[str, str, list[str], str]] = []

    async def send_text(self, to: str, text: str) -> None:  # unused by chasing
        raise AssertionError("chasing must use a template, not free text")

    async def send_template(self, to: str, name: str, params: list[str], lang: str) -> None:
        self.templates.append((to, name, params, lang))

    async def aclose(self) -> None:
        return None


async def _overdue(ledger: InMemoryLedger, business: str, debtor: str, amount: int) -> None:
    await ledger.add(
        ParsedInvoice(
            debtor_name=debtor, amount_ngn=amount, due_date=date(2026, 7, 15), confidence=0.98
        ),
        business,
    )


def _service(ledger, debtors, chases, wa, template=TEMPLATE) -> ChaseService:
    return ChaseService(ledger, debtors, chases, wa, template_name=template)


async def test_chases_a_debtor_with_a_saved_contact() -> None:
    ledger, debtors, chases, wa = (
        InMemoryLedger(),
        InMemoryDebtorStore(),
        InMemoryChaseStore(),
        CapturingWhatsApp(),
    )
    await _overdue(ledger, "biz1", "Chidi", 80_000)
    await debtors.upsert("biz1", "Chidi", "08031234567")

    sent = await _service(ledger, debtors, chases, wa).run(NOW)

    assert sent == 1
    to, name, params, _ = wa.templates[0]
    assert to == "2348031234567" and name == TEMPLATE
    assert params[0] == "Chidi" and "80,000" in params[1]


async def test_skips_a_debtor_who_opted_out() -> None:
    ledger, debtors, chases, wa = (
        InMemoryLedger(),
        InMemoryDebtorStore(),
        InMemoryChaseStore(),
        CapturingWhatsApp(),
    )
    await _overdue(ledger, "biz1", "Chidi", 80_000)
    await debtors.upsert("biz1", "Chidi", "08031234567")
    await debtors.opt_out("biz1", "Chidi")

    assert await _service(ledger, debtors, chases, wa).run(NOW) == 0
    assert wa.templates == []


async def test_skips_a_debtor_with_no_saved_contact() -> None:
    ledger, debtors, chases, wa = (
        InMemoryLedger(),
        InMemoryDebtorStore(),
        InMemoryChaseStore(),
        CapturingWhatsApp(),
    )
    await _overdue(ledger, "biz1", "Chidi", 80_000)  # no contact saved

    assert await _service(ledger, debtors, chases, wa).run(NOW) == 0


async def test_does_not_chase_the_same_debt_twice_in_a_window() -> None:
    ledger, debtors, chases, wa = (
        InMemoryLedger(),
        InMemoryDebtorStore(),
        InMemoryChaseStore(),
        CapturingWhatsApp(),
    )
    await _overdue(ledger, "biz1", "Chidi", 80_000)
    await debtors.upsert("biz1", "Chidi", "08031234567")
    service = _service(ledger, debtors, chases, wa)

    assert await service.run(NOW) == 1
    assert await service.run(NOW + timedelta(hours=2)) == 0  # too soon
    assert len(wa.templates) == 1


async def test_no_op_when_no_template_is_configured() -> None:
    ledger, debtors, chases, wa = (
        InMemoryLedger(),
        InMemoryDebtorStore(),
        InMemoryChaseStore(),
        CapturingWhatsApp(),
    )
    await _overdue(ledger, "biz1", "Chidi", 80_000)
    await debtors.upsert("biz1", "Chidi", "08031234567")

    assert await _service(ledger, debtors, chases, wa, template="").run(NOW) == 0
    assert wa.templates == []


async def test_never_chases_from_a_web_demo_business() -> None:
    # Even if a demo debtor somehow had a saved number, a demo must never message a phone.
    ledger, debtors, chases, wa = (
        InMemoryLedger(),
        InMemoryDebtorStore(),
        InMemoryChaseStore(),
        CapturingWhatsApp(),
    )
    demo = "demo:" + "a" * 32
    await _overdue(ledger, demo, "Chidi", 80_000)
    await debtors.upsert(demo, "Chidi", "08031234567")

    assert await _service(ledger, debtors, chases, wa).run(NOW) == 0
    assert wa.templates == []
