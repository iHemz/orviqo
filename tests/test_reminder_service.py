"""ReminderService — overdue detection, per-owner digest, and dedup, with fakes."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from orviqo.adapters.businesses import InMemoryBusinessStore
from orviqo.adapters.ledger import InMemoryLedger
from orviqo.adapters.reminders import InMemoryReminderStore
from orviqo.domain.models import Invoice, ParsedInvoice
from orviqo.services.reminder_service import ReminderService, digest_template_params

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


# --- the 24-hour window: free text inside it, the template outside ---------


class TemplateCapturingWhatsApp(CapturingWhatsApp):
    def __init__(self) -> None:
        super().__init__()
        self.templates: list[tuple[str, str, list[str]]] = []

    async def send_template(self, to: str, name: str, params: list[str], lang: str) -> str:
        self.templates.append((to, name, params))
        return "wamid.1"


async def _owing_owner(
    last_message: datetime | None,
) -> tuple[InMemoryLedger, InMemoryBusinessStore]:
    ledger, businesses = InMemoryLedger(), InMemoryBusinessStore()
    await _add(ledger, "biz1", "Randi", 250_000, date(2026, 7, 17))
    await _add(ledger, "biz1", "Chidi", 80_000, date(2026, 7, 19))
    if last_message is not None:
        await businesses.note_message("biz1", last_message, "Ada O.")
    return ledger, businesses


async def test_an_owner_who_wrote_today_gets_the_full_digest_as_text() -> None:
    ledger, businesses = await _owing_owner(NOW - timedelta(hours=3))
    wa = TemplateCapturingWhatsApp()
    service = ReminderService(
        ledger, InMemoryReminderStore(), wa, businesses=businesses, template_name="owner_digest"
    )

    assert await service.run(NOW) == 1
    assert wa.templates == [] and "Randi" in wa.sent[0][1] and "Chidi" in wa.sent[0][1]


async def test_an_owner_outside_the_window_gets_the_template() -> None:
    ledger, businesses = await _owing_owner(NOW - timedelta(days=2))
    wa, reminders = TemplateCapturingWhatsApp(), InMemoryReminderStore()
    service = ReminderService(
        ledger, reminders, wa, businesses=businesses, template_name="owner_digest"
    )

    assert await service.run(NOW) == 1
    assert wa.sent == []
    assert wa.templates == [
        ("biz1", "owner_digest", ["Ada O.", "2", "₦330,000", "Randi, ₦250,000, 3 days overdue"])
    ]
    assert await reminders.last_reminder_at("biz1") == NOW


async def test_without_a_template_an_owner_outside_the_window_is_skipped() -> None:
    ledger, businesses = await _owing_owner(None)  # never messaged: no profile at all
    wa, reminders = TemplateCapturingWhatsApp(), InMemoryReminderStore()
    service = ReminderService(ledger, reminders, wa, businesses=businesses)

    assert await service.run(NOW) == 0
    assert wa.sent == [] and wa.templates == []
    assert await reminders.last_reminder_at("biz1") is None  # tried again next run


def test_template_params_fit_on_one_line() -> None:
    ledger_free = [
        Invoice(
            id="i1",
            business_id="b",
            debtor_name="Ngozi",
            amount_ngn=5_000,
            due_date=date(2026, 7, 19),
            confidence=1.0,
        )
    ]
    params = digest_template_params(None, ledger_free, date(2026, 7, 20))
    assert params == ["there", "1", "₦5,000", "Ngozi, ₦5,000, 1 day overdue"]
    assert not any("\n" in p for p in params)  # WhatsApp rejects line breaks in params
