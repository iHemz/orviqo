"""The public entry point — how a new owner finds their way into a chat with Orviqo.

Nobody can search WhatsApp for a business number, so discovery happens through a
``wa.me`` click-to-chat link (or a QR code of it) shared on a landing page or
socials. Opening the chat with a prefilled greeting means the owner's first tap
already sends a message, which triggers the first-run welcome.
"""

from __future__ import annotations

from urllib.parse import quote

from orviqo.domain.phone import normalize_phone

# Prefilled into the owner's compose box; they just hit send.
GREETING = "Hi Orviqo"


def whatsapp_link(number: str, text: str = GREETING) -> str:
    """Return the ``wa.me`` click-to-chat URL for ``number``, prefilled with ``text``.

    wa.me wants the number as bare international digits (no ``+``, no leading 0),
    which is exactly the canonical wa_id form ``normalize_phone`` produces.
    """
    digits = normalize_phone(number)
    if not digits:
        raise ValueError("A WhatsApp number is required to build a wa.me link.")
    url = f"https://wa.me/{digits}"
    return f"{url}?text={quote(text)}" if text else url
