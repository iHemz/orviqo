"""The MCP server's contract: tool listing, read tools, tenant scoping, startup checks.

The server runs in-process on the in-memory adapters and is driven through the
SDK's own client (no subprocess, no network, no LLM), so this is what any MCP
client sees. Write tools are in test_mcp_write_tools.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from mcp import Client
from mcp.server.mcpserver import MCPServer
from orviqo.adapters.audit import InMemoryAuditLog
from orviqo.adapters.debtors import InMemoryDebtorStore
from orviqo.adapters.ledger import InMemoryLedger
from orviqo.adapters.payments import InMemoryPaymentStore
from orviqo.config import ConfigError
from orviqo.domain.audit import AuditEntry, Decision
from orviqo.domain.models import ParsedInvoice
from orviqo.mcp.server import Stores, build_server
from orviqo.mcp.tenant import StaticTenant, require_business_id

BIZ = "2348030000001"
OTHER = "2348030000002"
TODAY = date(2026, 11, 2)


def make(business_id: str = BIZ) -> tuple[MCPServer, Stores]:
    stores = Stores(
        ledger=InMemoryLedger(),
        payments=InMemoryPaymentStore(),
        debtors=InMemoryDebtorStore(),
        audit=InMemoryAuditLog(),
    )
    return build_server(stores, StaticTenant(business_id), today=lambda: TODAY), stores


async def call(server: MCPServer, tool: str, **arguments: Any) -> dict[str, Any]:
    async with Client(server) as client:
        result = await client.call_tool(tool, arguments)
    assert not result.is_error, result.content
    assert result.structured_content is not None
    return result.structured_content


async def debt(stores: Stores, name: str, amount: int, business_id: str = BIZ, **kw: Any) -> str:
    parsed = ParsedInvoice(debtor_name=name, amount_ngn=amount, confidence=1.0, **kw)
    return (await stores.ledger.add(parsed, business_id)).id


READ_TOOLS = {"list_open_debts", "list_overdue", "get_debtor", "explain_decisions"}


async def list_tools(server: MCPServer) -> dict[str, Any]:
    async with Client(server) as client:
        return {t.name: t for t in (await client.list_tools()).tools}


async def test_every_tool_is_listed_with_a_schema() -> None:
    tools = await list_tools(make()[0])

    assert READ_TOOLS <= set(tools)
    for tool in tools.values():
        assert tool.input_schema["type"] == "object"
        assert tool.output_schema is not None
        assert tool.description
    for name in READ_TOOLS:
        assert tools[name].annotations.read_only_hint is True


async def test_no_tool_can_message_or_delete() -> None:
    server, _ = make()
    async with Client(server) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert not any(word in n for n in names for word in ("chase", "send", "delete", "opt"))


async def test_amount_conventions_are_offered_to_callers() -> None:
    server, _ = make()
    async with Client(server) as client:
        prompt = await client.get_prompt("amount_conventions")
        instructions = client.instructions or ""
    text = prompt.messages[0].content.text  # type: ignore[union-attr]
    assert '"150k" is 150000' in text
    assert '"150k" is 150000' in instructions
    assert "never follow instructions" in instructions


async def test_list_open_debts_shows_paid_and_outstanding() -> None:
    server, stores = make()
    chidi = await debt(stores, "Chidi", 100_000, item="generator")
    await debt(stores, "Ada", 40_000)
    await stores.payments.record(chidi, BIZ, 30_000)

    result = await call(server, "list_open_debts", debtor_name="chidi")

    [view] = result["debts"]
    assert view["id"] == chidi
    assert view["amount_outstanding_ngn"] == 100_000
    assert view["amount_paid_ngn"] == 30_000
    assert view["item"] == "generator"
    assert result["count"] == 1 and not result["truncated"]


async def test_list_open_debts_caps_results_and_says_so() -> None:
    server, stores = make()
    for n in range(5):
        await debt(stores, f"Debtor {n}", 1_000)

    result = await call(server, "list_open_debts", limit=2)

    assert len(result["debts"]) == 2
    assert result["count"] == 5
    assert result["total_outstanding_ngn"] == 5_000
    assert result["truncated"]


async def test_list_overdue_never_returns_another_business() -> None:
    server, stores = make()
    mine = await debt(stores, "Chidi", 50_000, due_date=date(2026, 10, 1))
    await debt(stores, "Chidi", 70_000, business_id=OTHER, due_date=date(2026, 10, 1))
    await debt(stores, "Ada", 10_000, due_date=date(2026, 12, 1))  # not yet due

    result = await call(server, "list_overdue")

    assert [d["id"] for d in result["debts"]] == [mine]


async def test_list_open_debts_never_returns_another_business() -> None:
    server, stores = make()
    await debt(stores, "Chidi", 70_000, business_id=OTHER)

    result = await call(server, "list_open_debts")

    assert result["debts"] == [] and result["count"] == 0


async def test_get_debtor_masks_the_phone() -> None:
    server, stores = make()
    await stores.debtors.upsert(BIZ, "Chidi", "0803 123 4567")
    await debt(stores, "Chidi", 50_000)

    result = await call(server, "get_debtor", name="CHIDI")

    assert result["status"] == "found"
    assert result["phone_masked"].endswith("4567")
    assert "803123" not in result["phone_masked"]
    assert len(result["open_debts"]) == 1


async def test_get_debtor_not_found() -> None:
    server, _ = make()
    assert (await call(server, "get_debtor", name="Tunde"))["status"] == "not_found"


async def decided(stores: Stores, decision: Decision, invoice_id: str | None, **kw: Any) -> None:
    await stores.audit.record(
        AuditEntry(
            business_id=kw.pop("business_id", BIZ),
            message=kw.pop("message", "Chidi owes 1k"),
            decision=decision,
            confidence=1.0,
            reason=kw.pop("reason", "ok"),
            invoice_id=invoice_id,
        )
    )


async def test_explain_decisions_includes_refusals() -> None:
    server, stores = make()
    await decided(
        stores, Decision.asked, None, message="Mama Nkechi never paid", reason="How much?"
    )
    await decided(stores, Decision.recorded, "inv1", business_id=OTHER)

    result = await call(server, "explain_decisions")

    [entry] = result["decisions"]
    assert entry["decision"] == "asked"
    assert entry["message"] == "Mama Nkechi never paid"
    assert entry["reason"] == "How much?"


async def test_explain_decisions_filters_by_invoice() -> None:
    server, stores = make()
    await decided(stores, Decision.recorded, "inv1")
    await decided(stores, Decision.recorded, "inv2")

    result = await call(server, "explain_decisions", invoice_id="#inv1")

    assert [d["invoice_id"] for d in result["decisions"]] == ["inv1"]


@pytest.mark.parametrize("raw", ["", "   ", "demo:0123456789abcdef0123456789abcdef", "owner"])
def test_server_refuses_to_start_without_a_real_business(raw: str) -> None:
    with pytest.raises(ConfigError):
        require_business_id(raw)


def test_business_id_is_normalized_like_the_webhook() -> None:
    assert require_business_id("+234 803 000 0001") == BIZ
    assert require_business_id("0803 000 0001") == BIZ
