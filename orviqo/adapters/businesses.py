"""Business-profile port + the in-memory adapter (dev, CLI, tests).

Holds each business's display name: the one its owner set, and the WhatsApp
profile name noted from their messages, plus when they last messaged (which
decides whether a digest can go as plain text). ``SqlAlchemyBusinessStore`` in
``sql_businesses`` is the durable adapter.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from orviqo.domain.business import BusinessProfile


class BusinessStore(Protocol):
    async def get(self, business_id: str) -> BusinessProfile | None: ...

    async def set_name(self, business_id: str, name: str) -> BusinessProfile:
        """The owner's chosen name: it wins over the WhatsApp profile name."""
        ...

    async def note_message(
        self, business_id: str, at: datetime, whatsapp_name: str | None = None
    ) -> None:
        """They messaged Orviqo at ``at``. Also remember their latest WhatsApp profile
        name, when WhatsApp sent one; it never overrides a chosen name."""
        ...


class InMemoryBusinessStore:
    def __init__(self) -> None:
        self._profiles: dict[str, BusinessProfile] = {}

    async def get(self, business_id: str) -> BusinessProfile | None:
        return self._profiles.get(business_id)

    async def set_name(self, business_id: str, name: str) -> BusinessProfile:
        current = self._profiles.get(business_id) or BusinessProfile(business_id=business_id)
        profile = current.model_copy(update={"name": name})
        self._profiles[business_id] = profile
        return profile

    async def note_message(
        self, business_id: str, at: datetime, whatsapp_name: str | None = None
    ) -> None:
        current = self._profiles.get(business_id) or BusinessProfile(business_id=business_id)
        update: dict[str, object] = {"last_message_at": at}
        if whatsapp_name:
            update["whatsapp_name"] = whatsapp_name
        self._profiles[business_id] = current.model_copy(update=update)
