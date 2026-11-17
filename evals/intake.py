"""Run the WhatsApp intake evals and write a report: ``make eval-intake``.

    uv run --group eval python -m evals.intake                    # every case
    uv run --group eval python -m evals.intake --only reminder    # names or a category
    uv run --group eval python -m evals.intake --model google:gemini-flash-latest

Where ``evals.run`` has a model drive the MCP server, this checks the agent behind
WhatsApp: one owner message plus its context (open debts, reminders they received,
recent chat) in, one ``IntakeAction`` out, scored by evals/intake_checks.py. One
model call per case, on EVAL_GOOGLE_API_KEY's free quota, like the MCP evals.

The report lands in evals/results/<date>-intake-<model>.md. The run exits non-zero
if any decision carried an invented amount; if every model's daily quota runs out
it stops (exit 2) and writes no report.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from orviqo.agents.intake import PydanticAIIntakeAgent
from orviqo.domain.intake import IntakeAction, Reminder, Turn
from orviqo.domain.models import Invoice
from orviqo.mcp.server import lagos_today

from evals.checks import due_dates
from evals.intake_checks import allowed_amounts, check, invented_amount

# The runner's eval-only dependencies (pydantic-evals, pyyaml) are imported where
# they are used, so the offline suite can import build_context without them.

HERE = Path(__file__).resolve().parent
_RETRIES = 4


@dataclass
class IntakeCase:
    name: str
    category: str
    message: str
    expect: dict[str, Any]
    invoices: list[dict[str, Any]] = field(default_factory=list)
    reminders: list[dict[str, Any]] = field(default_factory=list)
    history: list[list[str]] = field(default_factory=list)


@dataclass
class Result:
    case: IntakeCase
    action: IntakeAction | None
    checks: dict[str, bool]
    invented: int | None = None
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.action is not None and all(self.checks.values())


def load_cases(only: str | None) -> list[IntakeCase]:
    import yaml

    raw = yaml.safe_load((HERE / "intake_cases.yaml").read_text(encoding="utf-8"))
    cases = [IntakeCase(**c) for c in raw]
    return [c for c in cases if not only or only in c.name or only == c.category]


def _due(spec: Any, today: date) -> date | None:
    """A context date: the earliest a relative spec resolves to (weekdays have one)."""
    return None if spec is None else min(due_dates(str(spec), today))


def build_context(
    case: IntakeCase, today: date
) -> tuple[list[Invoice], list[Reminder], list[Turn], set[int]]:
    """The case's context as the agent sees it, and the amounts that context holds."""
    invoices = [
        Invoice(
            id=i["id"],
            business_id="eval",
            debtor_name=i["debtor"],
            amount_ngn=i["amount"],
            item=i.get("item"),
            due_date=_due(i.get("due"), today),
            confidence=1.0,
        )
        for i in case.invoices
    ]
    reminded = datetime.combine(today, datetime.min.time(), tzinfo=UTC)
    reminders = [
        Reminder(
            invoice_id=r["id"],
            business_id="2348031234567",
            creditor_name=r.get("creditor"),
            debtor_name=r["debtor"],
            amount_ngn=r["amount"],
            item=r.get("item"),
            due_date=_due(r.get("due"), today),
            reminded_at=reminded,
            quoted=r.get("quoted", False),
        )
        for r in case.reminders
    ]
    history = [Turn(user=user, bot=bot) for user, bot in case.history]
    amounts = {i.amount_ngn for i in invoices if i.amount_ngn} | {r.amount_ngn for r in reminders}
    for turn in history:
        amounts |= allowed_amounts(turn.user, set()) | allowed_amounts(turn.bot, set())
    return invoices, reminders, history, amounts


class QuotaExhausted(RuntimeError):
    """Every model's daily quota is spent: every later case would fail the same way."""


async def decide(agent: PydanticAIIntakeAgent, case: IntakeCase, today: date) -> Result:
    from evals.run import _model_errors

    invoices, reminders, history, context_amounts = build_context(case, today)
    allowed = allowed_amounts(case.message, context_amounts)
    for attempt in range(1, _RETRIES + 1):
        try:
            action = await agent.decide(case.message, invoices, history, reminders)
        except Exception as exc:
            errors = _model_errors(exc)
            if errors and all("PerDay" in str(e) for e in errors):
                raise QuotaExhausted("daily free-tier quota exhausted") from exc
            if not errors or attempt == _RETRIES:
                return Result(case, None, {}, error=str(errors[0] if errors else exc)[:160])
            wait = 20 * attempt
            print(f"  {case.name}: {errors[0]}, retrying in {wait}s", file=sys.stderr, flush=True)
            await asyncio.sleep(wait)
            continue
        return Result(
            case,
            action,
            check(case.expect, action, allowed, today),
            invented=invented_amount(action, allowed),
        )
    raise AssertionError("unreachable")


def _rate(hits: int, total: int) -> str:
    return f"{hits}/{total} ({hits / total:.0%})" if total else "n/a"


