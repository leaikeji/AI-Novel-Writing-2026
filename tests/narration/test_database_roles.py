from __future__ import annotations

import os
from pathlib import Path
import re
import stat
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from scripts.tts.validate_database_roles import (
    API_ROLE,
    EXPECTED_HEAD,
    MIGRATOR_ROLE,
    PROTECTED_TABLES,
    SCHEMA_OWNER,
    WORKER_ROLE,
    DatabaseTarget,
    RoleValidationError,
    collect_and_validate,
    validate_target,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROLE_PACKAGE = PROJECT_ROOT / "docker" / "postgres-roles"


def _write_test_passfile(
    root: Path,
    *,
    host: str,
    port: int,
    database: str,
    role: str,
) -> Path:
    root.mkdir(mode=0o700)
    path = root / ".pgpass"
    path.write_text(
        f"{host}:{port}:{database}:{role}:{'0' * 64}\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def _static_target(tmp_path: Path) -> DatabaseTarget:
    host = "127.0.0.1"
    port = 15438
    database = "ai_novel_world_2026_tts_roles_test"
    admin = "t1g_role_admin"
    return DatabaseTarget(
        host=host,
        port=port,
        database=database,
        admin_role=admin,
        admin_passfile=_write_test_passfile(
            tmp_path / "admin", host=host, port=port, database=database, role=admin
        ),
        migrator_passfile=_write_test_passfile(
            tmp_path / "migrator",
            host=host,
            port=port,
            database=database,
            role=MIGRATOR_ROLE,
        ),
        api_passfile=_write_test_passfile(
            tmp_path / "api", host=host, port=port, database=database, role=API_ROLE
        ),
        worker_passfile=_write_test_passfile(
            tmp_path / "worker",
            host=host,
            port=port,
            database=database,
            role=WORKER_ROLE,
        ),
    )


def _live_target() -> DatabaseTarget:
    required = {
        "host": os.environ.get("TTS_ROLE_TEST_HOST"),
        "port": os.environ.get("TTS_ROLE_TEST_PORT"),
        "database": os.environ.get("TTS_ROLE_TEST_DATABASE"),
        "admin_role": os.environ.get("TTS_ROLE_TEST_ADMIN_ROLE"),
        "admin_passfile": os.environ.get("TTS_ROLE_TEST_ADMIN_PGPASS"),
        "migrator_passfile": os.environ.get("TTS_ROLE_TEST_MIGRATOR_PGPASS"),
        "api_passfile": os.environ.get("TTS_ROLE_TEST_API_PGPASS"),
        "worker_passfile": os.environ.get("TTS_ROLE_TEST_WORKER_PGPASS"),
    }
    missing = sorted(key for key, value in required.items() if not value)
    if missing:
        pytest.skip("T1-G disposable PostgreSQL role environment is not configured")
    return DatabaseTarget(
        host=str(required["host"]),
        port=int(str(required["port"])),
        database=str(required["database"]),
        admin_role=str(required["admin_role"]),
        admin_passfile=Path(str(required["admin_passfile"])),
        migrator_passfile=Path(str(required["migrator_passfile"])),
        api_passfile=Path(str(required["api_passfile"])),
        worker_passfile=Path(str(required["worker_passfile"])),
        expected_head=os.environ.get("TTS_ROLE_TEST_EXPECTED_HEAD", EXPECTED_HEAD),
    )


def _connect(target: DatabaseTarget, role: str) -> psycopg.Connection[tuple[object, ...]]:
    return psycopg.connect(
        host=target.host,
        port=target.port,
        dbname=target.database,
        user=role,
        passfile=str(target.passfile_for(role)),
        connect_timeout=5,
        autocommit=True,
        application_name="ai-novel-t1g-role-pytest",
    )


def test_role_names_and_protected_table_contract_are_fixed() -> None:
    assert (SCHEMA_OWNER, MIGRATOR_ROLE, API_ROLE, WORKER_ROLE) == (
        "ai_novel_schema_owner",
        "ai_novel_migrator",
        "ai_novel_api",
        "ai_novel_worker",
    )
    assert len(PROTECTED_TABLES) == len(set(PROTECTED_TABLES)) == 55
    assert tuple(sorted(PROTECTED_TABLES)) == PROTECTED_TABLES


def test_sql_and_python_protected_table_contracts_match() -> None:
    sql_source = (ROLE_PACKAGE / "protected-tables.sql").read_text(encoding="utf-8")
    sql_tables = tuple(re.findall(r"\('([a-z][a-z0-9_]*)'\)", sql_source))
    assert sql_tables == PROTECTED_TABLES


def test_bootstrap_contract_never_embeds_runtime_passwords() -> None:
    shell_source = (ROLE_PACKAGE / "bootstrap.sh").read_text(encoding="utf-8")
    sql_source = (ROLE_PACKAGE / "bootstrap.sql").read_text(encoding="utf-8")
    migration_source = (ROLE_PACKAGE / "migrate-as-owner.sh").read_text(encoding="utf-8")

    assert "PGPASSWORD is forbidden" in shell_source
    assert "PGPASSWORD is forbidden" in migration_source
    assert "postgresql+psycopg://ai_novel_migrator@" in migration_source
    assert "postgresql+psycopg://ai_novel_migrator:" not in migration_source
    assert "/run/ai-novel-db-auth/migrator/.pgpass" in sql_source
    assert "/run/ai-novel-db-auth/api/.pgpass" in sql_source
    assert "/run/ai-novel-db-auth/worker/.pgpass" in sql_source
    assert "mountpoint -q" in shell_source
    executable_sql = re.sub(r"--.*", "", sql_source)
    assert "CREATE FUNCTION" not in executable_sql
    assert "CREATE PROCEDURE" not in executable_sql


def test_passfiles_require_distinct_0700_parents_and_0600_regular_files(tmp_path: Path) -> None:
    target = _static_target(tmp_path)
    validate_target(target)
    assert stat.S_IMODE(target.api_passfile.stat().st_mode) == 0o600

    target.api_passfile.chmod(0o640)
    with pytest.raises(RoleValidationError, match="ai_novel_api_passfile_mode"):
        validate_target(target)


def test_passfile_hardlinks_and_wrong_admin_identity_fail_closed(tmp_path: Path) -> None:
    target = _static_target(tmp_path)
    hardlink = tmp_path / "api" / "alias"
    os.link(target.api_passfile, hardlink)
    with pytest.raises(RoleValidationError, match="ai_novel_api_passfile_hardlink"):
        validate_target(target)
    hardlink.unlink()

    managed_admin_target = DatabaseTarget(
        **{**target.__dict__, "admin_role": API_ROLE}
    )
    with pytest.raises(RoleValidationError, match="admin_role_must_be_external"):
        validate_target(managed_admin_target)


def test_live_catalog_role_ownership_and_acl_contract() -> None:
    report = collect_and_validate(_live_target())
    assert report["status"] == "PASS"
    assert report["protected_table_count"] == len(PROTECTED_TABLES)
    assert report["worker_business_procedures_present"] is False
    assert report["production_role_switch"] == "HOLD"


@pytest.mark.parametrize("role", [API_ROLE, WORKER_ROLE])
def test_live_runtime_roles_cannot_raw_mutate_protected_tables(role: str) -> None:
    target = _live_target()
    with _connect(target, role) as connection, connection.cursor() as cursor:
        for table_name in PROTECTED_TABLES:
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                  AND is_generated = 'NEVER'
                ORDER BY ordinal_position
                LIMIT 1
                """,
                (table_name,),
            )
            first_column_row = cursor.fetchone()
            assert first_column_row is not None
            first_column = str(first_column_row[0])

            statements = (
                sql.SQL("INSERT INTO public.{} DEFAULT VALUES").format(sql.Identifier(table_name)),
                sql.SQL("UPDATE public.{} SET {} = {} WHERE FALSE").format(
                    sql.Identifier(table_name),
                    sql.Identifier(first_column),
                    sql.Identifier(first_column),
                ),
                sql.SQL("DELETE FROM public.{} WHERE FALSE").format(sql.Identifier(table_name)),
            )
            for statement in statements:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    cursor.execute(statement)


def test_live_api_and_worker_have_no_raw_dml_on_other_tables() -> None:
    target = _live_target()
    with _connect(target, API_ROLE) as connection, connection.cursor() as cursor:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute("UPDATE public.private_assets SET title = title WHERE FALSE")

    with _connect(target, WORKER_ROLE) as connection, connection.cursor() as cursor:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute("UPDATE public.private_assets SET title = title WHERE FALSE")


def test_live_migrator_future_objects_are_owner_owned_and_fail_closed() -> None:
    target = _live_target()
    suffix = uuid4().hex
    table_name = f"t1g_owner_probe_{suffix}"
    routine_name = f"t1g_exec_probe_{suffix}"

    try:
        with _connect(target, MIGRATOR_ROLE) as connection, connection.cursor() as cursor:
            cursor.execute("SET ROLE ai_novel_schema_owner")
            cursor.execute(
                sql.SQL("CREATE TABLE public.{} (id integer PRIMARY KEY)").format(
                    sql.Identifier(table_name)
                )
            )
            cursor.execute(
                sql.SQL(
                    "CREATE FUNCTION public.{}() RETURNS integer "
                    "LANGUAGE sql SECURITY INVOKER AS 'SELECT 1'"
                ).format(sql.Identifier(routine_name))
            )
            cursor.execute("RESET ROLE")

        with _connect(target, API_ROLE) as connection, connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("SELECT count(*) FROM public.{}").format(sql.Identifier(table_name))
            )
            assert cursor.fetchone() == (0,)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cursor.execute(
                    sql.SQL("INSERT INTO public.{} (id) VALUES (1)").format(
                        sql.Identifier(table_name)
                    )
                )
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cursor.execute(
                    sql.SQL("SELECT public.{}()").format(sql.Identifier(routine_name))
                )

        with _connect(target, target.admin_role) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT owner.rolname
                FROM pg_catalog.pg_class relation
                JOIN pg_catalog.pg_namespace namespace ON namespace.oid = relation.relnamespace
                JOIN pg_catalog.pg_roles owner ON owner.oid = relation.relowner
                WHERE namespace.nspname = 'public' AND relation.relname = %s
                """,
                (table_name,),
            )
            assert cursor.fetchone() == (SCHEMA_OWNER,)
            cursor.execute(
                """
                SELECT owner.rolname,
                       has_function_privilege('ai_novel_api', routine.oid, 'EXECUTE'),
                       has_function_privilege('ai_novel_worker', routine.oid, 'EXECUTE')
                FROM pg_catalog.pg_proc routine
                JOIN pg_catalog.pg_namespace namespace ON namespace.oid = routine.pronamespace
                JOIN pg_catalog.pg_roles owner ON owner.oid = routine.proowner
                WHERE namespace.nspname = 'public' AND routine.proname = %s
                """,
                (routine_name,),
            )
            assert cursor.fetchone() == (SCHEMA_OWNER, False, False)
    finally:
        with _connect(target, MIGRATOR_ROLE) as connection, connection.cursor() as cursor:
            cursor.execute("SET ROLE ai_novel_schema_owner")
            cursor.execute(
                sql.SQL("DROP FUNCTION IF EXISTS public.{}()").format(
                    sql.Identifier(routine_name)
                )
            )
            cursor.execute(
                sql.SQL("DROP TABLE IF EXISTS public.{}").format(sql.Identifier(table_name))
            )
            cursor.execute("RESET ROLE")
