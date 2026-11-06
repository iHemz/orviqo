"""OAuth types for the hosted MCP server: how an owner's assistant gets a ledger.

An MCP client (claude.ai, ChatGPT) asks to connect; that request is a ``Grant``
until the owner proves which business is theirs, by sending its link code to the
Orviqo WhatsApp number or by taking a demo sandbox. Then the client gets an
authorization code and swaps it for tokens. Codes and tokens are stored only as
hashes, and each carries the ``business_id`` every tool call is scoped to.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

TokenKind = Literal["code", "access", "refresh"]


class Grant(BaseModel):
    """A client's request to connect, waiting for the owner to sign in."""

    id: str  # in the sign-in page URL: unguessable
    link_code: str  # what the owner sends on WhatsApp: short, typeable, single-use
    client_id: str
    client_name: str | None
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    state: str | None
    code_challenge: str
    scopes: list[str]
    resource: str | None
    expires_at: datetime
    business_id: str | None = None  # set once the owner has proved who they are


class IssuedToken(BaseModel):
    """An authorization code, access token or refresh token, keyed by its hash."""

    token_hash: str
    kind: TokenKind
    client_id: str
    business_id: str
    scopes: list[str]
    resource: str | None
    expires_at: datetime
    # Authorization codes only: what the token endpoint checks the exchange against.
    code_challenge: str | None = None
    redirect_uri: str | None = None
    redirect_uri_provided_explicitly: bool = False
