# Common developer tasks. On Windows without `make`, run the commands directly.
.PHONY: dev lint format typecheck test run try check

dev:            ## Install the package + dev tools (editable)
	pip install -e ".[dev]"

lint:           ## Static lint
	ruff check .

format:         ## Auto-format
	ruff format .

typecheck:      ## Type-check the package
	mypy

test:           ## Run the offline test suite
	pytest -q

run:            ## Start the webhook server (needs ANTHROPIC_API_KEY)
	uvicorn --factory orviqo.api.webhook:create_app --reload

try:            ## Try the intake agent (needs ANTHROPIC_API_KEY)
	orviqo "Chidi owes 150k for the generator, due Friday"

check: lint test  ## What CI runs
