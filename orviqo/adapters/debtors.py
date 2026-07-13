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
from orviqo.domain.phone import normalize_phone


class DebtorStore(Protocol):
    async def upsert(self, business_id: str, name: str, phone: str) -> Debtor: ...

    async def find(self, business_id: str, name: str) -> Debtor | None: ...

    async def find_by_phone(self, phone: str) -> Debtor | None: ...

    async def opt_out(self, business_id: str, name: str) -> None: ...


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
            phone=normalize_phone(phone),  # store canonical so inbound replies match
            opted_out=existing.opted_out if existing else False,
        )
        self._debtors[key] = debtor
        return debtor

    async def find(self, business_id: str, name: str) -> Debtor | None:
        return self._debtors.get((business_id, name.casefold()))

    async def find_by_phone(self, phone: str) -> Debtor | None:
        target = normalize_phone(phone)
        return next((d for d in self._debtors.values() if d.phone == target), None)

    async def opt_out(self, business_id: str, name: str) -> None:
        key = (business_id, name.casefold())
        debtor = self._debtors.get(key)
        if debtor is not None:
            self._debtors[key] = debtor.model_copy(update={"opted_out": True})
