"""Debtor-contact port + the in-memory adapter.

``DebtorStore`` is the async interface the service depends on to remember a
debtor's phone and whether they've opted out of being chased. ``InMemoryDebtorStore``
is the non-durable adapter (dev, CLI, tests); ``SqlAlchemyDebtorStore`` in
``sql_debtors`` is the durable one.

Debtors are keyed by (business_id, case-folded name): one contact per debtor per
business. ``upsert`` refreshes the phone while preserving an existing opt-out —
saving a number must never silently re-enrol someone who said STOP.
"""

from __future__ import annotations

from typing import Protocol

from orviqo.domain.models import Debtor


class DebtorStore(Protocol):
    async def upsert(self, business_id: str, name: str, phone: str) -> Debtor: ...

    async def find(self, business_id: str, name: str) -> Debtor | None: ...


class InMemoryDebtorStore:
    """Non-durable debtor store for local development, the CLI demo, and tests."""

    def __init__(self) -> None:
        self._debtors: dict[tuple[str, str], Debtor] = {}

    async def upsert(self, business_id: str, name: str, phone: str) -> Debtor:
        key = (business_id, name.casefold())
        existing = self._debtors.get(key)
        debtor = Debtor(
            business_id=business_id,
            name=name,
            phone=phone,
            opted_out=existing.opted_out if existing else False,
        )
        self._debtors[key] = debtor
        return debtor

    async def find(self, business_id: str, name: str) -> Debtor | None:
        return self._debtors.get((business_id, name.casefold()))
