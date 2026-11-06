"""Who a business is, to the people it reminds.

A business is keyed by its owner's WhatsApp number, and that alone is a poor
introduction: a reminder that doesn't say who is owed is incomplete, and looks
like a scam. So each business has a display name: the one its owner set ("my
business name is Ada Fabrics"), else the WhatsApp profile name WhatsApp sends
with every message. Reminders show the name together with the number, so the
debtor can check it's genuine and knows who to pay.
"""

from __future__ import annotations

from pydantic import BaseModel


class BusinessProfile(BaseModel):
    business_id: str  # the owner's WhatsApp number (wa_id digits)
    name: str | None = None  # set by the owner; wins
    whatsapp_name: str | None = None  # the owner's WhatsApp profile name

    @property
    def display_name(self) -> str | None:
        return self.name or self.whatsapp_name


def identify(business_id: str, profile: BusinessProfile | None) -> str:
    """How a business is named to its debtors: "Ada Fabrics (+2348031234567)"."""
    number = f"+{business_id}" if business_id.isdigit() else business_id
    name = profile.display_name if profile else None
    return f"{name} ({number})" if name else number
