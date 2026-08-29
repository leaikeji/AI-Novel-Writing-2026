#!/usr/bin/env python3
"""Validate the T1-G PostgreSQL role/ownership/ACL contract without passwords in argv.

All credentials are read through role-specific libpq passfiles.  The JSON output
contains catalog facts only and deliberately omits passfile paths and secrets.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import stat
import sys
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row


SCHEMA_OWNER = "ai_novel_schema_owner"
MIGRATOR_ROLE = "ai_novel_migrator"
API_ROLE = "ai_novel_api"
WORKER_ROLE = "ai_novel_worker"
MANAGED_ROLES = (SCHEMA_OWNER, MIGRATOR_ROLE, API_ROLE, WORKER_ROLE)
RUNTIME_ROLES = (API_ROLE, WORKER_ROLE)
EXPECTED_HEAD = "20260829_0032"

PROTECTED_TABLES = (
    "active_job_assets",
    "alembic_version",
    "anonymous_speakers",
    "asset_tombstones",
    "background_executor_epochs",
    "background_job_attempts",
    "background_job_kind_policies",
    "background_jobs",
    "background_manual_retry_commands",
    "background_resource_class_policies",
    "background_resource_class_slots",
    "background_resource_locks",
    "character_aliases",
    "character_voice_bindings",
    "derived_source_bindings",
    "document_narration_state",
    "document_revisions",
    "document_working_copies",
    "documents",
    "generic_voice_pools",
    "generic_voice_slots",
    "media_assets",
    "media_gc_deletion_plans",
    "model_run_records",
    "narration_cloud_consents",
    "narration_edition_segments",
    "narration_edition_state",
    "narration_editions",
    "narration_exports",
    "narration_manifest_segments",
    "narration_manifests",
    "narration_playback_progress",
    "narration_render_assets",
    "narration_request_sources",
    "narration_requests",
    "narration_scenes",
    "narration_scope_overrides",
    "narration_script_issues",
    "narration_script_versions",
    "narration_scripts",
    "narration_segment_renders",
    "narration_segments",
    "narration_settings_snapshots",
    "novel_characters",
    "novel_narration_settings",
    "novels",
    "pronunciation_entries",
    "pronunciation_profiles",
    "voice_casting_rules",
    "voice_deletion_requests",
    "voice_profile_versions",
    "voice_profiles",
    "voice_rights_events",
    "voice_rights_records",
    "volumes",
)

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_HOST = re.compile(r"^[A-Za-z0-9._-]+$")
_HEX_PASSWORD = re.compile(r"^[0-9a-f]{64}$")


class RoleValidationError(RuntimeError):
    """Raised with a secret-free contract check identifier."""


@dataclass(frozen=True)
class DatabaseTarget:
    host: str
    port: int
    database: str
    admin_role: str
    admin_passfile: Path
    migrator_passfile: Path
    api_passfile: Path
    worker_passfile: Path
    expected_head: str = EXPECTED_HEAD

    def passfile_for(self, role: str) -> Path:
        mapping = {
            self.admin_role: self.admin_passfile,
            MIGRATOR_ROLE: self.migrator_passfile,
            API_ROLE: self.api_passfile,
            WORKER_ROLE: self.worker_passfile,
        }
        try:
            return mapping[role]
        except KeyError as error:  # pragma: no cover - defensive only
            raise RoleValidationError("unknown_connection_role") from error


def _require(condition: bool, check: str) -> None:
    if not condition:
        raise RoleValidationError(check)


def _validate_identifier(value: str, label: str) -> None:
    _require(bool(_IDENTIFIER.fullmatch(value)), f"invalid_{label}")


def _validate_passfile(
    path: Path,
    *,
    host: str,
    port: int,
    database: str,
    role: str,
) -> None:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise RoleValidationError(f"{role}_passfile_missing") from error
    _require(stat.S_ISREG(metadata.st_mode), f"{role}_passfile_not_regular")
    _require(not stat.S_ISLNK(metadata.st_mode), f"{role}_passfile_symlink")
    _require(stat.S_IMODE(metadata.st_mode) == 0o600, f"{role}_passfile_mode")
    _require(metadata.st_nlink == 1, f"{role}_passfile_hardlink")
    _require(not path.parent.is_symlink(), f"{role}_passfile_parent_symlink")
    _require(stat.S_IMODE(path.parent.stat().st_mode) == 0o700, f"{role}_passfile_parent_mode")

    try:
        records = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise RoleValidationError(f"{role}_passfile_unreadable") from error
    _require(len(records) == 1, f"{role}_passfile_record_count")
    fields = records[0].split(":")
    _require(len(fields) == 5, f"{role}_passfile_shape")
    record_host, record_port, record_database, record_role, password = fields
    _require(record_host == host, f"{role}_passfile_host")
    _require(record_port == str(port), f"{role}_passfile_port")
    _require(record_database == database, f"{role}_passfile_database")
    _require(record_role == role, f"{role}_passfile_role")
    _require(bool(_HEX_PASSWORD.fullmatch(password)), f"{role}_passfile_password_strength")
    del password


def validate_target(target: DatabaseTarget) -> None:
    _require(bool(_HOST.fullmatch(target.host)), "invalid_host")
    _require(1 <= target.port <= 65535, "invalid_port")
    _validate_identifier(target.database, "database")
    _validate_identifier(target.admin_role, "admin_role")
    _require(target.admin_role not in MANAGED_ROLES, "admin_role_must_be_external")

    runtime_paths = (
        target.migrator_passfile.resolve(strict=False),
        target.api_passfile.resolve(strict=False),
        target.worker_passfile.resolve(strict=False),
    )
    _require(len(set(runtime_paths)) == 3, "runtime_passfiles_not_distinct")
    runtime_parents = tuple(path.parent for path in runtime_paths)
    _require(len(set(runtime_parents)) == 3, "runtime_passfile_parents_not_distinct")

    for role in (target.admin_role, MIGRATOR_ROLE, API_ROLE, WORKER_ROLE):
        _validate_passfile(
            target.passfile_for(role),
            host=target.host,
            port=target.port,
            database=target.database,
            role=role,
        )


def _connect(target: DatabaseTarget, role: str) -> psycopg.Connection[dict[str, Any]]:
    return psycopg.connect(
        host=target.host,
        port=target.port,
        dbname=target.database,
        user=role,
        passfile=str(target.passfile_for(role)),
        connect_timeout=5,
        application_name="ai-novel-t1g-role-validator",
        row_factory=dict_row,
        autocommit=True,
    )


def _fetch_one(connection: psycopg.Connection[dict[str, Any]], query: str, parameters: Iterable[Any] = ()) -> dict[str, Any]:
    with connection.cursor() as cursor:
        cursor.execute(query, tuple(parameters))
        row = cursor.fetchone()
    _require(row is not None, "catalog_query_returned_no_row")
    return row


def _fetch_all(connection: psycopg.Connection[dict[str, Any]], query: str, parameters: Iterable[Any] = ()) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(query, tuple(parameters))
        return list(cursor.fetchall())


def _validate_role_logins(target: DatabaseTarget) -> dict[str, bool]:
    authenticated: dict[str, bool] = {}
    for role in (MIGRATOR_ROLE, API_ROLE, WORKER_ROLE):
        with _connect(target, role) as connection:
            identity = _fetch_one(
                connection,
                "SELECT session_user AS session_user, current_user AS current_user",
            )
            _require(identity == {"session_user": role, "current_user": role}, f"{role}_login_identity")
            authenticated[role] = True

            if role == MIGRATOR_ROLE:
                with connection.cursor() as cursor:
                    cursor.execute("SET ROLE ai_novel_schema_owner")
                    owner_identity = cursor.execute(
                        "SELECT current_user AS current_user"
                    ).fetchone()
                    _require(
                        owner_identity == {"current_user": SCHEMA_OWNER},
                        "migrator_set_role",
                    )
                    cursor.execute("RESET ROLE")
    return authenticated


def collect_and_validate(target: DatabaseTarget) -> dict[str, Any]:
    """Return secret-free catalog evidence or raise ``RoleValidationError``."""

    validate_target(target)
    authenticated = _validate_role_logins(target)

    with _connect(target, target.admin_role) as connection:
        identity = _fetch_one(
            connection,
            """
            SELECT current_database() AS database,
                   session_user AS session_user,
                   current_user AS current_user,
                   (SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname = current_user) AS is_superuser
            """,
        )
        _require(identity["database"] == target.database, "live_database_identity")
        _require(identity["session_user"] == target.admin_role, "live_admin_session_identity")
        _require(identity["current_user"] == target.admin_role, "live_admin_current_identity")
        _require(identity["is_superuser"] is True, "live_admin_not_superuser")

        heads = _fetch_all(
            connection,
            "SELECT version_num FROM public.alembic_version ORDER BY version_num",
        )
        head_values = [row["version_num"] for row in heads]
        _require(head_values == [target.expected_head], "alembic_head")

        role_rows = _fetch_all(
            connection,
            """
            SELECT auth.rolname, auth.rolsuper, auth.rolinherit,
                   auth.rolcreaterole, auth.rolcreatedb, auth.rolcanlogin,
                   auth.rolreplication, auth.rolbypassrls,
                   auth.rolpassword LIKE 'SCRAM-SHA-256$%%' AS password_is_scram,
                   exposed.rolconfig
            FROM pg_catalog.pg_authid auth
            JOIN pg_catalog.pg_roles exposed ON exposed.oid = auth.oid
            WHERE auth.rolname = ANY(%s)
            ORDER BY auth.rolname
            """,
            (list(MANAGED_ROLES),),
        )
        _require(len(role_rows) == len(MANAGED_ROLES), "managed_role_count")
        roles = {row["rolname"]: row for row in role_rows}
        for role in MANAGED_ROLES:
            row = roles[role]
            _require(row["rolsuper"] is False, f"{role}_superuser")
            _require(row["rolcreaterole"] is False, f"{role}_createrole")
            _require(row["rolcreatedb"] is False, f"{role}_createdb")
            _require(row["rolreplication"] is False, f"{role}_replication")
            _require(row["rolbypassrls"] is False, f"{role}_bypassrls")
            _require(row["rolinherit"] is False, f"{role}_inherit")
            _require(row["rolcanlogin"] is (role != SCHEMA_OWNER), f"{role}_login_flag")
            _require(
                row["rolconfig"] == ["search_path=pg_catalog, public"],
                f"{role}_role_config",
            )
            if role != SCHEMA_OWNER:
                _require(row["password_is_scram"] is True, f"{role}_password_not_scram")

        memberships = _fetch_all(
            connection,
            """
            SELECT granted.rolname AS granted_role,
                   member_role.rolname AS member_role,
                   membership.admin_option,
                   membership.inherit_option,
                   membership.set_option
            FROM pg_catalog.pg_auth_members membership
            JOIN pg_catalog.pg_roles granted ON granted.oid = membership.roleid
            JOIN pg_catalog.pg_roles member_role ON member_role.oid = membership.member
            WHERE member_role.rolname = ANY(%s)
               OR granted.rolname = ANY(%s)
            ORDER BY granted.rolname, member_role.rolname
            """,
            (list(MANAGED_ROLES), list(MANAGED_ROLES)),
        )
        _require(
            memberships
            == [
                {
                    "granted_role": SCHEMA_OWNER,
                    "member_role": MIGRATOR_ROLE,
                    "admin_option": False,
                    "inherit_option": False,
                    "set_option": True,
                }
            ],
            "managed_role_memberships",
        )

        database_acl = _fetch_one(
            connection,
            """
            SELECT owner.rolname AS owner,
                   count(*) FILTER (
                       WHERE acl.grantee = 0
                         AND acl.privilege_type IN ('CONNECT', 'CREATE', 'TEMPORARY')
                   ) AS public_privilege_count
            FROM pg_catalog.pg_database database
            JOIN pg_catalog.pg_roles owner ON owner.oid = database.datdba
            LEFT JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(database.datacl, pg_catalog.acldefault('d', database.datdba))
            ) acl ON true
            WHERE database.datname = current_database()
            GROUP BY owner.rolname
            """,
        )
        _require(database_acl["owner"] == SCHEMA_OWNER, "database_owner")
        _require(database_acl["public_privilege_count"] == 0, "database_public_acl")

        schema_acl = _fetch_one(
            connection,
            """
            SELECT owner.rolname AS owner,
                   count(*) FILTER (WHERE acl.grantee = 0) AS public_privilege_count
            FROM pg_catalog.pg_namespace namespace
            JOIN pg_catalog.pg_roles owner ON owner.oid = namespace.nspowner
            LEFT JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(namespace.nspacl, pg_catalog.acldefault('n', namespace.nspowner))
            ) acl ON true
            WHERE namespace.nspname = 'public'
            GROUP BY owner.rolname
            """,
        )
        _require(schema_acl["owner"] == SCHEMA_OWNER, "public_schema_owner")
        _require(schema_acl["public_privilege_count"] == 0, "public_schema_acl")

        relation_violations = _fetch_all(
            connection,
            """
            SELECT namespace.nspname || '.' || relation.relname AS object_name
            FROM pg_catalog.pg_class relation
            JOIN pg_catalog.pg_namespace namespace ON namespace.oid = relation.relnamespace
            JOIN pg_catalog.pg_roles owner ON owner.oid = relation.relowner
            WHERE namespace.nspname = 'public'
              AND relation.relkind IN ('r', 'p', 'S', 'v', 'm', 'f')
              AND owner.rolname <> %s
              AND NOT EXISTS (
                  SELECT 1 FROM pg_catalog.pg_depend dependency
                  WHERE dependency.classid = 'pg_catalog.pg_class'::pg_catalog.regclass
                    AND dependency.objid = relation.oid
                    AND dependency.deptype = 'e'
              )
            ORDER BY object_name
            """,
            (SCHEMA_OWNER,),
        )
        _require(not relation_violations, "application_relation_owner")

        routine_violations = _fetch_all(
            connection,
            """
            SELECT namespace.nspname || '.' || routine.proname AS object_name
            FROM pg_catalog.pg_proc routine
            JOIN pg_catalog.pg_namespace namespace ON namespace.oid = routine.pronamespace
            JOIN pg_catalog.pg_roles owner ON owner.oid = routine.proowner
            WHERE namespace.nspname = 'public'
              AND owner.rolname <> %s
              AND NOT EXISTS (
                  SELECT 1 FROM pg_catalog.pg_depend dependency
                  WHERE dependency.classid = 'pg_catalog.pg_proc'::pg_catalog.regclass
                    AND dependency.objid = routine.oid
                    AND dependency.deptype = 'e'
              )
            ORDER BY object_name
            """,
            (SCHEMA_OWNER,),
        )
        _require(not routine_violations, "application_routine_owner")

        type_violations = _fetch_all(
            connection,
            """
            SELECT namespace.nspname || '.' || type_entry.typname AS object_name
            FROM pg_catalog.pg_type type_entry
            JOIN pg_catalog.pg_namespace namespace ON namespace.oid = type_entry.typnamespace
            JOIN pg_catalog.pg_roles owner ON owner.oid = type_entry.typowner
            WHERE namespace.nspname = 'public'
              AND type_entry.typtype IN ('d', 'e', 'm', 'r')
              AND type_entry.typelem = 0
              AND owner.rolname <> %s
              AND NOT EXISTS (
                  SELECT 1 FROM pg_catalog.pg_depend dependency
                  WHERE dependency.classid = 'pg_catalog.pg_type'::pg_catalog.regclass
                    AND dependency.objid = type_entry.oid
                    AND dependency.deptype = 'e'
              )
            ORDER BY object_name
            """,
            (SCHEMA_OWNER,),
        )
        _require(not type_violations, "application_type_owner")

        protected_rows = _fetch_all(
            connection,
            """
            SELECT relation.relname AS table_name,
                   runtime_role.role_name,
                   pg_catalog.has_table_privilege(runtime_role.role_name, relation.oid, 'SELECT') AS can_select,
                   pg_catalog.has_table_privilege(runtime_role.role_name, relation.oid, 'INSERT') AS can_insert,
                   pg_catalog.has_table_privilege(runtime_role.role_name, relation.oid, 'UPDATE') AS can_update,
                   pg_catalog.has_table_privilege(runtime_role.role_name, relation.oid, 'DELETE') AS can_delete,
                   pg_catalog.has_table_privilege(runtime_role.role_name, relation.oid, 'TRUNCATE') AS can_truncate,
                   pg_catalog.has_table_privilege(runtime_role.role_name, relation.oid, 'REFERENCES') AS can_reference,
                   pg_catalog.has_table_privilege(runtime_role.role_name, relation.oid, 'TRIGGER') AS can_trigger
            FROM pg_catalog.pg_class relation
            JOIN pg_catalog.pg_namespace namespace ON namespace.oid = relation.relnamespace
            CROSS JOIN (VALUES (%s::name), (%s::name)) runtime_role(role_name)
            WHERE namespace.nspname = 'public'
              AND relation.relkind IN ('r', 'p')
              AND relation.relname = ANY(%s)
            ORDER BY relation.relname, runtime_role.role_name
            """,
            (API_ROLE, WORKER_ROLE, list(PROTECTED_TABLES)),
        )
        _require(len(protected_rows) == len(PROTECTED_TABLES) * 2, "protected_table_presence")
        for row in protected_rows:
            _require(row["can_select"] is True, "protected_table_select")
            for key in (
                "can_insert",
                "can_update",
                "can_delete",
                "can_truncate",
                "can_reference",
                "can_trigger",
            ):
                _require(row[key] is False, f"protected_table_{key}")

        global_runtime_dml = _fetch_one(
            connection,
            """
            SELECT count(*) FILTER (
                       WHERE pg_catalog.has_table_privilege(%s, relation.oid, 'INSERT')
                          OR pg_catalog.has_table_privilege(%s, relation.oid, 'UPDATE')
                          OR pg_catalog.has_table_privilege(%s, relation.oid, 'DELETE')
                   ) AS api_mutable_table_count,
                   count(*) FILTER (
                       WHERE pg_catalog.has_table_privilege(%s, relation.oid, 'INSERT')
                          OR pg_catalog.has_table_privilege(%s, relation.oid, 'UPDATE')
                          OR pg_catalog.has_table_privilege(%s, relation.oid, 'DELETE')
                   ) AS worker_mutable_table_count
            FROM pg_catalog.pg_class relation
            JOIN pg_catalog.pg_namespace namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public' AND relation.relkind IN ('r', 'p')
            """,
            (API_ROLE, API_ROLE, API_ROLE, WORKER_ROLE, WORKER_ROLE, WORKER_ROLE),
        )
        _require(global_runtime_dml["api_mutable_table_count"] == 0, "api_global_raw_dml")
        _require(global_runtime_dml["worker_mutable_table_count"] == 0, "worker_global_raw_dml")

        routine_acl = _fetch_one(
            connection,
            """
            SELECT count(*) FILTER (
                       WHERE acl.grantee = 0 AND acl.privilege_type = 'EXECUTE'
                   ) AS public_execute_count,
                   count(*) FILTER (
                       WHERE pg_catalog.has_function_privilege(%s, routine.oid, 'EXECUTE')
                   ) AS api_execute_count,
                   count(*) FILTER (
                       WHERE pg_catalog.has_function_privilege(%s, routine.oid, 'EXECUTE')
                   ) AS worker_execute_count,
                   count(*) FILTER (WHERE routine.prosecdef) AS security_definer_count,
                   count(*) FILTER (
                       WHERE routine.prosecdef
                         AND NOT EXISTS (
                             SELECT 1
                             FROM pg_catalog.unnest(
                                 COALESCE(routine.proconfig, ARRAY[]::text[])
                             ) setting
                             WHERE setting IN ('search_path=', 'search_path=""')
                         )
                   ) AS unsafe_security_definer_count
            FROM pg_catalog.pg_proc routine
            JOIN pg_catalog.pg_namespace namespace ON namespace.oid = routine.pronamespace
            LEFT JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(routine.proacl, pg_catalog.acldefault('f', routine.proowner))
            ) acl ON true
            WHERE namespace.nspname = 'public'
            """,
            (API_ROLE, WORKER_ROLE),
        )
        _require(routine_acl["public_execute_count"] == 0, "public_routine_execute")
        _require(routine_acl["api_execute_count"] == 0, "api_routine_execute")
        _require(routine_acl["worker_execute_count"] == 0, "worker_routine_execute")
        _require(routine_acl["unsafe_security_definer_count"] == 0, "unsafe_security_definer")

        default_acl = _fetch_one(
            connection,
            """
            SELECT count(*) FILTER (
                       WHERE owner.rolname IN (%s, %s)
                         AND defaults.defaclobjtype = 'f'
                         AND acl.grantee = 0
                         AND acl.privilege_type = 'EXECUTE'
                   ) AS public_future_execute_count,
                   count(*) FILTER (
                       WHERE owner.rolname IN (%s, %s)
                         AND defaults.defaclobjtype = 'f'
                   ) AS function_default_acl_entry_count,
                   count(*) FILTER (
                       WHERE owner.rolname IN (%s, %s)
                         AND defaults.defaclobjtype = 'T'
                         AND acl.grantee = 0
                         AND acl.privilege_type = 'USAGE'
                   ) AS public_future_type_usage_count,
                   count(*) FILTER (
                       WHERE owner.rolname = %s
                         AND defaults.defaclobjtype = 'r'
                         AND grantee.rolname = %s
                         AND acl.privilege_type = 'SELECT'
                   ) AS api_future_select_count,
                   count(*) FILTER (
                       WHERE owner.rolname = %s
                         AND defaults.defaclobjtype = 'r'
                         AND grantee.rolname = %s
                         AND acl.privilege_type = 'SELECT'
                   ) AS worker_future_select_count
            FROM pg_catalog.pg_default_acl defaults
            JOIN pg_catalog.pg_roles owner ON owner.oid = defaults.defaclrole
            CROSS JOIN LATERAL pg_catalog.aclexplode(defaults.defaclacl) acl
            LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid = acl.grantee
            WHERE defaults.defaclnamespace IN (0, 'public'::pg_catalog.regnamespace)
            """,
            (
                SCHEMA_OWNER,
                MIGRATOR_ROLE,
                SCHEMA_OWNER,
                MIGRATOR_ROLE,
                SCHEMA_OWNER,
                MIGRATOR_ROLE,
                SCHEMA_OWNER,
                API_ROLE,
                SCHEMA_OWNER,
                WORKER_ROLE,
            ),
        )
        _require(default_acl["public_future_execute_count"] == 0, "default_public_execute")
        _require(default_acl["function_default_acl_entry_count"] >= 2, "default_function_acl_missing")
        _require(default_acl["public_future_type_usage_count"] == 0, "default_public_type_usage")
        _require(default_acl["api_future_select_count"] == 1, "default_api_select")
        _require(default_acl["worker_future_select_count"] == 1, "default_worker_select")

        extension_summary = _fetch_all(
            connection,
            """
            SELECT extension.extname, owner.rolname AS owner
            FROM pg_catalog.pg_extension extension
            JOIN pg_catalog.pg_roles owner ON owner.oid = extension.extowner
            WHERE extension.extname = 'vector'
            """,
        )
        _require(len(extension_summary) == 1, "vector_extension_preprovision")

        relation_count = _fetch_one(
            connection,
            """
            SELECT count(*) AS count
            FROM pg_catalog.pg_class relation
            JOIN pg_catalog.pg_namespace namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public' AND relation.relkind IN ('r', 'p')
            """,
        )["count"]
        routine_count = _fetch_one(
            connection,
            """
            SELECT count(*) AS count
            FROM pg_catalog.pg_proc routine
            JOIN pg_catalog.pg_namespace namespace ON namespace.oid = routine.pronamespace
            WHERE namespace.nspname = 'public'
            """,
        )["count"]

    return {
        "schema_version": "t1-g-database-roles/1",
        "status": "PASS",
        "database": target.database,
        "admin_role": target.admin_role,
        "alembic_head": target.expected_head,
        "managed_roles": list(MANAGED_ROLES),
        "authenticated_roles": authenticated,
        "protected_table_count": len(PROTECTED_TABLES),
        "public_relation_count": relation_count,
        "public_routine_count": routine_count,
        "security_definer_count": routine_acl["security_definer_count"],
        "runtime_passfiles": {
            "distinct_paths": True,
            "bootstrap_requires_independent_mountpoints": True,
            "regular_mode_0600": True,
            "single_link": True,
            "password_bytes": 32,
        },
        "ownership": {
            "database": SCHEMA_OWNER,
            "public_schema": SCHEMA_OWNER,
            "application_relations": SCHEMA_OWNER,
            "application_routines": SCHEMA_OWNER,
            "application_types": SCHEMA_OWNER,
            "extension_members_external": True,
        },
        "acl": {
            "public_routine_execute": False,
            "api_protected_raw_dml": False,
            "worker_protected_raw_dml": False,
            "api_any_raw_dml": False,
            "worker_any_raw_dml": False,
            "future_objects_fail_closed": True,
        },
        "worker_business_procedures_present": False,
        "production_role_switch": "HOLD",
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--database", required=True)
    parser.add_argument("--admin-role", required=True)
    parser.add_argument("--admin-passfile", required=True, type=Path)
    parser.add_argument("--migrator-passfile", required=True, type=Path)
    parser.add_argument("--api-passfile", required=True, type=Path)
    parser.add_argument("--worker-passfile", required=True, type=Path)
    parser.add_argument("--expected-head", default=EXPECTED_HEAD)
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = _parse_args(sys.argv[1:] if argv is None else argv)
    target = DatabaseTarget(
        host=arguments.host,
        port=arguments.port,
        database=arguments.database,
        admin_role=arguments.admin_role,
        admin_passfile=arguments.admin_passfile,
        migrator_passfile=arguments.migrator_passfile,
        api_passfile=arguments.api_passfile,
        worker_passfile=arguments.worker_passfile,
        expected_head=arguments.expected_head,
    )
    try:
        report = collect_and_validate(target)
    except (RoleValidationError, psycopg.Error, OSError) as error:
        error_code = error.args[0] if isinstance(error, RoleValidationError) and error.args else type(error).__name__
        print(
            json.dumps(
                {
                    "schema_version": "t1-g-database-roles/1",
                    "status": "FAIL",
                    "error_code": str(error_code),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1

    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2 if arguments.pretty else None,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
