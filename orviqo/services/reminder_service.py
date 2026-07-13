"""The reminder use-case: nudge owners about overdue debts, on a schedule.

Finds overdue open invoices, groups them by business (owner), and sends each
owner a digest — at most once per cadence. Depends only on ports, so it is fully
unit-testable with fakes (no DB, no WhatsApp). The scheduled worker in
``orviqo.worker`` drives it in production.

v1 nudges the *owner*. Chasing the *debtor* (needs a phone number + WhatsApp
opt-in per debtor) is a later step.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from orviqo.adapters.ledger import LedgerStore
from orviqo.adapters.reminders import ReminderStore
from orviqo.adapters.whatsapp import WhatsAppClient
from orviqo.domain.models import Invoice

_MIN_INTERVAL_HOURS = 20


def _digest(invoices: list[Invoice], today: date) -> str:
    total = sum(inv.amount_ngn or 0 for inv in invoices)
    lines = []
    for inv in invoices:
        days = (today - inv.due_date).days if inv.due_date else 0
        item = inv.item or "unspecified"
        lines.append(f"- {inv.debtor_name}: ₦{inv.amount_ngn:,} for {item} ({days}d overdue)")
    body = "\n".join(lines)
    return (
        f"Reminder: you have {len(invoices)} overdue debt(s) totalling ₦{total:,}.\n"
        f"{body}\nReply to manage them."
    )


class ReminderService:
    def __init__(
        self,
        ledger: LedgerStore,
        reminders: ReminderStore,
        whatsapp: WhatsAppClient,
        min_interval_hours: float = _MIN_INTERVAL_HOURS,
    ) -> None:
        self._ledger = ledger
        self._reminders = reminders
        self._whatsapp = whatsapp
        self._min_interval = timedelta(hours=min_interval_hours)

    async def run(self, now: datetime) -> int:
        """Send due digests. Returns how many owners were reminded."""
        by_business: dict[str, list[Invoice]] = defaultdict(list)
        for inv in await self._ledger.overdue(now.date()):
            by_business[inv.business_id].append(inv)

        sent = 0
        for business_id, invoices in by_business.items():
            if await self._reminded_recently(business_id, now):
                continue
            await self._whatsapp.send_text(business_id, _digest(invoices, now.date()))
            await self._reminders.record(business_id, now)
            sent += 1
        return sent

    async def _reminded_recently(self, business_id: str, now: datetime) -> bool:
        last = await self._reminders.last_reminder_at(business_id)
        if last is None:
            return False
        if last.tzinfo is None:  # SQLite returns naive datetimes; assume UTC
            last = last.replace(tzinfo=UTC)
        return now - last < self._min_interval
