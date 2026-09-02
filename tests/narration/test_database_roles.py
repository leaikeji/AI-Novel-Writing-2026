from __future__ import annotations

import os
from pathlib import Path
import re
import stat
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from backend.models import Base
from scripts.tts.validate_database_roles import (
    API_ROLE,
    CURRENT_PROTECTED_TABLES,
    MIGRATOR_ROLE,
    NON_TTS_CHARACTER_TABLE_ALLOWLIST,
    PROTECTED_TABLES_BY_HEAD,
    SCHEMA_OWNER,
    SUPPORTED_HEADS,
    WORKER_ROLE,
    DatabaseTarget,
    RoleValidationError,
    _parse_args,
    collect_and_validate,
    protected_tables_for_head,
    unclassified_tts_authority_tables,
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
    encoded_password: str | None = None,
) -> Path:
    root.mkdir(mode=0o700)
    path = root / ".pgpass"
    password = encoded_password if encoded_password is not None else "0" * 64
    path.write_text(
        f"{host}:{port}:{database}:{role}:{password}\n",
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
            tmp_path / "admin",
            host=host,
            port=port,
            database=database,
            role=admin,
            encoded_password=r"local\:admin\\password",
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
        expected_head="20260829_0034",
        maintenance_step="validate-20260829_0034",
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
        "expected_head": os.environ.get("TTS_ROLE_TEST_EXPECTED_HEAD"),
        "maintenance_step": os.environ.get("TTS_ROLE_TEST_MAINTENANCE_STEP"),
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
        expected_head=str(required["expected_head"]),
        maintenance_step=str(required["maintenance_step"]),
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


def test_role_names_and_versioned_protected_table_contract_are_fixed() -> None:
    assert (SCHEMA_OWNER, MIGRATOR_ROLE, API_ROLE, WORKER_ROLE) == (
        "ai_novel_schema_owner",
        "ai_novel_migrator",
        "ai_novel_api",
        "ai_novel_worker",
    )
    assert tuple(PROTECTED_TABLES_BY_HEAD) == SUPPORTED_HEADS
    expected_counts = {
        "20260829_0034": 62,
        "20260830_0035": 65,
        "20260901_0036": 67,
        "20260902_0037": 67,
        "20260902_0038": 67,
    }
    for head, protected_tables in PROTECTED_TABLES_BY_HEAD.items():
        assert (
            len(protected_tables)
            == len(set(protected_tables))
            == expected_counts[head]
        )
        assert tuple(sorted(protected_tables)) == protected_tables
        assert protected_tables_for_head(head) is protected_tables
    assert set(PROTECTED_TABLES_BY_HEAD["20260829_0034"]) < set(
        PROTECTED_TABLES_BY_HEAD["20260830_0035"]
    ) < set(PROTECTED_TABLES_BY_HEAD["20260901_0036"])
    assert set(PROTECTED_TABLES_BY_HEAD["20260902_0037"]) == set(
        PROTECTED_TABLES_BY_HEAD["20260901_0036"]
    )
    assert set(PROTECTED_TABLES_BY_HEAD["20260902_0038"]) == set(
        PROTECTED_TABLES_BY_HEAD["20260902_0037"]
    )
    assert {
        "nano_voice_experiment_commands",
        "narration_script_review_actions",
        "voice_action_commands",
        "voice_action_receipts",
        "voice_deletion_asset_plans",
        "voice_previews",
        "voice_reference_asset_links",
    } <= set(PROTECTED_TABLES_BY_HEAD["20260829_0034"])
    assert set(PROTECTED_TABLES_BY_HEAD["20260830_0035"]) - set(
        PROTECTED_TABLES_BY_HEAD["20260829_0034"]
    ) == {
        "voice_design_drafts",
        "voice_generator_commands",
        "voice_generator_run_evidence",
    }
    assert set(PROTECTED_TABLES_BY_HEAD["20260901_0036"]) - set(
        PROTECTED_TABLES_BY_HEAD["20260830_0035"]
    ) == {
        "character_cast_plan_commands",
        "character_cast_plan_items",
    }
    assert CURRENT_PROTECTED_TABLES is PROTECTED_TABLES_BY_HEAD["20260902_0038"]


def test_sql_and_python_protected_table_contracts_match() -> None:
    sql_source = (ROLE_PACKAGE / "protected-tables.sql").read_text(encoding="utf-8")
    sql_tables = tuple(re.findall(r"\('([a-z][a-z0-9_]*)'\)", sql_source))
    assert sql_tables == CURRENT_PROTECTED_TABLES
    executable_sql = re.sub(r"--.*", "", sql_source).upper()
    assert "GRANT " not in executable_sql


def test_current_protected_tables_are_66_orm_tables_plus_alembic_system_table() -> None:
    orm_tables = set(Base.metadata.tables)
    protected_tables = set(CURRENT_PROTECTED_TABLES)

    assert protected_tables - orm_tables == {"alembic_version"}
    assert len(protected_tables - {"alembic_version"}) == 66
    assert protected_tables - {"alembic_version"} <= orm_tables


def test_tts_authority_prefix_audit_fails_closed_for_unclassified_tables() -> None:
    assert set(NON_TTS_CHARACTER_TABLE_ALLOWLIST) == {
        "character_instance_revisions",
        "character_instances",
        "character_profile_apply_batches",
        "character_relationship_revisions",
        "character_relationships",
    }
    assert all(NON_TTS_CHARACTER_TABLE_ALLOWLIST.values())
    assert unclassified_tts_authority_tables(
        Base.metadata.tables,
        protected_tables=CURRENT_PROTECTED_TABLES,
    ) == ()
    assert unclassified_tts_authority_tables(
        (*Base.metadata.tables, "voice_future_authority"),
        protected_tables=CURRENT_PROTECTED_TABLES,
    ) == ("voice_future_authority",)


@pytest.mark.parametrize(
    ("head", "error_code"),
    [
        ("20260901-0036", "invalid_expected_head"),
        ("", "invalid_expected_head"),
        (None, "invalid_expected_head"),
        ("20990101_9999", "unsupported_expected_head"),
        ("20260829_0033", "unsupported_expected_head"),
    ],
)
def test_expected_head_is_formatted_supported_and_fail_closed(
    tmp_path: Path,
    head: object,
    error_code: str,
) -> None:
    target = _static_target(tmp_path)
    invalid = DatabaseTarget(
        **{**target.__dict__, "expected_head": head}  # type: ignore[arg-type]
    )
    with pytest.raises(RoleValidationError, match=error_code):
        validate_target(invalid)


def test_cli_requires_explicit_expected_head(tmp_path: Path) -> None:
    target = _static_target(tmp_path)
    arguments = [
        "--host",
        target.host,
        "--port",
        str(target.port),
        "--database",
        target.database,
        "--admin-role",
        target.admin_role,
        "--admin-passfile",
        str(target.admin_passfile),
        "--migrator-passfile",
        str(target.migrator_passfile),
        "--api-passfile",
        str(target.api_passfile),
        "--worker-passfile",
        str(target.worker_passfile),
        "--maintenance-step",
        target.maintenance_step,
    ]
    with pytest.raises(SystemExit, match="2"):
        _parse_args(arguments)


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
    assert "PASSWORD NULL" in sql_source
    assert "upgrade-20260902_0038" in migration_source
    assert "downgrade-20260902_0037" in migration_source
    assert "downgrade-20260830_0035" in migration_source
    assert "upgrade head" not in migration_source
    executable_sql = re.sub(r"--.*", "", sql_source)
    assert "CREATE FUNCTION" not in executable_sql
    assert "CREATE PROCEDURE" not in executable_sql


def test_production_maintenance_overlay_is_explicit_and_fail_closed() -> None:
    overlay = ROLE_PACKAGE / "compose.maintenance.yaml"
    source = overlay.read_text(encoding="utf-8")

    assert not (ROLE_PACKAGE / "compose.example.yaml").exists()
    assert source.count('profiles: ["database-role-maintenance"]') == 3
    for service in (
        "database-role-bootstrap",
        "database-role-validate",
        "database-schema-migrate",
    ):
        assert f"  {service}:" in source
    for variable in (
        "AI_NOVEL_MAINTENANCE_ROOT_VOLUME:?",
        "POSTGRES_ROLE_BOOTSTRAP_ADMIN_PGPASS_DIR:?",
        "AI_NOVEL_ROLE_EXPECTED_HEAD:?",
        "AI_NOVEL_MIGRATION_COMMAND:?",
        "AI_NOVEL_MIGRATION_TARGET:?",
        "AI_NOVEL_MAINTENANCE_STEP:?",
        "AI_NOVEL_MAINTENANCE_QWENPAW_IMAGE:?",
    ):
        assert variable in source
    assert "POSTGRES_PASSWORD" not in source
    assert "PGPASSWORD" not in source
    assert 'user: "65532:65532"' in source
    assert 'AI_NOVEL_MIGRATOR_UID: "65532"' in source
    assert 'AI_NOVEL_API_UID: "0"' in source
    assert 'AI_NOVEL_WORKER_UID: "0"' in source
    assert "ai-novel-2026-db-migrator-auth" in source
    assert "ai-novel-2026-db-api-auth" in source
    assert "ai-novel-2026-db-worker-auth" in source
    assert source.count("external: true") == 5
    assert "AI_NOVEL_DATABASE_NETWORK" in source
    assert "AI_NOVEL_ROLE_PGHOST" in source
    assert "create_host_path: false" in source
    assert 'cap_add: ["DAC_READ_SEARCH"]' in source
    assert source.count("pull_policy: never") == 3

    migrate_block = source.split("  database-schema-migrate:", 1)[1].split(
        "\nvolumes:", 1
    )[0]
    assert "source: db-migrator-auth" in migrate_block
    assert "source: db-api-auth" not in migrate_block
    assert "source: db-worker-auth" not in migrate_block
    assert "read_only: true" in migrate_block
    assert 'cap_drop: ["ALL"]' in migrate_block


def test_passfiles_require_distinct_0700_parents_and_0600_regular_files(tmp_path: Path) -> None:
    target = _static_target(tmp_path)
    validate_target(target)
    assert stat.S_IMODE(target.api_passfile.stat().st_mode) == 0o600

    target.api_passfile.chmod(0o640)
    with pytest.raises(RoleValidationError, match="ai_novel_api_passfile_mode"):
        validate_target(target)


def test_admin_passfile_allows_non_hex_password_and_libpq_escapes(tmp_path: Path) -> None:
    target = _static_target(tmp_path)

    validate_target(target)

    target.migrator_passfile.write_text(
        (
            f"{target.host}:{target.port}:{target.database}:"
            f"{MIGRATOR_ROLE}:not-a-generated-password\n"
        ),
        encoding="utf-8",
    )
    target.migrator_passfile.chmod(0o600)
    with pytest.raises(
        RoleValidationError,
        match="ai_novel_migrator_passfile_password_strength",
    ):
        validate_target(target)


def test_validation_step_must_match_expected_head(tmp_path: Path) -> None:
    target = _static_target(tmp_path)
    mismatched = DatabaseTarget(
        **{**target.__dict__, "maintenance_step": "validate-20260830_0035"}
    )

    with pytest.raises(
        RoleValidationError,
        match="maintenance_step_expected_head_mismatch",
    ):
        validate_target(mismatched)


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
    target = _live_target()
    report = collect_and_validate(target)
    assert report["status"] == "PASS"
    assert report["protected_table_count"] == len(
        protected_tables_for_head(target.expected_head)
    )
    assert report["worker_business_procedures_present"] is False
    assert report["production_role_switch"] == "HOLD"


@pytest.mark.parametrize("role", [API_ROLE, WORKER_ROLE])
def test_live_runtime_roles_cannot_raw_mutate_protected_tables(role: str) -> None:
    target = _live_target()
    with _connect(target, role) as connection, connection.cursor() as cursor:
        for table_name in protected_tables_for_head(target.expected_head):
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
