"""Reminder worker — the scheduled process that chases overdue debts.

Runs on Fly as a second process (see fly.toml ``[processes]``): a long-running
loop that, once a day, sends each owner a digest of their overdue invoices.

    python -m orviqo.worker            # loop forever (the Fly worker process)
    python -m orviqo.worker --once     # a single pass, then exit (cron / manual)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import UTC, datetime

from orviqo.adapters.db import make_engine
from orviqo.adapters.sql_ledger import SqlAlchemyLedger
from orviqo.adapters.sql_reminders import SqlAlchemyReminderStore
from orviqo.adapters.whatsapp import make_whatsapp_client
from orviqo.config import bootstrap, settings
from orviqo.services.reminder_service import ReminderService

log = logging.getLogger("orviqo.worker")


async def run_once() -> int:
    bootstrap()
    engine = make_engine(settings.database_url)
    whatsapp = make_whatsapp_client(settings)
    service = ReminderService(
        ledger=SqlAlchemyLedger(engine),
        reminders=SqlAlchemyReminderStore(engine),
        whatsapp=whatsapp,
    )
    try:
        return await service.run(datetime.now(UTC))
    finally:
        await whatsapp.aclose()
        await engine.dispose()


async def run_forever(interval_hours: float) -> None:
    while True:
        try:
            sent = await run_once()
            log.info("reminder run: sent %d digest(s)", sent)
        except Exception:
            log.exception("reminder run failed")
        await asyncio.sleep(interval_hours * 3600)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(prog="orviqo-worker", description="Reminder worker.")
    parser.add_argument("--once", action="store_true", help="Run a single pass and exit.")
    parser.add_argument("--interval-hours", type=float, default=24.0)
    args = parser.parse_args()

    if args.once:
        print(f"sent {asyncio.run(run_once())} digest(s)")
    else:
        asyncio.run(run_forever(args.interval_hours))


if __name__ == "__main__":
    main()
