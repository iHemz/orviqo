"""Phone normalization — one canonical form for matching and sending.

WhatsApp identifies a sender by their ``wa_id`` (digits only, country code first,
e.g. ``2348031234567``). Owners, though, type numbers however they like:
``0803 123 4567``, ``+234 803 123 4567``. We canonicalize every number to the
wa_id form so a stored debtor phone matches the sender of an inbound reply — the
basis for routing a debtor's STOP to the right record.
"""

from __future__ import annotations

# Nigerian mobile numbers are 11 local digits (leading 0) or 13 in country form.
_LOCAL_LEN = 11
_COUNTRY_CODE = "234"


def normalize_phone(raw: str) -> str:
    """Return a phone as wa_id digits: strip punctuation, turn a leading 0 into 234.

    Already-canonical numbers (``234...``, or an international ``+...``) pass through
    with only punctuation removed. Non-Nigerian numbers keep their own country code.
    """
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == _LOCAL_LEN and digits.startswith("0"):
        return _COUNTRY_CODE + digits[1:]
    return digits
