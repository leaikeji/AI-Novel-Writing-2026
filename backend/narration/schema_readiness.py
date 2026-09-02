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
REPOSITORY_BASE_REVISION = "20260823_0001"
NARRATION_FEATURE_MINIMUM_DATABASE_REVISION = "20260829_0034"
VOICE_GENERATOR_MINIMUM_DATABASE_REVISION = "20260830_0035"
CHARACTER_CAST_MINIMUM_DATABASE_REVISION = "20260901_0036"

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

_VOICE_GENERATOR_REQUIRED_COLUMNS = {
    "voice_design_drafts": {
        "id",
        "novel_id",
        "character_id",
        "instruction_digest",
        "runtime_identity_json",
        "fingerprint",
    },
    "voice_generator_commands": {
        "id",
        "draft_id",
        "background_job_id",
        "host_request_id",
        "generated_reference_asset_id",
        "nano_validation_asset_id",
        "generator_model_run_id",
        "nano_model_run_id",
        "voice_version_id",
        "state",
    },
    "voice_generator_run_evidence": {
        "id",
        "command_id",
        "model_run_id",
        "requested_identity_json",
        "actual_identity_json",
        "runtime_fingerprint",
        "result_classification",
    },
}
_VOICE_GENERATOR_REQUIRED_CHECKS = {
    "voice_design_drafts": {
        "ck_voice_design_draft_brief_schema",
        "ck_voice_design_draft_official_parameters",
        "ck_voice_design_draft_runtime_identity",
    },
    "voice_generator_commands": {
        "ck_voice_generator_command_state",
        "ck_voice_generator_command_terminal_shape",
        "ck_voice_generator_command_request_identity",
    },
    "voice_generator_run_evidence": {
        "ck_voice_generator_run_runtime_identity",
        "ck_voice_generator_run_success_shape",
    },
}
_VOICE_GENERATOR_REQUIRED_TRIGGERS = {
    "trg_voice_design_draft_immutable",
    "trg_voice_generator_run_evidence_immutable",
    "trg_voice_generator_command_lifecycle",
    "trg_two_phase_voice_generator_model_run",
    "trg_voice_generator_command_closure",
    "trg_voice_generator_job_closure",
    "trg_voice_generator_model_run_closure",
    "trg_voice_generator_version_closure",
    "trg_voice_generator_binding_closure",
    "trg_voice_generator_media_closure",
    "trg_voice_generator_profile_closure",
}
_VOICE_GENERATOR_REQUIRED_FUNCTION_MARKERS = {
    "narration_reject_voice_generator_immutable_v1()": (
        "immutable VoiceGenerator evidence cannot be changed",
    ),
    "narration_guard_voice_generator_command_v1()": (
        "terminal VoiceGenerator command is immutable",
        "invalid VoiceGenerator command state transition",
        "VoiceGenerator command progress is not monotonic",
    ),
    "narration_guard_two_phase_voice_generator_run_v1()": (
        "narration.voice_generate",
        "background attempt cannot carry another ModelRun",
    ),
    "narration_check_voice_generator_closure_v1()": (
        "VoiceGenerator draft/job closure mismatch",
        "VoiceGenerator result evidence closure mismatch",
        "VoiceGenerator applied binding closure mismatch",
        "generated voice version lacks its command",
    ),
    "narration_guard_media_identity()": (
        "planned_voice_deletion",
        "voice_deletion_asset_plans",
        "referenced media identity is immutable",
    ),
}

