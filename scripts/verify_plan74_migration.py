"""Verify Plan 74 migration round-trip in one exact disposable database."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from uuid import uuid4

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import URL


ROOT = Path(__file__).resolve().parents[1]
DATABASE_PREFIX = "plan74_migration_"


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _database_name() -> str:
    value = f"{DATABASE_PREFIX}{uuid4().hex[:16]}"
    if not re.fullmatch(r"plan74_migration_[0-9a-f]{16}", value):
        raise RuntimeError("unsafe disposable database name")
    return value


def _assert_schema(database_url: str, *, upgraded: bool) -> None:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        schema = inspect(engine)
        table_names = set(schema.get_table_names())
        columns = {
            item["name"] for item in schema.get_columns("private_assets")
        }
        plan74_tables = {"library_change_requests", "library_check_reports"}
        plan74_columns = {
            "scope_kind", "scope_novel_id", "collection_key",
            "source_asset_id", "source_version_id",
        }
        if upgraded:
            assert plan74_tables <= table_names
            assert plan74_columns <= columns
        else:
            assert plan74_tables.isdisjoint(table_names)
            assert plan74_columns.isdisjoint(columns)
    finally:
        engine.dispose()


def main() -> None:
    user = os.environ.get("POSTGRES_USER", "ai_novel").strip() or "ai_novel"
    password = _required_environment("POSTGRES_PASSWORD")
    host = os.environ.get("PLAN74_POSTGRES_HOST", "127.0.0.1").strip()
    port = int(os.environ.get("PLAN74_POSTGRES_PORT", "15432"))
    database = _database_name()
    control = psycopg.connect(
        host=host,
        port=port,
        dbname="postgres",
        user=user,
        password=password,
        autocommit=True,
    )
    created = False
    try:
        role = control.execute(
            "SELECT rolcreatedb FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        if role is None or role[0] is not True:
            raise RuntimeError("configured PostgreSQL role cannot create a disposable database")
        exists = control.execute(
            "SELECT 1 FROM pg_database WHERE datname=%s", (database,)
        ).fetchone()
        if exists is not None:
            raise RuntimeError("disposable database already exists")
        control.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(
            sql.Identifier(database), sql.Identifier(user)
        ))
        created = True

        url = URL.create(
            "postgresql+psycopg",
            username=user,
            password=password,
            host=host,
            port=port,
            database=database,
        ).render_as_string(hide_password=False)
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        prior_database_url = os.environ.get("AI_NOVEL_DATABASE_URL")
        os.environ["AI_NOVEL_DATABASE_URL"] = url
        try:
            command.upgrade(config, "head")
            _assert_schema(url, upgraded=True)
            command.downgrade(config, "20260912_0055")
            _assert_schema(url, upgraded=False)
            command.upgrade(config, "head")
            _assert_schema(url, upgraded=True)
        finally:
            if prior_database_url is None:
                os.environ.pop("AI_NOVEL_DATABASE_URL", None)
            else:
                os.environ["AI_NOVEL_DATABASE_URL"] = prior_database_url
        print(json.dumps({
            "status": "PASS",
            "database_kind": "disposable",
            "upgrade": "head",
            "downgrade": "20260912_0055",
            "reupgrade": "head",
        }, ensure_ascii=False))
    finally:
        if created:
            control.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname=%s AND pid<>pg_backend_pid()",
                (database,),
            )
            control.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))
        control.close()


if __name__ == "__main__":
    main()
