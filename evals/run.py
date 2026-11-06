"""Run the MCP evals and write a report: ``make eval`` (``uv run python -m evals.run``).

    uv run --group eval python -m evals.run                       # every case
    uv run --group eval python -m evals.run --only payment        # names containing "payment"
    uv run --group eval python -m evals.run --model google:gemini-flash-latest

Costs nothing: it runs on Gemini's free tier with EVAL_GOOGLE_API_KEY, a key from
its own Google AI Studio project. Free quotas are per project, so evals never eat
the daily quota the live demo and WhatsApp run on (GOOGLE_API_KEY). Pass
--shared-key to use GOOGLE_API_KEY anyway.

The report lands in evals/results/<date>-<model>.md. The run exits non-zero if
any write carried an invented amount: that rate must be 0. If every model's daily
quota runs out mid-run it stops (exit 2) and writes no report.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from orviqo.agents.intake import FALLBACK_ON
from orviqo.mcp.server import lagos_today
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext
from pydantic_settings import BaseSettings, SettingsConfigDict

from evals.checks import Outcome, check, invented_amounts
from evals.harness import CaseSpec, run_case

HERE = Path(__file__).resolve().parent
# Flash-Lite, then Flash: separate free daily quotas, as in the app's own chain.
DEFAULT_MODEL = "google:gemini-flash-lite-latest,google:gemini-flash-latest"


class EvalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    eval_google_api_key: str = ""
    google_api_key: str = ""  # the app's key: used only with --shared-key


def build_model(spec: str, api_key: str) -> Model:
    """A Gemini model (or fallback chain) on ``api_key``, never on the environment's key."""
    provider = GoogleProvider(api_key=api_key)
    models: list[Model] = []
    for name in (m.strip() for m in spec.split(",") if m.strip()):
        prefix, _, model_name = name.partition(":")
        if prefix != "google":
            raise SystemExit(f"evals run on Gemini's free tier; {name!r} isn't a google: model")
        models.append(GoogleModel(model_name, provider=provider))
    return models[0] if len(models) == 1 else FallbackModel(*models, fallback_on=FALLBACK_ON)


_RETRIES = 4
_CASE_TIMEOUT = 180


@dataclass
class RigorChecks(Evaluator[CaseSpec, Outcome, dict[str, str]]):
    """Every deterministic check from evals/checks.py, as named assertions."""

    today: date

    def evaluate(self, ctx: EvaluatorContext[CaseSpec, Outcome, dict[str, str]]) -> dict[str, bool]:
        return check(ctx.inputs.expect, ctx.output, self.today)


def load_cases(only: str | None) -> list[CaseSpec]:
    raw = yaml.safe_load((HERE / "cases.yaml").read_text(encoding="utf-8"))
    specs = [CaseSpec(**c) for c in raw]
    return [s for s in specs if not only or only in s.name or only == s.category]


class QuotaExhausted(RuntimeError):
    """The model's daily quota is spent: every later case would fail the same way."""


_exhausted: list[str] = []  # set once a daily quota runs out; later cases skip the model


async def run_with_retry(
    spec: CaseSpec, model: Model, label: str, today: date, pause: float
) -> Outcome:
    """Run a case from scratch, waiting out overloads and per-minute rate limits.

    A daily quota is not waited out (it resets in hours): the run stops instead.
    """
    if _exhausted:
        raise QuotaExhausted(_exhausted[0])
    for attempt in range(1, _RETRIES + 1):
        started = time.monotonic()
        try:
            # A hung model call or server becomes a failed case, never a stuck run.
            outcome = await asyncio.wait_for(run_case(spec, model, today), _CASE_TIMEOUT)
            took = time.monotonic() - started
            print(
                f"  {spec.name}: {', '.join(outcome.tools) or 'no tools'} ({took:.0f}s)",
                file=sys.stderr,
                flush=True,
            )
            await asyncio.sleep(pause)  # stay under the free tier's requests per minute
            return outcome
        except TimeoutError:
            print(f"  {spec.name}: timed out after {_CASE_TIMEOUT}s", file=sys.stderr, flush=True)
            raise
        except Exception as exc:  # the MCP client's task group wraps model errors
            errors = _model_errors(exc)
            if not errors or attempt == _RETRIES:
                raise (errors[0] if errors else exc) from exc
            if all("PerDay" in str(e) for e in errors):  # every model in the chain is spent
                _exhausted.append(f"{label}: daily free-tier quota exhausted")
                raise QuotaExhausted(_exhausted[0]) from exc
            exc = errors[0]
            wait = 20 * attempt
            print(f"  {spec.name}: {exc}, retrying in {wait}s", file=sys.stderr, flush=True)
            await asyncio.sleep(wait)
    raise AssertionError("unreachable")


def _model_errors(exc: BaseException) -> list[ModelAPIError]:
    """Every model API error (overload, rate limit) inside ``exc``.

    The MCP client's task group and the fallback chain both wrap them in groups.
    """
    if isinstance(exc, ModelAPIError):
        return [exc]
    if isinstance(exc, BaseExceptionGroup):
        return [e for inner in exc.exceptions for e in _model_errors(inner)]
    return []


def _passed(case: Any) -> bool:
    return all(bool(a.value) for a in case.assertions.values())


def _rate(hits: int, total: int) -> str:
    return f"{hits}/{total} ({hits / total:.0%})" if total else "n/a"


