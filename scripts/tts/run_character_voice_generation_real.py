#!/usr/bin/env python3
"""Run bounded real character VoiceGenerator -> Nano acceptance work.

This operator-only harness is intentionally restricted to the disposable TTS
database.  It reads the authoritative saved character workspace, accepts only
an explicit frozen brief for each target, and then drives the same durable
VoiceGenerator service, background job and processor used by the product.
It never calls a second analysis model and never touches the long-term PawApp
database or media root.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.character_workspace.service import service_for_session
from backend.models import (
    CharacterVoiceBinding,
    Novel,
    NovelCharacter,
    VoiceProfile,
    VoiceProfileVersion,
)
from backend.narration.character_voice_matching import (
    CharacterVoiceBrief,
    CharacterVoiceLanguage,
    CharacterVoicePresentation,
    CharacterVoiceTexture,
)
from backend.narration.contracts import NarrationRequestScope
from backend.narration.digest_keyring import load_digest_keyring
from backend.narration.jobs import claim_next_job
from backend.narration.runtime import (
    EXPECTED_PRODUCTION_MODEL_FINGERPRINT_SHA256,
    SidecarRuntimeError,
    build_moss_adapter_from_environment,
)
from backend.narration.services import canonical_sha256
from backend.narration.storage import NarrationStorage
from backend.narration.voice_design import build_voice_design_instruction
from backend.narration.voice_generator_processor import (
    SqlAlchemyVoiceGeneratorRepository,
    VoiceGeneratorProcessor,
)
from backend.narration.voice_generator_runtime import (
    NativeVoiceGeneratorHostClient,
    VoiceGeneratorHostConfig,
)
from backend.narration.voice_generator_service import (
    VOICE_GENERATOR_JOB_KIND,
    SqlAlchemyVoiceGeneratorService,
    VoiceGeneratorAnalysis,
    voice_generator_request_hash,
)


EXPECTED_DATABASE: Final = "ai_novel_world_2026_tts_test"
EXPECTED_HEAD: Final = "20260903_0040"
GENERATED_ACTIVATION_BASIS: Final = "character_one_click_generation"


class RealCharacterVoiceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CharacterSpec:
    character_id: UUID
    presentation: CharacterVoicePresentation
    pitch: int
    pace: int
    energy: int
    texture: CharacterVoiceTexture


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--novel-id", type=UUID, required=True)
    parser.add_argument(
        "--character",
        action="append",
        required=True,
        metavar="UUID|presentation|pitch|pace|energy|texture",
        help="Explicit brief backed by saved character.details fields.",
    )
    parser.add_argument("--media-root", type=Path, required=True)
    parser.add_argument("--sidecar-host", required=True)
    parser.add_argument("--sidecar-port", type=int, default=8765)
    parser.add_argument("--sidecar-token-file", type=Path, required=True)
    parser.add_argument("--voice-generator-host", required=True)
    parser.add_argument("--voice-generator-port", type=int, default=18765)
    parser.add_argument("--voice-generator-token-file", type=Path, required=True)
    parser.add_argument("--digest-keyring-file", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path)
    return parser


def parse_character_spec(value: str) -> CharacterSpec:
    parts = value.split("|")
    if len(parts) != 6:
        raise RealCharacterVoiceError("CHARACTER_SPEC_INVALID")
    try:
        character_id = UUID(parts[0])
        presentation = CharacterVoicePresentation(parts[1])
        axes = tuple(int(item) for item in parts[2:5])
        texture = CharacterVoiceTexture(parts[5])
    except (ValueError, TypeError) as error:
        raise RealCharacterVoiceError("CHARACTER_SPEC_INVALID") from error
    if any(value not in {-2, -1, 0, 1, 2} for value in axes):
        raise RealCharacterVoiceError("CHARACTER_SPEC_INVALID")
    return CharacterSpec(
        character_id=character_id,
        presentation=presentation,
        pitch=axes[0],
        pace=axes[1],
        energy=axes[2],
        texture=texture,
    )


def _database_url() -> str:
    value = os.environ.get("TTS_TEST_DATABASE_URL", "").strip()
    if not value:
        raise RealCharacterVoiceError("TTS_TEST_DATABASE_URL_REQUIRED")
    parsed = make_url(value)
    if (
        not parsed.drivername.startswith("postgresql")
        or parsed.database != EXPECTED_DATABASE
        or parsed.host not in {"127.0.0.1", "localhost", "::1", "host.docker.internal"}
    ):
        raise RealCharacterVoiceError("TEST_DATABASE_SCOPE_INVALID")
    production = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
    if production:
        current = make_url(production)
        if (parsed.host, parsed.port, parsed.database) == (
            current.host,
            current.port,
            current.database,
        ):
            raise RealCharacterVoiceError("TEST_DATABASE_MATCHES_PRODUCTION")
    return value


def _private_file(path: Path, label: str) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise RealCharacterVoiceError(f"{label}_INVALID")
    return resolved


def _directory(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise RealCharacterVoiceError("MEDIA_ROOT_INVALID")
    return resolved


def _write_summary(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary_name).replace(path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def _workspace_payload(workspace) -> dict[str, object]:
    return {
        "character": workspace.character.model_dump(mode="json"),
        "selected_instance": workspace.selected_instance.model_dump(mode="json"),
        "aliases": [item.model_dump(mode="json") for item in workspace.aliases],
        "relationships": [
            item.model_dump(mode="json") for item in workspace.relationships
        ],
        "projected_state": workspace.projected_state.model_dump(mode="json"),
    }


def _analysis(factory, novel_id: UUID, spec: CharacterSpec) -> VoiceGeneratorAnalysis:
    with factory() as session:
        novel = session.get(Novel, novel_id)
        character = session.scalar(
            select(NovelCharacter).where(
                NovelCharacter.id == spec.character_id,
                NovelCharacter.novel_id == novel_id,
                NovelCharacter.lifecycle_state == "active",
            )
        )
        if novel is None or character is None:
            raise RealCharacterVoiceError("CHARACTER_SCOPE_INVALID")
        details = character.details if isinstance(character.details, dict) else {}
        if not str(details.get("voice", "")).strip() or not str(
            details.get("gender", "")
        ).strip():
            raise RealCharacterVoiceError("SAVED_VOICE_EVIDENCE_REQUIRED")
        workspace = service_for_session(session).get_workspace(
            novel_id, spec.character_id
        )
        payload = _workspace_payload(workspace)
        brief = CharacterVoiceBrief(
            language=CharacterVoiceLanguage.ZH_CN,
            presentation=spec.presentation,
            pitch=spec.pitch,
            pace=spec.pace,
            energy=spec.energy,
            texture=spec.texture,
            evidence_fields=(
                "language:character.details.voice",
                "presentation:character.details.gender",
                "pitch:character.details.voice",
                "pace:character.details.voice",
                "energy:character.details.voice",
                "texture:character.details.voice",
            ),
        )
        instruction = build_voice_design_instruction(
            brief, default_language=CharacterVoiceLanguage.ZH_CN
        )
        return VoiceGeneratorAnalysis(
            character_version=character.version,
            character_catalog_version=novel.character_catalog_version,
            workspace_digest=canonical_sha256(payload),
            brief=brief,
            instruction=instruction.text,
            model_evidence={
                "schema_version": "tts55-operator-verified-brief/1",
                "source": "saved_character_workspace",
                "analysis_model_called": False,
            },
            language=instruction.language.value,
            seed=104_729,
        )


def _generated_binding(factory, spec: CharacterSpec) -> tuple[UUID, UUID] | None:
    with factory() as session:
        binding = session.scalar(
            select(CharacterVoiceBinding).where(
                CharacterVoiceBinding.character_id == spec.character_id
            )
        )
        if (
            binding is None
            or binding.voice_profile_id is None
            or binding.voice_profile_version_id is None
        ):
            return None
        version = session.get(VoiceProfileVersion, binding.voice_profile_version_id)
        profile = session.get(VoiceProfile, binding.voice_profile_id)
        if (
            version is None
            or profile is None
            or version.activation_basis != GENERATED_ACTIVATION_BASIS
            or profile.status != "active"
        ):
            return None
        return profile.id, version.id


async def _run(args: argparse.Namespace) -> dict[str, object]:
    specs = tuple(parse_character_spec(value) for value in args.character)
    if len(specs) > 12 or len({item.character_id for item in specs}) != len(specs):
        raise RealCharacterVoiceError("CHARACTER_SET_INVALID")
    media_root = _directory(args.media_root)
    models_root = _directory(media_root.parent / f".{media_root.name}-models-unused")
    sidecar_token = _private_file(args.sidecar_token_file, "SIDECAR_TOKEN_FILE")
    voice_generator_token = _private_file(
        args.voice_generator_token_file, "VOICE_GENERATOR_TOKEN_FILE"
    )
    digest_keyring_file = _private_file(
        args.digest_keyring_file, "DIGEST_KEYRING_FILE"
    )
    engine = create_engine(_database_url(), pool_pre_ping=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with engine.connect() as connection:
            heads = tuple(connection.scalars(text("SELECT version_num FROM alembic_version")))
        if heads != (EXPECTED_HEAD,):
            raise RealCharacterVoiceError("TEST_DATABASE_HEAD_INVALID")
        adapter = build_moss_adapter_from_environment(
            {
                "AI_NOVEL_TTS_RUNTIME_ENABLED": "true",
                "MOSS_TTS_PROTOCOL_VERSION": "moss-tts-sidecar/1.1",
                "MOSS_TTS_EXPECTED_MODEL_FINGERPRINT_SHA256": (
                    EXPECTED_PRODUCTION_MODEL_FINGERPRINT_SHA256
                ),
                "MOSS_TTS_LIFECYCLE": "compose_on_failure_supervisor",
                "MOSS_TTS_SIDECAR_HOST": args.sidecar_host,
                "MOSS_TTS_SIDECAR_PORT": str(args.sidecar_port),
                "MOSS_TTS_SIDECAR_TOKEN_FILE": str(sidecar_token),
                "MOSS_TTS_REQUEST_TIMEOUT_SECONDS": "300",
            }
        )
        if adapter is None:
            raise RealCharacterVoiceError("SIDECAR_ADAPTER_UNAVAILABLE")
        host = NativeVoiceGeneratorHostClient(
            VoiceGeneratorHostConfig(
                host=args.voice_generator_host,
                port=args.voice_generator_port,
                token_file=voice_generator_token,
                timeout_seconds=5.0,
            )
        )
        if not (await host.health()).ready:
            raise RealCharacterVoiceError("VOICE_GENERATOR_HOST_NOT_READY")
        keyring = load_digest_keyring(digest_keyring_file)
        service = SqlAlchemyVoiceGeneratorService(factory, digest_keyring=keyring)
        processor = VoiceGeneratorProcessor(
            repository=SqlAlchemyVoiceGeneratorRepository(
                factory, digest_keyring=keyring
            ),
            host=host,
            nano_adapter=adapter,
            storage=NarrationStorage(models_root=models_root, media_root=media_root),
            digest_keyring=keyring,
            poll_seconds=1.0,
        )
        renewal_stop = asyncio.Event()

        async def renew_sidecar_lease() -> None:
            while True:
                try:
                    await asyncio.wait_for(renewal_stop.wait(), timeout=10.0)
                    return
                except TimeoutError:
                    pass
                if not adapter.worker_lease_active:
                    continue
                try:
                    await adapter.renew_lease()
                except SidecarRuntimeError as error:
                    if error.code != "WORKER_LEASE_INACTIVE":
                        raise

        renewal_task = asyncio.create_task(
            renew_sidecar_lease(), name="tts55-character-sidecar-lease-renewal"
        )
        results: list[dict[str, object]] = []
        try:
            for position, spec in enumerate(specs, start=1):
                existing = _generated_binding(factory, spec)
                if existing is not None:
                    profile_id, version_id = existing
                    results.append(
                        {
                            "character_id": str(spec.character_id),
                            "state": "preserved_generated",
                            "profile_id": str(profile_id),
                            "voice_version_id": str(version_id),
                        }
                    )
                    continue
                analysis = _analysis(factory, args.novel_id, spec)
                with factory() as session:
                    binding = session.scalar(
                        select(CharacterVoiceBinding).where(
                            CharacterVoiceBinding.character_id == spec.character_id
                        )
                    )
                    expected_binding_version = 0 if binding is None else binding.version
                request_hash = voice_generator_request_hash(
                    novel_id=args.novel_id,
                    character_id=spec.character_id,
                    timeline_id=None,
                    character_instance_id=None,
                    expected_binding_version=expected_binding_version,
                    seed=str(analysis.seed),
                )
                reservation = service.reserve(
                    novel_id=args.novel_id,
                    character_id=spec.character_id,
                    expected_binding_version=expected_binding_version,
                    idempotency_key=(
                        f"tts55-real-character:{spec.character_id}:"
                        f"{canonical_sha256(analysis.brief.to_payload())[:24]}"
                    ),
                    request_hash=request_hash,
                )
                if not reservation.replayed:
                    if not service.begin_analysis(
                        novel_id=args.novel_id, command_id=reservation.command_id
                    ):
                        raise RealCharacterVoiceError("CHARACTER_ANALYSIS_NOT_CLAIMED")
                    job_id = service.finish_analysis(
                        novel_id=args.novel_id,
                        command_id=reservation.command_id,
                        analysis=analysis,
                    )
                else:
                    resource = service.get_resource(
                        novel_id=args.novel_id, command_id=reservation.command_id
                    )
                    job_id = resource.background_job_id
                if job_id is None:
                    raise RealCharacterVoiceError("CHARACTER_JOB_NOT_READY")
                with factory() as session:
                    lease = claim_next_job(
                        session,
                        scope=NarrationRequestScope.fixed_local(),
                        lease_owner=f"tts55-real-character:{uuid4()}",
                        resource_classes=("moss-nano",),
                        job_kinds=(VOICE_GENERATOR_JOB_KIND,),
                        lease_seconds=1800,
                    )
                    if lease is not None:
                        session.commit()
                if lease is None or lease.fence.job_id != job_id:
                    raise RealCharacterVoiceError("CHARACTER_JOB_NOT_CLAIMABLE")
                await processor.process(lease)
                resource = service.get_resource(
                    novel_id=args.novel_id, command_id=reservation.command_id
                )
                if resource.state != "ready_applied":
                    raise RealCharacterVoiceError(
                        resource.failure_code or "CHARACTER_GENERATION_FAILED"
                    )
                results.append(
                    {
                        "character_id": str(spec.character_id),
                        "state": resource.state,
                        "profile_id": str(resource.voice_profile_id),
                        "voice_version_id": str(resource.voice_version_id),
                        "command_id": str(resource.command_id),
                    }
                )
                print(
                    json.dumps(
                        {
                            "schema_version": "tts55-real-character-progress/1",
                            "position": position,
                            "total": len(specs),
                            "character_id": str(spec.character_id),
                            "state": resource.state,
                            "updated_at": datetime.now(UTC).isoformat(),
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
        finally:
            renewal_stop.set()
            await renewal_task
            try:
                await adapter.release_model_for_heavy_runtime()
            finally:
                await adapter.deactivate()
        return {
            "schema_version": "tts55-real-character-summary/1",
            "database": EXPECTED_DATABASE,
            "migration_head": EXPECTED_HEAD,
            "novel_id": str(args.novel_id),
            "characters": results,
            "all_ready": all(item["state"] in {"ready_applied", "preserved_generated"} for item in results),
            "analysis_source": "operator_verified_saved_character_workspace",
            "analysis_model_called": False,
            "long_term_database_touched": False,
            "completed_at": datetime.now(UTC).isoformat(),
        }
    finally:
        engine.dispose()


def main() -> int:
    args = _parser().parse_args()
    try:
        summary = asyncio.run(_run(args))
    except (RealCharacterVoiceError, OSError, RuntimeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "schema_version": "tts55-real-character-summary/1",
                    "status": "failed",
                    "failure_code": str(error),
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return 1
    if args.summary_output is not None:
        _write_summary(args.summary_output, summary)
    print(json.dumps({**summary, "status": "ok"}, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
