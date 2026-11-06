"""The Vercel build step: migrate the database, on production builds only.

Preview deployments share production's DATABASE_URL, so a preview of a branch
with a new migration would upgrade the live database ahead of ``main``. Then
``main`` (which doesn't have that migration file yet) fails to build with
"Can't locate revision". So only a production build (``VERCEL_ENV=production``)
migrates; a preview runs against the schema production already has.

    python -m orviqo.migrate            # what [tool.vercel.scripts] build runs
"""

from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config


def main() -> None:
    env = os.environ.get("VERCEL_ENV")
    if env not in (None, "production"):
        print(f"skipping migrations on a {env} build: only production migrates")
        return
    root = Path(__file__).resolve().parent.parent
    command.upgrade(Config(str(root / "alembic.ini")), "head")


if __name__ == "__main__":
    main()
