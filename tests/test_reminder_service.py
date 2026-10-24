"""ReminderService — overdue detection, per-owner digest, and dedup, with fakes."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from orviqo.adapters.ledger import InMemoryLedger
from orviqo.adapters.reminders import InMemoryReminderStore
from orviqo.domain.models import ParsedInvoice
from orviqo.services.reminder_service import ReminderService

NOW = datetime(2026, 7, 20, 9, 0, tzinfo=UTC)


class CapturingWhatsApp:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_text(self, to: str, text: str) -> None:
        self.sent.append((to, text))

    async def aclose(self) -> None:
        return None


async def _add(ledger: InMemoryLedger, business: str, debtor: str, amount: int, due: date) -> None:
    await ledger.add(
        ParsedInvoice(debtor_name=debtor, amount_ngn=amount, due_date=due, confidence=0.98),
        business,
    )


async def test_sends_a_digest_for_overdue_debts() -> None:
    ledger, reminders, wa = InMemoryLedger(), InMemoryReminderStore(), CapturingWhatsApp()
    await _add(ledger, "biz1", "Randi", 250_000, date(2026, 7, 17))
    service = ReminderService(ledger, reminders, wa)

    sent = await service.run(NOW)

    assert sent == 1
    to, text = wa.sent[0]
    assert to == "biz1"
    assert "Randi" in text and "overdue" in text


async def test_skips_when_reminded_recently() -> None:
    ledger, reminders, wa = InMemoryLedger(), InMemoryReminderStore(), CapturingWhatsApp()
    await _add(ledger, "biz1", "Randi", 250_000, date(2026, 7, 17))
    await reminders.record("biz1", NOW - timedelta(hours=2))
    service = ReminderService(ledger, reminders, wa)

    assert await service.run(NOW) == 0
    assert wa.sent == []


async def test_does_not_remind_when_nothing_is_overdue() -> None:
    ledger, reminders, wa = InMemoryLedger(), InMemoryReminderStore(), CapturingWhatsApp()
    await _add(ledger, "biz1", "Randi", 250_000, date(2026, 7, 30))  # due in the future
    service = ReminderService(ledger, reminders, wa)

    assert await service.run(NOW) == 0


async def test_one_digest_per_business_covering_all_their_debts() -> None:
    ledger, reminders, wa = InMemoryLedger(), InMemoryReminderStore(), CapturingWhatsApp()
    await _add(ledger, "biz1", "Randi", 250_000, date(2026, 7, 17))
    await _add(ledger, "biz1", "Chidi", 80_000, date(2026, 7, 18))
    await _add(ledger, "biz2", "Ada", 50_000, date(2026, 7, 15))
    service = ReminderService(ledger, reminders, wa)

    sent = await service.run(NOW)

    assert sent == 2  # one digest per business, not per debt
    assert sorted(to for to, _ in wa.sent) == ["biz1", "biz2"]
    biz1_text = next(text for to, text in wa.sent if to == "biz1")
    assert "Randi" in biz1_text and "Chidi" in biz1_text


async def test_never_reminds_a_web_demo_business() -> None:
    # A demo visitor's business id is not a WhatsApp number; never message it.
    ledger, reminders, wa = InMemoryLedger(), InMemoryReminderStore(), CapturingWhatsApp()
    await _add(ledger, "demo:" + "a" * 32, "Randi", 250_000, date(2026, 7, 17))
    service = ReminderService(ledger, reminders, wa)

    assert await service.run(NOW) == 0
    assert wa.sent == []