_CHARACTER_CAST_REQUIRED_COLUMNS = {
    "character_cast_plan_commands": {
        "id",
        "novel_id",
        "timeline_id",
        "idempotency_key",
        "request_hash",
        "character_catalog_version",
        "settings_version",
        "catalog_fingerprint",
        "workspace_digest",
        "bindings_digest",
        "state",
        "progress_current",
        "progress_total",
    },
    "character_cast_plan_items": {
        "id",
        "command_id",
        "target_key",
        "target_kind",
        "expected_binding_version",
        "workspace_digest",
        "attempt",
        "lease_fence",
        "lease_expires_at",
        "brief_json",
        "model_evidence_json",
        "selected_preset_key",
        "voice_action_command_id",
        "voice_source_type",
        "current_preset_key",
        "state",
    },
}
_CHARACTER_CAST_REQUIRED_CHECKS = {
    "character_cast_plan_commands": {
        "ck_character_cast_plan_state",
        "ck_character_cast_plan_digests",
        "ck_character_cast_plan_terminal_shape",
    },
    "character_cast_plan_items": {
        "ck_character_cast_plan_item_target",
        "ck_character_cast_plan_item_state",
        "ck_character_cast_plan_item_lease",
        "ck_character_cast_plan_item_brief_schema",
    },
}
_CHARACTER_CAST_REQUIRED_INDEXES = {
    "character_cast_plan_commands": {
        "uq_character_cast_plan_active",
        "ix_character_cast_plan_scope_created",
    },
    "character_cast_plan_items": {
        "ix_character_cast_plan_items_command_state",
    },
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
    if not chain or chain[-1] != REPOSITORY_BASE_REVISION:
        return False
    current_revision = values[0]
    try:
        current_index = chain.index(current_revision)
        minimum_index = chain.index(minimum_revision)
    except ValueError:
        return False
    return current_index <= minimum_index


def repository_unique_head() -> str | None:
    """Return the trusted repository's sole canonical head, or fail closed.

    This intentionally accepts no path.  Candidate packages must use the
    separate no-execution AST parser and cannot be routed through Alembic's
    trusted-repository loader.
    """

    chain = _linear_repository_chain(str(ALEMBIC_CONFIG_PATH.resolve()))
    if not chain or chain[-1] != REPOSITORY_BASE_REVISION:
        return None
    return chain[0]


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


def voice_generator_schema_ready(engine: Engine) -> bool:
    """Verify the complete 0035 VoiceGenerator authority without writes."""

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
                minimum_revision=VOICE_GENERATOR_MINIMUM_DATABASE_REVISION,
            ):
                return False
            inspector = inspect(connection)
            table_names = set(inspector.get_table_names())
            if not set(_VOICE_GENERATOR_REQUIRED_COLUMNS).issubset(table_names):
                return False
            for table_name, required in _VOICE_GENERATOR_REQUIRED_COLUMNS.items():
                columns = {
                    str(column.get("name"))
                    for column in inspector.get_columns(table_name)
                }
                if not required.issubset(columns):
                    return False
            for table_name, required in _VOICE_GENERATOR_REQUIRED_CHECKS.items():
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
            if not _VOICE_GENERATOR_REQUIRED_TRIGGERS.issubset(triggers):
                return False
            for signature, markers in _VOICE_GENERATOR_REQUIRED_FUNCTION_MARKERS.items():
                definition = connection.scalar(
                    text(
                        "SELECT pg_get_functiondef(to_regprocedure(:signature))"
                    ),
                    {"signature": signature},
                )
                if type(definition) is not str or not all(
                    marker in definition for marker in markers
                ):
                    return False
            resource_class = connection.scalar(
                text(
                    "SELECT resource_class FROM background_job_kind_policies "
                    "WHERE job_kind='narration.voice_generate'"
                )
            )
            if resource_class != "moss-nano":
                return False
    except Exception:
        return False
    return True


def character_cast_schema_ready(engine: Engine) -> bool:
    """Verify the complete 0036 cast-command authority without writes."""

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
                minimum_revision=CHARACTER_CAST_MINIMUM_DATABASE_REVISION,
            ):
                return False
            inspector = inspect(connection)
            table_names = set(inspector.get_table_names())
            if not set(_CHARACTER_CAST_REQUIRED_COLUMNS).issubset(table_names):
                return False
            for table_name, required in _CHARACTER_CAST_REQUIRED_COLUMNS.items():
                columns = {
                    str(column.get("name"))
                    for column in inspector.get_columns(table_name)
                }
                if not required.issubset(columns):
                    return False
            for table_name, required in _CHARACTER_CAST_REQUIRED_CHECKS.items():
                checks = {
                    str(constraint.get("name"))
                    for constraint in inspector.get_check_constraints(table_name)
                }
                if not required.issubset(checks):
                    return False
            for table_name, required in _CHARACTER_CAST_REQUIRED_INDEXES.items():
                indexes = {
                    str(index.get("name"))
                    for index in inspector.get_indexes(table_name)
                }
                if not required.issubset(indexes):
                    return False
    except Exception:
        return False
    return True


__all__ = [
    "ALEMBIC_CONFIG_PATH",
    "CHARACTER_CAST_MINIMUM_DATABASE_REVISION",
    "NARRATION_FEATURE_MINIMUM_DATABASE_REVISION",
    "REPOSITORY_BASE_REVISION",
    "VOICE_GENERATOR_MINIMUM_DATABASE_REVISION",
    "database_revision_satisfies",
    "character_cast_schema_ready",
    "narration_feature_schema_ready",
    "repository_unique_head",
    "voice_generator_schema_ready",
]
