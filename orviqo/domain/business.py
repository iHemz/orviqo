"""Who a business is, to the people it reminds.

A business is keyed by its owner's WhatsApp number, and that alone is a poor
introduction: a reminder that doesn't say who is owed is incomplete, and looks
like a scam. So each business has a display name: the one its owner set ("my
business name is Ada Fabrics"), else the WhatsApp profile name WhatsApp sends
with every message. Reminders show the name together with the number, so the
debtor can check it's genuine and knows who to pay.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel

# WhatsApp lets a business send free-form messages, free of charge, for 24 hours
# after the person last messaged it. An hour's margin covers a slow send.
SERVICE_WINDOW = timedelta(hours=23)


class BusinessProfile(BaseModel):
    business_id: str  # the owner's WhatsApp number (wa_id digits)
    name: str | None = None  # set by the owner; wins
    whatsapp_name: str | None = None  # the owner's WhatsApp profile name
    last_message_at: datetime | None = None  # when they last messaged Orviqo

    @property
    def display_name(self) -> str | None:
        return self.name or self.whatsapp_name

    def can_message_freely(self, now: datetime) -> bool:
        """Inside WhatsApp's 24-hour window, so a plain text reaches them (and is free)."""
        last = self.last_message_at
        if last is None:
            return False
        if last.tzinfo is None:  # SQLite returns naive datetimes; they are UTC
            last = last.replace(tzinfo=UTC)
        return now - last < SERVICE_WINDOW


def identify(business_id: str, profile: BusinessProfile | None) -> str:
    """How a business is named to its debtors: "Ada Fabrics (+2348031234567)"."""
    number = f"+{business_id}" if business_id.isdigit() else business_id
    name = profile.display_name if profile else None
    return f"{name} ({number})" if name else number
