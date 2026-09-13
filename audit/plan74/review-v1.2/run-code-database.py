"""Run code tests in an exact disposable database, never a product environment.

The password is supplied only via PLAN74_CODE_DATABASE_PASSWORD. No credential
is printed or persisted. Database creation and deletion are limited to this run.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy.engine import URL


def main() -> int:
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root))
    from alembic import command
    from alembic.config import Config

    password = os.environ.pop("PLAN74_CODE_DATABASE_PASSWORD", "").strip()
    if len(password) > 1 and password[0] == password[-1] and password[0] in "\"'":
        password = password[1:-1]
    if not password:
        raise RuntimeError("explicit code-database credential required")
    user = os.environ.get("PLAN74_CODE_DATABASE_USER", "ai_novel").strip() or "ai_novel"
    database = f"plan74_v12_{uuid4().hex[:16]}_test"
    if not re.fullmatch(r"plan74_v12_[a-f0-9]{16}_test", database):
        raise RuntimeError("invalid disposable database name")
    connection = psycopg.connect(host="127.0.0.1", port=15432, user=user, password=password,
                                 dbname="postgres", autocommit=True)
    created = False
    try:
        connection.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(database), sql.Identifier(user)))
        created = True
        url = URL.create("postgresql+psycopg", username=user, password=password,
                         host="127.0.0.1", port=15432, database=database).render_as_string(hide_password=False)
        prior = os.environ.get("AI_NOVEL_DATABASE_URL")
        os.environ["AI_NOVEL_DATABASE_URL"] = url
        try:
            command.upgrade(Config(str(root / "alembic.ini")), "head")
        finally:
            if prior is None:
                os.environ.pop("AI_NOVEL_DATABASE_URL", None)
            else:
                os.environ["AI_NOVEL_DATABASE_URL"] = prior
        child_env = {**os.environ, "AI_NOVEL_TEST_DATABASE_URL": url}
        print(f"Code-only disposable database ready: {database}", flush=True)
        return subprocess.run([sys.executable, "-m", "pytest", *(sys.argv[1:] or ["tests/private_library"]), "-q"],
                              cwd=root, env=child_env, check=False).returncode
    finally:
        if created:
            connection.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()", (database,))
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))
            print(f"Removed only disposable code-test database: {database}", flush=True)
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
