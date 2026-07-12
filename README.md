# Orviqo — Week 1 scaffold

WhatsApp-native receivables agent for Nigerian SMBs. This is the **Week 1**
milestone from the [spec](https://github.com/iHemz/ideas/blob/main/orviqo-receivables-agent.md):

> WhatsApp loop + intake → send a message, get a structured invoice row back.

## What's here

```
orviqo/
├── pyproject.toml            deps + tooling
├── .env.example              copy to .env and fill in
├── src/orviqo/
│   ├── config.py             settings (model IDs, WhatsApp creds)
│   ├── models.py             Pydantic schemas — the ledger's shape
│   ├── store.py              in-memory ledger (swap for Postgres in Week 2)
│   ├── agents/intake.py      Pydantic AI intake agent (NL → invoice)
│   └── webhook.py            FastAPI WhatsApp webhook (stubbed)
└── scripts/try_intake.py     test intake from the terminal — no WhatsApp needed
```

## The two models (the rigor layer starts here)

| Job | Model | Why |
|-----|-------|-----|
| Intake / parsing | `anthropic:claude-haiku-4-5` | cheap + fast for high-volume NL→struct extraction |
| Collections / reconciliation (Week 3–4) | `anthropic:claude-opus-4-8` | judgment: tone-matching, dispute detection |

The intake agent **never guesses** an amount or date — if it's unsure it returns
`confidence < 1` and a `clarify` question instead of inventing a value. That's the
trust-first discipline the whole product is built on.

## Run it

```bash
# 1. Install (uses uv; falls back to pip)
cd orviqo
uv venv && uv pip install -e ".[dev]"     # or: python -m venv .venv && pip install -e ".[dev]"

# 2. Set your Anthropic key
cp .env.example .env
# edit .env → ANTHROPIC_API_KEY=sk-ant-...

# 3. Test intake with no WhatsApp wiring:
python scripts/try_intake.py "Chidi owes 150k for the generator, due Friday"

# 4. Run the webhook server (WhatsApp integration stubbed for Week 1):
uvicorn orviqo.webhook:app --reload
```

## Next (Week 2)

- Swap `store.py` in-memory dict for Postgres (schema is in the spec §8)
- Wire the real WhatsApp Cloud API webhook verification + send
- Add the `audit_log` table so every agent action is traceable
