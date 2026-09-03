#!/usr/bin/env python3
"""Run a bounded real generic-voice pack build against a disposable database.

The operator must provide an exact loopback/host-gateway test database, private
Sidecar and VoiceGenerator token paths, and a disposable media root.  The
script never creates novels or touches the long-term PawApp database.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Final
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from backend.models import GenericVoiceGenerationCommand, GenericVoicePackVersionSlot
from backend.narration.contracts import NarrationRequestScope
from backend.narration.digest_keyring import load_digest_keyring
from backend.narration.generic_voice_generation import GENERIC_VOICE_JOB_KIND
from backend.narration.generic_voice_pack_service import (
    SqlAlchemyGenericVoicePackService,
    SqlAlchemyGenericVoiceRepository,
)
from backend.narration.jobs import claim_next_job
from backend.narration.runtime import (
    EXPECTED_PRODUCTION_MODEL_FINGERPRINT_SHA256,
    SidecarRuntimeError,
    build_moss_adapter_from_environment,
)
from backend.narration.storage import NarrationStorage
from backend.narration.voice_generator_processor import VoiceGeneratorProcessor
from backend.narration.voice_generator_runtime import (
    NativeVoiceGeneratorHostClient,
    VoiceGeneratorHostConfig,
)


EXPECTED_DATABASE: Final = "ai_novel_world_2026_tts_test"
EXPECTED_HEAD: Final = "20260903_0040"


class RealPackError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--media-root", type=Path, required=True)
    parser.add_argument("--sidecar-host", required=True)
    parser.add_argument("--sidecar-port", type=int, default=8765)
    parser.add_argument("--sidecar-token-file", type=Path, required=True)
    parser.add_argument("--voice-generator-host", required=True)
    parser.add_argument("--voice-generator-port", type=int, default=18765)
    parser.add_argument("--voice-generator-token-file", type=Path, required=True)
    parser.add_argument("--digest-keyring-file", type=Path, required=True)
    parser.add_argument("--max-slots", type=int, default=1)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--summary-output", type=Path)
    return parser


def _database_url() -> str:
    value = os.environ.get("TTS_TEST_DATABASE_URL", "").strip()
    if not value:
        raise RealPackError("TTS_TEST_DATABASE_URL_REQUIRED")
    parsed = make_url(value)
    if (
        not parsed.drivername.startswith("postgresql")
        or parsed.database != EXPECTED_DATABASE
        or parsed.host not in {"127.0.0.1", "localhost", "::1", "host.docker.internal"}
    ):
        raise RealPackError("TEST_DATABASE_SCOPE_INVALID")
    production = os.environ.get("AI_NOVEL_DATABASE_URL", "").strip()
    if production:
        current = make_url(production)
        if (parsed.host, parsed.port, parsed.database) == (
            current.host,
            current.port,
            current.database,
        ):
            raise RealPackError("TEST_DATABASE_MATCHES_PRODUCTION")
    return value


def _private_file(path: Path, label: str) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise RealPackError(f"{label}_INVALID")
    return resolved


def _directory(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise RealPackError("MEDIA_ROOT_INVALID")
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


async def _run(args: argparse.Namespace) -> dict[str, object]:
    if not 1 <= args.max_slots <= 24:
        raise RealPackError("MAX_SLOTS_INVALID")
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
            raise RealPackError("TEST_DATABASE_HEAD_INVALID")
        service = SqlAlchemyGenericVoicePackService(factory)
        current = service.get_load_resource()
        if current.pack.state == "missing":
            current = service.build(idempotency_key="tts55-real-generic-pack-v1")
        elif current.pack.state in {
            "failed",
            "superseded",
            "rejected",
            "retired_for_new_use",
        } and args.retry_failed:
            if current.command is None:
                raise RealPackError("GENERIC_VOICE_PACK_COMMAND_MISSING")
            current = service.retry(current.command.command_id)
        if current.pack.state not in {"building", "active"}:
            raise RealPackError(
                current.pack.failure_code or "GENERIC_VOICE_PACK_NOT_RUNNABLE"
            )
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
            raise RealPackError("SIDECAR_ADAPTER_UNAVAILABLE")
        host = NativeVoiceGeneratorHostClient(
            VoiceGeneratorHostConfig(
                host=args.voice_generator_host,
                port=args.voice_generator_port,
                token_file=voice_generator_token,
                timeout_seconds=5.0,
            )
        )
        health = await host.health()
        if not health.ready:
            raise RealPackError("VOICE_GENERATOR_HOST_NOT_READY")
        keyring = load_digest_keyring(digest_keyring_file)
        processor = VoiceGeneratorProcessor(
            repository=SqlAlchemyGenericVoiceRepository(factory),  # type: ignore[arg-type]
            host=host,
            nano_adapter=adapter,
            storage=NarrationStorage(models_root=models_root, media_root=media_root),
            digest_keyring=keyring,
            poll_seconds=1.0,
        )
        renewal_stop = asyncio.Event()

        async def renew_sidecar_lease() -> None:
            # Product runtime owns the equivalent renewal loop.  This isolated
            # harness must do the same while VoiceGenerator runs for several
            # minutes, otherwise the intentionally short Sidecar lease expires
            # before Nano validation begins.
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
            renew_sidecar_lease(), name="tts55-real-sidecar-lease-renewal"
        )
        completed_before = current.pack.prepared_slots
        processed = 0
        try:
            while processed < args.max_slots:
                current = service.get_load_resource()
                if current.pack.state == "active":
                    break
                if current.pack.state != "building":
                    raise RealPackError(
                        current.pack.failure_code or "GENERIC_VOICE_PACK_BUILD_FAILED"
                    )
                with factory() as session:
                    lease = claim_next_job(
                        session,
                        scope=NarrationRequestScope.fixed_local(),
                        lease_owner=f"tts55-real:{uuid4()}",
                        resource_classes=("moss-nano",),
                        job_kinds=(GENERIC_VOICE_JOB_KIND,),
                        lease_seconds=1800,
                    )
                    if lease is not None:
                        session.commit()
                if lease is None:
                    raise RealPackError("GENERIC_VOICE_JOB_NOT_CLAIMABLE")
                await processor.process(lease)
                processed += 1
                current = service.get_load_resource()
                progress = {
                    "schema_version": "tts55-real-generic-pack-progress/1",
                    "pack_version_id": str(current.pack.pack_version_id),
                    "processed_this_run": processed,
                    "prepared_slots": current.pack.prepared_slots,
                    "pack_state": current.pack.state,
                    "updated_at": datetime.now(UTC).isoformat(),
                }
                print(json.dumps(progress, sort_keys=True), flush=True)
                if current.pack.state not in {"building", "active"}:
                    raise RealPackError(
                        current.pack.failure_code or "GENERIC_VOICE_PACK_BUILD_FAILED"
                    )
        finally:
            renewal_stop.set()
            await renewal_task
            # Leave the isolated Sidecar alive but unloaded, and release its
            # worker lease so teardown does not depend on process exit timing.
            try:
                await adapter.release_model_for_heavy_runtime()
            finally:
                await adapter.deactivate()

        current = service.get_load_resource()
        pack_id = current.pack.pack_version_id
        with factory() as session:
            command_count = session.scalar(
                select(text("count(*)")).select_from(GenericVoiceGenerationCommand)
            )
            validated = tuple(
                session.scalars(
                    select(GenericVoicePackVersionSlot)
                    .where(
                        GenericVoicePackVersionSlot.pack_version_id == pack_id,
                        GenericVoicePackVersionSlot.state.in_(("validated", "reused")),
                    )
                    .order_by(GenericVoicePackVersionSlot.position)
                )
            )
        return {
            "schema_version": "tts55-real-generic-pack-summary/1",
            "database": EXPECTED_DATABASE,
            "migration_head": EXPECTED_HEAD,
            "pack_version_id": str(pack_id),
            "pack_state": current.pack.state,
            "prepared_before": completed_before,
            "processed_this_run": processed,
            "prepared_slots": current.pack.prepared_slots,
            "command_count": int(command_count or 0),
            "validated_slot_keys": [slot.slot_key for slot in validated],
            "all_media_private": True,
            "long_term_database_touched": False,
            "completed_at": datetime.now(UTC).isoformat(),
        }
    finally:
        engine.dispose()


def main() -> int:
    args = _parser().parse_args()
    try:
        summary = asyncio.run(_run(args))
    except (RealPackError, OSError, RuntimeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "schema_version": "tts55-real-generic-pack-summary/1",
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
