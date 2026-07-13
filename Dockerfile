# Orviqo — production image. Built by Fly from uv.lock for reproducible installs.
FROM python:3.13-slim

# uv, copied from the official image (no pip bootstrap needed).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# 1) Install dependencies as a cached layer (only re-runs when the lock changes).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# 2) Install the project itself.
COPY . .
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000

# Persistent process — the app's lifespan wiring runs exactly as designed.
CMD ["uvicorn", "--factory", "orviqo.api.webhook:create_app", "--host", "0.0.0.0", "--port", "8000"]
