"""The reminder use-case: nudge owners about overdue debts, on a schedule.

Finds overdue open invoices, groups them by business (owner), and sends each
owner a digest — at most once per cadence. Depends only on ports, so it is fully
unit-testable with fakes (no DB, no WhatsApp). The scheduled worker in
``orviqo.worker`` drives it in production.

WhatsApp only delivers free-form text to someone who messaged the business in
the last 24 hours. So an owner who wrote recently gets the full digest as text
(free); anyone else gets the approved digest template, a one-line summary whose
reply opens the window again. Without a template those owners are skipped
rather than sent a text WhatsApp would drop. Debtors are chased separately, by
``ChaseService``.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from orviqo.adapters.businesses import BusinessStore
from orviqo.adapters.ledger import LedgerStore
from orviqo.adapters.reminders import ReminderStore
from orviqo.adapters.whatsapp import WhatsAppClient
from orviqo.domain.demo import is_demo
from orviqo.domain.models import Invoice

log = logging.getLogger("orviqo.reminders")

_MIN_INTERVAL_HOURS = 20


def _days_overdue(inv: Invoice, today: date) -> int:
    return (today - inv.due_date).days if inv.due_date else 0


def _digest(invoices: list[Invoice], today: date) -> str:
    total = sum(inv.amount_ngn or 0 for inv in invoices)
    lines = []
    for inv in invoices:
        item = inv.item or "unspecified"
        days = _days_overdue(inv, today)
        lines.append(f"- {inv.debtor_name}: ₦{inv.amount_ngn:,} for {item} ({days}d overdue)")
    body = "\n".join(lines)
    return (
        f"Reminder: you have {len(invoices)} overdue debt(s) totalling ₦{total:,}.\n"
        f"{body}\nReply to manage them."
    )


def digest_template_params(name: str | None, invoices: list[Invoice], today: date) -> list[str]:
    """The digest template's {{1}}..{{4}}: who, how many, how much, and the oldest.

    Template parameters can't hold line breaks, so this is the one-line summary;
    the owner's reply opens the 24-hour window, and asking gets the full list.
    """
    total = sum(inv.amount_ngn or 0 for inv in invoices)
    oldest = max(invoices, key=lambda inv: _days_overdue(inv, today))
    days = _days_overdue(oldest, today)
    when = "1 day" if days == 1 else f"{days} days"
    return [
        name or "there",
        str(len(invoices)),
        f"₦{total:,}",
        f"{oldest.debtor_name}, ₦{oldest.amount_ngn:,}, {when} overdue",
    ]


class ReminderService:
    def __init__(
        self,
        ledger: LedgerStore,
        reminders: ReminderStore,
        whatsapp: WhatsAppClient,
        min_interval_hours: float = _MIN_INTERVAL_HOURS,
        *,
        businesses: BusinessStore | None = None,
        template_name: str = "",
        template_lang: str = "en_US",
    ) -> None:
        # Without a business store there is no way to know who is inside the
        # 24-hour window, so every digest goes as text (the CLI, older callers).
        self._ledger = ledger
        self._reminders = reminders
        self._whatsapp = whatsapp
        self._min_interval = timedelta(hours=min_interval_hours)
        self._businesses = businesses
        self._template_name = template_name
        self._template_lang = template_lang

    async def run(self, now: datetime) -> int:
        """Send due digests. Returns how many owners were reminded."""
        by_business: dict[str, list[Invoice]] = defaultdict(list)
        for inv in await self._ledger.overdue(now.date()):
            if is_demo(inv.business_id):
                continue  # a web-demo visitor is not a WhatsApp user to remind
            by_business[inv.business_id].append(inv)

        sent = 0
        for business_id, invoices in by_business.items():
            if await self._reminded_recently(business_id, now):
                continue
            if await self._send(business_id, invoices, now):
                await self._reminders.record(business_id, now)
                sent += 1
        return sent

    async def _send(self, business_id: str, invoices: list[Invoice], now: datetime) -> bool:
        today = now.date()
        if self._businesses is None:
            await self._whatsapp.send_text(business_id, _digest(invoices, today))
            return True
        profile = await self._businesses.get(business_id)
        if profile is not None and profile.can_message_freely(now):
            await self._whatsapp.send_text(business_id, _digest(invoices, today))
            return True
        if not self._template_name:
            log.info("digest skipped: owner outside the 24h window and no digest template")
            return False
        name = profile.display_name if profile else None
        params = digest_template_params(name, invoices, today)
        await self._whatsapp.send_template(
            business_id, self._template_name, params, self._template_lang
        )
        return True

    async def _reminded_recently(self, business_id: str, now: datetime) -> bool:
        last = await self._reminders.last_reminder_at(business_id)
        if last is None:
            return False
        if last.tzinfo is None:  # SQLite returns naive datetimes; assume UTC
            last = last.replace(tzinfo=UTC)
        return now - last < self._min_interval
