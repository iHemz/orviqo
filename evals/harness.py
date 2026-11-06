"""Run one eval case: a real model drives ``orviqo-mcp`` over stdio.

Each case gets a fresh SQLite file, seeded through the same adapters the app uses,
and its own server process pointed at it, exactly as Claude Desktop would launch
one. The model sees only a one-line persona plus whatever the server tells it
(instructions, tool descriptions, results), because that is what's under test.
"""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters
from mcp.types import Tool as MCPTool
from orviqo.adapters.db import create_schema, debtors, invoices, make_engine
from orviqo.adapters.sql_audit import SqlAlchemyAuditLog
from orviqo.adapters.sql_debtors import SqlAlchemyDebtorStore
from orviqo.adapters.sql_ledger import SqlAlchemyLedger
from orviqo.adapters.sql_payments import SqlAlchemyPaymentStore
from orviqo.domain.audit import AuditEntry, Decision
from orviqo.domain.models import ParsedInvoice
from pydantic_ai import Agent, Tool
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits
from sqlalchemy import select

from evals.checks import Outcome, ToolCall, amounts_in, due_dates

BUSINESS_ID = "2348030000001"
REPO = Path(__file__).resolve().parent.parent


@dataclass
class CaseSpec:
    name: str
    category: str
    messages: list[str]
    expect: dict[str, Any]
    seed: dict[str, Any] = field(default_factory=dict)


def persona(today: date) -> str:
    return (
        "You are the assistant of a small-business owner in Nigeria. You keep track of "
        "money people owe them using the Orviqo tools. Reply to the owner briefly. "
        f"Today is {today:%A} {today.isoformat()} (Africa/Lagos)."
    )


async def run_case(case: CaseSpec, model: Model | str, today: date) -> Outcome:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        url = f"sqlite+aiosqlite:///{Path(tmp, 'eval.db').as_posix()}"
        engine = make_engine(url)
        await create_schema(engine)
        try:
            allowed = await _seed(engine, case.seed, today)
            audit = SqlAlchemyAuditLog(engine)
            seeded = len(await audit.entries(BUSINESS_ID))
            calls, final, error = await _converse(case, model, today, url)
            for message in case.messages:
                allowed |= amounts_in(message)
            return Outcome(
                tool_calls=calls,
                final_text=final,
                invoices=await _invoices(engine),
                debtors=await _debtors(engine),
                new_audit=[
                    e.model_dump(mode="json") for e in (await audit.entries(BUSINESS_ID))[seeded:]
                ],
                allowed_amounts=allowed,
                error=error,
            )
        finally:
            await engine.dispose()


async def _converse(
    case: CaseSpec, model: Model | str, today: date, url: str
) -> tuple[list[ToolCall], str, str | None]:
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "orviqo.mcp.server"],
        # Explicit values win over .env, so a case can never touch a real database.
        env={**os.environ, "ORVIQO_MCP_BUSINESS_ID": BUSINESS_ID, "DATABASE_URL": url},
        cwd=str(REPO),
    )
    history: list[Any] = []
    final, error = "", None
    async with Client(server) as mcp:
        # The official SDK client is the MCP side; Pydantic AI only runs the model.
        # Each tool is handed over as-is: the server's name, description and schema.
        tools = [_bridge(mcp, t) for t in (await mcp.list_tools()).tools]
        agent = Agent(model, tools=tools, instructions=[persona(today), mcp.instructions or ""])
        for message in case.messages:
            try:
                result = await agent.run(
                    message, message_history=history, usage_limits=UsageLimits(request_limit=8)
                )
            except UsageLimitExceeded as exc:  # looping on tools: a failed case, not a crash
                error = f"usage limit: {exc}"
                break
            history = result.all_messages()
            final = str(result.output)
    calls = [
        ToolCall(part.tool_name, part.args_as_dict())
        for msg in history
        if isinstance(msg, ModelResponse)
        for part in msg.parts
        if isinstance(part, ToolCallPart)
    ]
    return calls, final, error


def _bridge(mcp: Client, tool: MCPTool) -> Tool[None]:
    """Expose one MCP tool to the agent; a call goes to the server over stdio."""

    async def call(**arguments: Any) -> Any:
        result = await mcp.call_tool(tool.name, arguments)
        if result.is_error:  # e.g. a schema rejection: shown to the model, as clients do
            return {"error": " ".join(getattr(c, "text", "") for c in result.content)}
        return result.structured_content

    return Tool.from_schema(call, tool.name, tool.description, tool.input_schema)


async def _seed(engine: Any, seed: dict[str, Any], today: date) -> set[int]:
    """Write the case's starting state; return the amounts it puts on the record."""
    ledger, payments = SqlAlchemyLedger(engine), SqlAlchemyPaymentStore(engine)
    allowed: set[int] = set()
    for inv in seed.get("invoices", []):
        due = min(due_dates(str(inv["due"]), today)) if inv.get("due") else None
        paid = inv.get("paid", 0)
        # The ledger holds what's still owed; the payments table holds what was paid.
        created = await ledger.add(
            ParsedInvoice(
                debtor_name=inv["debtor"],
                amount_ngn=inv["amount"] - paid,
                item=inv.get("item"),
                due_date=due,
                confidence=1.0,
            ),
            BUSINESS_ID,
        )
        if paid:
            await payments.record(created.id, BUSINESS_ID, paid)
        allowed |= {inv["amount"], inv["amount"] - paid} | ({paid} if paid else set())
    store = SqlAlchemyDebtorStore(engine)
    for d in seed.get("debtors", []):
        await store.upsert(BUSINESS_ID, d["name"], d["phone"])
        if d.get("opted_out"):
            await store.opt_out(BUSINESS_ID, d["name"])
    audit = SqlAlchemyAuditLog(engine)
    for entry in seed.get("audit", []):
        await audit.record(
            AuditEntry(
                business_id=BUSINESS_ID,
                message=entry["message"],
                decision=Decision(entry["decision"]),
                confidence=entry.get("confidence", 0.4),
                reason=entry["reason"],
            )
        )
    return allowed


async def _invoices(engine: Any) -> list[dict[str, Any]]:
    async with engine.connect() as conn:
        rows = list(await conn.execute(select(invoices)))
    paid = await SqlAlchemyPaymentStore(engine).totals_paid([r.id for r in rows])
    return [
        {
            "id": r.id,
            "debtor_name": r.debtor_name,
            "amount_ngn": r.amount_ngn,
            "item": r.item,
            "due_date": r.due_date,
            "status": r.status,
            "paid_ngn": paid[r.id],
        }
        for r in rows
    ]


async def _debtors(engine: Any) -> list[dict[str, Any]]:
    async with engine.connect() as conn:
        rows = list(await conn.execute(select(debtors)))
    return [{"name": r.name, "phone": r.phone, "opted_out": bool(r.opted_out)} for r in rows]
