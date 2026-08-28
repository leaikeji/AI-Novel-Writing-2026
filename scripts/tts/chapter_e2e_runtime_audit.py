#!/usr/bin/env python3
"""Read-only PostgreSQL evidence port for the guarded T4-K real executor.

The public PawApp API deliberately omits private voice-version and ModelRun
rows.  This module fills only that evidence gap.  Every database operation is
performed in an explicitly read-only PostgreSQL transaction, scoped to the
fixed local owner/workspace and the dedicated novel/document supplied by the
runner.  It never returns chapter text, audio bytes, paths, or secrets.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Callable, Iterator, Protocol
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.models import (
    BackgroundJob,
    BackgroundJobAttempt,
    CharacterVoiceBinding,
    Document,
    MediaAsset,
    ModelRunRecord,
    NarrationEdition,
    NarrationEditionSegment,
    NarrationRequest,
    NarrationRenderAsset,
    NarrationScript,
    NarrationScriptVersion,
    NarrationSegment,
    NarrationSegmentRender,
    NovelCharacter,
    NovelNarrationSettings,
    VoiceProfile,
    VoiceProfileVersion,
    VoiceReferenceAssetLink,
    VoiceRightsEvent,
    VoiceRightsRecord,
)
from backend.narration.contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID
from scripts.tts.chapter_e2e_executor import (
    ChainAuditEvidence,
    HttpResponse,
    LoopbackHttpTransport,
    RuntimePreflightEvidence,
    RuntimeTechnicalEvidence,
    TechnicalProbeContext,
)
from scripts.tts.chapter_e2e_probes import BoundProbeReportCache
from scripts.tts.validate_chapter_e2e import ChapterFixture, RunnerConfig, RunnerError


_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_OFFICIAL_PRESET_ID_RE = re.compile(r"^onnx\.[A-Za-z][A-Za-z0-9_-]{0,79}$")
_NEGATIVE_RIGHTS_EVENTS = frozenset({"revoked", "expired", "review_blocked"})
_OFFICIAL_REPOSITORY = "OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX"
_OFFICIAL_REVISION = "f52645cb467506d8e18e746ddd59482685b74e58"
_OFFICIAL_MANIFEST_PATH = "browser_poc_manifest.json"
_OFFICIAL_MANIFEST_SHA256 = (
    "097d80e993dc29f0bae427590b4f77084a161cb578b50d82c29f455d5faa9eee"
)
_OFFICIAL_MODEL_FINGERPRINT_SHA256 = (
    "3c76f3e9e1381699c5555287cf66eeb023632d0c3ee94adc6d8ae1b1d455fd7d"
)
_OFFICIAL_PROVENANCE_SCHEMA = "moss-tts-official-preset-provenance/1.0"


def _valid_official_provenance(version: VoiceProfileVersion) -> bool:
    parameters = version.parameters_json
    if type(parameters) is not dict:
        return False
    provenance = parameters.get("official_preset")
    exact_keys = {
        "schema_version",
        "repository",
        "revision",
        "manifest_path",
        "manifest_sha256",
        "preset_id",
        "manifest_voice",
        "prompt_codes_sha256",
        "prompt_frame_count",
        "prompt_quantizer_count",
        "model_fingerprint_sha256",
        "provenance_fingerprint_sha256",
    }
    if type(provenance) is not dict or set(provenance) != exact_keys:
        return False
    preset_id = provenance.get("preset_id")
    manifest_voice = provenance.get("manifest_voice")
    fingerprint = provenance.get("provenance_fingerprint_sha256")
    if (
        provenance.get("schema_version") != _OFFICIAL_PROVENANCE_SCHEMA
        or provenance.get("repository") != _OFFICIAL_REPOSITORY
        or provenance.get("revision") != _OFFICIAL_REVISION
        or provenance.get("manifest_path") != _OFFICIAL_MANIFEST_PATH
        or provenance.get("manifest_sha256") != _OFFICIAL_MANIFEST_SHA256
        or type(preset_id) is not str
        or _OFFICIAL_PRESET_ID_RE.fullmatch(preset_id) is None
        or version.preset_key != preset_id
        or type(manifest_voice) is not str
        or preset_id != f"onnx.{manifest_voice}"
        or type(provenance.get("prompt_frame_count")) is not int
        or provenance["prompt_frame_count"] <= 0
        or provenance.get("prompt_quantizer_count") != 16
        or _SHA256_RE.fullmatch(str(provenance.get("prompt_codes_sha256", "")))
        is None
        or provenance.get("model_fingerprint_sha256")
        != _OFFICIAL_MODEL_FINGERPRINT_SHA256
        or type(fingerprint) is not str
        or _SHA256_RE.fullmatch(fingerprint) is None
    ):
        return False
    unsigned = dict(provenance)
    unsigned.pop("provenance_fingerprint_sha256")
    return fingerprint == hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


SessionFactory = Callable[[], Session]


class RuntimeAuditReader(Protocol):
    """Narrow seam used to test orchestration without a product database."""

    def preflight(self, config: RunnerConfig) -> RuntimePreflightEvidence: ...

    def audit_chain(
        self,
        config: RunnerConfig,
        *,
        request_id: UUID,
        edition_id: UUID,
        script_version_id: UUID,
        job_ids: tuple[UUID, ...],
        segment_ids: tuple[UUID, ...],
    ) -> ChainAuditEvidence: ...


def _response_json(response: HttpResponse) -> dict[str, object]:
    if type(response) is not HttpResponse or response.status != 200:
        raise RunnerError("RUNTIME_AUDIT_HEALTH_INVALID")
    content_type = response.header("Content-Type") or ""
    if content_type.split(";", 1)[0].strip() != "application/json":
        raise RunnerError("RUNTIME_AUDIT_HEALTH_INVALID")
    try:
        value = json.loads(response.body.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RunnerError("RUNTIME_AUDIT_HEALTH_INVALID") from error
    if type(value) is not dict:
        raise RunnerError("RUNTIME_AUDIT_HEALTH_INVALID")
    return value


class SqlAlchemyRuntimeAuditReader:
    """Production reader over the existing project PostgreSQL database."""

    def __init__(self, session_factory: SessionFactory) -> None:
        if not callable(session_factory):
            raise RunnerError("RUNTIME_AUDIT_DATABASE_REQUIRED")
        self._session_factory = session_factory
        self._model_fingerprint: str | None = None
        self._narrator_voice: tuple[UUID, UUID] | None = None
        self._character_ids_by_name: dict[str, UUID] = {}
        self._character_voices_by_id: dict[UUID, tuple[UUID, UUID]] = {}
        self._expected_profiles: dict[UUID, UUID] = {}

    @contextmanager
    def _read_session(self) -> Iterator[Session]:
        try:
            with self._session_factory() as session:
                bind = session.get_bind()
                if bind.dialect.name != "postgresql":
                    raise RunnerError("RUNTIME_AUDIT_POSTGRES_REQUIRED")
                session.execute(text("SET TRANSACTION READ ONLY"))
                read_only = session.scalar(
                    text("SELECT current_setting('transaction_read_only')")
                )
                if read_only != "on":
                    raise RunnerError("RUNTIME_AUDIT_READ_ONLY_REQUIRED")
                yield session
                session.rollback()
        except RunnerError:
            raise
        except Exception as error:
            raise RunnerError("RUNTIME_AUDIT_DATABASE_FAILED") from error

    def preflight(self, config: RunnerConfig) -> RuntimePreflightEvidence:
        if type(config) is not RunnerConfig:
            raise RunnerError("RUNTIME_AUDIT_SCOPE_INVALID")
        health = _response_json(
            LoopbackHttpTransport(config.api_base).request(
                method="GET",
                path="/health",
                timeout_seconds=30,
            )
        )
        narration = health.get("narration")
        production = health.get("narration_production")
        if type(narration) is not dict or type(production) is not dict:
            raise RunnerError("RUNTIME_AUDIT_HEALTH_INVALID")
        fingerprint = narration.get("model_fingerprint_sha256")
        if (
            health.get("status") != "ready"
            or narration.get("technical_enabled") is not True
            or narration.get("lifecycle_status") != "ready"
            or narration.get("sidecar_reachable") is not True
            or narration.get("model_ready") is not True
            or narration.get("product_visible") is not False
            or type(fingerprint) is not str
            or fingerprint != _OFFICIAL_MODEL_FINGERPRINT_SHA256
            or production.get("product_requested") is not True
            or production.get("lifecycle_status") != "ready"
            or production.get("production_backend_installed") is not True
            or production.get("worker_running") is not True
            or production.get("reference_clone_ready") is not False
            or production.get("reason_code") is not None
        ):
            raise RunnerError("RUNTIME_AUDIT_HEALTH_INVALID")
        with self._read_session() as session:
            self._validate_dedicated_voice_preflight(session, config)
        self._model_fingerprint = fingerprint
        return RuntimePreflightEvidence(
            production_ready=True,
            sidecar_ready=True,
            product_visible=False,
            model_fingerprint=fingerprint,
        )

    def _validate_dedicated_voice_preflight(
        self,
        session: Session,
        config: RunnerConfig,
    ) -> None:
        expected_names = config.expected_formal_speakers
        if (
            len(expected_names) != 2
            or len(expected_names) != len(set(expected_names))
            or any(
                type(name) is not str
                or not name
                or name != name.strip()
                or len(name) > 240
                for name in expected_names
            )
        ):
            raise RunnerError("RUNTIME_AUDIT_DEDICATED_SCOPE_INVALID")
        document = session.get(Document, config.document_id)
        settings = session.scalar(
            select(NovelNarrationSettings).where(
                NovelNarrationSettings.novel_id == config.novel_id
            )
        )
        if (
            document is None
            or document.novel_id != config.novel_id
            or document.kind != "chapter"
            or settings is None
            or settings.narrator_profile_id is None
            or settings.narrator_version_id is None
            or settings.script_review_policy != "blockers_only"
        ):
            raise RunnerError("RUNTIME_AUDIT_DEDICATED_SCOPE_INVALID")
        characters = session.scalars(
            select(NovelCharacter).where(
                NovelCharacter.novel_id == config.novel_id,
                NovelCharacter.lifecycle_state == "active",
                NovelCharacter.name.in_(expected_names),
            )
        ).all()
        character_ids_by_name = {row.name: row.id for row in characters}
        if (
            len(characters) != len(expected_names)
            or set(character_ids_by_name) != set(expected_names)
            or len(set(character_ids_by_name.values())) != len(expected_names)
        ):
            raise RunnerError("RUNTIME_AUDIT_DEDICATED_SCOPE_INVALID")
        expected_character_ids = set(character_ids_by_name.values())
        bindings = session.scalars(
            select(CharacterVoiceBinding).where(
                CharacterVoiceBinding.novel_id == config.novel_id,
                CharacterVoiceBinding.character_id.in_(expected_character_ids),
                CharacterVoiceBinding.binding_policy == "dedicated",
            )
        ).all()
        character_voices_by_id: dict[UUID, tuple[UUID, UUID]] = {}
        expected_profiles: dict[UUID, UUID] = {
            settings.narrator_version_id: settings.narrator_profile_id
        }
        for binding in bindings:
            if (
                binding.character_id not in expected_character_ids
                or binding.profile_id is None
                or binding.voice_version_id is None
                or binding.character_id in character_voices_by_id
            ):
                raise RunnerError("RUNTIME_AUDIT_DEDICATED_SCOPE_INVALID")
            character_voices_by_id[binding.character_id] = (
                binding.voice_version_id,
                binding.profile_id,
            )
            existing = expected_profiles.setdefault(
                binding.voice_version_id,
                binding.profile_id,
            )
            if existing != binding.profile_id:
                raise RunnerError("RUNTIME_AUDIT_DEDICATED_SCOPE_INVALID")
        if (
            set(character_voices_by_id) != expected_character_ids
            or len(expected_profiles) != 3
            or len(set(expected_profiles.values())) != 3
        ):
            raise RunnerError("RUNTIME_AUDIT_DEDICATED_SCOPE_INVALID")
        self._validate_voice_versions(
            session,
            novel_id=config.novel_id,
            expected_profiles=expected_profiles,
        )
        self._narrator_voice = (
            settings.narrator_version_id,
            settings.narrator_profile_id,
        )
        self._character_ids_by_name = character_ids_by_name
        self._character_voices_by_id = character_voices_by_id
        self._expected_profiles = expected_profiles

    @staticmethod
    def _validate_voice_versions(
        session: Session,
        *,
        novel_id: UUID,
        expected_profiles: dict[UUID, UUID],
    ) -> None:
        versions = session.scalars(
            select(VoiceProfileVersion).where(
                VoiceProfileVersion.id.in_(tuple(expected_profiles))
            )
        ).all()
        if {row.id for row in versions} != set(expected_profiles):
            raise RunnerError("RUNTIME_AUDIT_VOICE_INVALID")
        profiles = {
            row.id: row
            for row in session.scalars(
                select(VoiceProfile).where(
                    VoiceProfile.id.in_(tuple(expected_profiles.values()))
                )
            ).all()
        }
        rights_ids = {row.rights_record_id for row in versions}
        rights = {
            row.id: row
            for row in session.scalars(
                select(VoiceRightsRecord).where(
                    VoiceRightsRecord.id.in_(tuple(rights_ids))
                )
            ).all()
        }
        links = {
            row.voice_version_id: row
            for row in session.scalars(
                select(VoiceReferenceAssetLink).where(
                    VoiceReferenceAssetLink.voice_version_id.in_(
                        tuple(expected_profiles)
                    )
                )
            ).all()
        }
        confirmed_rights = set(
            session.scalars(
                select(VoiceRightsEvent.rights_record_id).where(
                    VoiceRightsEvent.rights_record_id.in_(tuple(rights_ids)),
                    VoiceRightsEvent.event_type == "confirmed",
                )
            ).all()
        )
        negative_rights = set(
            session.scalars(
                select(VoiceRightsEvent.rights_record_id).where(
                    VoiceRightsEvent.rights_record_id.in_(tuple(rights_ids)),
                    VoiceRightsEvent.event_type.in_(tuple(_NEGATIVE_RIGHTS_EVENTS)),
                )
            ).all()
        )
        now = datetime.now(timezone.utc)
        preset_ids: set[str] = set()
        for version in versions:
            profile = profiles.get(version.profile_id)
            right = rights.get(version.rights_record_id)
            link = links.get(version.id)
            if (
                expected_profiles.get(version.id) != version.profile_id
                or version.owner_id != LOCAL_OWNER_ID
                or version.workspace_id != LOCAL_WORKSPACE_ID
                or version.source_type != "preset"
                or version.reference_asset_id is not None
                or version.state != "locked"
                or version.quality_state != "accepted"
                or version.locked_actor is None
                or version.locked_at is None
                or _SHA256_RE.fullmatch(version.fingerprint) is None
                or profile is None
                or profile.owner_id != LOCAL_OWNER_ID
                or profile.workspace_id != LOCAL_WORKSPACE_ID
                or profile.novel_id != novel_id
                or profile.status != "active"
                or profile.current_version_id != version.id
                or right is None
                or right.owner_id != LOCAL_OWNER_ID
                or right.workspace_id != LOCAL_WORKSPACE_ID
                or right.novel_id != novel_id
                or right.source_kind != "official_preset"
                or right.purpose != "private_novel_narration"
                or right.commercial_use is not False
                or right.redistribution is not False
                or right.voice_cloning is not False
                or right.subject_consent_reference is not None
                or not right.confirmed_actor
                or right.confirmed_at is None
                or right.id not in confirmed_rights
                or right.id in negative_rights
                or (right.expires_at is not None and right.expires_at <= now)
                or link is not None
                or not _valid_official_provenance(version)
            ):
                raise RunnerError("RUNTIME_AUDIT_VOICE_INVALID")
            assert version.preset_key is not None
            preset_ids.add(version.preset_key)
        if len(preset_ids) != 3:
            raise RunnerError("RUNTIME_AUDIT_VOICE_INVALID")

    @staticmethod
    def _validate_segment_voice_mapping(
        script_segments: list[NarrationSegment],
        edition_segments: list[NarrationEditionSegment],
        *,
        narrator_voice: tuple[UUID, UUID],
        character_voices_by_id: dict[UUID, tuple[UUID, UUID]],
        expected_profiles: dict[UUID, UUID],
    ) -> None:
        """Prove narrator and both formal speakers use their frozen voices."""

        if (
            len(script_segments) != len(edition_segments)
            or len(character_voices_by_id) != 2
            or len(expected_profiles) != 3
        ):
            raise RunnerError("RUNTIME_AUDIT_CHAIN_INVALID")
        seen_narrator = False
        seen_character_ids: set[UUID] = set()
        for script_row, edition_row in zip(
            script_segments,
            edition_segments,
            strict=True,
        ):
            if script_row.speaker_kind == "narrator":
                seen_narrator = True
                expected_voice = narrator_voice
            elif (
                script_row.speaker_kind == "character"
                and script_row.character_id in character_voices_by_id
            ):
                seen_character_ids.add(script_row.character_id)
                expected_voice = character_voices_by_id[script_row.character_id]
            else:
                raise RunnerError("RUNTIME_AUDIT_CHAIN_INVALID")
            if (
                edition_row.voice_version_id != expected_voice[0]
                or edition_row.profile_id != expected_voice[1]
            ):
                raise RunnerError("RUNTIME_AUDIT_CHAIN_INVALID")
        if (
            not seen_narrator
            or seen_character_ids != set(character_voices_by_id)
            or {
                (row.voice_version_id, row.profile_id)
                for row in edition_segments
            }
            != set(expected_profiles.items())
        ):
            raise RunnerError("RUNTIME_AUDIT_CHAIN_INVALID")

    def audit_chain(
        self,
        config: RunnerConfig,
        *,
        request_id: UUID,
        edition_id: UUID,
        script_version_id: UUID,
        job_ids: tuple[UUID, ...],
        segment_ids: tuple[UUID, ...],
    ) -> ChainAuditEvidence:
        expected_model = self._model_fingerprint
        if (
            type(config) is not RunnerConfig
            or expected_model is None
            or self._narrator_voice is None
            or set(self._character_ids_by_name)
            != set(config.expected_formal_speakers)
            or len(self._character_voices_by_id) != 2
            or len(self._expected_profiles) != 3
            or not job_ids
            or len(job_ids) != len(set(job_ids))
            or not segment_ids
            or len(segment_ids) != len(set(segment_ids))
        ):
            raise RunnerError("RUNTIME_AUDIT_CHAIN_INVALID")
        with self._read_session() as session:
            return self._audit_chain_rows(
                session,
                config=config,
                request_id=request_id,
                edition_id=edition_id,
                script_version_id=script_version_id,
                job_ids=job_ids,
                segment_ids=segment_ids,
                expected_model=expected_model,
            )

    def _audit_chain_rows(
        self,
        session: Session,
        *,
        config: RunnerConfig,
        request_id: UUID,
        edition_id: UUID,
        script_version_id: UUID,
        job_ids: tuple[UUID, ...],
        segment_ids: tuple[UUID, ...],
        expected_model: str,
    ) -> ChainAuditEvidence:
        request = session.get(NarrationRequest, request_id)
        edition = session.get(NarrationEdition, edition_id)
        script_version = session.get(NarrationScriptVersion, script_version_id)
        script = (
            session.get(NarrationScript, script_version.script_id)
            if script_version is not None
            else None
        )
        if (
            request is None
            or request.owner_id != LOCAL_OWNER_ID
            or request.workspace_id != LOCAL_WORKSPACE_ID
            or request.novel_id != config.novel_id
            or request.document_id != config.document_id
            or request.state != "ready"
            or edition is None
            or edition.request_id != request_id
            or edition.script_version_id != script_version_id
            or edition.novel_id != config.novel_id
            or edition.document_id != config.document_id
            or edition.state != "ready"
            or edition.tts_fingerprint != expected_model
            or type(edition.edition_fingerprint) is not str
            or _SHA256_RE.fullmatch(edition.edition_fingerprint) is None
            or script_version is None
            or script_version.state != "approved"
            or script_version.blocker_count != 0
            or script is None
            or script.novel_id != config.novel_id
            or script.document_id != config.document_id
        ):
            raise RunnerError("RUNTIME_AUDIT_CHAIN_INVALID")
        edition_segments = session.scalars(
            select(NarrationEditionSegment)
            .where(NarrationEditionSegment.edition_id == edition_id)
            .order_by(NarrationEditionSegment.ordinal)
        ).all()
        if (
            tuple(row.segment_id for row in edition_segments) != segment_ids
            or any(
                row.script_version_id != script_version_id
                or row.render_state != "ready"
                for row in edition_segments
            )
        ):
            raise RunnerError("RUNTIME_AUDIT_CHAIN_INVALID")
        script_segments = session.scalars(
            select(NarrationSegment)
            .where(
                NarrationSegment.script_version_id == script_version_id,
                NarrationSegment.id.in_(segment_ids),
            )
            .order_by(NarrationSegment.ordinal)
        ).all()
        if tuple(row.id for row in script_segments) != segment_ids:
            raise RunnerError("RUNTIME_AUDIT_CHAIN_INVALID")
        expected_profiles = self._expected_profiles
        narrator_voice = self._narrator_voice
        if narrator_voice is None:
            raise RunnerError("RUNTIME_AUDIT_CHAIN_INVALID")
        self._validate_segment_voice_mapping(
            script_segments,
            edition_segments,
            narrator_voice=narrator_voice,
            character_voices_by_id=self._character_voices_by_id,
            expected_profiles=expected_profiles,
        )
        jobs = session.scalars(
            select(BackgroundJob).where(BackgroundJob.id.in_(job_ids))
        ).all()
        if {row.id for row in jobs} != set(job_ids) or any(
            row.owner_id != LOCAL_OWNER_ID
            or row.workspace_id != LOCAL_WORKSPACE_ID
            or row.novel_id != config.novel_id
            or row.request_id != request_id
            or row.job_kind != "narration.segment_render"
            or row.resource_class != "moss-nano"
            or row.state != "succeeded"
            for row in jobs
        ):
            raise RunnerError("RUNTIME_AUDIT_MODEL_RUN_INVALID")
        renders = session.scalars(
            select(NarrationSegmentRender).where(
                NarrationSegmentRender.source_job_id.in_(job_ids)
            )
        ).all()
        render_by_job = {row.source_job_id: row for row in renders}
        edition_render_fingerprints = {
            row.render_fingerprint for row in edition_segments
        }
        if set(render_by_job) != set(job_ids) or any(
            row.request_id != request_id
            or row.novel_id != config.novel_id
            or row.state != "ready"
            or row.voice_version_id not in expected_profiles
            or row.model_fingerprint != expected_model
            or row.render_fingerprint not in edition_render_fingerprints
            for row in renders
        ):
            raise RunnerError("RUNTIME_AUDIT_MODEL_RUN_INVALID")
        render_ids = {row.id for row in renders}
        playback_links = session.scalars(
            select(NarrationRenderAsset).where(
                NarrationRenderAsset.render_id.in_(tuple(render_ids)),
                NarrationRenderAsset.role == "playback",
            )
        ).all()
        link_by_render = {row.render_id: row for row in playback_links}
        if set(link_by_render) != render_ids:
            raise RunnerError("RUNTIME_AUDIT_MODEL_RUN_INVALID")
        attempts = session.scalars(
            select(BackgroundJobAttempt).where(
                BackgroundJobAttempt.job_id.in_(job_ids)
            )
        ).all()
        attempts_by_id = {row.id: row for row in attempts}
        runs = session.scalars(
            select(ModelRunRecord).where(
                ModelRunRecord.attempt_id.in_(tuple(attempts_by_id))
            )
        ).all()
        successful_jobs: set[UUID] = set()
        for run in runs:
            attempt = attempts_by_id.get(run.attempt_id)
            if attempt is None or run.result_classification != "success":
                continue
            render = render_by_job.get(attempt.job_id)
            link = link_by_render.get(render.id) if render is not None else None
            if (
                render is None
                or link is None
                or attempt.completed_at is None
                or attempt.error_classification is not None
                or attempt.actual_result_digest is None
                or run.actual_model_id is None
                or run.model_fingerprint != expected_model
                or run.output_digest != attempt.actual_result_digest
                or run.output_digest != link.actual_sha256
            ):
                raise RunnerError("RUNTIME_AUDIT_MODEL_RUN_INVALID")
            if attempt.job_id in successful_jobs:
                raise RunnerError("RUNTIME_AUDIT_MODEL_RUN_INVALID")
            successful_jobs.add(attempt.job_id)
        if successful_jobs != set(job_ids):
            raise RunnerError("RUNTIME_AUDIT_MODEL_RUN_INVALID")
        return ChainAuditEvidence(
            request_id=request_id,
            edition_id=edition_id,
            script_version_id=script_version_id,
            edition_fingerprint=edition.edition_fingerprint,
            distinct_voice_version_count=3,
            uncached_nano_job_count=len(successful_jobs),
            model_run_fingerprints=(expected_model,),
        )


class ReportBackedRuntimeAuditProbe:
    """Runtime port combining read-only authority rows with the bound report."""

    def __init__(
        self,
        config: RunnerConfig,
        *,
        reader: RuntimeAuditReader,
        cache: BoundProbeReportCache,
    ) -> None:
        if (
            type(config) is not RunnerConfig
            or not callable(getattr(reader, "preflight", None))
            or not callable(getattr(reader, "audit_chain", None))
            or type(cache) is not BoundProbeReportCache
        ):
            raise RunnerError("RUNTIME_AUDIT_PORT_INVALID")
        self._config = config
        self._reader = reader
        self._cache = cache
        self._preflight: RuntimePreflightEvidence | None = None
        self._audited: dict[UUID, tuple[UUID, UUID]] = {}

    def _require_config(self, config: RunnerConfig) -> None:
        if config != self._config:
            raise RunnerError("RUNTIME_AUDIT_SCOPE_INVALID")

    def preflight(self, config: RunnerConfig) -> RuntimePreflightEvidence:
        self._require_config(config)
        if self._preflight is not None:
            raise RunnerError("RUNTIME_AUDIT_SEQUENCE_INVALID")
        evidence = self._reader.preflight(config)
        if type(evidence) is not RuntimePreflightEvidence:
            raise RunnerError("RUNTIME_AUDIT_EVIDENCE_INVALID")
        self._preflight = evidence
        return evidence

    def audit_chain(
        self,
        config: RunnerConfig,
        *,
        request_id: UUID,
        edition_id: UUID,
        script_version_id: UUID,
        job_ids: tuple[UUID, ...],
        segment_ids: tuple[UUID, ...],
    ) -> ChainAuditEvidence:
        self._require_config(config)
        if self._preflight is None or request_id in self._audited:
            raise RunnerError("RUNTIME_AUDIT_SEQUENCE_INVALID")
        evidence = self._reader.audit_chain(
            config,
            request_id=request_id,
            edition_id=edition_id,
            script_version_id=script_version_id,
            job_ids=job_ids,
            segment_ids=segment_ids,
        )
        if type(evidence) is not ChainAuditEvidence:
            raise RunnerError("RUNTIME_AUDIT_EVIDENCE_INVALID")
        self._audited[request_id] = (edition_id, script_version_id)
        return evidence

    def collect_technical(
        self,
        config: RunnerConfig,
        fixture: ChapterFixture,
        context: TechnicalProbeContext,
    ) -> RuntimeTechnicalEvidence:
        self._require_config(config)
        expected_editions = {
            context.automatic_request_id: context.automatic_edition_id,
            context.manual_request_id: context.manual_edition_id,
        }
        if (
            type(fixture) is not ChapterFixture
            or type(context) is not TechnicalProbeContext
            or self._preflight is None
            or set(self._audited) != set(expected_editions)
            or any(
                self._audited[request_id][0] != edition_id
                for request_id, edition_id in expected_editions.items()
            )
        ):
            raise RunnerError("RUNTIME_AUDIT_SEQUENCE_INVALID")
        outcome = self._cache.load(config, context).to_technical_outcome()
        return RuntimeTechnicalEvidence(
            stability_elapsed_seconds=outcome.stability_elapsed_seconds,
            peak_memory_bytes=outcome.peak_memory_bytes,
            pageout_delta=outcome.pageout_delta,
            swapout_delta=outcome.swapout_delta,
            memory_baseline_median_bytes=(
                outcome.memory_baseline_median_bytes
            ),
            memory_tail_median_bytes=outcome.memory_tail_median_bytes,
            memory_growth_bytes=outcome.memory_growth_bytes,
            memory_growth_limit_bytes=outcome.memory_growth_limit_bytes,
            sidecar_memory_growth_observed=(
                outcome.sidecar_memory_growth_observed
            ),
            seam_pairs_checked=outcome.seam_pairs_checked,
            sidecar_restart_count=outcome.sidecar_restart_count,
            health_failure_count=outcome.health_failure_count,
            host_paging_observed=outcome.host_paging_observed,
            qwenpaw_slowdown_observed=outcome.qwenpaw_slowdown_observed,
        )


__all__ = [
    "ReportBackedRuntimeAuditProbe",
    "RuntimeAuditReader",
    "SessionFactory",
    "SqlAlchemyRuntimeAuditReader",
]
