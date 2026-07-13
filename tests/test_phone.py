"""Phone normalization to the canonical wa_id form."""

from __future__ import annotations

import pytest
from orviqo.domain.phone import normalize_phone


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("08031234567", "2348031234567"),  # local, leading 0 -> country code
        ("0803 123 4567", "2348031234567"),  # spaces stripped
        ("+234 803 123 4567", "2348031234567"),  # +country, punctuation
        ("234-803-123-4567", "2348031234567"),  # dashes
        ("2348031234567", "2348031234567"),  # already canonical
    ],
)
def test_normalize_phone_canonicalizes(raw: str, expected: str) -> None:
    assert normalize_phone(raw) == expected
