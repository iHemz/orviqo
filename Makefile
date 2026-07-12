# Common developer tasks. On Windows without `make`, run the commands directly.
.PHONY: dev lint format typecheck test run try check

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

run:            ## Start the webhook server (needs ANTHROPIC_API_KEY)
	uv run uvicorn --factory orviqo.api.webhook:create_app --reload

try:            ## Try the intake agent (needs ANTHROPIC_API_KEY)
	uv run orviqo "Chidi owes 150k for the generator, due Friday"

check: lint test  ## What CI runs
