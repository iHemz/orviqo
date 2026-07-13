"""Terminal entry point — try the intake service without any WhatsApp wiring.

Installed as the ``orviqo`` console script (see pyproject ``[project.scripts]``),
so after ``pip install -e .`` you run:

    orviqo "Chidi owes 150k for the generator, due Friday"
    orviqo                      # runs the built-in examples
    python -m orviqo "..."      # equivalent
"""

from __future__ import annotations

import argparse
import asyncio

from orviqo.adapters.audit import InMemoryAuditLog
from orviqo.adapters.ledger import InMemoryLedger
from orviqo.agents.intake import PydanticAIIntakeAgent
from orviqo.config import ConfigError, bootstrap
from orviqo.services.intake_service import IntakeService

_EXAMPLES = [
    "Randi owes 250k, due Friday",
    "The debt is for a generator",  # should UPDATE the Randi invoice, not re-ask
    "Mama Nkechi never paid",  # ambiguous -> should ask
]


async def _run(messages: list[str]) -> None:
    settings = bootstrap()
    service = IntakeService(
        agent=PydanticAIIntakeAgent(),
        ledger=InMemoryLedger(),
        audit=InMemoryAuditLog(),
        confidence_threshold=settings.intake_confidence_threshold,
    )
    for msg in messages:
        reply = await service.handle_message("cli-demo", msg)
        print(f"\n> {msg}\n{reply.text}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="orviqo", description="Try the intake agent from the terminal."
    )
    parser.add_argument(
        "message", nargs="*", help="A debt message. Omit to run the built-in examples."
    )
    args = parser.parse_args()
    messages = [" ".join(args.message)] if args.message else _EXAMPLES

    try:
        asyncio.run(_run(messages))
    except ConfigError as exc:
        raise SystemExit(f"error: {exc}") from exc


if __name__ == "__main__":
    main()
