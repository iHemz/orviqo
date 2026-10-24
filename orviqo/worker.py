"""Collections worker — the scheduled process that chases overdue debts.

Once a day it (1) sends each owner a digest of their overdue invoices and (2)
chases each debtor with a saved contact directly. On Vercel a daily Cron Job hits
``/cron/collections``, which calls ``run_once``; on a container host (Fly) it runs
as a long-lived second process instead (see fly.toml ``[processes]``).

    python -m orviqo.worker            # loop forever (container worker process)
    python -m orviqo.worker --once     # a single pass, then exit (cron / manual)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import UTC, datetime

from orviqo.adapters.db import make_engine
from orviqo.adapters.sql_chases import SqlAlchemyChaseStore
from orviqo.adapters.sql_debtors import SqlAlchemyDebtorStore
from orviqo.adapters.sql_ledger import SqlAlchemyLedger
from orviqo.adapters.sql_reminders import SqlAlchemyReminderStore
from orviqo.adapters.whatsapp import make_whatsapp_client
from orviqo.config import settings
from orviqo.services.chase_service import ChaseService
from orviqo.services.reminder_service import ReminderService

log = logging.getLogger("orviqo.worker")


async def run_once() -> tuple[int, int]:
    """One collections pass: returns (owner digests sent, debtors chased).

    Needs no LLM, so it doesn't require an API key: only the database and WhatsApp.
    """
    engine = make_engine(settings.database_url)
    whatsapp = make_whatsapp_client(settings)
    ledger = SqlAlchemyLedger(engine)
    reminders = ReminderService(
        ledger=ledger,
        reminders=SqlAlchemyReminderStore(engine),
        whatsapp=whatsapp,
    )
    chases = ChaseService(
        ledger=ledger,
        debtors=SqlAlchemyDebtorStore(engine),
        chases=SqlAlchemyChaseStore(engine),
        whatsapp=whatsapp,
        template_name=settings.whatsapp_chase_template,
        template_lang=settings.whatsapp_template_lang,
    )
    now = datetime.now(UTC)
    try:
        return await reminders.run(now), await chases.run(now)
    finally:
        await whatsapp.aclose()
        await engine.dispose()


async def run_forever(interval_hours: float) -> None:
    while True:
        try:
            reminded, chased = await run_once()
            log.info("collections run: %d owner digest(s), %d debtor chase(s)", reminded, chased)
        except Exception:
            log.exception("collections run failed")
        await asyncio.sleep(interval_hours * 3600)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(prog="orviqo-worker", description="Collections worker.")
    parser.add_argument("--once", action="store_true", help="Run a single pass and exit.")
    parser.add_argument("--interval-hours", type=float, default=24.0)
    args = parser.parse_args()

    if args.once:
        reminded, chased = asyncio.run(run_once())
        print(f"sent {reminded} digest(s), {chased} chase(s)")
    else:
        asyncio.run(run_forever(args.interval_hours))


if __name__ == "__main__":
    main()
