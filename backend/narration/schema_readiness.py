"""Fail-closed Alembic ancestry checks for narration feature gates.

Narration owns a minimum required migration, not the application's global
head.  A later, known migration on the same single linear chain must remain
compatible instead of disabling TTS merely because another feature advanced
the repository head.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Iterable, Mapping

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG_PATH = REPOSITORY_ROOT / "alembic.ini"
NARRATION_FEATURE_MINIMUM_DATABASE_REVISION = "20260829_0034"

_FEATURE_REQUIRED_COLUMNS = {
    "voice_profile_versions": {"model_run_id"},
    "voice_deletion_requests": {
        "superseded_at",
        "job_drain_started_at",
        "job_drain_deadline",
    },
    "nano_voice_experiment_commands": {
        "id",
        "profile_id",
        "version_id",
        "preview_id",
        "background_job_id",
        "parameters_digest",
        "input_digest",
        "fingerprint",
        "state",
    },
}
_FEATURE_REQUIRED_CHECKS = {
    "voice_profile_versions": {
        "ck_voice_profile_version_locked_shape",
        "ck_voice_profile_version_model_run_shape",
    },
    "voice_deletion_requests": {
        "ck_voice_deletion_request_superseded_shape",
        "ck_voice_deletion_request_job_drain_shape",
        "ck_voice_deletion_request_failure_shape",
    },
    "nano_voice_experiment_commands": {
        "ck_nano_voice_experiment_state",
        "ck_nano_voice_experiment_lifecycle",
        "ck_nano_voice_experiment_parameters_shape",
    },
}
_FEATURE_REQUIRED_TRIGGERS = {
    "trg_voice_profile_version_locked",
    "trg_voice_deletion_state",
    "trg_nano_voice_experiment_lifecycle",
    "trg_nano_voice_experiment_closure",
    "trg_nano_voice_experiment_preview_closure",
    "trg_nano_voice_experiment_job_closure",
    "trg_nano_voice_experiment_version_closure",
    "trg_nano_voice_experiment_model_run_closure",
    "trg_nano_voice_experiment_model_run_immutable",
}
_FEATURE_REQUIRED_FUNCTION_MARKERS = {
    "narration_check_nano_voice_experiment_closure_v1()": (
        "nano_voice_experiment_commands",
        "OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX+MOSS-Audio-Tokenizer-Nano-ONNX",
        "f52645cb467506d8e18e746ddd59482685b74e58+ceff0d0749bfb3fa2d61149794ec6feef0d1e1ae",
        "command_row.reused_version",
    ),
    "narration_guard_voice_preview_job_closure_v1()": (
        "nano_voice_experiment_commands",
        "command.reused_version IS TRUE",
        "experimental_machine_validated",
    ),
    "narration_guard_voice_preview_scope_v1()": (
        "narration-nano-experiment-version/1",
        "nano_voice_experiment_commands",
    ),
    "narration_guard_voice_deletion()": (
        "superseded",
        "VOICE_DELETE_WAITING_FOR_JOBS",
    ),
}


@lru_cache(maxsize=8)
def _linear_repository_chain(config_path: str) -> tuple[str, ...]:
    """Return the sole repository chain from head to base.

    Empty means the migration graph is missing, branched, cyclic, malformed,
    or otherwise unsafe for a runtime readiness decision.
    """

    try:
        config_file = Path(config_path)
        config = Config(str(config_file))
        raw_script_location = config.get_main_option("script_location")
        if not raw_script_location:
            return ()
        script_location = Path(raw_script_location)
        if not script_location.is_absolute():
            script_location = config_file.parent / script_location
        config.set_main_option("script_location", str(script_location.resolve()))
        scripts = ScriptDirectory.from_config(config)
        heads = tuple(scripts.get_heads())
        if len(heads) != 1:
            return ()
        chain: list[str] = []
        seen: set[str] = set()
        current = scripts.get_revision(heads[0])
        while current is not None:
            revision = current.revision
            if type(revision) is not str or not revision or revision in seen:
                return ()
            seen.add(revision)
            chain.append(revision)
            down_revision = current.down_revision
            if down_revision is None:
                break
            if type(down_revision) is not str or not down_revision:
                return ()
            current = scripts.get_revision(down_revision)
            if current is None:
                return ()
        return tuple(chain)
    except Exception:
        return ()


def database_revision_satisfies(
    revisions: Iterable[object],
    *,
    minimum_revision: str,
    config_path: Path = ALEMBIC_CONFIG_PATH,
) -> bool:
    """Return true only for one known revision containing the minimum.

    Both the installed revision and the minimum must lie on the repository's
    sole linear head-to-base chain, and the minimum must be an ancestor of (or
    equal to) the installed revision.  Unknown/forked/multiple values fail
    closed without leaking database or filesystem details.
    """

    values = tuple(revisions)
    if (
        len(values) != 1
        or type(values[0]) is not str
        or not values[0]
        or type(minimum_revision) is not str
        or not minimum_revision
    ):
        return False
    chain = _linear_repository_chain(str(config_path.resolve()))
    if not chain:
        return False
    current_revision = values[0]
    try:
        current_index = chain.index(current_revision)
        minimum_index = chain.index(minimum_revision)
    except ValueError:
        return False
    return current_index <= minimum_index


def _function_definitions_satisfy(
    definitions: Mapping[str, object],
) -> bool:
    """Reject a named-but-stale 0034 database function surface."""

    if set(definitions) != set(_FEATURE_REQUIRED_FUNCTION_MARKERS):
        return False
    return all(
        type(definition) is str
        and all(marker in definition for marker in markers)
        for signature, markers in _FEATURE_REQUIRED_FUNCTION_MARKERS.items()
        for definition in (definitions.get(signature),)
    )


def narration_feature_schema_ready(engine: Engine) -> bool:
    """Verify the complete 0034 schema surface without changing the database.

    An Alembic revision alone is not sufficient for destructive deletion or
    automatic voice binding.  This sentinel also proves the required columns,
    checks and cross-table triggers are present in the current PostgreSQL
    schema.  Any inspection error fails closed and is intentionally redacted
    to a boolean for readiness/health callers.
    """

    if not isinstance(engine, Engine):
        return False
    try:
        with engine.connect() as connection:
            if connection.dialect.name != "postgresql":
                return False
            revisions = tuple(
                str(value)
                for value in connection.scalars(
                    text("SELECT version_num FROM alembic_version")
                )
            )
            if not database_revision_satisfies(
                revisions,
                minimum_revision=NARRATION_FEATURE_MINIMUM_DATABASE_REVISION,
            ):
                return False
            inspector = inspect(connection)
            table_names = set(inspector.get_table_names())
            if not set(_FEATURE_REQUIRED_COLUMNS).issubset(table_names):
                return False
            for table_name, required in _FEATURE_REQUIRED_COLUMNS.items():
                columns = {
                    str(column.get("name"))
                    for column in inspector.get_columns(table_name)
                }
                if not required.issubset(columns):
                    return False
            for table_name, required in _FEATURE_REQUIRED_CHECKS.items():
                checks = {
                    str(constraint.get("name"))
                    for constraint in inspector.get_check_constraints(table_name)
                }
                if not required.issubset(checks):
                    return False
            triggers = set(
                connection.scalars(
                    text(
                        "SELECT trigger_name FROM information_schema.triggers "
                        "WHERE trigger_schema = current_schema()"
                    )
                )
            )
            if not _FEATURE_REQUIRED_TRIGGERS.issubset(triggers):
                return False
            definitions = {
                signature: connection.scalar(
                    text(
                        "SELECT pg_get_functiondef(to_regprocedure(:signature))"
                    ),
                    {"signature": signature},
                )
                for signature in _FEATURE_REQUIRED_FUNCTION_MARKERS
            }
            if not _function_definitions_satisfy(definitions):
                return False
    except Exception:
        return False
    return True


__all__ = [
    "ALEMBIC_CONFIG_PATH",
    "NARRATION_FEATURE_MINIMUM_DATABASE_REVISION",
    "database_revision_satisfies",
    "narration_feature_schema_ready",
]
