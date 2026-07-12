# Orviqo

WhatsApp-native receivables agent for Nigerian SMBs — the AI accounts-receivable
clerk that tracks who owes you, chases them politely, and reconciles payments,
without ever dunning the wrong person because it knows when it isn't sure.

This is **Week 1**: the intake loop — a message in, a structured (or clarified)
invoice out. See the [spec](https://github.com/iHemz/ideas/blob/main/orviqo-receivables-agent.md)
for the full plan and [`docs/architecture.md`](docs/architecture.md) for the design.

## Quickstart

Uses [uv](https://docs.astral.sh/uv/). `uv sync` creates the virtualenv, writes
`uv.lock`, and installs everything (deps + dev tools) — one command, reproducible.

```bash
cd orviqo
uv sync

cp .env.example .env          # add ANTHROPIC_API_KEY

uv run orviqo "Chidi owes 150k for the generator, due Friday"
# or: uv run python -m orviqo "..."
```

Ambiguous input is where the design shows: `uv run orviqo "Mama Nkechi never
paid for the rice"` returns a **question**, not an invented amount.

## Layout

```
orviqo/
├── domain/        pure types (Invoice, ParsedInvoice) — no I/O
├── agents/        base.py = InvoiceParser port · intake.py = Pydantic AI impl
├── services/      intake_service.py — the rigor gate (record vs. ask)
├── adapters/      ledger.py (LedgerStore) · whatsapp.py (inbound parse + client)
├── api/           webhook.py — FastAPI, wired via create_app()
├── cli.py         terminal entry point
└── config.py      settings + bootstrap()
tests/             offline suite (fakes for the LLM — no network)
```

Dependencies point inward; only the delivery layer (`api`, `cli`) wires concrete
adapters to the service. See [`docs/architecture.md`](docs/architecture.md).

## Models

| Job | Model | Why |
|-----|-------|-----|
| Intake / parsing | `anthropic:claude-haiku-4-5` | cheap + fast for high-volume NL→struct |
| Collections / reconciliation (Week 3+) | `anthropic:claude-opus-4-8` | judgment: tone, dispute detection |

## Develop

```bash
uv run pytest       # offline, no API key needed
uv run ruff check .
uv run mypy
make test           # same as `uv run pytest -q` (see Makefile for all tasks)
```

## Next (Week 2)

- `PostgresLedger` implementing `LedgerStore` (schema in spec §8) — swaps in, core untouched
- Real WhatsApp Cloud API client implementing `WhatsAppClient`
- `audit_log` so every recorded action carries a citation
