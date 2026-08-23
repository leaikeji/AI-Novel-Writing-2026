"""Run explicit Alembic migrations; never called from PawApp startup."""

from __future__ import annotations

from pathlib import Path
import sys

from alembic import command
from alembic.config import Config


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else "upgrade"
    revision = sys.argv[2] if len(sys.argv) > 2 else "head"
    config = Config(str(ROOT / "alembic.ini"))
    if target == "upgrade":
        command.upgrade(config, revision)
    elif target == "downgrade":
        command.downgrade(config, revision)
    elif target == "current":
        command.current(config, verbose=True)
    else:
        raise SystemExit("usage: migrate.py [upgrade|downgrade|current] [revision]")


if __name__ == "__main__":
    main()