def _summary(action: IntakeAction | None) -> str:
    if action is None:
        return ""
    fields = action.model_dump(exclude={"kind", "confidence", "clarify"}, exclude_defaults=True)
    shown = ", ".join(f"{k}={v}" for k, v in fields.items())
    return f"`{action.kind}`" + (f" {shown}" if shown else "")


def render(results: list[Result], model: str, today: date) -> tuple[str, int]:
    """The markdown report, and the number of invented amounts (must be 0)."""
    total = len(results)
    passed = sum(r.passed for r in results)
    kind_ok = sum(r.checks.get("kind", False) for r in results)
    invented = sum(r.invented is not None for r in results)
    carrying = sum(r.action is not None and r.action.amount_ngn is not None for r in results)
    asks = [r for r in results if r.case.expect["kind"] == "clarify"]

    per_category: dict[str, list[bool]] = defaultdict(list)
    for r in results:
        per_category[r.case.category].append(r.passed)

    lines = [
        f"# WhatsApp intake eval: {model}, {today.isoformat()}",
        "",
        f"{total} synthetic messages from `evals/intake_cases.yaml`, each with its context "
        "(open debts, reminders received, recent chat), one model call each. Scored by "
        "deterministic checks (`evals/intake_checks.py`), no LLM judge. A small regression "
        "check, not evidence of real-world accuracy.",
        "",
        "| Metric | Result |",
        "|--------|--------|",
        f"| **Invented-amount rate** (must be 0) | **{_rate(invented, carrying)}** "
        "of decisions carrying an amount |",
        f"| Cases passed | {_rate(passed, total)} |",
        f"| Right kind of message | {_rate(kind_ok, total)} |",
        f"| Asked when it should | "
        f"{_rate(sum(r.checks.get('kind', False) for r in asks), len(asks))} |",
        "",
        "## By category",
        "",
        "| Category | Passed |",
        "|----------|--------|",
    ]
    for category, outcomes in per_category.items():
        lines.append(f"| {category} | {_rate(sum(outcomes), len(outcomes))} |")
    lines += [
        "",
        "## Cases",
        "",
        "| Case | Result | Decision | Failed checks |",
        "|---|---|---|---|",
    ]
    for r in results:
        failed = ", ".join(k for k, ok in r.checks.items() if not ok)
        if r.error:
            failed = f"error: {r.error}"
        verdict = "pass" if r.passed else ("ERROR" if r.error else "FAIL")
        lines.append(f"| {r.case.name} | {verdict} | {_summary(r.action)} | {failed} |")
    lines.append("")
    return "\n".join(lines), invented


async def main(argv: list[str] | None = None) -> int:
    from evals.run import DEFAULT_MODEL, EvalSettings, build_model

    parser = argparse.ArgumentParser(prog="evals.intake", description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Pydantic AI model string.")
    parser.add_argument("--only", help="Run cases whose name contains this, or one category.")
    parser.add_argument("--pause", type=float, default=4.0, help="Seconds between cases.")
    parser.add_argument("--no-report", action="store_true", help="Print, don't write a file.")
    parser.add_argument(
        "--shared-key", action="store_true", help="Use the app's GOOGLE_API_KEY (and its quota)."
    )
    args = parser.parse_args(argv)

    keys = EvalSettings()
    api_key = keys.google_api_key if args.shared_key else keys.eval_google_api_key
    if not api_key:
        raise SystemExit(
            "Set EVAL_GOOGLE_API_KEY in .env (see `python -m evals.run --help`), "
            "or pass --shared-key to spend GOOGLE_API_KEY's quota."
        )
    agent = PydanticAIIntakeAgent(build_model(args.model, api_key))
    today = lagos_today()

    results: list[Result] = []
    try:
        for case in load_cases(args.only):
            started = time.monotonic()
            result = await decide(agent, case, today)
            took = time.monotonic() - started
            mark = "ok" if result.passed else "FAIL"
            print(f"  {case.name}: {mark} {_summary(result.action)} ({took:.0f}s)", file=sys.stderr)
            results.append(result)
            await asyncio.sleep(args.pause)  # stay under the free tier's requests per minute
    except QuotaExhausted as exc:
        # A half-run report would misstate every rate, so none is written.
        print(f"Stopped: {exc}. Re-run when it resets, or use --model.", file=sys.stderr)
        return 2

    markdown, invented = render(results, args.model, today)
    print(markdown)
    if not args.no_report:
        first = args.model.split(",")[0]  # the chain's primary model names the report
        slug = re.sub(r"[^a-z0-9.-]+", "-", first.lower()).strip("-")
        out = HERE / "results" / f"{today.isoformat()}-intake-{slug}.md"
        out.write_text(markdown, encoding="utf-8")
        print(f"\nReport: {out.relative_to(HERE.parent)}", file=sys.stderr)
    if invented:
        print(f"FAIL: {invented} decision(s) carried an invented amount.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