def render(report: Any, specs: list[CaseSpec], model: str, today: date) -> tuple[str, int]:
    """The markdown report, and the number of invented amounts (must be 0)."""
    by_name = {s.name: s for s in specs}
    cases = list(report.cases)
    failures = list(report.failures)

    invented = sum(len(invented_amounts(c.output)) for c in cases)
    amount_calls = sum(
        1 for c in cases for call in c.output.tool_calls if call.args.get("amount_ngn") is not None
    )
    tool_cases = [c for c in cases if {"tools", "forbid_tools"} & set(by_name[c.name].expect)]
    tool_ok = [
        c
        for c in tool_cases
        if all(
            c.assertions[k].value
            for k in ("called_expected_tools", "avoided_forbidden_tools")
            if k in c.assertions
        )
    ]
    should_ask = [c for c in cases if by_name[c.name].expect.get("asks") is True]
    should_write = [c for c in cases if by_name[c.name].expect.get("writes") is True]
    over_asked = [c for c in should_write if c.output.asked]

    per_category: dict[str, list[bool]] = defaultdict(list)
    for c in cases:
        per_category[by_name[c.name].category].append(_passed(c))
    for f in failures:
        per_category[by_name[f.name].category].append(False)
    total = len(cases) + len(failures)
    passed = sum(_passed(c) for c in cases)

    lines = [
        f"# MCP eval: {model}, {today.isoformat()}",
        "",
        f"{total} synthetic cases from `evals/cases.yaml`, one fresh SQLite ledger each, "
        "the model driving `orviqo-mcp` over stdio. Scored by deterministic checks "
        "(`evals/checks.py`), no LLM judge. A small regression check, not evidence of "
        "real-world accuracy.",
        "",
        "| Metric | Result |",
        "|--------|--------|",
        f"| **Invented-amount rate** (must be 0) | **{_rate(invented, amount_calls)}** "
        "of calls carrying an amount |",
        f"| Cases passed | {_rate(passed, total)} |",
        f"| Tool-selection accuracy | {_rate(len(tool_ok), len(tool_cases))} |",
        f"| Clarification recall (asked when it should) | "
        f"{_rate(sum(c.output.asked for c in should_ask), len(should_ask))} |",
        f"| Over-asking (asked when everything was given) | "
        f"{_rate(len(over_asked), len(should_write))} |",
        "",
        "## By category",
        "",
        "| Category | Passed |",
        "|----------|--------|",
    ]
    for category, results in per_category.items():
        lines.append(f"| {category} | {_rate(sum(results), len(results))} |")

    lines += [
        "",
        "## Cases",
        "",
        "| Case | Result | Tool calls | Failed checks |",
        "|---|---|---|---|",
    ]
    for c in cases:
        calls = ", ".join(f"`{t.name}({_args(t.args)})`" for t in c.output.tool_calls) or "none"
        failed = ", ".join(k for k, a in c.assertions.items() if not a.value) or ""
        if c.output.error:
            failed = f"{failed} ({c.output.error})".strip()
        lines.append(f"| {c.name} | {'pass' if _passed(c) else 'FAIL'} | {calls} | {failed} |")
    for f in failures:
        lines.append(f"| {f.name} | ERROR | | {f.error_message.splitlines()[0][:120]} |")
    lines.append("")
    return "\n".join(lines), invented


def _args(args: dict[str, Any]) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in args.items() if v not in (None, False))


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.run", description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Pydantic AI model string.")
    parser.add_argument("--only", help="Run cases whose name contains this, or one category.")
    parser.add_argument("--pause", type=float, default=6.0, help="Seconds between cases.")
    parser.add_argument("--no-report", action="store_true", help="Print, don't write a file.")
    parser.add_argument(
        "--shared-key", action="store_true", help="Use the app's GOOGLE_API_KEY (and its quota)."
    )
    args = parser.parse_args(argv)

    keys = EvalSettings()
    api_key = keys.google_api_key if args.shared_key else keys.eval_google_api_key
    if not api_key:
        raise SystemExit(
            "Set EVAL_GOOGLE_API_KEY in .env: a free key from a NEW project in Google AI "
            "Studio (aistudio.google.com/apikey), so evals get their own quota and leave "
            "the live demo's alone. Or pass --shared-key to spend GOOGLE_API_KEY's quota."
        )
    model = build_model(args.model, api_key)

    today = lagos_today()
    specs = load_cases(args.only)
    dataset = Dataset[CaseSpec, Outcome, dict[str, str]](
        name="orviqo-mcp",
        cases=[Case(name=s.name, inputs=s, metadata={"category": s.category}) for s in specs],
        evaluators=[RigorChecks(today)],
    )

    async def task(spec: CaseSpec) -> Outcome:
        return await run_with_retry(spec, model, args.model, today, args.pause)

    report = await dataset.evaluate(task, max_concurrency=1, progress=False)
    if _exhausted:
        # A half-run report would misstate every rate, so none is written.
        print(f"Stopped: {_exhausted[0]}. Re-run when it resets, or use --model.", file=sys.stderr)
        return 2
    markdown, invented = render(report, specs, args.model, today)

    print(markdown)
    if not args.no_report:
        first = args.model.split(",")[0]  # the chain's primary model names the report
        slug = re.sub(r"[^a-z0-9.-]+", "-", first.lower()).strip("-")
        out = HERE / "results" / f"{today.isoformat()}-{slug}.md"
        out.parent.mkdir(exist_ok=True)
        out.write_text(markdown, encoding="utf-8")
        print(f"\nReport: {out.relative_to(HERE.parent)}", file=sys.stderr)
    if invented:
        print(f"FAIL: {invented} write(s) carried an invented amount.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
