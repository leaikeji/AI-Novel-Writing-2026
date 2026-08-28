"""Server-derived render identity and fenced authoritative publication."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from uuid import UUID, uuid4

from ..models import (
    BackgroundJob,
    MediaAsset,
    NarrationEdition,
    NarrationEditionSegment,
    NarrationRenderAsset,
    NarrationSegment,
    NarrationSegmentRender,
    PronunciationProfile,
)

from .fingerprints import render_fingerprint
from .contracts import PRODUCTION_NANO_MAX_NEW_FRAMES
from .digest_keyring import (
    DigestKeyring,
    HmacDigestKey,
    historical_private_text_digest,
    private_text_digest,
)
from .jobs import JobFence, PublicationFenceContext
from .requests import require_generation_request
from .services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationScopeMismatch,
    NarrationStore,
    canonical_payload,
    canonical_sha256,
    require_exact_int,
    require_nonempty,
    require_row,
    require_sha256,
    require_usable_voice,
    utc_now,
)
from .synthesis_policy import resolve_effective_synthesis_policy


LEGACY_RENDER_CANONICAL_INPUT_VERSION = "narration-render-input/1"
LEGACY_RENDER_CANONICAL_INPUT_V2_VERSION = "narration-render-input/2"
RENDER_CANONICAL_INPUT_VERSION = "narration-render-input/3"
SHORT_POLICY_RENDER_CANONICAL_INPUT_VERSION = "narration-render-input/4"
SUPPORTED_RENDER_CANONICAL_INPUT_VERSIONS = frozenset(
    {
        LEGACY_RENDER_CANONICAL_INPUT_VERSION,
        LEGACY_RENDER_CANONICAL_INPUT_V2_VERSION,
        RENDER_CANONICAL_INPUT_VERSION,
        SHORT_POLICY_RENDER_CANONICAL_INPUT_VERSION,
    }
)


@dataclass(frozen=True, slots=True)
class RenderCanonicalInput:
    segment_id: UUID
    canonical_spoken_text_hash: str
    canonical_spoken_text_digest_key_id: str | None
    canonical_spoken_text_hmac_sha256: str | None
    source_local_hash: str
    pronunciation_profile_fingerprint: str | None
    voice_profile_version_fingerprint: str
    reference_audio_hash: str | None
    tts_model_fingerprint: str
    tokenizer_fingerprint: str
    normalizer_fingerprint: str
    language: str
    synthesis_style_and_parameters: dict[str, object]
    pause_before_ms: int
    pause_after_ms: int
    deterministic_seed: int | None
    postprocess_fingerprint: str

    def payload(
        self,
        *,
        schema_version: str = RENDER_CANONICAL_INPUT_VERSION,
    ) -> dict[str, object]:
        if schema_version not in SUPPORTED_RENDER_CANONICAL_INPUT_VERSIONS:
            raise InvalidNarrationState("unsupported render canonical input version")
        for field_name, value in (
            ("canonical_spoken_text_hash", self.canonical_spoken_text_hash),
            ("source_local_hash", self.source_local_hash),
            ("voice_profile_version_fingerprint", self.voice_profile_version_fingerprint),
            ("tts_model_fingerprint", self.tts_model_fingerprint),
            ("tokenizer_fingerprint", self.tokenizer_fingerprint),
            ("normalizer_fingerprint", self.normalizer_fingerprint),
            ("postprocess_fingerprint", self.postprocess_fingerprint),
        ):
            require_sha256(value, field=field_name)
        for field_name, value in (
            ("pronunciation_profile_fingerprint", self.pronunciation_profile_fingerprint),
            ("reference_audio_hash", self.reference_audio_hash),
        ):
            if value is not None:
                require_sha256(value, field=field_name)
        require_nonempty(self.language, field="language")
        if type(self.synthesis_style_and_parameters) is not dict:
            raise InvalidNarrationState("synthesis parameters must be an object")
        require_exact_int(self.pause_before_ms, field="pause_before_ms", minimum=0)
        require_exact_int(self.pause_after_ms, field="pause_after_ms", minimum=0)
        if self.deterministic_seed is not None:
            require_exact_int(
                self.deterministic_seed,
                field="deterministic_seed",
                minimum=-(2**63),
                maximum=2**63 - 1,
            )
        payload: dict[str, object] = {
            "schema_version": schema_version,
            "pronunciation_profile_fingerprint": self.pronunciation_profile_fingerprint,
            "voice_profile_version_fingerprint": self.voice_profile_version_fingerprint,
            "reference_audio_hash": self.reference_audio_hash,
            "tts_model_fingerprint": self.tts_model_fingerprint,
            "tokenizer_fingerprint": self.tokenizer_fingerprint,
            "normalizer_fingerprint": self.normalizer_fingerprint,
            "language": self.language,
            "synthesis_style_and_parameters": canonical_payload(
                self.synthesis_style_and_parameters
            ),
            "deterministic_seed": self.deterministic_seed,
            "postprocess_fingerprint": self.postprocess_fingerprint,
        }
        if schema_version == LEGACY_RENDER_CANONICAL_INPUT_VERSION:
            # v1 accidentally mixed immutable provenance and Edition timeline
            # fields into the audio cache key.  Keep it readable so already
            # persisted Editions remain reproducible; every new Edition emits
            # v3 and does not bridge cache identity across schema versions.
            payload.update(
                {
                    "segment_id": str(self.segment_id),
                    "canonical_spoken_text_hash": self.canonical_spoken_text_hash,
                    "source_local_hash": self.source_local_hash,
                    "pause_before_ms": self.pause_before_ms,
                    "pause_after_ms": self.pause_after_ms,
                }
            )
        elif schema_version == LEGACY_RENDER_CANONICAL_INPUT_V2_VERSION:
            # v2 corrected audio-cache semantics, but persisted a naked SHA of
            # private spoken text.  It remains read-only so historical rows are
            # reproducible without relabelling them as the privacy-safe v3.
            payload["canonical_spoken_text_hash"] = self.canonical_spoken_text_hash
        else:
            require_nonempty(
                self.canonical_spoken_text_digest_key_id or "",
                field="canonical_spoken_text_digest_key_id",
            )
            require_sha256(
                self.canonical_spoken_text_hmac_sha256 or "",
                field="canonical_spoken_text_hmac_sha256",
            )
            payload.update(
                {
                    "canonical_spoken_text_digest_key_id": (
                        self.canonical_spoken_text_digest_key_id
                    ),
                    "canonical_spoken_text_hmac_sha256": (
                        self.canonical_spoken_text_hmac_sha256
                    ),
                }
            )
        return payload


@dataclass(frozen=True, slots=True)
class CreateRender:
    edition_segment_id: UUID
    digest_keyring: DigestKeyring = field(repr=False)
    # None is permitted only for a ready-cache lookup before enqueue. Creating
    # or resuming an in-flight render always requires the exact source job.
    source_job_id: UUID | None = None


def render_job_input_hash(*, edition_segment_id: UUID, render_fingerprint: str) -> str:
    """Frozen T1-F input identity expected on a segment-render background job."""

    return canonical_sha256(
        {
            "schema_version": "narration-segment-render-job/1",
            "edition_segment_id": str(edition_segment_id),
            "render_fingerprint": require_sha256(
                render_fingerprint, field="render_fingerprint"
            ),
        }
    )


def derive_render_identity(
    store: NarrationStore,
    *,
    novel_id: UUID,
    segment: NarrationSegment,
    voice_version_id: UUID,
    pronunciation_profile_id: UUID | None,
    tts_fingerprint: str,
    tokenizer_fingerprint: str,
    normalizer_fingerprint: str,
    postprocess_fingerprint: str,
    canonical_input_version: str | None = None,
    digest_key: HmacDigestKey | None = None,
) -> tuple[str, dict[str, object]]:
    """Derive audio identity from persisted production inputs.

    v2, v3 and v4 intentionally exclude segment identity, source mapping hashes, and
    timeline pauses.  Those values still receive strict validation and remain
    authoritative Edition/Manifest provenance, but they do not change the
    synthesized waveform and therefore must not defeat cross-Edition reuse.
    """

    profile, voice, _rights = require_usable_voice(
        store, voice_version_id, novel_id=novel_id
    )
    require_nonempty(segment.spoken_text, field="spoken_text")
    require_sha256(segment.local_hash, field="segment local_hash")
    pronunciation_fingerprint: str | None = None
    if pronunciation_profile_id is not None:
        pronunciation = require_row(
            store.get(PronunciationProfile, pronunciation_profile_id),
            label="pronunciation profile",
        )
        if pronunciation.novel_id != novel_id:
            raise NarrationScopeMismatch("pronunciation profile belongs to another novel")
        pronunciation_fingerprint = require_sha256(
            pronunciation.fingerprint, field="pronunciation profile fingerprint"
        )
    reference_hash: str | None = None
    if voice.reference_asset_id is not None:
        reference = require_row(
            store.get(MediaAsset, voice.reference_asset_id), label="voice reference asset"
        )
        if (
            reference.owner_id != profile.owner_id
            or reference.workspace_id != profile.workspace_id
            or reference.novel_id not in {None, novel_id}
            or reference.state != "ready"
            or reference.asset_class != "voice_reference"
        ):
            raise NarrationScopeMismatch("voice reference asset is outside usable scope")
        reference_hash = require_sha256(
            reference.content_hash, field="reference audio hash"
        )
    voice_parameters = voice.parameters_json
    if type(voice_parameters) is not dict:
        raise InvalidNarrationState("voice synthesis parameters must be an object")
    base_seed = voice.seed if voice.seed is not None else 0
    effective_policy = resolve_effective_synthesis_policy(
        spoken_text=segment.spoken_text,
        segment_kind=segment.segment_kind,
        speaker_kind=segment.speaker_kind,
        language=voice.language,
        preset_key=voice.preset_key,
        base_seed=base_seed,
        base_sample_mode=voice_parameters.get("sample_mode", "fixed"),
        base_max_new_frames=voice_parameters.get(
            "max_new_frames", PRODUCTION_NANO_MAX_NEW_FRAMES
        ),
    )
    resolved_input_version = canonical_input_version
    if resolved_input_version is None:
        resolved_input_version = (
            SHORT_POLICY_RENDER_CANONICAL_INPUT_VERSION
            if effective_policy.applied
            else RENDER_CANONICAL_INPUT_VERSION
        )
    if (
        resolved_input_version == SHORT_POLICY_RENDER_CANONICAL_INPUT_VERSION
        and not effective_policy.applied
    ):
        raise InvalidNarrationState(
            "render input v4 requires an applied short-attribution policy"
        )
    if resolved_input_version in {
        RENDER_CANONICAL_INPUT_VERSION,
        SHORT_POLICY_RENDER_CANONICAL_INPUT_VERSION,
    }:
        if type(digest_key) is not HmacDigestKey:
            raise InvalidNarrationState(
                "privacy-safe render input requires a server-owned HMAC digest key"
            )
        text_digest_key_id: str | None = digest_key.key_id
        digest_function = (
            private_text_digest
            if digest_key.status == "active"
            else historical_private_text_digest
        )
        text_hmac: str | None = digest_function(
            digest_key, purpose="render-spoken-text", text=segment.spoken_text
        )
    elif resolved_input_version in {
        LEGACY_RENDER_CANONICAL_INPUT_VERSION,
        LEGACY_RENDER_CANONICAL_INPUT_V2_VERSION,
    }:
        text_digest_key_id = None
        text_hmac = None
    else:
        raise InvalidNarrationState("unsupported render canonical input version")
    synthesis_parameters: dict[str, object] = {
        "voice_parameters": canonical_payload(voice_parameters),
        "emotion": segment.emotion,
        "expression": segment.expression,
    }
    deterministic_seed = voice.seed
    if resolved_input_version == SHORT_POLICY_RENDER_CANONICAL_INPUT_VERSION:
        evidence = effective_policy.evidence_payload()
        if evidence is None:
            raise InvalidNarrationState("render input v4 policy evidence is absent")
        synthesis_parameters["effective_synthesis_policy"] = evidence
        deterministic_seed = effective_policy.effective_seed
    value = RenderCanonicalInput(
        segment_id=segment.id,
        canonical_spoken_text_hash=canonical_sha256(
            {"spoken_text": segment.spoken_text}
        ),
        canonical_spoken_text_digest_key_id=text_digest_key_id,
        canonical_spoken_text_hmac_sha256=text_hmac,
        source_local_hash=segment.local_hash,
        pronunciation_profile_fingerprint=pronunciation_fingerprint,
        voice_profile_version_fingerprint=require_sha256(
            voice.fingerprint, field="voice profile version fingerprint"
        ),
        reference_audio_hash=reference_hash,
        tts_model_fingerprint=tts_fingerprint,
        tokenizer_fingerprint=tokenizer_fingerprint,
        normalizer_fingerprint=normalizer_fingerprint,
        language=voice.language,
        synthesis_style_and_parameters=synthesis_parameters,
        pause_before_ms=require_exact_int(
            segment.pause_before_ms, field="segment pause_before_ms", minimum=0
        ),
        pause_after_ms=require_exact_int(
            segment.pause_after_ms, field="segment pause_after_ms", minimum=0
        ),
        deterministic_seed=deterministic_seed,
        postprocess_fingerprint=postprocess_fingerprint,
    )
    payload = value.payload(schema_version=resolved_input_version)
    return render_fingerprint({"novel_id": str(novel_id), "canonical_input": payload}), payload


def _edition_render_identity(
    store: NarrationStore,
    edition_segment_id: UUID,
    digest_keyring: DigestKeyring,
) -> tuple[
    NarrationEdition,
    NarrationEditionSegment,
    str,
    dict[str, object],
    bool,
]:
    if type(digest_keyring) is not DigestKeyring:
        raise InvalidNarrationState("render identity requires a digest keyring")
    row = require_row(
        store.get(NarrationEditionSegment, edition_segment_id), label="Edition segment"
    )
    edition = require_row(store.get(NarrationEdition, row.edition_id), label="Edition")
    segment = require_row(store.get(NarrationSegment, row.segment_id), label="segment")
    if segment.script_version_id != edition.script_version_id:
        raise NarrationScopeMismatch("render segment is outside the Edition script")
    identity_args = {
        "novel_id": edition.novel_id,
        "segment": segment,
        "voice_version_id": row.voice_version_id,
        "pronunciation_profile_id": edition.pronunciation_profile_id,
        "tts_fingerprint": edition.tts_fingerprint,
        "tokenizer_fingerprint": edition.tokenizer_fingerprint,
        "normalizer_fingerprint": edition.normalizer_fingerprint,
        "postprocess_fingerprint": edition.postprocess_fingerprint,
    }
    historical_policy_fallback = False
    if row.render_digest_key_id is None:
        # NULL predates the key-id column.  Try the later naked-SHA v2 shape
        # first, then the original v1 provenance-heavy shape.  Neither legacy
        # form is allowed to create new cache rows.
        fingerprint, payload = derive_render_identity(
            store,
            canonical_input_version=LEGACY_RENDER_CANONICAL_INPUT_V2_VERSION,
            **identity_args,
        )
        if row.render_fingerprint != fingerprint:
            fingerprint, payload = derive_render_identity(
                store,
                canonical_input_version=LEGACY_RENDER_CANONICAL_INPUT_VERSION,
                **identity_args,
            )
    else:
        digest_key = digest_keyring.require(row.render_digest_key_id)
        fingerprint, payload = derive_render_identity(
            store,
            digest_key=digest_key,
            **identity_args,
        )
        if (
            row.render_fingerprint != fingerprint
            and payload.get("schema_version")
            == SHORT_POLICY_RENDER_CANONICAL_INPUT_VERSION
        ):
            # A pre-policy v3 Edition remains reproducible and readable.  New
            # Editions use v4 for matching short attributions, so this fallback
            # never permits a fresh v3 cache key to masquerade as the fix.
            fingerprint, payload = derive_render_identity(
                store,
                canonical_input_version=RENDER_CANONICAL_INPUT_VERSION,
                digest_key=digest_key,
                **identity_args,
            )
            historical_policy_fallback = True
    if row.render_fingerprint != fingerprint:
        raise InvalidNarrationState(
            "Edition render fingerprint differs from server derivation"
        )
    return edition, row, fingerprint, payload, historical_policy_fallback


def compute_render_fingerprint(store: NarrationStore, command: CreateRender) -> str:
    return _edition_render_identity(
        store, command.edition_segment_id, command.digest_keyring
    )[2]


def _source_job_matches_request_render(
    store: NarrationStore,
    *,
    job: BackgroundJob,
    edition: NarrationEdition,
    row: NarrationEditionSegment,
    fingerprint: str,
    payload: dict[str, object],
    digest_keyring: DigestKeyring,
) -> bool:
    """Prove that a segment-specific job owns this request-wide render.

    A v3 render fingerprint deliberately excludes the Edition segment ID. Two
    canonical-identical segments in one request therefore share one render and
    the first segment's job.  The job input hash remains segment-specific: it
    must name one immutable, canonically identical source segment in the same
    request instead of being rewritten to match every fan-out target.
    """

    candidate_editions = store.find_all(
        NarrationEdition,
        request_id=edition.request_id,
    )
    for candidate_edition in candidate_editions:
        if (
            candidate_edition.owner_id != edition.owner_id
            or candidate_edition.workspace_id != edition.workspace_id
            or candidate_edition.novel_id != edition.novel_id
            or candidate_edition.document_id != edition.document_id
        ):
            raise NarrationScopeMismatch(
                "render source Edition is outside the request scope"
            )
        candidates = store.find_all(
            NarrationEditionSegment,
            edition_id=candidate_edition.id,
        )
        for candidate in candidates:
            if job.input_hash != render_job_input_hash(
                edition_segment_id=candidate.id,
                render_fingerprint=fingerprint,
            ):
                continue
            (
                derived_edition,
                derived_row,
                derived_fingerprint,
                derived_payload,
                _derived_historical_policy_fallback,
            ) = _edition_render_identity(
                store,
                candidate.id,
                digest_keyring,
            )
            return (
                derived_edition.id == candidate_edition.id
                and derived_row.id == candidate.id
                and derived_fingerprint == fingerprint
                and derived_payload == payload
                and candidate.voice_version_id == row.voice_version_id
            )
    return False


def create_or_reuse_render(
    store: NarrationStore, command: CreateRender
) -> tuple[NarrationSegmentRender, bool]:
    (
        edition,
        row,
        fingerprint,
        payload,
        historical_policy_fallback,
    ) = _edition_render_identity(
        store, command.edition_segment_id, command.digest_keyring
    )
    request = require_generation_request(
        store, edition.request_id, novel_id=edition.novel_id, for_update=True
    )
    if request.state not in {"queued", "rendering", "partial_ready"}:
        raise InvalidNarrationState("generation request is not accepting render work")
    existing = store.find_one(
        NarrationSegmentRender,
        owner_id=request.owner_id,
        workspace_id=request.workspace_id,
        render_fingerprint=fingerprint,
    )
    if existing is not None:
        if existing.novel_id != edition.novel_id:
            raise NarrationScopeMismatch("render cache cannot cross novel scope")
        if (
            existing.voice_version_id != row.voice_version_id
            or existing.model_fingerprint != edition.tts_fingerprint
            or existing.postprocess_fingerprint != edition.postprocess_fingerprint
            or existing.canonical_input_json != payload
        ):
            raise IdempotencyConflict("render fingerprint collision")
        require_usable_voice(store, existing.voice_version_id, novel_id=edition.novel_id)
        if existing.state == "ready":
            if command.source_job_id not in {None, existing.source_job_id}:
                raise InvalidNarrationState(
                    "ready cache must be resolved before enqueueing another render job"
                )
            return existing, True
        if historical_policy_fallback:
            raise InvalidNarrationState(
                "historical v3 short-attribution render cannot resume under v4 policy"
            )
        if existing.state not in {"pending", "rendering"}:
            raise InvalidNarrationState("terminal non-ready render cannot be reused")
        if existing.request_id != request.id:
            raise InvalidNarrationState(
                "cross-request in-flight render reuse has no publication fence"
            )
        if existing.source_job_id != command.source_job_id:
            raise InvalidNarrationState(
                "in-flight render belongs to another source job"
            )
    if historical_policy_fallback:
        raise InvalidNarrationState(
            "historical v3 short-attribution render cannot be newly synthesized"
        )
    if command.source_job_id is None:
        raise InvalidNarrationState("render cache miss requires a source job")
    if row.render_digest_key_id != command.digest_keyring.active_key_id:
        raise InvalidNarrationState(
            "render cache miss requires a new Edition with the active digest key"
        )
    job = require_row(store.get(BackgroundJob, command.source_job_id), label="render job")
    if (
        job.job_kind != "narration.segment_render"
        or job.resource_class != "moss-nano"
        or job.request_id != request.id
        or job.novel_id != edition.novel_id
        or job.owner_id != request.owner_id
        or job.workspace_id != request.workspace_id
        or job.request_allows_render is not True
        or not _source_job_matches_request_render(
            store,
            job=job,
            edition=edition,
            row=row,
            fingerprint=fingerprint,
            payload=payload,
            digest_keyring=command.digest_keyring,
        )
        or job.state not in {"queued", "running"}
    ):
        raise NarrationScopeMismatch("source job does not belong to this render request")
    if existing is not None:
        return existing, True
    render = NarrationSegmentRender(
        id=uuid4(),
        owner_id=request.owner_id,
        workspace_id=request.workspace_id,
        novel_id=edition.novel_id,
        request_id=request.id,
        request_allows_render=True,
        render_fingerprint=fingerprint,
        canonical_input_json=payload,
        voice_version_id=row.voice_version_id,
        model_fingerprint=edition.tts_fingerprint,
        postprocess_fingerprint=edition.postprocess_fingerprint,
        state="pending",
        source_job_id=command.source_job_id,
        audio_validation_json={},
    )
    store.add(render)
    store.flush()
    return render, False


def _ready_asset(
    store: NarrationStore, render: NarrationSegmentRender, role: str
) -> tuple[NarrationRenderAsset, MediaAsset]:
    link = require_row(
        store.find_one(NarrationRenderAsset, render_id=render.id, role=role),
        label=f"render {role} asset link",
    )
    asset = require_row(store.get(MediaAsset, link.asset_id), label=f"render {role} asset")
    if (
        asset.owner_id != render.owner_id
        or asset.workspace_id != render.workspace_id
        or asset.novel_id != render.novel_id
        or asset.state != "ready"
        or asset.asset_class != f"segment_{role}"
        or asset.checksum_algorithm != "sha256"
        or link.actual_sha256 != asset.content_hash
    ):
        raise InvalidNarrationState(f"render {role} asset is not authoritative and ready")
    require_sha256(asset.content_hash, field=f"{role} asset content hash")
    return link, asset


def publish_render_ready(
    store: NarrationStore,
    render_id: UUID,
    *,
    publication_context: PublicationFenceContext,
) -> NarrationSegmentRender:
    """Publish ready while consuming a pre-acquired T1-C combined context.

    The caller must acquire the context before inserting authoritative media/link
    rows in this same short transaction.  Completion revalidates both leases.
    """

    render = require_row(
        store.get(NarrationSegmentRender, render_id, for_update=True), label="render"
    )
    if render.source_job_id is None:
        raise InvalidNarrationState("production render requires a source job")
    if type(publication_context) is not PublicationFenceContext:
        raise InvalidNarrationState(
            "render result requires a transaction-bound publication context"
        )
    job_fence = publication_context.job_lease.fence
    resource_fence = publication_context.resource_lease.fence
    if type(job_fence) is not JobFence or job_fence.job_id != render.source_job_id:
        raise InvalidNarrationState("render result fence names another source job")
    if (
        publication_context.resource_class != "moss-nano"
        or resource_fence.resource_key != "moss-nano:inference"
    ):
        raise InvalidNarrationState("render result requires the mapped MOSS-Nano resource fence")
    _master_link, master = _ready_asset(store, render, "master")
    _playback_link, playback = _ready_asset(store, render, "playback")
    for field, value in (
        ("playback duration_ms", playback.duration_ms),
        ("playback sample_rate", playback.sample_rate),
        ("playback channels", playback.channels),
    ):
        require_exact_int(value, field=field, minimum=1)  # type: ignore[arg-type]
    if master.duration_ms is not None and master.duration_ms != playback.duration_ms:
        raise InvalidNarrationState("master/playback duration mismatch")
    require_usable_voice(store, render.voice_version_id, novel_id=render.novel_id)
    if render.state == "ready":
        raise InvalidNarrationState("ready render publication is already terminal")
    if render.state not in {"pending", "rendering"}:
        raise InvalidNarrationState("cancelled/failed/quarantined render cannot publish ready")
    store.consume_render_publication_context(
        publication_context=publication_context,
        source_job_id=render.source_job_id,
        request_id=render.request_id,
        novel_id=render.novel_id,
        actual_result_digest=playback.content_hash,
    )
    render.duration_ms = playback.duration_ms
    render.audio_validation_json = {
        "master_sha256": master.content_hash,
        "playback_sha256": playback.content_hash,
        "playback_mime_type": playback.mime_type,
        "sample_rate": playback.sample_rate,
        "channels": playback.channels,
    }
    render.ready_at = utc_now()
    render.state = "ready"
    store.flush()
    return render


__all__ = [
    "CreateRender",
    "LEGACY_RENDER_CANONICAL_INPUT_VERSION",
    "LEGACY_RENDER_CANONICAL_INPUT_V2_VERSION",
    "RENDER_CANONICAL_INPUT_VERSION",
    "SHORT_POLICY_RENDER_CANONICAL_INPUT_VERSION",
    "RenderCanonicalInput",
    "SUPPORTED_RENDER_CANONICAL_INPUT_VERSIONS",
    "compute_render_fingerprint",
    "create_or_reuse_render",
    "derive_render_identity",
    "publish_render_ready",
    "render_job_input_hash",
]
