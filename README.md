# Orviqo

WhatsApp-native receivables agent for Nigerian SMBs — the AI accounts-receivable
clerk that tracks who owes you, chases them politely, and reconciles payments,
without ever dunning the wrong person because it knows when it isn't sure.

This is **Week 1**: the intake loop — a message in, a structured (or clarified)
invoice out. See the [spec](https://github.com/iHemz/ideas/blob/main/orviqo-receivables-agent.md)
for the full plan and [`docs/architecture.md`](docs/architecture.md) for the design.

## Quickstart

The package lives under `src/`, so it must be **installed** to be importable —
you can't run a loose script with bare `python`. That's deliberate: it forces
you to test against the real, installed package.

```bash
cd orviqo
python -m venv .venv && . .venv/Scripts/activate   # Windows; use .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"                            # or: make dev

cp .env.example .env                               # add ANTHROPIC_API_KEY

orviqo "Chidi owes 150k for the generator, due Friday"   # console entry point
# or: python -m orviqo "..."
```

Ambiguous input is where the design shows: `orviqo "Mama Nkechi never paid for
the rice"` returns a **question**, not an invented amount.

## Layout

```
src/orviqo/
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
make test        # pytest — runs offline, no API key needed
make lint        # ruff
make typecheck   # mypy
make run         # uvicorn --factory orviqo.api.webhook:create_app --reload
```

(No `make` on Windows? Run the underlying command from the [Makefile](Makefile).)

## Next (Week 2)

- `PostgresLedger` implementing `LedgerStore` (schema in spec §8) — swaps in, core untouched
- Real WhatsApp Cloud API client implementing `WhatsAppClient`
- `audit_log` so every recorded action carries a citation
