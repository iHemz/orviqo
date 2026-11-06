"""Housekeeping for the hosted MCP server, run by the daily collections pass.

Demo sandboxes are throwaway by design and live on a free database, so they are
deleted a few days after they were made, along with OAuth rows nobody can use
any more. A sandbox's age is its first audit entry (its seed), so a sandbox is
removed whole, never half-way through someone's session.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from orviqo.adapters.db import (
    audit_log,
    debtors,
    invoices,
    oauth_grants,
    oauth_tokens,
    payments,
)


async def purge_sandboxes(engine: AsyncEngine, prefix: str, created_before: datetime) -> int:
    """Delete every business under ``prefix`` first seen before ``created_before``.

    Returns how many businesses were removed.
    """
    stale = (
        select(audit_log.c.business_id)
        .where(audit_log.c.business_id.startswith(prefix, autoescape=True))
        .group_by(audit_log.c.business_id)
        .having(func.min(audit_log.c.created_at) < created_before)
    )
    async with engine.begin() as conn:
        businesses = list((await conn.execute(stale)).scalars())
        if businesses:
            for table in (payments, invoices, debtors, oauth_tokens, audit_log):
                await conn.execute(delete(table).where(table.c.business_id.in_(businesses)))
    return len(businesses)


async def purge_expired_oauth(engine: AsyncEngine, now: datetime) -> None:
    """Drop sign-ins and tokens past their expiry: they can never be used again."""
    async with engine.begin() as conn:
        await conn.execute(delete(oauth_grants).where(oauth_grants.c.expires_at < now))
        await conn.execute(delete(oauth_tokens).where(oauth_tokens.c.expires_at < now))
