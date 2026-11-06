# Common developer tasks. On Windows without `make`, run the commands directly.
.PHONY: dev lint format typecheck test simulate worker migrate revision run try eval check

dev:            ## Sync the venv from uv.lock (deps + dev tools)
	uv sync

lint:           ## Static lint
	uv run ruff check .

format:         ## Auto-format
	uv run ruff format .

typecheck:      ## Type-check the package
	uv run mypy

test:           ## Run the offline test suite
	uv run pytest -q

simulate:       ## Simulate an inbound WhatsApp message. msg="..." [url=...]
	uv run python tools/simulate_inbound.py "$(msg)" --url "$(or $(url),http://localhost:8000/webhook)"

worker:         ## Run the reminder worker a single pass (needs secrets)
	uv run python -m orviqo.worker --once

migrate:        ## Apply database migrations
	uv run alembic upgrade head

revision:       ## Autogenerate a migration from model changes (msg="...")
	uv run alembic revision --autogenerate -m "$(msg)"

run: migrate    ## Migrate, then start the webhook server (needs ANTHROPIC_API_KEY)
	uv run uvicorn --factory orviqo.api.webhook:create_app --reload

try:            ## Try the intake agent (needs ANTHROPIC_API_KEY)
	uv run orviqo "Chidi owes 150k for the generator, due Friday"

eval:           ## Model evals for the MCP server (needs GOOGLE_API_KEY; not in CI). [only=...] [model=...]
	uv run --group eval python -m evals.run $(if $(only),--only $(only)) $(if $(model),--model $(model))

check: lint test  ## What CI runs
