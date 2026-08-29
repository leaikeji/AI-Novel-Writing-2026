"""Append-only Manifest v2 derivation and current-pointer CAS publication."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Literal, Mapping
from uuid import UUID, uuid4

from ..models import (
    BackgroundJob,
    MediaAsset,
    NarrationEdition,
    NarrationEditionSegment,
    NarrationEditionState,
    NarrationManifest,
    NarrationManifestSegment,
    NarrationRenderAsset,
    NarrationScript,
    NarrationScriptVersion,
    NarrationSegment,
    NarrationSegmentRender,
)

from .fingerprints import canonical_json_bytes
from .renders import render_job_input_hash
from .services import (
    InvalidNarrationState,
    ManifestRevisionCollision,
    NarrationCasConflict,
    NarrationScopeMismatch,
    NarrationStore,
    canonical_payload,
    canonical_sha256,
    require_exact_bool,
    require_exact_int,
    require_local_novel,
    require_nonempty,
    require_row,
    require_sha256,
    require_usable_voice,
    utc_now,
)


MANIFEST_SCHEMA_VERSION = "narration-manifest/2.0"
_CONTROLLED_URL = re.compile(
    r"^/api/ai-novel-world-2026/[A-Za-z0-9_~-]+(?:/[A-Za-z0-9_~-]+)*$"
)
_PLAYBACK_URL = re.compile(
    r"^/api/ai-novel-world-2026/media-assets/"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})/content$",
    re.IGNORECASE,
)
_FAILURE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "edition_id",
        "chapter_id",
        "source_revision_id",
        "source_sha256",
        "buffer_policy",
        "manifest_revision",
        "etag",
        "generated_at",
        "status",
        "ready_prefix_count",
        "default_start_ready",
        "last_playable_start_ordinal",
        "ready_ranges",
        "segments",
    }
)
_POLICY_KEYS = frozenset(
    {
        "version",
        "minimum_segments",
        "minimum_duration_ms",
        "target_segments",
        "chapter_end_exception",
    }
)
_RANGE_KEYS = frozenset(
    {
        "start_ordinal",
        "end_ordinal_exclusive",
        "segment_count",
        "duration_ms",
        "last_playable_start_ordinal",
    }
)
_SEGMENT_KEYS = frozenset(
    {
        "segment_id",
        "ordinal",
        "paragraph_ordinal",
        "source_block_key",
        "source_start_utf16",
        "source_end_utf16",
        "gap_after_ms",
        "render_status",
        "audio",
        "failure",
    }
)
_AUDIO_KEYS = frozenset(
    {"url", "actual_sha256", "duration_ms", "sample_rate", "channels", "etag"}
)
_FAILURE_KEYS = frozenset({"code", "retryable", "message"})
_PUBLIC_RENDER_STATES = frozenset(
    {"pending", "queued", "rendering", "ready", "failed", "cancelled"}
)
_PUBLIC_MANIFEST_STATES = frozenset(
    {"pending", "partial_ready", "ready", "failed", "cancelled"}
)


@dataclass(frozen=True, slots=True)
class BufferPolicy:
    version: str
    minimum_segments: int
    minimum_duration_ms: int
    target_segments: int
    chapter_end_exception: bool

    def payload(self) -> dict[str, object]:
        require_nonempty(self.version, field="buffer policy version")
        require_exact_int(self.minimum_segments, field="minimum_segments", minimum=1)
        require_exact_int(
            self.minimum_duration_ms, field="minimum_duration_ms", minimum=0
        )
        require_exact_int(self.target_segments, field="target_segments", minimum=1)
        require_exact_bool(self.chapter_end_exception, field="chapter_end_exception")
        if self.target_segments < self.minimum_segments:
            raise InvalidNarrationState("target buffer must cover the minimum segment count")
        return {
            "version": self.version,
            "minimum_segments": self.minimum_segments,
            "minimum_duration_ms": self.minimum_duration_ms,
            "target_segments": self.target_segments,
            "chapter_end_exception": self.chapter_end_exception,
        }


INITIAL_BUFFER_POLICY = BufferPolicy(
    version="initial-buffer/v1-3-segments-8000ms",
    minimum_segments=3,
    minimum_duration_ms=8000,
    target_segments=5,
    chapter_end_exception=True,
)
BUFFER_POLICIES = {INITIAL_BUFFER_POLICY.version: INITIAL_BUFFER_POLICY}


def require_frozen_buffer_policy(
    policy: BufferPolicy, *, expected_version: str
) -> BufferPolicy:
    """Resolve a policy version to one immutable server-owned parameter set."""

    expected = BUFFER_POLICIES.get(expected_version)
    if expected is None:
        raise InvalidNarrationState("Edition references an unsupported buffer policy")
    if type(policy) is not BufferPolicy or policy != expected:
        raise InvalidNarrationState(
            "Manifest buffer policy differs from the Edition's frozen server policy"
        )
    policy.payload()
    return policy


@dataclass(frozen=True, slots=True)
class ManifestFailure:
    code: str
    retryable: bool
    message: str

    def payload(self) -> dict[str, object]:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", self.code):
            raise InvalidNarrationState("invalid manifest failure code")
        require_exact_bool(self.retryable, field="failure retryable")
        if type(self.message) is not str or not self.message or len(self.message) > 256:
            raise InvalidNarrationState("invalid manifest failure message")
        return {"code": self.code, "retryable": self.retryable, "message": self.message}


@dataclass(frozen=True, slots=True)
class ManifestSegmentInput:
    edition_segment_id: UUID
    render_status: str
    render_id: UUID | None = None
    failure: ManifestFailure | None = None


@dataclass(frozen=True, slots=True)
class PublishManifest:
    edition_id: UUID
    expected_current_revision: int
    expected_state_version: int
    buffer_policy: BufferPolicy
    segments: tuple[ManifestSegmentInput, ...]
    updated_actor: str


def _authoritative_audio_payload(
    store: NarrationStore,
    *,
    edition: NarrationEdition,
    edition_segment: NarrationEditionSegment,
    render: NarrationSegmentRender,
) -> dict[str, object]:
    if render.voice_version_id != edition_segment.voice_version_id:
        raise InvalidNarrationState("ready render voice differs from Edition voice")
    link = require_row(
        store.find_one(NarrationRenderAsset, render_id=render.id, role="playback"),
        label="render playback asset link",
    )
    asset = require_row(store.get(MediaAsset, link.asset_id), label="playback asset")
    if (
        asset.owner_id != edition.owner_id
        or asset.workspace_id != edition.workspace_id
        or asset.novel_id != edition.novel_id
        or asset.state != "ready"
        or asset.asset_class != "segment_playback"
        or asset.checksum_algorithm != "sha256"
        or link.actual_sha256 != asset.content_hash
        or render.duration_ms != asset.duration_ms
    ):
        raise InvalidNarrationState("Manifest playback asset provenance mismatch")
    actual_sha256 = require_sha256(asset.content_hash, field="audio actual_sha256")
    duration_ms = require_exact_int(asset.duration_ms, field="audio duration_ms", minimum=1)  # type: ignore[arg-type]
    sample_rate = require_exact_int(asset.sample_rate, field="audio sample_rate", minimum=1)  # type: ignore[arg-type]
    channels = require_exact_int(asset.channels, field="audio channels", minimum=1)  # type: ignore[arg-type]
    url = f"/api/ai-novel-world-2026/media-assets/{asset.id}/content"
    if not _CONTROLLED_URL.fullmatch(url):
        raise InvalidNarrationState("derived audio URL is outside the controlled PawApp route")
    return {
        "url": url,
        "actual_sha256": actual_sha256,
        "duration_ms": duration_ms,
        "sample_rate": sample_rate,
        "channels": channels,
        "etag": f'"{actual_sha256}"',
    }


def _range_duration(segments: list[dict[str, object]], start: int, end: int) -> int:
    duration = 0
    for index in range(start, end):
        audio = segments[index]["audio"]
        if isinstance(audio, dict):
            duration += int(audio["duration_ms"])
        if index + 1 < end:
            duration += int(segments[index]["gap_after_ms"])
    return duration


def derive_ready_ranges(
    segments: list[dict[str, object]], policy: BufferPolicy
) -> list[dict[str, int]]:
    policy.payload()
    ranges: list[dict[str, int]] = []
    start = 0
    while start < len(segments):
        if segments[start]["render_status"] != "ready" or not segments[start]["audio"]:
            start += 1
            continue
        end = start + 1
        while (
            end < len(segments)
            and segments[end]["render_status"] == "ready"
            and segments[end]["audio"]
        ):
            end += 1
        last_playable: int | None = None
        suffix_duration_ms = 0
        block_duration_ms = 0
        reaches_end = end == len(segments)
        for candidate in range(end - 1, start - 1, -1):
            audio = segments[candidate]["audio"]
            if not isinstance(audio, dict):
                raise InvalidNarrationState("ready range contains no authoritative audio")
            suffix_duration_ms += require_exact_int(
                audio["duration_ms"], field="audio duration_ms", minimum=1  # type: ignore[arg-type]
            )
            if candidate + 1 < end:
                suffix_duration_ms += require_exact_int(
                    segments[candidate]["gap_after_ms"],
                    field="gap_after_ms",
                    minimum=0,
                )  # type: ignore[arg-type]
            chapter_end_allowed = reaches_end and policy.chapter_end_exception
            threshold = (
                end - candidate >= policy.minimum_segments
                and suffix_duration_ms >= policy.minimum_duration_ms
            )
            if last_playable is None and (chapter_end_allowed or threshold):
                last_playable = candidate
            block_duration_ms = suffix_duration_ms
        if last_playable is not None:
            ranges.append(
                {
                    "start_ordinal": start,
                    "end_ordinal_exclusive": end,
                    "segment_count": end - start,
                    "duration_ms": block_duration_ms,
                    "last_playable_start_ordinal": last_playable,
                }
            )
        start = end
    return ranges


def _derive_status(segments: list[dict[str, object]]) -> str:
    states = [str(item["render_status"]) for item in segments]
    if all(state == "ready" for state in states):
        return "ready"
    if "ready" in states:
        return "partial_ready"
    if any(state in {"pending", "queued", "rendering"} for state in states):
        return "pending"
    if "failed" in states:
        return "failed"
    return "cancelled"


def _semantic_payload(
    store: NarrationStore,
    edition: NarrationEdition,
    revision: int,
    policy: BufferPolicy,
    inputs: tuple[ManifestSegmentInput, ...],
) -> dict[str, object]:
    version = require_row(
        store.get(NarrationScriptVersion, edition.script_version_id), label="script version"
    )
    script = require_row(store.get(NarrationScript, version.script_id), label="script")
    rows = store.find_all(
        NarrationEditionSegment, edition_id=edition.id, order_by=("ordinal",)
    )
    if not rows or [row.ordinal for row in rows] != list(range(len(rows))):
        raise InvalidNarrationState("Edition segment ordinals are not contiguous")
    by_id = {item.edition_segment_id: item for item in inputs}
    if len(by_id) != len(inputs) or set(by_id) != {row.id for row in rows}:
        raise InvalidNarrationState("Manifest input must cover each Edition segment exactly once")
    # Use a deterministic lock order across all voices before examining ready
    # media.  A concurrent revocation must therefore happen wholly before or
    # wholly after this Manifest transaction.
    for voice_version_id in sorted({row.voice_version_id for row in rows}, key=str):
        require_usable_voice(store, voice_version_id, novel_id=edition.novel_id)
    public_segments: list[dict[str, object]] = []
    last_end_by_block: dict[str, int] = {}
    for row in rows:
        item = by_id[row.id]
        segment = require_row(store.get(NarrationSegment, row.segment_id), label="segment")
        if segment.script_version_id != version.id or segment.ordinal != row.ordinal:
            raise NarrationScopeMismatch("Manifest segment provenance mismatch")
        if (
            segment.paragraph_ordinal is None
            or segment.source_start_utf16 is None
            or segment.source_end_utf16 is None
        ):
            raise InvalidNarrationState("public Manifest requires a complete source anchor")
        require_exact_int(segment.paragraph_ordinal, field="paragraph_ordinal", minimum=0)
        require_nonempty(segment.source_block_key, field="source_block_key")
        start_utf16 = require_exact_int(
            segment.source_start_utf16, field="source_start_utf16", minimum=0
        )
        end_utf16 = require_exact_int(
            segment.source_end_utf16,
            field="source_end_utf16",
            minimum=start_utf16 + 1,
        )
        previous_end = last_end_by_block.get(segment.source_block_key)
        if previous_end is not None and start_utf16 < previous_end:
            raise InvalidNarrationState("source ranges overlap inside one source block")
        last_end_by_block[segment.source_block_key] = end_utf16
        require_exact_int(row.gap_after_ms, field="gap_after_ms", minimum=0)
        if item.render_status not in {
            "pending", "queued", "rendering", "ready", "failed", "cancelled"
        }:
            raise InvalidNarrationState("invalid public render status")
        expected_internal_state = (
            "quarantined" if item.render_status == "cancelled" and row.render_state == "quarantined"
            else item.render_status
        )
        if row.render_state != expected_internal_state:
            raise InvalidNarrationState("Manifest status differs from Edition segment state")
        audio_payload: dict[str, object] | None = None
        failure_payload = item.failure.payload() if item.failure else None
        if item.render_status == "ready":
            if not item.render_id or item.failure:
                raise InvalidNarrationState("ready segment requires render and no failure")
            render = require_row(
                store.get(NarrationSegmentRender, item.render_id), label="segment render"
            )
            if (
                render.state != "ready"
                or render.novel_id != edition.novel_id
                or render.render_fingerprint != row.render_fingerprint
                or render.owner_id != edition.owner_id
                or render.workspace_id != edition.workspace_id
                or render.voice_version_id != row.voice_version_id
            ):
                raise InvalidNarrationState("ready Manifest input does not match a ready render")
            audio_payload = _authoritative_audio_payload(
                store,
                edition=edition,
                edition_segment=row,
                render=render,
            )
        elif item.render_status == "failed":
            if item.render_id or not item.failure:
                raise InvalidNarrationState("failed segment requires only structured failure")
            if row.failure_code != item.failure.code:
                raise InvalidNarrationState(
                    "Manifest failure code differs from the Edition segment"
                )
        elif item.render_id or item.failure:
            raise InvalidNarrationState("non-ready/non-failed segment cannot expose media or failure")
        public_segments.append(
            {
                "segment_id": str(segment.id),
                "ordinal": row.ordinal,
                "paragraph_ordinal": segment.paragraph_ordinal,
                "source_block_key": segment.source_block_key,
                "source_start_utf16": segment.source_start_utf16,
                "source_end_utf16": segment.source_end_utf16,
                "gap_after_ms": row.gap_after_ms,
                "render_status": item.render_status,
                "audio": audio_payload,
                "failure": failure_payload,
            }
        )
    ready_prefix = 0
    while ready_prefix < len(public_segments) and public_segments[ready_prefix]["render_status"] == "ready":
        ready_prefix += 1
    ranges = derive_ready_ranges(public_segments, policy)
    status = _derive_status(public_segments)
    if status == "pending":
        raise InvalidNarrationState("do not publish a Manifest before any segment is ready")
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "edition_id": str(edition.id),
        "chapter_id": str(edition.document_id),
        "source_revision_id": str(script.revision_id),
        "source_sha256": script.content_hash,
        "buffer_policy": policy.payload(),
        "manifest_revision": revision,
        "status": status,
        "ready_prefix_count": ready_prefix,
        "default_start_ready": any(item["start_ordinal"] == 0 for item in ranges),
        "last_playable_start_ordinal": max(
            (item["last_playable_start_ordinal"] for item in ranges), default=None
        ),
        "ready_ranges": ranges,
        "segments": public_segments,
    }


def _etag_payload(semantic: dict[str, object], generated_at: datetime) -> dict[str, object]:
    return {**semantic, "generated_at": generated_at.isoformat().replace("+00:00", "Z")}


def _persist_manifest_revision(
    store: NarrationStore,
    command: PublishManifest,
    *,
    project_edition_state: bool,
) -> NarrationManifest:
    require_nonempty(command.updated_actor, field="updated_actor")
    if type(command.segments) is not tuple or not all(
        type(item) is ManifestSegmentInput for item in command.segments
    ):
        raise InvalidNarrationState(
            "Manifest segments must be frozen ManifestSegmentInput values"
        )
    require_exact_int(
        command.expected_current_revision,
        field="expected_current_revision",
        minimum=0,
    )
    require_exact_int(
        command.expected_state_version,
        field="expected_state_version",
        minimum=0,
    )
    # The Edition exists before the optional pointer row, so it is the stable
    # mutex for both first publication and later pointer updates.
    edition = require_row(
        store.get(NarrationEdition, command.edition_id, for_update=True), label="Edition"
    )
    require_frozen_buffer_policy(
        command.buffer_policy,
        expected_version=edition.buffer_policy_version,
    )
    state = store.find_one(
        NarrationEditionState, edition_id=edition.id, for_update=True
    )
    current_revision = state.current_manifest_revision if state else 0
    current_version = state.version if state else 0
    semantic = _semantic_payload(
        store, edition, command.expected_current_revision + 1, command.buffer_policy, command.segments
    )
    if (
        current_revision == command.expected_current_revision + 1
        and current_version == command.expected_state_version + 1
    ):
        existing = require_row(
            store.find_one(
                NarrationManifest,
                edition_id=edition.id,
                manifest_revision=current_revision,
            ),
            label="current Manifest",
        )
        candidate = _etag_payload(semantic, existing.created_at)
        if canonical_sha256(candidate) != existing.etag_sha256:
            raise ManifestRevisionCollision("same Manifest revision has different canonical bytes")
        return existing
    if current_revision != command.expected_current_revision or current_version != command.expected_state_version:
        raise NarrationCasConflict("Manifest current pointer changed")
    revision = current_revision + 1
    if revision < 1:
        raise InvalidNarrationState("Manifest revision must start at one")
    generated_at = utc_now()
    hash_input = _etag_payload(semantic, generated_at)
    etag_sha256 = canonical_sha256(hash_input)
    canonical = {**hash_input, "etag": f'"{etag_sha256}"'}
    # Force canonical encoding now so unsupported/private values fail before persistence.
    canonical_json_bytes(canonical)
    existing_revision = store.find_one(
        NarrationManifest, edition_id=edition.id, manifest_revision=revision
    )
    if existing_revision is not None:
        if existing_revision.etag_sha256 != etag_sha256:
            raise ManifestRevisionCollision("Manifest revision already has another ETag")
        return existing_revision
    internal_status = (
        semantic["status"]
        if semantic["status"] in {"partial_ready", "ready"}
        else "unavailable"
    )
    manifest = NarrationManifest(
        id=uuid4(),
        edition_id=edition.id,
        manifest_revision=revision,
        schema_version=MANIFEST_SCHEMA_VERSION,
        canonical_json=canonical,
        etag_sha256=etag_sha256,
        ready_prefix_count=semantic["ready_prefix_count"],
        ready_ranges_json=semantic["ready_ranges"],
        total_duration_ms=sum(
            _range_duration(semantic["segments"], item["start_ordinal"], item["end_ordinal_exclusive"])
            for item in semantic["ready_ranges"]
        ),
        status=internal_status,
        created_at=generated_at,
    )
    store.add(manifest)
    store.flush()
    inputs = {item.edition_segment_id: item for item in command.segments}
    edition_rows = store.find_all(NarrationEditionSegment, edition_id=edition.id)
    edition_by_segment_id = {str(row.segment_id): row for row in edition_rows}
    for public in semantic["segments"]:
        edition_segment = edition_by_segment_id[str(public["segment_id"])]
        item = inputs[edition_segment.id]
        public_audio = public["audio"]
        store.add(
            NarrationManifestSegment(
                id=uuid4(),
                manifest_id=manifest.id,
                edition_id=edition.id,
                edition_segment_id=edition_segment.id,
                ordinal=edition_segment.ordinal,
                render_id=item.render_id,
                render_state=(
                    "pending"
                    if item.render_status == "queued"
                    else item.render_status
                    if item.render_status in {"pending", "rendering", "ready", "failed"}
                    else "unavailable"
                ),
                duration_ms=(
                    int(public_audio["duration_ms"])
                    if isinstance(public_audio, dict)
                    else None
                ),
                gap_after_ms=edition_segment.gap_after_ms,
            )
        )
    # Materialize immutable segment rows before advancing the aggregate. This
    # ordering lets database guards verify that a playable Edition is backed by
    # the exact persisted Manifest children in the same caller-owned transaction.
    store.flush()
    target_edition_state = internal_status
    if project_edition_state and edition.state != target_edition_state:
        allowed = {
            "created": {"partial_ready", "ready", "unavailable"},
            "rendering": {"partial_ready", "ready", "unavailable"},
            "partial_ready": {"ready", "unavailable"},
            "ready": {"unavailable"},
        }
        if target_edition_state not in allowed.get(edition.state, set()):
            raise InvalidNarrationState(
                f"invalid Edition aggregate transition {edition.state}->{target_edition_state}"
            )
        edition.state = target_edition_state
        edition.unavailable_reason = (
            f"manifest_{semantic['status']}"
            if target_edition_state == "unavailable"
            else None
        )
    if state is None:
        state = NarrationEditionState(
            edition_id=edition.id,
            current_manifest_id=manifest.id,
            current_manifest_revision=revision,
            version=1,
            updated_actor=command.updated_actor,
            updated_at=generated_at,
        )
        store.add(state)
    else:
        state.current_manifest_id = manifest.id
        state.current_manifest_revision = revision
        state.version = command.expected_state_version + 1
        state.updated_actor = command.updated_actor
        state.updated_at = generated_at
    store.flush()
    return manifest


def publish_manifest(store: NarrationStore, command: PublishManifest) -> NarrationManifest:
    """Append one revision and project its aggregate state onto the Edition."""

    return _persist_manifest_revision(
        store,
        command,
        project_edition_state=True,
    )


def append_manifest_revision(
    store: NarrationStore,
    command: PublishManifest,
) -> NarrationManifest:
    """Append one immutable revision without changing the Edition lifecycle.

    Worker terminalization uses this path because another render for the same
    Edition may still be pending.  The caller owns the aggregate transition
    after evaluating every Edition segment in the same transaction.
    """

    return _persist_manifest_revision(
        store,
        command,
        project_edition_state=False,
    )


@dataclass(frozen=True, slots=True)
class ManifestRead:
    """A validated immutable public Manifest and its persistence identity."""

    manifest_id: UUID
    edition_id: UUID
    manifest_revision: int
    etag: str
    payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class PrepareRangeCommand:
    edition_id: UUID
    start_segment_id: UUID
    reason: str
    expected_manifest_revision: int
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class PrepareRangeResult:
    edition_id: UUID
    start_segment_id: UUID
    start_ordinal: int
    state: Literal["ready", "preparing", "failed"]
    manifest_revision: int
    manifest_etag: str
    ready_range: Mapping[str, int] | None
    promoted_job_ids: tuple[UUID, ...]


JobPromoter = Callable[[BackgroundJob], bool]


def _exact_keys(value: object, expected: frozenset[str], *, field: str) -> dict[str, object]:
    if type(value) is not dict:
        raise InvalidNarrationState(f"{field} must be an object")
    candidate = value
    if set(candidate) != expected:
        raise InvalidNarrationState(f"{field} has unexpected or missing fields")
    return candidate


def _uuid_text(value: object, *, field: str) -> str:
    if type(value) is not str or not _UUID.fullmatch(value):
        raise InvalidNarrationState(f"{field} must be an RFC-4122 UUID")
    return str(UUID(value))


def _nonempty_text(value: object, *, field: str, maximum: int | None = None) -> str:
    if type(value) is not str or not value or not value.strip():
        raise InvalidNarrationState(f"{field} must be non-empty")
    if maximum is not None and len(value) > maximum:
        raise InvalidNarrationState(f"{field} is too long")
    return value


def _parse_policy(value: object) -> BufferPolicy:
    policy = _exact_keys(value, _POLICY_KEYS, field="buffer_policy")
    parsed = BufferPolicy(
        version=_nonempty_text(policy["version"], field="buffer_policy.version"),
        minimum_segments=require_exact_int(
            policy["minimum_segments"],  # type: ignore[arg-type]
            field="buffer_policy.minimum_segments",
            minimum=1,
        ),
        minimum_duration_ms=require_exact_int(
            policy["minimum_duration_ms"],  # type: ignore[arg-type]
            field="buffer_policy.minimum_duration_ms",
            minimum=0,
        ),
        target_segments=require_exact_int(
            policy["target_segments"],  # type: ignore[arg-type]
            field="buffer_policy.target_segments",
            minimum=1,
        ),
        chapter_end_exception=require_exact_bool(
            policy["chapter_end_exception"],  # type: ignore[arg-type]
            field="buffer_policy.chapter_end_exception",
        ),
    )
    return require_frozen_buffer_policy(
        parsed, expected_version=INITIAL_BUFFER_POLICY.version
    )


def _parse_audio(value: object, *, field: str) -> dict[str, object]:
    audio = _exact_keys(value, _AUDIO_KEYS, field=field)
    url = _nonempty_text(audio["url"], field=f"{field}.url")
    match = _PLAYBACK_URL.fullmatch(url)
    if match is None or not _CONTROLLED_URL.fullmatch(url):
        raise InvalidNarrationState(f"{field}.url is outside the playback media route")
    _uuid_text(match.group(1), field=f"{field}.asset_id")
    actual_sha256 = require_sha256(
        audio["actual_sha256"], field=f"{field}.actual_sha256"  # type: ignore[arg-type]
    )
    duration_ms = require_exact_int(
        audio["duration_ms"], field=f"{field}.duration_ms", minimum=1  # type: ignore[arg-type]
    )
    sample_rate = require_exact_int(
        audio["sample_rate"], field=f"{field}.sample_rate", minimum=1  # type: ignore[arg-type]
    )
    channels = require_exact_int(
        audio["channels"], field=f"{field}.channels", minimum=1  # type: ignore[arg-type]
    )
    etag = _nonempty_text(audio["etag"], field=f"{field}.etag")
    if etag != f'"{actual_sha256}"':
        raise InvalidNarrationState(f"{field}.etag does not identify actual audio bytes")
    return {
        "url": url,
        "actual_sha256": actual_sha256,
        "duration_ms": duration_ms,
        "sample_rate": sample_rate,
        "channels": channels,
        "etag": etag,
    }


def _parse_failure(value: object, *, field: str) -> dict[str, object]:
    failure = _exact_keys(value, _FAILURE_KEYS, field=field)
    code = _nonempty_text(failure["code"], field=f"{field}.code", maximum=96)
    if not _FAILURE_CODE.fullmatch(code):
        raise InvalidNarrationState(f"{field}.code is not a public failure code")
    retryable = require_exact_bool(
        failure["retryable"], field=f"{field}.retryable"  # type: ignore[arg-type]
    )
    message = _nonempty_text(
        failure["message"], field=f"{field}.message", maximum=256
    )
    return {"code": code, "retryable": retryable, "message": message}


def _parse_segment(value: object, *, ordinal: int) -> dict[str, object]:
    field = f"segments[{ordinal}]"
    segment = _exact_keys(value, _SEGMENT_KEYS, field=field)
    segment_id = _uuid_text(segment["segment_id"], field=f"{field}.segment_id")
    actual_ordinal = require_exact_int(
        segment["ordinal"], field=f"{field}.ordinal", minimum=0  # type: ignore[arg-type]
    )
    if actual_ordinal != ordinal:
        raise InvalidNarrationState("Manifest segment ordinals must be contiguous and zero-based")
    paragraph_ordinal = require_exact_int(
        segment["paragraph_ordinal"],
        field=f"{field}.paragraph_ordinal",
        minimum=0,
    )  # type: ignore[arg-type]
    source_block_key = _nonempty_text(
        segment["source_block_key"], field=f"{field}.source_block_key"
    )
    source_start_utf16 = require_exact_int(
        segment["source_start_utf16"],
        field=f"{field}.source_start_utf16",
        minimum=0,
    )  # type: ignore[arg-type]
    source_end_utf16 = require_exact_int(
        segment["source_end_utf16"],
        field=f"{field}.source_end_utf16",
        minimum=source_start_utf16 + 1,
    )  # type: ignore[arg-type]
    gap_after_ms = require_exact_int(
        segment["gap_after_ms"], field=f"{field}.gap_after_ms", minimum=0  # type: ignore[arg-type]
    )
    render_status = _nonempty_text(
        segment["render_status"], field=f"{field}.render_status"
    )
    if render_status not in _PUBLIC_RENDER_STATES:
        raise InvalidNarrationState(f"{field}.render_status is unsupported")
    audio: dict[str, object] | None = None
    failure: dict[str, object] | None = None
    if render_status == "ready":
        audio = _parse_audio(segment["audio"], field=f"{field}.audio")
        if segment["failure"] is not None:
            raise InvalidNarrationState("ready segments cannot expose a failure")
    elif render_status == "failed":
        if segment["audio"] is not None:
            raise InvalidNarrationState("failed segments cannot expose audio")
        failure = _parse_failure(segment["failure"], field=f"{field}.failure")
    elif segment["audio"] is not None or segment["failure"] is not None:
        raise InvalidNarrationState(
            "non-ready/non-failed segments cannot expose audio or failure"
        )
    return {
        "segment_id": segment_id,
        "ordinal": actual_ordinal,
        "paragraph_ordinal": paragraph_ordinal,
        "source_block_key": source_block_key,
        "source_start_utf16": source_start_utf16,
        "source_end_utf16": source_end_utf16,
        "gap_after_ms": gap_after_ms,
        "render_status": render_status,
        "audio": audio,
        "failure": failure,
    }


def _parse_ready_range(value: object, *, index: int) -> dict[str, int]:
    field = f"ready_ranges[{index}]"
    item = _exact_keys(value, _RANGE_KEYS, field=field)
    start = require_exact_int(
        item["start_ordinal"], field=f"{field}.start_ordinal", minimum=0  # type: ignore[arg-type]
    )
    end = require_exact_int(
        item["end_ordinal_exclusive"],
        field=f"{field}.end_ordinal_exclusive",
        minimum=start + 1,
    )  # type: ignore[arg-type]
    count = require_exact_int(
        item["segment_count"], field=f"{field}.segment_count", minimum=1  # type: ignore[arg-type]
    )
    duration = require_exact_int(
        item["duration_ms"], field=f"{field}.duration_ms", minimum=1  # type: ignore[arg-type]
    )
    last = require_exact_int(
        item["last_playable_start_ordinal"],
        field=f"{field}.last_playable_start_ordinal",
        minimum=start,
        maximum=end - 1,
    )  # type: ignore[arg-type]
    if count != end - start:
        raise InvalidNarrationState("ready range segment_count is inconsistent")
    return {
        "start_ordinal": start,
        "end_ordinal_exclusive": end,
        "segment_count": count,
        "duration_ms": duration,
        "last_playable_start_ordinal": last,
    }


def parse_manifest_v2(value: object) -> dict[str, object]:
    """Parse stored or remote Manifest v2 with strict public and derived invariants."""

    normalized = canonical_payload(value)
    root = _exact_keys(normalized, _MANIFEST_KEYS, field="Manifest")
    if root["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise InvalidNarrationState("unsupported Manifest schema version")
    edition_id = _uuid_text(root["edition_id"], field="edition_id")
    chapter_id = _uuid_text(root["chapter_id"], field="chapter_id")
    source_revision_id = _uuid_text(
        root["source_revision_id"], field="source_revision_id"
    )
    source_sha256 = require_sha256(
        root["source_sha256"], field="source_sha256"  # type: ignore[arg-type]
    )
    policy = _parse_policy(root["buffer_policy"])
    revision = require_exact_int(
        root["manifest_revision"], field="manifest_revision", minimum=1  # type: ignore[arg-type]
    )
    etag = _nonempty_text(root["etag"], field="etag")
    if not re.fullmatch(r'"[a-f0-9]{64}"', etag):
        raise InvalidNarrationState("Manifest ETag must be a strong SHA-256 ETag")
    generated_at = _nonempty_text(root["generated_at"], field="generated_at")
    try:
        parsed_time = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise InvalidNarrationState("generated_at must be an RFC-3339 date-time") from error
    if parsed_time.tzinfo is None:
        raise InvalidNarrationState("generated_at must include an offset")
    status = _nonempty_text(root["status"], field="status")
    if status not in _PUBLIC_MANIFEST_STATES:
        raise InvalidNarrationState("unsupported Manifest status")
    ready_prefix_count = require_exact_int(
        root["ready_prefix_count"], field="ready_prefix_count", minimum=0  # type: ignore[arg-type]
    )
    default_start_ready = require_exact_bool(
        root["default_start_ready"], field="default_start_ready"  # type: ignore[arg-type]
    )
    last_value = root["last_playable_start_ordinal"]
    last_playable = (
        None
        if last_value is None
        else require_exact_int(
            last_value, field="last_playable_start_ordinal", minimum=0  # type: ignore[arg-type]
        )
    )
    if type(root["segments"]) is not list or not root["segments"]:
        raise InvalidNarrationState("Manifest segments must be a non-empty array")
    segments = [
        _parse_segment(item, ordinal=index)
        for index, item in enumerate(root["segments"])
    ]
    if len({item["segment_id"] for item in segments}) != len(segments):
        raise InvalidNarrationState("Manifest segment ids must be unique")
    last_end_by_block: dict[str, int] = {}
    for segment in segments:
        block = str(segment["source_block_key"])
        start = int(segment["source_start_utf16"])
        end = int(segment["source_end_utf16"])
        if start < last_end_by_block.get(block, 0):
            raise InvalidNarrationState("source ranges overlap inside one source block")
        last_end_by_block[block] = end
    if type(root["ready_ranges"]) is not list:
        raise InvalidNarrationState("ready_ranges must be an array")
    ranges = [
        _parse_ready_range(item, index=index)
        for index, item in enumerate(root["ready_ranges"])
    ]
    derived_ranges = derive_ready_ranges(segments, policy)
    if ranges != derived_ranges:
        raise InvalidNarrationState("ready_ranges drift from segments and buffer_policy")
    derived_prefix = 0
    while (
        derived_prefix < len(segments)
        and segments[derived_prefix]["render_status"] == "ready"
        and segments[derived_prefix]["audio"] is not None
    ):
        derived_prefix += 1
    if ready_prefix_count != derived_prefix:
        raise InvalidNarrationState("ready_prefix_count drifts from segments")
    if default_start_ready != any(item["start_ordinal"] == 0 for item in ranges):
        raise InvalidNarrationState("default_start_ready drifts from ready_ranges")
    derived_last = max(
        (item["last_playable_start_ordinal"] for item in ranges), default=None
    )
    if last_playable != derived_last:
        raise InvalidNarrationState(
            "last_playable_start_ordinal drifts from ready_ranges"
        )
    if status != _derive_status(segments):
        raise InvalidNarrationState("Manifest status drifts from segment states")
    candidate_without_etag = {key: item for key, item in root.items() if key != "etag"}
    if canonical_sha256(candidate_without_etag) != etag[1:-1]:
        raise InvalidNarrationState("Manifest ETag does not match canonical bytes")
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "edition_id": edition_id,
        "chapter_id": chapter_id,
        "source_revision_id": source_revision_id,
        "source_sha256": source_sha256,
        "buffer_policy": policy.payload(),
        "manifest_revision": revision,
        "etag": etag,
        "generated_at": generated_at,
        "status": status,
        "ready_prefix_count": ready_prefix_count,
        "default_start_ready": default_start_ready,
        "last_playable_start_ordinal": last_playable,
        "ready_ranges": ranges,
        "segments": segments,
    }


def _require_edition_scope(
    store: NarrationStore, edition_id: UUID, *, for_update: bool = False
) -> NarrationEdition:
    edition = require_row(
        store.get(NarrationEdition, edition_id, for_update=for_update), label="Edition"
    )
    require_local_novel(store, edition.novel_id)
    from .contracts import LOCAL_OWNER_ID, LOCAL_WORKSPACE_ID

    if (
        edition.owner_id != LOCAL_OWNER_ID
        or edition.workspace_id != LOCAL_WORKSPACE_ID
    ):
        raise NarrationScopeMismatch("Edition is outside the fixed local scope")
    return edition


def load_public_manifest(
    store: NarrationStore,
    *,
    edition_id: UUID,
    manifest_revision: int | None = None,
) -> ManifestRead:
    """Load one exact, validated, playable Manifest revision."""

    edition = _require_edition_scope(store, edition_id)
    state = require_row(
        store.find_one(NarrationEditionState, edition_id=edition.id),
        label="Edition Manifest state",
    )
    revision = (
        state.current_manifest_revision
        if manifest_revision is None
        else require_exact_int(
            manifest_revision, field="manifest_revision", minimum=1
        )
    )
    if revision is None:
        raise InvalidNarrationState("Edition has no public Manifest yet")
    manifest = require_row(
        store.find_one(
            NarrationManifest,
            edition_id=edition.id,
            manifest_revision=revision,
        ),
        label="Manifest revision",
    )
    if manifest_revision is None and state.current_manifest_id != manifest.id:
        raise InvalidNarrationState("Edition current Manifest pointer is inconsistent")
    payload = parse_manifest_v2(manifest.canonical_json)
    public_status = str(payload["status"])
    expected_internal_status = (
        public_status
        if public_status in {"partial_ready", "ready"}
        else "unavailable"
    )
    ranges_payload = payload["ready_ranges"]
    expected_total_duration = (
        sum(int(item["duration_ms"]) for item in ranges_payload)
        if isinstance(ranges_payload, list)
        else -1
    )
    if (
        payload["edition_id"] != str(edition.id)
        or payload["chapter_id"] != str(edition.document_id)
        or payload["manifest_revision"] != revision
        or payload["etag"] != f'"{manifest.etag_sha256}"'
        or manifest.schema_version != MANIFEST_SCHEMA_VERSION
        or manifest.ready_prefix_count != payload["ready_prefix_count"]
        or manifest.ready_ranges_json != payload["ready_ranges"]
        or manifest.status != expected_internal_status
        or manifest.total_duration_ms != expected_total_duration
    ):
        raise InvalidNarrationState("stored Manifest metadata differs from canonical bytes")
    public_segments = payload["segments"]
    if not isinstance(public_segments, list) or public_segments[0]["render_status"] != "ready":
        raise InvalidNarrationState("Edition is not yet playable from its first segment")
    persisted = store.find_all(
        NarrationManifestSegment, manifest_id=manifest.id, order_by=("ordinal",)
    )
    if len(persisted) != len(public_segments) or [row.ordinal for row in persisted] != list(
        range(len(public_segments))
    ):
        raise InvalidNarrationState("Manifest segment rows are incomplete")
    for row, public in zip(persisted, public_segments, strict=True):
        edition_segment = require_row(
            store.get(NarrationEditionSegment, row.edition_segment_id),
            label="Edition segment",
        )
        if (
            row.edition_id != edition.id
            or edition_segment.edition_id != edition.id
            or edition_segment.ordinal != row.ordinal
            or edition_segment.segment_id != UUID(str(public["segment_id"]))
            or row.gap_after_ms != public["gap_after_ms"]
            or (public["render_status"] == "ready" and row.render_state != "ready")
            or (public["render_status"] == "ready" and row.render_id is None)
            or (
                public["render_status"] == "ready"
                and row.duration_ms != public["audio"]["duration_ms"]
            )
            or (
                public["render_status"] != "ready"
                and (row.render_id is not None or row.duration_ms is not None)
            )
        ):
            raise InvalidNarrationState("Manifest segment persistence chain is inconsistent")
    return ManifestRead(
        manifest_id=manifest.id,
        edition_id=edition.id,
        manifest_revision=revision,
        etag=str(payload["etag"]),
        payload=payload,
    )


def prepare_manifest_range(
    store: NarrationStore,
    command: PrepareRangeCommand,
    *,
    promote_job: JobPromoter,
) -> PrepareRangeResult:
    """Resolve a seek window and monotonically boost its existing queued jobs."""

    if type(command) is not PrepareRangeCommand:
        raise InvalidNarrationState("prepare-range command must be frozen")
    if type(command.edition_id) is not UUID or type(command.start_segment_id) is not UUID:
        raise InvalidNarrationState("prepare-range identities must be UUIDs")
    expected_revision = require_exact_int(
        command.expected_manifest_revision,
        field="expected_manifest_revision",
        minimum=1,
    )
    if not callable(promote_job):
        raise InvalidNarrationState("prepare-range requires a job promoter")
    if command.reason not in {"user_seek", "resume"}:
        raise InvalidNarrationState("unsupported prepare-range reason")
    require_nonempty(command.idempotency_key, field="idempotency_key")
    edition = _require_edition_scope(store, command.edition_id)
    observed_state = require_row(
        store.find_one(NarrationEditionState, edition_id=edition.id),
        label="Edition Manifest state",
    )
    if observed_state.current_manifest_revision != expected_revision:
        raise NarrationCasConflict("Manifest revision changed")
    current = load_public_manifest(
        store,
        edition_id=command.edition_id,
        manifest_revision=expected_revision,
    )
    if observed_state.current_manifest_id != current.manifest_id:
        raise InvalidNarrationState("Edition current Manifest pointer is inconsistent")

    def lock_current_pointer() -> None:
        # Render workers acquire their job fence before publishing a Manifest.
        # prepare-range therefore locks queued jobs first and takes the
        # Edition/pointer CAS locks only immediately before returning/commit.
        locked_edition = _require_edition_scope(
            store, command.edition_id, for_update=True
        )
        locked_state = require_row(
            store.find_one(
                NarrationEditionState,
                edition_id=locked_edition.id,
                for_update=True,
            ),
            label="Edition Manifest state",
        )
        if locked_state.current_manifest_revision != expected_revision:
            raise NarrationCasConflict("Manifest revision changed")
        if locked_state.current_manifest_id != current.manifest_id:
            raise InvalidNarrationState(
                "Edition current Manifest pointer is inconsistent"
            )
    payload = current.payload
    segments = payload["segments"]
    if not isinstance(segments, list):
        raise InvalidNarrationState("Manifest segments are unavailable")
    start = next(
        (
            item
            for item in segments
            if item["segment_id"] == str(command.start_segment_id)
        ),
        None,
    )
    if start is None:
        raise NarrationScopeMismatch("start segment does not belong to Edition")
    start_ordinal = int(start["ordinal"])
    ready_ranges = payload["ready_ranges"]
    if not isinstance(ready_ranges, list):
        raise InvalidNarrationState("Manifest ready ranges are unavailable")
    ready_range = next(
        (
            item
            for item in ready_ranges
            if int(item["start_ordinal"]) <= start_ordinal
            <= int(item["last_playable_start_ordinal"])
            and start_ordinal < int(item["end_ordinal_exclusive"])
        ),
        None,
    )
    if ready_range is not None:
        lock_current_pointer()
        return PrepareRangeResult(
            edition_id=command.edition_id,
            start_segment_id=command.start_segment_id,
            start_ordinal=start_ordinal,
            state="ready",
            manifest_revision=current.manifest_revision,
            manifest_etag=current.etag,
            ready_range=ready_range,
            promoted_job_ids=(),
        )
    policy = _parse_policy(payload["buffer_policy"])
    window = segments[
        start_ordinal : min(len(segments), start_ordinal + policy.target_segments)
    ]
    if any(item["render_status"] in {"failed", "cancelled"} for item in window):
        lock_current_pointer()
        return PrepareRangeResult(
            edition_id=command.edition_id,
            start_segment_id=command.start_segment_id,
            start_ordinal=start_ordinal,
            state="failed",
            manifest_revision=current.manifest_revision,
            manifest_etag=current.etag,
            ready_range=None,
            promoted_job_ids=(),
        )
    jobs_to_promote: list[BackgroundJob] = []
    for public in window:
        if public["render_status"] == "ready":
            continue
        edition_segment = require_row(
            store.find_one(
                NarrationEditionSegment,
                edition_id=edition.id,
                segment_id=UUID(str(public["segment_id"])),
            ),
            label="Edition segment",
        )
        render = require_row(
            store.find_one(
                NarrationSegmentRender,
                owner_id=edition.owner_id,
                workspace_id=edition.workspace_id,
                novel_id=edition.novel_id,
                render_fingerprint=edition_segment.render_fingerprint,
            ),
            label="segment render",
        )
        job = require_row(store.get(BackgroundJob, render.source_job_id), label="render job")
        if (
            render.request_id != edition.request_id
            or render.voice_version_id != edition_segment.voice_version_id
            or job.owner_id != edition.owner_id
            or job.workspace_id != edition.workspace_id
            or job.novel_id != edition.novel_id
            or job.request_id != edition.request_id
            or job.job_kind != "narration.segment_render"
            or job.input_hash
            != render_job_input_hash(
                edition_segment_id=edition_segment.id,
                render_fingerprint=edition_segment.render_fingerprint,
            )
        ):
            raise NarrationScopeMismatch("prepare-range render/job provenance mismatch")
        if render.state in {"failed", "cancelled", "quarantined"} or job.state in {
            "failed",
            "dead_letter",
            "cancel_requested",
            "cancelled",
        }:
            lock_current_pointer()
            return PrepareRangeResult(
                edition_id=command.edition_id,
                start_segment_id=command.start_segment_id,
                start_ordinal=start_ordinal,
                state="failed",
                manifest_revision=current.manifest_revision,
                manifest_etag=current.etag,
                ready_range=None,
                promoted_job_ids=(),
            )
        if job.state == "queued" and job.id not in {
            candidate.id for candidate in jobs_to_promote
        }:
            jobs_to_promote.append(job)
    promoted: list[UUID] = []
    for job in jobs_to_promote:
        if promote_job(job):
            promoted.append(job.id)
    lock_current_pointer()
    return PrepareRangeResult(
        edition_id=command.edition_id,
        start_segment_id=command.start_segment_id,
        start_ordinal=start_ordinal,
        state="preparing",
        manifest_revision=current.manifest_revision,
        manifest_etag=current.etag,
        ready_range=None,
        promoted_job_ids=tuple(promoted),
    )


def resolve_playback_media_asset(
    store: NarrationStore,
    *,
    edition_id: UUID,
    manifest_revision: int,
    asset_id: UUID,
) -> MediaAsset:
    """Prove exact Manifest reachability before exposing playback bytes."""

    edition = _require_edition_scope(store, edition_id)
    if (
        edition.state == "unavailable"
        and edition.unavailable_reason == "unavailable_private_voice_deleted"
    ):
        raise InvalidNarrationState("unavailable_private_voice_deleted")
    manifest = load_public_manifest(
        store, edition_id=edition_id, manifest_revision=manifest_revision
    )
    link = require_row(
        store.find_one(NarrationRenderAsset, asset_id=asset_id),
        label="playback render asset",
    )
    if link.role != "playback":
        raise NarrationScopeMismatch("asset is not a playback render")
    manifest_segment = require_row(
        store.find_one(
            NarrationManifestSegment,
            manifest_id=manifest.manifest_id,
            edition_id=edition.id,
            render_id=link.render_id,
        ),
        label="reachable Manifest segment",
    )
    edition_segment = require_row(
        store.get(NarrationEditionSegment, manifest_segment.edition_segment_id),
        label="Edition segment",
    )
    render = require_row(
        store.get(NarrationSegmentRender, link.render_id), label="segment render"
    )
    asset = require_row(store.get(MediaAsset, asset_id), label="playback media asset")
    public_segments = manifest.payload["segments"]
    if not isinstance(public_segments, list):
        raise InvalidNarrationState("Manifest segments are unavailable")
    public = public_segments[manifest_segment.ordinal]
    audio = public["audio"]
    if not isinstance(audio, dict):
        raise NarrationScopeMismatch("Manifest segment does not expose playback audio")
    url_match = _PLAYBACK_URL.fullmatch(str(audio["url"]))
    if (
        url_match is None
        or UUID(url_match.group(1)) != asset.id
        or manifest_segment.render_state != "ready"
        or edition_segment.edition_id != edition.id
        or edition_segment.segment_id != UUID(str(public["segment_id"]))
        or edition_segment.render_fingerprint != render.render_fingerprint
        or render.id != link.render_id
        or render.state != "ready"
        or render.owner_id != edition.owner_id
        or render.workspace_id != edition.workspace_id
        or render.novel_id != edition.novel_id
        or render.voice_version_id != edition_segment.voice_version_id
        or asset.owner_id != edition.owner_id
        or asset.workspace_id != edition.workspace_id
        or asset.novel_id != edition.novel_id
        or asset.asset_class != "segment_playback"
        or asset.state != "ready"
        or asset.checksum_algorithm != "sha256"
        or link.actual_sha256 != asset.content_hash
        or audio["actual_sha256"] != asset.content_hash
        or audio["etag"] != f'"{asset.content_hash}"'
        or audio["duration_ms"] != asset.duration_ms
        or audio["sample_rate"] != asset.sample_rate
        or audio["channels"] != asset.channels
    ):
        raise NarrationScopeMismatch("media is not reachable from the exact Manifest")
    return asset


__all__ = [
    "append_manifest_revision",
    "BUFFER_POLICIES",
    "BufferPolicy",
    "INITIAL_BUFFER_POLICY",
    "MANIFEST_SCHEMA_VERSION",
    "ManifestFailure",
    "ManifestRead",
    "ManifestSegmentInput",
    "PrepareRangeCommand",
    "PrepareRangeResult",
    "PublishManifest",
    "derive_ready_ranges",
    "load_public_manifest",
    "parse_manifest_v2",
    "prepare_manifest_range",
    "publish_manifest",
    "require_frozen_buffer_policy",
    "resolve_playback_media_asset",
]
