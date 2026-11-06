"""Which business a tool call acts for.

Tools never read the business id from a global: they ask a ``TenantResolver`` on
every call. Over stdio (v1) one process serves one owner, so the resolver is a
fixed id from config. A shared HTTP deployment (v2) swaps in a resolver that maps
the request's verified access token to its business, and the tools stay as they are.
"""

from __future__ import annotations

from typing import Protocol

from mcp.server.auth.middleware.auth_context import get_access_token

from orviqo.config import ConfigError
from orviqo.domain.demo import is_demo
from orviqo.domain.phone import normalize_phone


class TenantResolver(Protocol):
    def business_id(self) -> str:
        """The business the current request acts for. Raises if there is none."""
        ...


class StaticTenant:
    """One business for the whole process: the stdio transport's model."""

    def __init__(self, business_id: str) -> None:
        self._business_id = business_id

    def business_id(self) -> str:
        return self._business_id


def require_business_id(raw: str) -> str:
    """Validate ``ORVIQO_MCP_BUSINESS_ID`` and return it in the webhook's wa_id form.

    Refuses an empty id (the server would have no ledger to serve) and a ``demo:``
    id (public demo sessions are throwaway, and must stay unreachable from tools).
    """
    raw = raw.strip()
    if not raw:
        raise ConfigError(
            "ORVIQO_MCP_BUSINESS_ID is not set. Set it to the owner's WhatsApp number "
            "(e.g. 2348031234567), the business whose ledger this server serves."
        )
    if is_demo(raw):
        raise ConfigError("ORVIQO_MCP_BUSINESS_ID cannot be a demo: session.")
    business_id = normalize_phone(raw)
    if not business_id:
        raise ConfigError(f"ORVIQO_MCP_BUSINESS_ID {raw!r} is not a phone number.")
    return business_id


class TokenTenant:
    """The business named by the request's verified access token: the HTTP transport's model.

    The SDK's bearer middleware has already checked the token (signature-free: it is
    a stored secret, looked up by hash) before any tool runs; its ``subject`` is the
    business the owner proved on WhatsApp, or their demo sandbox.
    """

    def business_id(self) -> str:
        token = get_access_token()
        if token is None or not token.subject:
            raise PermissionError("This request carries no Orviqo sign-in.")
        return token.subject
