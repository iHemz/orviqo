"""The public web demo: anyone can try Orviqo in a browser, safely.

Each browser session becomes its own business, ``demo:<session>``, so a visitor
gets a private, durable ledger exactly like a real owner, and nothing they type
can reach a real owner's data. The prefix is also how the collections worker
knows to leave demo businesses alone: a demo must never message a real phone.
"""

from __future__ import annotations

import re

DEMO_PREFIX = "demo:"

# Sessions are minted client-side (a random UUID); accept only that shape so the
# id is safe to store and can't be used to pick another business's id.
_SESSION = re.compile(r"^[0-9a-f]{32}$")


def demo_business_id(session: str) -> str:
    """The business id for a demo session. Raises ``ValueError`` on a bad session."""
    session = session.replace("-", "").lower()
    if not _SESSION.match(session):
        raise ValueError("Invalid demo session id.")
    return DEMO_PREFIX + session


def is_demo(business_id: str) -> bool:
    return business_id.startswith(DEMO_PREFIX)
