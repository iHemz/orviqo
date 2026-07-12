"""Try the intake agent from the terminal — no WhatsApp needed.

    python scripts/try_intake.py "Chidi owes 150k for the generator, due Friday"
    python scripts/try_intake.py            # runs a few built-in examples

Requires ANTHROPIC_API_KEY in your environment or .env.
"""

from __future__ import annotations

import asyncio
import sys

from orviqo.agents.intake import parse_message

EXAMPLES = [
    "Chidi owes 150k for the generator, due Friday",
    "Mama Nkechi never paid for the rice",  # ambiguous amount -> should ask
    "Tunde 1.5m balance on the contract, end of month",
]


async def main() -> None:
    messages = sys.argv[1:] or EXAMPLES
    for msg in messages:
        parsed = await parse_message(msg)
        print(f"\n> {msg}")
        print(parsed.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
