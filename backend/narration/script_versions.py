"""Immutable script versions, approval policy, and derived staleness."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from uuid import UUID, uuid4, uuid5

from ..models import (
    AnonymousSpeaker,
    CharacterVoiceBinding,
    Document,
    DocumentRevision,
    GenericVoicePool,
    GenericVoiceSlot,
    NarrationRequest,
    NarrationRequestSource,
    NarrationScene,
    NarrationSettingsSnapshot,
    NarrationScript,
    NarrationScriptIssue,
    NarrationScriptVersion,
    NarrationSegment,
    NovelCharacter,
    VoiceProfile,
    VoiceProfileVersion,
)

from .contracts import (
    LOCAL_OWNER_ID,
    LOCAL_WORKSPACE_ID,
    NARRATION_REVIEW_TAXONOMY_VERSION,
    ReviewIssue,
    ReviewIssueSeverity,
    issue_severity,
)
from .aliases import CHARACTER_ALIAS_NORMALIZATION_VERSION
from .casting import CASTING_RESOLVER_VERSION
from .expression import EXPRESSION_RULESET_VERSION
from .scenes import SCENE_RULESET_VERSION
from .snapshots import SETTINGS_SNAPSHOT_SCHEMA_VERSION
from .speaker_rules import LOCAL_SPEAKER_RULESET_VERSION
from .requests import require_generation_request
from .script_contracts import (
    NARRATION_CASTING_DECISION_VERSION,
    NARRATION_SCRIPT_CONTRACT_VERSION,
    NARRATION_SEGMENT_EVIDENCE_VERSION,
    AnonymousScopeKind,
    AnonymousSpeakerIdentity,
    ApprovalActorType,
    AttributionEvidence,
    AttributionOrigin,
    CastingDecision,
    CastingDecisionOrigin,
    CastingTargetKind,
    CastingTargetRef,
    NarrationScriptContract,
    ScriptApproval,
    ScriptApprovalKind,
    ScriptAuthorityContext,
    ScriptContractError,
    ScriptReviewPolicy,
    ScriptVersionState,
    SpeakerKind,
    SpeakerRef,
    _parse_anonymous,
    _parse_attribution,
    _parse_casting_decision,
    _parse_speaker,
    initial_materialized_state,
    script_contract_from_dict,
    script_contract_to_dict,
    script_immutable_hash,
    script_immutable_payload,
    speaker_target_hash,
    utf16_length,
)
from .script_review import (
    ReviewDisposition,
    ReviewIntent,
    ReviewRequestContext,
    ReviewStateError,
    auto_freeze_script,
    decide_script_review,
    manual_freeze_script,
)
from .services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationScopeMismatch,
    NarrationServiceError,
    NarrationStore,
    StaleNarrationInput,
    canonical_sha256,
    canonical_payload,
    require_exact_bool,
    require_exact_int,
    require_local_novel,
    require_nonempty,
    require_row,
    require_same_novel,
    require_sha256,
    utc_now,
)


SCRIPT_ANALYZER_VERSION = "narration-local-script-analyzer/1"
SCRIPT_ANALYZER_FINGERPRINT = canonical_sha256(
    {
        "pipeline": SCRIPT_ANALYZER_VERSION,
        "script_contract": NARRATION_SCRIPT_CONTRACT_VERSION,
        "casting": CASTING_RESOLVER_VERSION,
    }
)
SCRIPT_RULES_FINGERPRINT = canonical_sha256(
    {
        "aliases": CHARACTER_ALIAS_NORMALIZATION_VERSION,
        "scene": SCENE_RULESET_VERSION,
        "speaker": LOCAL_SPEAKER_RULESET_VERSION,
        "expression": EXPRESSION_RULESET_VERSION,
    }
)


@dataclass(frozen=True, slots=True)
class ScriptSceneInput:
    scene_id: UUID
    ordinal: int
    source_start: int | None
    source_end: int | None
    boundary_source: str
    local_hash: str
    title: str | None = None


@dataclass(frozen=True, slots=True)
class ScriptSegmentInput:
    segment_id: UUID
    ordinal: int
    segment_kind: str
    source_block_key: str
    source_text: str
    spoken_text: str
    local_hash: str
    speaker_kind: str
    casting_json: dict[str, object]
    evidence_json: dict[str, object]
    confidence: str
    pause_before_ms: int
    pause_after_ms: int
    manual_override: bool
    scene_id: UUID | None = None
    paragraph_ordinal: int | None = None
    source_start_utf16: int | None = None
    source_end_utf16: int | None = None
    anchor_before_hash: str | None = None
    anchor_after_hash: str | None = None
    character_id: UUID | None = None
    anonymous_speaker_id: UUID | None = None
    emotion: str | None = None
    expression: str | None = None


@dataclass(frozen=True, slots=True)
class CreateScriptDraft:
    novel_id: UUID
    document_id: UUID
    revision_id: UUID
    content_hash: str
    settings_fingerprint: str
    analyzer_fingerprint: str
    rules_fingerprint: str
    idempotency_key: str
    effective_policy: str
    segments: tuple[ScriptSegmentInput, ...]
    scenes: tuple[ScriptSceneInput, ...] = ()
    issues: tuple[ReviewIssue, ...] = ()
    parent_version_id: UUID | None = None
    requested_model_fingerprint: str | None = None
    actual_model_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class ReserveScriptIdentity:
    """Server-owned input used before deterministic scene/segment IDs are built."""

    novel_id: UUID
    document_id: UUID
    revision_id: UUID
    content_hash: str
    idempotency_key: str
    parent_version_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ScriptVersionAllocation:
    """Stable identity reserved inside the caller-owned database transaction."""

    novel_id: UUID
    document_id: UUID
    revision_id: UUID
    content_hash: str
    script_id: UUID
    script_version_id: UUID
    version_number: int
    idempotency_key: str
    parent_version_id: UUID | None
    existing: bool


@dataclass(frozen=True, slots=True)
class LegacyScriptIssueSnapshot:
    code: str
    severity: ReviewIssueSeverity
    segment_id: UUID | None
    evidence_summary: str | None
    evidence_digest: str | None


@dataclass(frozen=True, slots=True)
class LegacyScriptVersionRead:
    """Read-only snapshot of a pre-T3 typed script row.

    This compatibility shape never masquerades as the frozen typed contract and
    never writes or upgrades storage as a side effect of reading.
    """

    script_id: UUID
    script_version_id: UUID
    novel_id: UUID
    document_id: UUID
    revision_id: UUID
    source_content_hash: str
    source_length_utf16: int
    version_number: int
    parent_version_id: UUID | None
    state: ScriptVersionState
    effective_policy: ScriptReviewPolicy
    settings_fingerprint: str
    analyzer_fingerprint: str
    rules_fingerprint: str
    requested_model_fingerprint: str | None
    actual_model_fingerprint: str | None
    immutable_hash: str
    warning_count: int
    blocker_count: int
    scenes: tuple[ScriptSceneInput, ...]
    segments: tuple[ScriptSegmentInput, ...]
    issues: tuple[LegacyScriptIssueSnapshot, ...]
    approval: ScriptApproval | None
    compatibility_status: str = "requires_reanalysis"
    contract_version: str = "narration-script-legacy-read/1"


@dataclass(frozen=True, slots=True)
class ParentReviewClassification:
    """Exhaustive, disjoint server classification for one optional parent."""

    parent_version_id: UUID | None
    verified_manual_review_parent: bool
    verified_non_review_parent: bool

    def __post_init__(self) -> None:
        has_parent = self.parent_version_id is not None
        classified = (
            self.verified_manual_review_parent
            or self.verified_non_review_parent
        )
        if has_parent != classified:
            raise InvalidNarrationState(
                "script parent classification must be exhaustive"
            )
        if (
            self.verified_manual_review_parent
            and self.verified_non_review_parent
        ):
            raise InvalidNarrationState(
                "script parent classifications must be disjoint"
            )


def _scene_payload(item: ScriptSceneInput | NarrationScene) -> dict[str, object]:
    return {
        "scene_id": str(item.scene_id if isinstance(item, ScriptSceneInput) else item.id),
        "ordinal": item.ordinal,
        "source_start": item.source_start,
        "source_end": item.source_end,
        "boundary_source": item.boundary_source,
        "local_hash": item.local_hash,
        "title": item.title,
    }


def _segment_payload(item: ScriptSegmentInput | NarrationSegment) -> dict[str, object]:
    return {
        "segment_id": str(item.segment_id if isinstance(item, ScriptSegmentInput) else item.id),
        "scene_id": str(item.scene_id) if item.scene_id else None,
        "ordinal": item.ordinal,
        "segment_kind": item.segment_kind,
        "paragraph_ordinal": item.paragraph_ordinal,
        "source_block_key": item.source_block_key,
        "source_start_utf16": item.source_start_utf16,
        "source_end_utf16": item.source_end_utf16,
        "source_text": item.source_text,
        "spoken_text": item.spoken_text,
        "local_hash": item.local_hash,
        "anchor_before_hash": item.anchor_before_hash,
        "anchor_after_hash": item.anchor_after_hash,
        "speaker_kind": item.speaker_kind,
        "character_id": str(item.character_id) if item.character_id else None,
        "anonymous_speaker_id": (
            str(item.anonymous_speaker_id) if item.anonymous_speaker_id else None
        ),
        "casting": canonical_payload(item.casting_json),
        "evidence": canonical_payload(item.evidence_json),
        "confidence": item.confidence,
        "emotion": item.emotion,
        "expression": item.expression,
        "pause_before_ms": item.pause_before_ms,
        "pause_after_ms": item.pause_after_ms,
        "manual_override": item.manual_override,
    }


def _issue_payload(item: ReviewIssue | NarrationScriptIssue) -> dict[str, object]:
    severity = item.severity.value if isinstance(item, ReviewIssue) else item.severity
    return {
        "code": item.code,
        "severity": severity,
        "segment_id": str(item.segment_id) if item.segment_id else None,
        "evidence_digest": item.evidence_digest,
    }


def _immutable_payload(
    *,
    script_id: UUID,
    parent_version_id: UUID | None,
    source_content_hash: str,
    settings_fingerprint: str,
    analyzer_fingerprint: str,
    rules_fingerprint: str,
    requested_model_fingerprint: str | None,
    actual_model_fingerprint: str | None,
    effective_policy: str,
    scenes: list[dict[str, object]],
    segments: list[dict[str, object]],
    issues: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "script_id": str(script_id),
        "parent_version_id": str(parent_version_id) if parent_version_id else None,
        "source_content_hash": source_content_hash,
        "settings_fingerprint": settings_fingerprint,
        "analyzer_fingerprint": analyzer_fingerprint,
        "rules_fingerprint": rules_fingerprint,
        "requested_model_fingerprint": requested_model_fingerprint,
        "actual_model_fingerprint": actual_model_fingerprint,
        "effective_policy": effective_policy,
        "taxonomy_version": NARRATION_REVIEW_TAXONOMY_VERSION,
        "scenes": scenes,
        "segments": segments,
        "issues": issues,
    }


def reserve_script_identity(
    store: NarrationStore,
    command: ReserveScriptIdentity,
) -> ScriptVersionAllocation:
    """Reserve stable script/version identity before child IDs are derived.

    The caller owns the surrounding transaction.  No placeholder version row is
    committed: the locked document serializes version-number allocation, while
    UUIDv5 makes a same-key retry stable even before materialization.
    """

    if type(command) is not ReserveScriptIdentity:
        raise NarrationServiceError("command must be ReserveScriptIdentity")
    require_local_novel(store, command.novel_id)
    document = require_row(
        store.get(Document, command.document_id, for_update=True),
        label="document",
    )
    require_same_novel(document.novel_id, command.novel_id, label="document")
    revision = require_row(
        store.get(DocumentRevision, command.revision_id), label="revision"
    )
    if (
        revision.document_id != document.id
        or revision.content_hash != command.content_hash
    ):
        raise StaleNarrationInput(
            "script source no longer matches the immutable revision"
        )
    require_sha256(command.content_hash, field="content_hash")
    key = require_nonempty(command.idempotency_key, field="idempotency_key")

    script = store.find_one(
        NarrationScript,
        document_id=command.document_id,
        revision_id=command.revision_id,
    )
    if script is None:
        script = NarrationScript(
            id=uuid5(
                command.document_id,
                f"narration-script:{command.revision_id}",
            ),
            novel_id=command.novel_id,
            document_id=command.document_id,
            revision_id=command.revision_id,
            content_hash=command.content_hash,
            version=1,
        )
        store.add(script)
        store.flush()
    else:
        require_same_novel(script.novel_id, command.novel_id, label="script")
        if (
            script.document_id != command.document_id
            or script.revision_id != command.revision_id
            or script.content_hash != command.content_hash
        ):
            raise StaleNarrationInput(
                "existing script has another immutable source guard"
            )

    existing = store.find_one(
        NarrationScriptVersion,
        script_id=script.id,
        idempotency_key=key,
    )
    if existing is not None:
        if existing.parent_version_id != command.parent_version_id:
            raise IdempotencyConflict(
                "script idempotency key has another parent version"
            )
        return ScriptVersionAllocation(
            novel_id=command.novel_id,
            document_id=command.document_id,
            revision_id=command.revision_id,
            content_hash=command.content_hash,
            script_id=script.id,
            script_version_id=existing.id,
            version_number=existing.version_number,
            idempotency_key=key,
            parent_version_id=command.parent_version_id,
            existing=True,
        )

    if command.parent_version_id is not None:
        parent = require_row(
            store.get(NarrationScriptVersion, command.parent_version_id),
            label="parent script version",
        )
        if parent.script_id != script.id:
            raise NarrationScopeMismatch(
                "parent script version belongs to another script"
            )
        classify_parent_review(store, script.id, command.parent_version_id)

    versions = store.find_all(NarrationScriptVersion, script_id=script.id)
    version_number = max(
        (item.version_number for item in versions), default=0
    ) + 1
    script_version_id = uuid5(
        script.id,
        f"narration-script-version:{key}",
    )
    collision = store.get(NarrationScriptVersion, script_version_id)
    if collision is not None:
        raise IdempotencyConflict(
            "deterministic script version identity is already occupied"
        )
    return ScriptVersionAllocation(
        novel_id=command.novel_id,
        document_id=command.document_id,
        revision_id=command.revision_id,
        content_hash=command.content_hash,
        script_id=script.id,
        script_version_id=script_version_id,
        version_number=version_number,
        idempotency_key=key,
        parent_version_id=command.parent_version_id,
        existing=False,
    )


def classify_parent_review(
    store: NarrationStore,
    script_id: UUID,
    parent_version_id: UUID | None,
) -> ParentReviewClassification:
    """Classify a parent from persisted state and its active review lineage.

    A corrected ``review_required`` version may receive more than one owner
    patch after its last blocker is removed.  Those zero-blocker intermediate
    versions still belong to the same manual-review continuation.  Follow that
    unapproved lineage until blocker evidence is found, while stopping at an
    approved/analyzed version so an unrelated clean script cannot acquire
    manual approval authority from historical ancestry.
    """

    if parent_version_id is None:
        return ParentReviewClassification(None, False, False)
    script = require_row(store.get(NarrationScript, script_id), label="script")
    current_id: UUID | None = parent_version_id
    visited: set[UUID] = set()
    while current_id is not None:
        if current_id in visited:
            raise InvalidNarrationState("script parent lineage contains a cycle")
        visited.add(current_id)
        parent = require_row(
            store.get(NarrationScriptVersion, current_id),
            label="parent script version",
        )
        if parent.script_id != script_id:
            raise NarrationScopeMismatch(
                "parent script version belongs to another script"
            )
        if parent.state not in {"analyzed", "review_required", "approved"}:
            raise InvalidNarrationState(
                "parent script version is not a verified materialized version"
            )
        if _is_typed_script_version(store, parent.id):
            typed_parent = load_script_contract(store, parent.id)
            blockers = typed_parent.blocker_count
            warnings = typed_parent.warning_count
            parent_state = typed_parent.state.value
        else:
            persisted_hash, issues = _persisted_version_hash(
                store, parent, script, for_update=False
            )
            if persisted_hash != parent.immutable_hash:
                raise StaleNarrationInput(
                    "parent script children differ from the immutable hash"
                )
            blockers = sum(issue.severity == "blocker" for issue in issues)
            warnings = sum(issue.severity == "warning" for issue in issues)
            parent_state = parent.state
        if (warnings, blockers) != (parent.warning_count, parent.blocker_count):
            raise StaleNarrationInput(
                "parent script issue counts differ from persisted evidence"
            )
        if blockers:
            if parent_state != "review_required":
                raise InvalidNarrationState(
                    "blocker-bearing parent must remain review_required"
                )
            return ParentReviewClassification(parent_version_id, True, False)
        if parent_state != "review_required":
            break
        current_id = parent.parent_version_id
    return ParentReviewClassification(parent_version_id, False, True)


def _require_typed_evidence(value: object) -> dict[str, object]:
    if type(value) is not dict:
        raise InvalidNarrationState("segment evidence must be an object")
    expected = {
        "contract_version",
        "source_block_kind",
        "source_block_hash",
        "segment_ordinal_in_block",
        "inheritance_anchor_before_hash",
        "inheritance_anchor_after_hash",
        "group_key",
        "attribution",
        "anonymous_identity",
        "emotion_confidence",
    }
    if set(value) != expected:
        raise InvalidNarrationState(
            "segment evidence does not match the frozen closed schema"
        )
    if value["contract_version"] != NARRATION_SEGMENT_EVIDENCE_VERSION:
        raise InvalidNarrationState(
            "unknown narration segment evidence contract version"
        )
    return value


def _verify_casting_target(
    store: NarrationStore,
    *,
    novel_id: UUID,
    target: CastingTargetRef,
    historical_read: bool,
) -> None:
    if target.kind is CastingTargetKind.CHARACTER_BINDING:
        character = require_row(
            store.get(NovelCharacter, target.character_id),
            label="casting target character",
        )
        if character.novel_id != novel_id:
            raise NarrationScopeMismatch(
                "character casting target is outside novel scope"
            )
        binding = store.get(CharacterVoiceBinding, target.binding_id)
        if binding is None and historical_read:
            return
        binding = require_row(binding, label="character voice binding")
        if (
            binding.novel_id != novel_id
            or binding.character_id != target.character_id
        ):
            raise NarrationScopeMismatch(
                "character casting target relation is not authorized"
            )
        if historical_read:
            return
        if (
            binding.binding_policy not in {"dedicated", "inherited"}
            or binding.profile_id is None
            or binding.voice_version_id is None
        ):
            raise NarrationScopeMismatch(
                "character casting target relation is not usable"
            )
        profile = require_row(
            store.get(VoiceProfile, binding.profile_id),
            label="character binding voice profile",
        )
        version = require_row(
            store.get(VoiceProfileVersion, binding.voice_version_id),
            label="character binding voice version",
        )
        if (
            profile.owner_id != LOCAL_OWNER_ID
            or profile.workspace_id != LOCAL_WORKSPACE_ID
            or profile.novel_id not in {None, novel_id}
            or version.owner_id != LOCAL_OWNER_ID
            or version.workspace_id != LOCAL_WORKSPACE_ID
            or version.profile_id != profile.id
        ):
            raise NarrationScopeMismatch(
                "character binding voice relation is outside fixed local scope"
            )
        return
    if target.kind is CastingTargetKind.ANONYMOUS_BINDING:
        anonymous = require_row(
            store.get(AnonymousSpeaker, target.anonymous_speaker_id),
            label="anonymous speaker binding",
        )
        if (
            anonymous.novel_id != novel_id
        ):
            raise NarrationScopeMismatch(
                "anonymous casting target relation is not authorized"
            )
        if historical_read:
            return
        if (
            anonymous.lifecycle_state != "active"
            or anonymous.voice_version_id is None
        ):
            raise NarrationScopeMismatch(
                "anonymous casting target relation is not usable"
            )
        return
    if target.kind is CastingTargetKind.GENERIC_SLOT:
        pool = require_row(
            store.get(GenericVoicePool, target.pool_id),
            label="generic voice pool",
        )
        slot = require_row(
            store.get(GenericVoiceSlot, target.slot_id),
            label="generic voice slot",
        )
        if (
            pool.novel_id != novel_id
            or slot.pool_id != pool.id
        ):
            raise NarrationScopeMismatch(
                "generic casting pool/slot relation is not authorized"
            )
        if historical_read:
            return
        if pool.status != "active" or not slot.enabled:
            raise NarrationScopeMismatch(
                "generic casting pool/slot relation is not usable"
            )
        return
    profile = require_row(
        store.get(VoiceProfile, target.profile_id), label="voice profile"
    )
    if (
        profile.owner_id != LOCAL_OWNER_ID
        or profile.workspace_id != LOCAL_WORKSPACE_ID
        or profile.novel_id not in {None, novel_id}
    ):
        raise NarrationScopeMismatch("voice profile is outside narration scope")


def _settings_snapshot_narrator_profile(
    store: NarrationStore,
    *,
    novel_id: UUID,
    resolved_settings: dict[str, object],
    historical_read: bool,
) -> UUID | None:
    raw_profile_id = resolved_settings["narrator_profile_id"]
    raw_version_id = resolved_settings["narrator_version_id"]
    if (raw_profile_id is None) != (raw_version_id is None):
        raise InvalidNarrationState(
            "settings snapshot narrator profile/version identity is incomplete"
        )
    if raw_profile_id is None:
        return None
    try:
        profile_id = UUID(str(raw_profile_id))
        version_id = UUID(str(raw_version_id))
    except ValueError as error:
        raise InvalidNarrationState(
            "settings snapshot narrator profile/version identity is invalid"
        ) from error
    profile = require_row(
        store.get(VoiceProfile, profile_id), label="settings narrator profile"
    )
    version = require_row(
        store.get(VoiceProfileVersion, version_id),
        label="settings narrator voice version",
    )
    if (
        profile.owner_id != LOCAL_OWNER_ID
        or profile.workspace_id != LOCAL_WORKSPACE_ID
        or profile.novel_id not in {None, novel_id}
        or version.owner_id != LOCAL_OWNER_ID
        or version.workspace_id != LOCAL_WORKSPACE_ID
        or version.profile_id != profile.id
    ):
        raise NarrationScopeMismatch(
            "settings narrator profile/version is outside fixed local scope"
        )
    return profile_id


def _settings_snapshot_authority(
    store: NarrationStore,
    *,
    novel_id: UUID,
    settings_fingerprint: str,
    effective_policy: ScriptReviewPolicy,
    historical_read: bool,
) -> dict[str, object]:
    """Reload and validate the immutable T3 settings root unconditionally."""

    require_sha256(settings_fingerprint, field="settings_fingerprint")
    snapshot = require_row(
        store.find_one(
            NarrationSettingsSnapshot,
            owner_id=LOCAL_OWNER_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            fingerprint=settings_fingerprint,
        ),
        label="narration settings snapshot",
    )
    if (
        snapshot.novel_id != novel_id
        or snapshot.schema_version != SETTINGS_SNAPSHOT_SCHEMA_VERSION
        or snapshot.taxonomy_version != NARRATION_REVIEW_TAXONOMY_VERSION
        or canonical_sha256(snapshot.snapshot_json) != snapshot.fingerprint
    ):
        raise StaleNarrationInput("narration settings snapshot changed")
    payload = snapshot.snapshot_json
    if type(payload) is not dict or set(payload) != {
        "schema_version",
        "taxonomy_version",
        "novel_id",
        "settings_version",
        "resolved_settings",
    }:
        raise InvalidNarrationState(
            "narration settings snapshot has an unknown shape"
        )
    if (
        payload["schema_version"] != snapshot.schema_version
        or payload["taxonomy_version"] != snapshot.taxonomy_version
        or payload["novel_id"] != str(novel_id)
    ):
        raise StaleNarrationInput(
            "narration settings snapshot root metadata differs"
        )
    require_exact_int(
        payload["settings_version"], field="settings_version", minimum=1
    )
    resolved = payload["resolved_settings"]
    if type(resolved) is not dict or set(resolved) != {
        "script_review_policy",
        "analysis_mode",
        "narrator_profile_id",
        "narrator_version_id",
        "settings",
        "scope_overrides",
    }:
        raise InvalidNarrationState(
            "resolved narration settings have an unknown shape"
        )
    if resolved["script_review_policy"] != effective_policy.value:
        raise StaleNarrationInput(
            "script review policy differs from its settings snapshot"
        )
    if resolved["analysis_mode"] != "local_rules_only":
        raise InvalidNarrationState(
            "cloud-assisted script authority remains HOLD at T3-GATE"
        )
    if resolved["scope_overrides"] != []:
        raise InvalidNarrationState(
            "volume/chapter narration overrides remain HOLD at T3-GATE"
        )
    if type(resolved["settings"]) is not dict:
        raise InvalidNarrationState(
            "narration settings snapshot payload must be an object"
        )
    canonical_payload(resolved["settings"])
    _settings_snapshot_narrator_profile(
        store,
        novel_id=novel_id,
        resolved_settings=resolved,
        historical_read=historical_read,
    )
    return resolved


def _build_script_authority_for_candidate(
    store: NarrationStore,
    candidate: object,
    *,
    historical_read: bool = False,
) -> ScriptAuthorityContext:
    require_local_novel(store, candidate.novel_id)
    if candidate.analyzer_fingerprint != SCRIPT_ANALYZER_FINGERPRINT:
        raise InvalidNarrationState(
            "script analyzer fingerprint is outside the T3 server registry"
        )
    if candidate.rules_fingerprint != SCRIPT_RULES_FINGERPRINT:
        raise InvalidNarrationState(
            "script rules fingerprint is outside the T3 server registry"
        )
    if (
        candidate.requested_model_fingerprint is not None
        or candidate.actual_model_fingerprint is not None
    ):
        raise InvalidNarrationState(
            "local-only T3 script authority cannot carry model fingerprints"
        )
    resolved_settings = _settings_snapshot_authority(
        store,
        novel_id=candidate.novel_id,
        settings_fingerprint=candidate.settings_fingerprint,
        effective_policy=candidate.effective_policy,
        historical_read=historical_read,
    )
    script = require_row(
        store.get(NarrationScript, candidate.script_id), label="script"
    )
    if (
        script.novel_id != candidate.novel_id
        or script.document_id != candidate.document_id
        or script.revision_id != candidate.revision_id
        or script.content_hash != candidate.source_content_hash
    ):
        raise NarrationScopeMismatch("script root is outside server authority")
    document = require_row(
        store.get(Document, candidate.document_id), label="document"
    )
    if document.novel_id != candidate.novel_id:
        raise NarrationScopeMismatch("script document is outside server authority")
    revision = require_row(
        store.get(DocumentRevision, candidate.revision_id), label="revision"
    )
    if (
        revision.document_id != candidate.document_id
        or revision.content_hash != candidate.source_content_hash
    ):
        raise StaleNarrationInput("script revision guard changed")

    parent = classify_parent_review(
        store, candidate.script_id, candidate.parent_version_id
    )
    blocker_count = require_exact_int(
        candidate.blocker_count,
        field="script blocker_count",
        minimum=0,
    )
    if candidate.approval is None:
        expected_state = (
            ScriptVersionState.REVIEW_REQUIRED
            if parent.verified_manual_review_parent
            else initial_materialized_state(
                candidate.effective_policy,
                blocker_count=blocker_count,
            )
        )
    else:
        if blocker_count:
            raise InvalidNarrationState(
                "approved script authority cannot contain blockers"
            )
        expected_state = ScriptVersionState.APPROVED
    character_ids: set[UUID] = set()
    anonymous_identities = set(candidate.anonymous_speakers)
    anonymous_by_id = {
        item.anonymous_speaker_id: item for item in anonymous_identities
    }
    casting_targets: set[CastingTargetRef] = set()
    historical_anonymous_ids: set[UUID] = set()
    current_scene_ids = {scene.scene_id for scene in candidate.scenes}

    for identity in anonymous_identities:
        row = require_row(
            store.get(AnonymousSpeaker, identity.anonymous_speaker_id),
            label="anonymous speaker",
        )
        if (
            row.novel_id != candidate.novel_id
            or row.stable_key_algorithm != identity.stable_key_algorithm
            or row.stable_key != identity.stable_key
            or row.scope_kind != identity.scope_kind.value
            or row.scope_id != identity.scope_id
            or row.display_name != identity.display_name
            or row.confidence != identity.confidence.value
        ):
            raise NarrationScopeMismatch(
                "anonymous identity snapshot is outside server authority"
            )
        if (
            identity.scope_kind is AnonymousScopeKind.SCENE
            and identity.scope_id not in current_scene_ids
        ):
            raise InvalidNarrationState(
                "historical anonymous identity replay remains HOLD at T3-GATE"
            )

    for segment in candidate.segments:
        speaker = segment.speaker
        if speaker.kind is SpeakerKind.GROUP:
            raise InvalidNarrationState(
                "group speaker authority is not persistently replayable in T3"
            )
        if speaker.character_id is not None:
            character = require_row(
                store.get(NovelCharacter, speaker.character_id), label="character"
            )
            if (
                character.novel_id != candidate.novel_id
                or (
                    not historical_read
                    and character.lifecycle_state != "active"
                )
            ):
                raise NarrationScopeMismatch(
                    "script character is outside the active novel scope"
                )
            character_ids.add(character.id)
        if speaker.anonymous_speaker_id is not None and (
            speaker.anonymous_speaker_id not in anonymous_by_id
        ):
            raise NarrationScopeMismatch(
                "segment anonymous speaker lacks an authorized snapshot"
            )
        attribution = segment.attribution
        if attribution.origin is not AttributionOrigin.LOCAL_RULE:
            raise InvalidNarrationState(
                "cloud and manual attribution remain HOLD without replayable authority"
            )
        for character_id in attribution.candidate_character_ids:
            character = require_row(
                store.get(NovelCharacter, character_id),
                label="candidate character",
            )
            if (
                character.novel_id != candidate.novel_id
                or (
                    not historical_read
                    and character.lifecycle_state != "active"
                )
            ):
                raise NarrationScopeMismatch(
                    "candidate character is outside the active novel scope"
                )
            character_ids.add(character_id)

        casting = segment.casting
        if casting.origin in {
            CastingDecisionOrigin.CASTING_RULE,
            CastingDecisionOrigin.MANUAL_OVERRIDE,
        }:
            raise InvalidNarrationState(
                "casting rule/manual authority remains HOLD until exact replay evidence exists"
            )
        for target in casting.candidate_targets:
            _verify_casting_target(
                store,
                novel_id=candidate.novel_id,
                target=target,
                historical_read=historical_read,
            )
            casting_targets.add(target)
        if casting.origin is CastingDecisionOrigin.NARRATOR_SETTING:
            profile_id = _settings_snapshot_narrator_profile(
                store,
                novel_id=candidate.novel_id,
                resolved_settings=resolved_settings,
                historical_read=historical_read,
            )
            if (
                casting.final_target is None
                or casting.final_target.kind is not CastingTargetKind.PROFILE
                or casting.final_target.profile_id != profile_id
            ):
                raise NarrationScopeMismatch(
                    "narrator casting differs from the frozen settings snapshot"
                )
        elif casting.origin is CastingDecisionOrigin.CHARACTER_BINDING:
            if (
                casting.final_target is None
                or casting.final_target.kind
                is not CastingTargetKind.CHARACTER_BINDING
            ):
                raise NarrationScopeMismatch(
                    "character binding casting relation is incomplete"
                )
        elif casting.origin is CastingDecisionOrigin.ANONYMOUS_BINDING:
            if (
                casting.final_target is None
                or casting.final_target.kind
                is not CastingTargetKind.ANONYMOUS_BINDING
            ):
                raise NarrationScopeMismatch(
                    "anonymous binding casting relation is incomplete"
                )

    approval = candidate.approval
    if approval is not None:
        request = require_generation_request(
            store,
            approval.request_id,
            novel_id=candidate.novel_id,
        )
        if (
            not request.allows_edition
            or request.effective_policy != candidate.effective_policy.value
            or request.settings_fingerprint != candidate.settings_fingerprint
            or not _request_covers_script(store, request, script)
        ):
            raise StaleNarrationInput(
                "approval request does not authorize this script snapshot"
            )
        if (
            approval.kind is ScriptApprovalKind.AUTO_NO_BLOCKERS
            and (
                request.force_review
                or request.effective_policy != ScriptReviewPolicy.BLOCKERS_ONLY.value
                or parent.verified_manual_review_parent
            )
        ):
            raise InvalidNarrationState(
                "automatic approval differs from the request review authority"
            )
        if (
            approval.kind is ScriptApprovalKind.MANUAL_AFTER_REVIEW
            and request.effective_policy != ScriptReviewPolicy.ALWAYS_REVIEW.value
            and not parent.verified_manual_review_parent
        ):
            raise InvalidNarrationState(
                "manual approval lacks request or parent review authority"
            )

    parent_ids = (
        frozenset({candidate.parent_version_id})
        if candidate.parent_version_id is not None
        else frozenset()
    )
    return ScriptAuthorityContext(
        novel_id=candidate.novel_id,
        document_id=candidate.document_id,
        revision_id=candidate.revision_id,
        script_id=candidate.script_id,
        script_version_id=candidate.script_version_id,
        version_number=candidate.version_number,
        state=expected_state,
        effective_policy=candidate.effective_policy,
        analyzer_fingerprint=candidate.analyzer_fingerprint,
        rules_fingerprint=candidate.rules_fingerprint,
        settings_fingerprint=candidate.settings_fingerprint,
        requested_model_fingerprint=candidate.requested_model_fingerprint,
        actual_model_fingerprint=candidate.actual_model_fingerprint,
        approval=approval,
        parent_version_ids=parent_ids,
        manual_review_parent_ids=(
            parent_ids if parent.verified_manual_review_parent else frozenset()
        ),
        non_review_parent_ids=(
            parent_ids if parent.verified_non_review_parent else frozenset()
        ),
        character_ids=frozenset(character_ids),
        anonymous_speakers=frozenset(anonymous_identities),
        verified_historical_anonymous_ids=frozenset(historical_anonymous_ids),
        group_keys=frozenset(),
        casting_targets=frozenset(casting_targets),
        casting_rule_records=frozenset(),
        cloud_records=frozenset(),
        override_provenances=frozenset(),
    )


def build_script_authority(
    store: NarrationStore,
    script: NarrationScriptContract,
) -> ScriptAuthorityContext:
    """Rebuild authority from storage; callers cannot supply trusted ID sets."""

    if type(script) is not NarrationScriptContract:
        raise NarrationServiceError(
            "script must be a NarrationScriptContract"
        )
    return _build_script_authority_for_candidate(store, script)


def create_script_draft(
    store: NarrationStore, command: CreateScriptDraft
) -> NarrationScriptVersion:
    require_local_novel(store, command.novel_id)
    # The immutable document is the stable mutex for first script/version writes.
    document = require_row(
        store.get(Document, command.document_id, for_update=True), label="document"
    )
    require_same_novel(document.novel_id, command.novel_id, label="document")
    revision = require_row(store.get(DocumentRevision, command.revision_id), label="revision")
    if revision.document_id != document.id or revision.content_hash != command.content_hash:
        raise StaleNarrationInput("script source no longer matches the immutable revision")
    for field, value in (
        ("content_hash", command.content_hash),
        ("settings_fingerprint", command.settings_fingerprint),
        ("analyzer_fingerprint", command.analyzer_fingerprint),
        ("rules_fingerprint", command.rules_fingerprint),
    ):
        require_sha256(value, field=field)
    if command.requested_model_fingerprint:
        require_sha256(command.requested_model_fingerprint, field="requested_model_fingerprint")
    if command.actual_model_fingerprint:
        require_sha256(command.actual_model_fingerprint, field="actual_model_fingerprint")
    if (
        (command.requested_model_fingerprint is None)
        != (command.actual_model_fingerprint is None)
        or (
            command.requested_model_fingerprint is not None
            and command.requested_model_fingerprint
            != command.actual_model_fingerprint
        )
    ):
        raise NarrationServiceError(
            "requested and actual model fingerprints must match"
        )
    require_nonempty(command.idempotency_key, field="idempotency_key")
    if command.effective_policy not in {"blockers_only", "always_review"}:
        raise NarrationServiceError("unsupported script review policy")
    if type(command.scenes) is not tuple or not all(
        type(item) is ScriptSceneInput for item in command.scenes
    ):
        raise NarrationServiceError("scenes must be a tuple of ScriptSceneInput")
    if type(command.segments) is not tuple or not all(
        type(item) is ScriptSegmentInput for item in command.segments
    ):
        raise NarrationServiceError("segments must be a tuple of ScriptSegmentInput")
    if type(command.issues) is not tuple or not all(
        type(item) is ReviewIssue for item in command.issues
    ):
        raise NarrationServiceError("issues must be a tuple of frozen ReviewIssue values")
    if not command.segments:
        raise NarrationServiceError("script version requires at least one frozen segment")
    if [item.ordinal for item in command.scenes] != list(range(len(command.scenes))):
        raise NarrationServiceError("scene ordinals must be contiguous from zero")
    if [item.ordinal for item in command.segments] != list(range(len(command.segments))):
        raise NarrationServiceError("segment ordinals must be contiguous from zero")
    scene_ids = {item.scene_id for item in command.scenes}
    if len(scene_ids) != len(command.scenes):
        raise NarrationServiceError("scene ids must be unique")
    segment_ids = {item.segment_id for item in command.segments}
    if len(segment_ids) != len(command.segments):
        raise NarrationServiceError("segment ids must be unique")
    for scene in command.scenes:
        require_exact_int(scene.ordinal, field="scene ordinal", minimum=0)
        require_nonempty(scene.boundary_source, field="scene boundary_source")
        require_sha256(scene.local_hash, field="scene local_hash")
        if (scene.source_start is None) != (scene.source_end is None):
            raise NarrationServiceError("scene source range must be completely present or absent")
        if scene.source_start is not None:
            require_exact_int(scene.source_start, field="scene source_start", minimum=0)
            require_exact_int(
                scene.source_end, field="scene source_end", minimum=scene.source_start
            )
    for segment in command.segments:
        require_exact_int(segment.ordinal, field="segment ordinal", minimum=0)
        require_nonempty(segment.segment_kind, field="segment_kind")
        require_nonempty(segment.source_block_key, field="source_block_key")
        if segment.segment_kind == "synthetic_pause":
            if (
                segment.source_text
                or segment.spoken_text
                or segment.source_start_utf16 is not None
                or segment.source_end_utf16 is not None
                or segment.pause_after_ms <= 0
            ):
                raise NarrationServiceError(
                    "synthetic_pause requires empty text, no source range, "
                    "and pause_after_ms > 0"
                )
        else:
            require_nonempty(segment.spoken_text, field="spoken_text")
        require_sha256(segment.local_hash, field="segment local_hash")
        for name, digest in (
            ("anchor_before_hash", segment.anchor_before_hash),
            ("anchor_after_hash", segment.anchor_after_hash),
        ):
            if digest is not None:
                require_sha256(digest, field=name)
        if segment.scene_id is not None and segment.scene_id not in scene_ids:
            raise NarrationScopeMismatch("segment references an unknown scene")
        if (segment.source_start_utf16 is None) != (segment.source_end_utf16 is None):
            raise NarrationServiceError("segment source anchor must be completely present or absent")
        if segment.source_start_utf16 is not None:
            require_exact_int(
                segment.source_start_utf16, field="source_start_utf16", minimum=0
            )
            require_exact_int(
                segment.source_end_utf16,
                field="source_end_utf16",
                minimum=segment.source_start_utf16 + 1,
            )
        if segment.paragraph_ordinal is not None:
            require_exact_int(
                segment.paragraph_ordinal, field="paragraph_ordinal", minimum=0
            )
        require_exact_int(segment.pause_before_ms, field="pause_before_ms", minimum=0)
        require_exact_int(segment.pause_after_ms, field="pause_after_ms", minimum=0)
        require_exact_bool(segment.manual_override, field="manual_override")
        if segment.speaker_kind not in {
            "narrator", "character", "anonymous", "group", "unknown"
        }:
            raise NarrationServiceError("unsupported speaker_kind")
        if segment.confidence not in {"high", "medium", "low", "unknown"}:
            raise NarrationServiceError("unsupported confidence")
        if type(segment.casting_json) is not dict or type(segment.evidence_json) is not dict:
            raise NarrationServiceError("segment casting/evidence payloads must be objects")
        canonical_payload(segment.casting_json)
        canonical_payload(segment.evidence_json)
    if any(issue.segment_id is not None and issue.segment_id not in segment_ids for issue in command.issues):
        raise NarrationScopeMismatch("script issue references an unknown segment")
    issue_keys = [
        (issue.code, issue.segment_id, issue.evidence_digest) for issue in command.issues
    ]
    if len(set(issue_keys)) != len(issue_keys):
        raise NarrationServiceError("duplicate script issue")

    script = store.find_one(
        NarrationScript, document_id=command.document_id, revision_id=command.revision_id
    )
    if script is None:
        script = NarrationScript(
            id=uuid4(),
            novel_id=command.novel_id,
            document_id=command.document_id,
            revision_id=command.revision_id,
            content_hash=command.content_hash,
            version=1,
        )
        store.add(script)
        store.flush()
    else:
        require_same_novel(script.novel_id, command.novel_id, label="script")
        if script.content_hash != command.content_hash:
            raise StaleNarrationInput("existing script has another immutable source hash")

    scene_payload = [_scene_payload(item) for item in command.scenes]
    segment_payload = [_segment_payload(item) for item in command.segments]
    issue_payload = sorted(
        [_issue_payload(issue) for issue in command.issues],
        key=lambda item: (
            str(item["code"]),
            str(item["segment_id"] or ""),
            str(item["evidence_digest"] or ""),
        ),
    )
    immutable_hash = canonical_sha256(
        _immutable_payload(
            script_id=script.id,
            parent_version_id=command.parent_version_id,
            source_content_hash=command.content_hash,
            settings_fingerprint=command.settings_fingerprint,
            analyzer_fingerprint=command.analyzer_fingerprint,
            rules_fingerprint=command.rules_fingerprint,
            requested_model_fingerprint=command.requested_model_fingerprint,
            actual_model_fingerprint=command.actual_model_fingerprint,
            effective_policy=command.effective_policy,
            scenes=scene_payload,
            segments=segment_payload,
            issues=issue_payload,
        )
    )
    existing = store.find_one(
        NarrationScriptVersion,
        script_id=script.id,
        idempotency_key=command.idempotency_key,
    )
    if existing is not None:
        if existing.immutable_hash != immutable_hash:
            raise IdempotencyConflict("script idempotency key has another canonical input")
        persisted_hash, _issues = _persisted_version_hash(
            store, existing, script, for_update=False
        )
        if persisted_hash != existing.immutable_hash:
            raise IdempotencyConflict("persisted script children differ from immutable hash")
        return existing
    versions = store.find_all(NarrationScriptVersion, script_id=script.id)
    if command.parent_version_id:
        parent = require_row(
            store.get(NarrationScriptVersion, command.parent_version_id), label="parent script version"
        )
        if parent.script_id != script.id:
            raise NarrationScopeMismatch("parent script version belongs to another script")
    row = NarrationScriptVersion(
        id=uuid4(),
        script_id=script.id,
        version_number=max((item.version_number for item in versions), default=0) + 1,
        parent_version_id=command.parent_version_id,
        state=(
            "review_required"
            if command.effective_policy == "always_review"
            or any(issue.severity is ReviewIssueSeverity.BLOCKER for issue in command.issues)
            else "analyzed"
        ),
        analyzer_fingerprint=command.analyzer_fingerprint,
        rules_fingerprint=command.rules_fingerprint,
        settings_fingerprint=command.settings_fingerprint,
        requested_model_fingerprint=command.requested_model_fingerprint,
        actual_model_fingerprint=command.actual_model_fingerprint,
        taxonomy_version=NARRATION_REVIEW_TAXONOMY_VERSION,
        immutable_hash=immutable_hash,
        idempotency_key=command.idempotency_key,
        warning_count=sum(
            issue.severity is ReviewIssueSeverity.WARNING for issue in command.issues
        ),
        blocker_count=sum(
            issue.severity is ReviewIssueSeverity.BLOCKER for issue in command.issues
        ),
        effective_policy=command.effective_policy,
    )
    store.add(row)
    store.flush()
    for scene in command.scenes:
        store.add(
            NarrationScene(
                id=scene.scene_id,
                script_version_id=row.id,
                ordinal=scene.ordinal,
                source_start=scene.source_start,
                source_end=scene.source_end,
                boundary_source=scene.boundary_source,
                local_hash=scene.local_hash,
                title=scene.title,
            )
        )
    for segment in command.segments:
        store.add(
            NarrationSegment(
                id=segment.segment_id,
                script_version_id=row.id,
                scene_id=segment.scene_id,
                ordinal=segment.ordinal,
                segment_kind=segment.segment_kind,
                paragraph_ordinal=segment.paragraph_ordinal,
                source_block_key=segment.source_block_key,
                source_start_utf16=segment.source_start_utf16,
                source_end_utf16=segment.source_end_utf16,
                source_text=segment.source_text,
                spoken_text=segment.spoken_text,
                local_hash=segment.local_hash,
                anchor_before_hash=segment.anchor_before_hash,
                anchor_after_hash=segment.anchor_after_hash,
                speaker_kind=segment.speaker_kind,
                character_id=segment.character_id,
                anonymous_speaker_id=segment.anonymous_speaker_id,
                casting_json=canonical_payload(segment.casting_json),
                evidence_json=canonical_payload(segment.evidence_json),
                confidence=segment.confidence,
                emotion=segment.emotion,
                expression=segment.expression,
                pause_before_ms=segment.pause_before_ms,
                pause_after_ms=segment.pause_after_ms,
                manual_override=segment.manual_override,
            )
        )
    store.flush()
    for issue in command.issues:
        store.add(
            NarrationScriptIssue(
                id=uuid4(),
                script_version_id=row.id,
                segment_id=issue.segment_id,
                taxonomy_version=NARRATION_REVIEW_TAXONOMY_VERSION,
                code=issue.code,
                severity=issue.severity.value,
                evidence_summary=getattr(issue, "evidence_summary", None),
                evidence_digest=issue.evidence_digest,
            )
        )
    store.flush()
    return row


def _approval_from_version(
    version: NarrationScriptVersion,
) -> ScriptApproval | None:
    approval_values = (
        version.approval_kind,
        version.approval_request_id,
        version.approval_request_allows_edition,
        version.approved_actor_type,
        version.approved_actor_id,
        version.approved_at,
    )
    if version.state != "approved":
        if any(value is not None for value in approval_values):
            raise InvalidNarrationState(
                "non-approved script contains approval audit fields"
            )
        return None
    if (
        any(value is None for value in approval_values)
        or version.approval_request_allows_edition is not True
    ):
        raise InvalidNarrationState(
            "approved script is missing its complete approval audit"
        )
    try:
        return ScriptApproval(
            kind=ScriptApprovalKind(version.approval_kind),
            request_id=version.approval_request_id,
            actor_type=ApprovalActorType(version.approved_actor_type),
            actor_id=version.approved_actor_id,
            approved_at=version.approved_at,
        )
    except (ScriptContractError, ValueError) as error:
        # ORM strings never become authority merely because they fit a column.
        raise InvalidNarrationState(
            "approved script contains an invalid approval audit"
        ) from error


def _typed_contract_payload_from_rows(
    store: NarrationStore,
    *,
    version: NarrationScriptVersion,
    script: NarrationScript,
) -> tuple[dict[str, object], object]:
    revision = require_row(
        store.get(DocumentRevision, script.revision_id), label="revision"
    )
    if (
        revision.document_id != script.document_id
        or revision.content_hash != script.content_hash
    ):
        raise StaleNarrationInput("script source revision guard changed")
    if version.taxonomy_version != NARRATION_REVIEW_TAXONOMY_VERSION:
        raise InvalidNarrationState("script taxonomy version is unknown")
    if (
        (version.requested_model_fingerprint is None)
        != (version.actual_model_fingerprint is None)
        or (
            version.requested_model_fingerprint is not None
            and version.requested_model_fingerprint
            != version.actual_model_fingerprint
        )
    ):
        raise InvalidNarrationState(
            "persisted requested/actual model fingerprints differ"
        )
    try:
        state = ScriptVersionState(version.state)
        policy = ScriptReviewPolicy(version.effective_policy)
    except ValueError as error:
        raise InvalidNarrationState("persisted script state/policy is unknown") from error
    approval = _approval_from_version(version)

    scene_rows = store.find_all(
        NarrationScene,
        script_version_id=version.id,
        order_by=("ordinal",),
    )
    scene_payloads: list[dict[str, object]] = []
    scene_views: list[object] = []
    for row in scene_rows:
        source_range = (
            None
            if row.source_start is None and row.source_end is None
            else {
                "start": row.source_start,
                "end_exclusive": row.source_end,
            }
        )
        scene_payloads.append(
            {
                "scene_id": str(row.id),
                "ordinal": row.ordinal,
                "source_range_utf16": source_range,
                "boundary_source": row.boundary_source,
                "local_hash": row.local_hash,
                "title": row.title,
            }
        )
        scene_views.append(SimpleNamespace(scene_id=row.id))

    segment_rows = store.find_all(
        NarrationSegment,
        script_version_id=version.id,
        order_by=("ordinal",),
    )
    segment_payloads: list[dict[str, object]] = []
    segment_views: list[object] = []
    anonymous_payloads: dict[UUID, dict[str, object]] = {}
    for row in segment_rows:
        evidence = _require_typed_evidence(row.evidence_json)
        if type(row.casting_json) is not dict:
            raise InvalidNarrationState("segment casting must be an object")
        if (
            row.casting_json.get("contract_version")
            != NARRATION_CASTING_DECISION_VERSION
        ):
            raise InvalidNarrationState(
                "unknown narration casting decision contract version"
            )
        try:
            casting = _parse_casting_decision(row.casting_json)
            attribution = _parse_attribution(evidence["attribution"])
            speaker_payload = {
                "kind": row.speaker_kind,
                "character_id": str(row.character_id) if row.character_id else None,
                "anonymous_speaker_id": (
                    str(row.anonymous_speaker_id)
                    if row.anonymous_speaker_id
                    else None
                ),
                "group_key": evidence["group_key"],
            }
            speaker = _parse_speaker(speaker_payload)
        except ScriptContractError as error:
            raise InvalidNarrationState(
                "persisted segment evidence violates the frozen contract"
            ) from error

        anonymous_snapshot = evidence["anonymous_identity"]
        if row.anonymous_speaker_id is None:
            if anonymous_snapshot is not None:
                raise InvalidNarrationState(
                    "non-anonymous segment contains an anonymous snapshot"
                )
        else:
            if type(anonymous_snapshot) is not dict or set(anonymous_snapshot) != {
                "anonymous_speaker_id",
                "stable_key_algorithm",
                "stable_key",
                "scope_kind",
                "scope_id",
            }:
                raise InvalidNarrationState(
                    "anonymous segment snapshot has an unknown shape"
                )
            anonymous_row = require_row(
                store.get(AnonymousSpeaker, row.anonymous_speaker_id),
                label="anonymous speaker",
            )
            if (
                anonymous_row.novel_id != script.novel_id
                or str(anonymous_row.id)
                != anonymous_snapshot["anonymous_speaker_id"]
                or anonymous_row.stable_key_algorithm
                != anonymous_snapshot["stable_key_algorithm"]
                or anonymous_row.stable_key != anonymous_snapshot["stable_key"]
                or anonymous_row.scope_kind != anonymous_snapshot["scope_kind"]
                or str(anonymous_row.scope_id) != anonymous_snapshot["scope_id"]
            ):
                raise NarrationScopeMismatch(
                    "anonymous identity differs from its immutable snapshot"
                )
            payload = {
                **anonymous_snapshot,
                "display_name": anonymous_row.display_name,
                "confidence": anonymous_row.confidence,
            }
            previous = anonymous_payloads.get(anonymous_row.id)
            if previous is not None and previous != payload:
                raise InvalidNarrationState(
                    "anonymous identity snapshots are inconsistent"
                )
            anonymous_payloads[anonymous_row.id] = payload

        source_range = (
            None
            if row.source_start_utf16 is None and row.source_end_utf16 is None
            else {
                "start": row.source_start_utf16,
                "end_exclusive": row.source_end_utf16,
            }
        )
        segment_payloads.append(
            {
                "segment_id": str(row.id),
                "ordinal": row.ordinal,
                "scene_id": str(row.scene_id) if row.scene_id else None,
                "segment_kind": row.segment_kind,
                "source_block_kind": evidence["source_block_kind"],
                "paragraph_ordinal": row.paragraph_ordinal,
                "segment_ordinal_in_block": evidence["segment_ordinal_in_block"],
                "source_block_key": row.source_block_key,
                "source_block_hash": evidence["source_block_hash"],
                "source_range_utf16": source_range,
                "source_text": row.source_text,
                "spoken_text": row.spoken_text,
                "local_hash": row.local_hash,
                "anchor_before_hash": row.anchor_before_hash,
                "anchor_after_hash": row.anchor_after_hash,
                "inheritance_anchor_before_hash": evidence[
                    "inheritance_anchor_before_hash"
                ],
                "inheritance_anchor_after_hash": evidence[
                    "inheritance_anchor_after_hash"
                ],
                "speaker": speaker_payload,
                "casting": canonical_payload(row.casting_json),
                "confidence": row.confidence,
                "emotion": row.emotion,
                "emotion_confidence": evidence["emotion_confidence"],
                "delivery": row.expression,
                "attribution": canonical_payload(evidence["attribution"]),
                "pause_before_ms": row.pause_before_ms,
                "pause_after_ms": row.pause_after_ms,
                "manual_override": row.manual_override,
            }
        )
        segment_views.append(
            SimpleNamespace(
                segment_id=row.id,
                scene_id=row.scene_id,
                local_hash=row.local_hash,
                inheritance_anchor_before_hash=evidence[
                    "inheritance_anchor_before_hash"
                ],
                inheritance_anchor_after_hash=evidence[
                    "inheritance_anchor_after_hash"
                ],
                speaker=speaker,
                casting=casting,
                attribution=attribution,
            )
        )

    issue_rows = store.find_all(
        NarrationScriptIssue,
        script_version_id=version.id,
    )
    issue_rows.sort(
        key=lambda item: (
            item.code,
            str(item.segment_id or ""),
            item.evidence_digest or "",
        )
    )
    issue_payloads = [
        {
            "code": row.code,
            "severity": row.severity,
            "segment_id": str(row.segment_id) if row.segment_id else None,
            "evidence_summary": row.evidence_summary,
            "evidence_digest": row.evidence_digest,
            "taxonomy_version": row.taxonomy_version,
        }
        for row in issue_rows
    ]
    approval_payload = None
    if approval is not None:
        approval_payload = {
            "kind": approval.kind.value,
            "request_id": str(approval.request_id),
            "actor_type": approval.actor_type.value,
            "actor_id": approval.actor_id,
            "approved_at": approval.approved_at.isoformat(),
        }
    payload: dict[str, object] = {
        "schema_version": NARRATION_SCRIPT_CONTRACT_VERSION,
        "taxonomy_version": version.taxonomy_version,
        "script_id": str(script.id),
        "script_version_id": str(version.id),
        "novel_id": str(script.novel_id),
        "document_id": str(script.document_id),
        "revision_id": str(script.revision_id),
        "source_content_hash": script.content_hash,
        "source_length_utf16": utf16_length(revision.content_markdown),
        "version_number": version.version_number,
        "parent_version_id": (
            str(version.parent_version_id) if version.parent_version_id else None
        ),
        "state": version.state,
        "effective_policy": version.effective_policy,
        "analyzer_fingerprint": version.analyzer_fingerprint,
        "rules_fingerprint": version.rules_fingerprint,
        "settings_fingerprint": version.settings_fingerprint,
        "requested_model_fingerprint": version.requested_model_fingerprint,
        "actual_model_fingerprint": version.actual_model_fingerprint,
        "anonymous_speakers": [
            anonymous_payloads[key]
            for key in sorted(anonymous_payloads, key=str)
        ],
        "scenes": scene_payloads,
        "segments": segment_payloads,
        "issues": issue_payloads,
        "warning_count": version.warning_count,
        "blocker_count": version.blocker_count,
        "immutable_hash": version.immutable_hash,
        "approval": approval_payload,
    }
    try:
        typed_anonymous = tuple(
            _parse_anonymous(item) for item in payload["anonymous_speakers"]
        )
    except ScriptContractError as error:
        raise InvalidNarrationState(
            "persisted anonymous identity violates the frozen contract"
        ) from error
    candidate = SimpleNamespace(
        script_id=script.id,
        script_version_id=version.id,
        novel_id=script.novel_id,
        document_id=script.document_id,
        revision_id=script.revision_id,
        source_content_hash=script.content_hash,
        version_number=version.version_number,
        parent_version_id=version.parent_version_id,
        state=state,
        effective_policy=policy,
        analyzer_fingerprint=version.analyzer_fingerprint,
        rules_fingerprint=version.rules_fingerprint,
        settings_fingerprint=version.settings_fingerprint,
        requested_model_fingerprint=version.requested_model_fingerprint,
        actual_model_fingerprint=version.actual_model_fingerprint,
        immutable_hash=version.immutable_hash,
        blocker_count=sum(row.severity == "blocker" for row in issue_rows),
        approval=approval,
        anonymous_speakers=typed_anonymous,
        scenes=tuple(scene_views),
        segments=tuple(segment_views),
    )
    return payload, candidate


def _has_deterministic_typed_identity(
    version: NarrationScriptVersion,
) -> bool:
    try:
        key = require_nonempty(
            version.idempotency_key,
            field="typed script idempotency_key",
        )
    except NarrationServiceError:
        return False
    return version.id == uuid5(
        version.script_id,
        f"narration-script-version:{key}",
    )


def load_script_contract(
    store: NarrationStore,
    version_id: UUID,
    *,
    for_update: bool = False,
) -> NarrationScriptContract:
    """Reload one typed script and re-prove its source, hash, and authority."""

    version = require_row(
        store.get(NarrationScriptVersion, version_id, for_update=for_update),
        label="script version",
    )
    if not _has_deterministic_typed_identity(version):
        raise InvalidNarrationState(
            "script contains an unknown or mixed typed storage contract"
        )
    script = require_row(store.get(NarrationScript, version.script_id), label="script")
    persisted_hash, _issues = _persisted_version_hash(
        store, version, script, for_update=for_update
    )
    if persisted_hash != version.immutable_hash:
        raise StaleNarrationInput(
            "script children differ from the frozen immutable hash"
        )
    payload, candidate = _typed_contract_payload_from_rows(
        store, version=version, script=script
    )
    if any(
        segment.attribution.origin is AttributionOrigin.MANUAL_OVERRIDE
        or segment.attribution.override_provenance is not None
        for segment in candidate.segments
    ):
        # Lazy import avoids the intentional review-actions -> script-versions
        # dependency while routing manual provenance through its ledger-backed
        # authority instead of disguising it as a local-rule result.
        from .review_actions import load_review_script_contract

        return load_review_script_contract(
            store,
            version_id,
            for_update=for_update,
        )
    authority = _build_script_authority_for_candidate(
        store,
        candidate,
        historical_read=(
            candidate.state is ScriptVersionState.APPROVED
            and candidate.approval is not None
        ),
    )
    revision = require_row(
        store.get(DocumentRevision, script.revision_id), label="revision"
    )
    try:
        return script_contract_from_dict(
            payload,
            authority=authority,
            source_text=revision.content_markdown,
        )
    except ScriptContractError as error:
        raise InvalidNarrationState(
            "persisted script violates the frozen typed contract"
        ) from error


def persist_script_contract(
    store: NarrationStore,
    allocation: ScriptVersionAllocation,
    contract: NarrationScriptContract,
) -> NarrationScriptVersion:
    """Persist the single frozen T3 contract without a second state/hash model."""

    if type(allocation) is not ScriptVersionAllocation:
        raise NarrationServiceError(
            "allocation must be ScriptVersionAllocation"
        )
    if type(contract) is not NarrationScriptContract:
        raise NarrationServiceError(
            "contract must be NarrationScriptContract"
        )
    expected_roots = (
        (contract.novel_id, allocation.novel_id),
        (contract.document_id, allocation.document_id),
        (contract.revision_id, allocation.revision_id),
        (contract.source_content_hash, allocation.content_hash),
        (contract.script_id, allocation.script_id),
        (contract.script_version_id, allocation.script_version_id),
        (contract.version_number, allocation.version_number),
        (contract.parent_version_id, allocation.parent_version_id),
    )
    if any(actual != expected for actual, expected in expected_roots):
        raise NarrationScopeMismatch(
            "typed script identity differs from its server allocation"
        )
    if contract.immutable_hash != script_immutable_hash(contract):
        raise StaleNarrationInput("typed script immutable hash changed")
    key = require_nonempty(
        allocation.idempotency_key,
        field="script allocation idempotency_key",
    )
    document = require_row(
        store.get(Document, allocation.document_id, for_update=True),
        label="document",
    )
    if document.novel_id != allocation.novel_id:
        raise NarrationScopeMismatch(
            "typed script allocation document is outside novel scope"
        )
    script = require_row(
        store.get(NarrationScript, allocation.script_id), label="script"
    )
    revision = require_row(
        store.get(DocumentRevision, allocation.revision_id), label="revision"
    )
    if (
        script.novel_id != allocation.novel_id
        or script.document_id != allocation.document_id
        or script.revision_id != allocation.revision_id
        or script.content_hash != allocation.content_hash
        or revision.document_id != allocation.document_id
        or revision.content_hash != allocation.content_hash
    ):
        raise StaleNarrationInput("typed script source guard changed")
    expected_version_id = uuid5(
        allocation.script_id,
        f"narration-script-version:{key}",
    )
    if allocation.script_version_id != expected_version_id:
        raise InvalidNarrationState(
            "typed script allocation identity is not server-derived"
        )
    existing = store.find_one(
        NarrationScriptVersion,
        script_id=allocation.script_id,
        idempotency_key=key,
    )
    if existing is not None:
        if (
            existing.id != allocation.script_version_id
            or existing.version_number != allocation.version_number
            or existing.parent_version_id != allocation.parent_version_id
            or existing.immutable_hash != contract.immutable_hash
        ):
            raise IdempotencyConflict(
                "script idempotency key has another canonical input"
            )
        loaded = load_script_contract(store, existing.id)
        if loaded.immutable_hash != contract.immutable_hash:
            raise IdempotencyConflict(
                "persisted script replay differs from canonical input"
            )
        return existing
    if allocation.existing:
        raise StaleNarrationInput(
            "reserved existing script version disappeared before replay"
        )
    versions = store.find_all(
        NarrationScriptVersion,
        script_id=allocation.script_id,
    )
    expected_version_number = max(
        (item.version_number for item in versions), default=0
    ) + 1
    if allocation.version_number != expected_version_number:
        raise StaleNarrationInput(
            "typed script allocation version number is no longer current"
        )
    identity_collision = store.get(
        NarrationScriptVersion,
        allocation.script_version_id,
    )
    if identity_collision is not None:
        raise IdempotencyConflict(
            "typed script allocation identity is already occupied"
        )
    if (
        contract.state is ScriptVersionState.APPROVED
        or contract.approval is not None
    ):
        raise InvalidNarrationState(
            "new typed script materialization cannot bypass the freeze service"
        )
    authority = build_script_authority(store, contract)
    try:
        validated = script_contract_from_dict(
            script_contract_to_dict(contract),
            authority=authority,
            source_text=revision.content_markdown,
        )
    except ScriptContractError as error:
        raise InvalidNarrationState(
            "typed script failed server authority validation"
        ) from error
    projection = script_immutable_payload(validated)
    row = NarrationScriptVersion(
        id=validated.script_version_id,
        script_id=validated.script_id,
        version_number=validated.version_number,
        parent_version_id=validated.parent_version_id,
        state=validated.state.value,
        analyzer_fingerprint=validated.analyzer_fingerprint,
        rules_fingerprint=validated.rules_fingerprint,
        settings_fingerprint=validated.settings_fingerprint,
        requested_model_fingerprint=validated.requested_model_fingerprint,
        actual_model_fingerprint=validated.actual_model_fingerprint,
        taxonomy_version=validated.taxonomy_version,
        immutable_hash=validated.immutable_hash,
        idempotency_key=key,
        warning_count=validated.warning_count,
        blocker_count=validated.blocker_count,
        effective_policy=validated.effective_policy.value,
        approval_kind=(validated.approval.kind.value if validated.approval else None),
        approval_request_id=(
            validated.approval.request_id if validated.approval else None
        ),
        approval_request_allows_edition=(True if validated.approval else None),
        approved_actor_type=(
            validated.approval.actor_type.value if validated.approval else None
        ),
        approved_actor_id=(
            validated.approval.actor_id if validated.approval else None
        ),
        approved_at=(validated.approval.approved_at if validated.approval else None),
    )
    store.add(row)
    store.flush()
    scene_payloads = projection["scenes"]
    segment_payloads = projection["segments"]
    if type(scene_payloads) is not list or type(segment_payloads) is not list:
        raise InvalidNarrationState("typed immutable projection is not materialized")
    for item in scene_payloads:
        if type(item) is not dict:
            raise InvalidNarrationState("typed scene projection is invalid")
        store.add(
            NarrationScene(
                id=UUID(str(item["scene_id"])),
                script_version_id=row.id,
                ordinal=item["ordinal"],
                source_start=item["source_start"],
                source_end=item["source_end"],
                boundary_source=item["boundary_source"],
                local_hash=item["local_hash"],
                title=item["title"],
            )
        )
    for item in segment_payloads:
        if type(item) is not dict:
            raise InvalidNarrationState("typed segment projection is invalid")
        store.add(
            NarrationSegment(
                id=UUID(str(item["segment_id"])),
                script_version_id=row.id,
                scene_id=(UUID(str(item["scene_id"])) if item["scene_id"] else None),
                ordinal=item["ordinal"],
                segment_kind=item["segment_kind"],
                paragraph_ordinal=item["paragraph_ordinal"],
                source_block_key=item["source_block_key"],
                source_start_utf16=item["source_start_utf16"],
                source_end_utf16=item["source_end_utf16"],
                source_text=item["source_text"],
                spoken_text=item["spoken_text"],
                local_hash=item["local_hash"],
                anchor_before_hash=item["anchor_before_hash"],
                anchor_after_hash=item["anchor_after_hash"],
                speaker_kind=item["speaker_kind"],
                character_id=(
                    UUID(str(item["character_id"])) if item["character_id"] else None
                ),
                anonymous_speaker_id=(
                    UUID(str(item["anonymous_speaker_id"]))
                    if item["anonymous_speaker_id"]
                    else None
                ),
                casting_json=canonical_payload(item["casting"]),
                evidence_json=canonical_payload(item["evidence"]),
                confidence=item["confidence"],
                emotion=item["emotion"],
                expression=item["expression"],
                pause_before_ms=item["pause_before_ms"],
                pause_after_ms=item["pause_after_ms"],
                manual_override=item["manual_override"],
            )
        )
    store.flush()
    for issue in validated.issues:
        store.add(
            NarrationScriptIssue(
                id=uuid4(),
                script_version_id=row.id,
                segment_id=issue.segment_id,
                taxonomy_version=issue.taxonomy_version,
                code=issue.code,
                severity=issue.severity.value,
                evidence_summary=issue.evidence_summary,
                evidence_digest=issue.evidence_digest,
            )
        )
    store.flush()
    reloaded = load_script_contract(store, row.id)
    if reloaded.immutable_hash != validated.immutable_hash:
        raise StaleNarrationInput(
            "typed script reload differs from its immutable projection"
        )
    return row


def _persisted_version_hash(
    store: NarrationStore,
    version: NarrationScriptVersion,
    script: NarrationScript,
    *,
    for_update: bool,
) -> tuple[str, list[NarrationScriptIssue]]:
    scenes = store.find_all(
        NarrationScene,
        script_version_id=version.id,
        order_by=("ordinal",),
        for_update=for_update,
    )
    segments = store.find_all(
        NarrationSegment,
        script_version_id=version.id,
        order_by=("ordinal",),
        for_update=for_update,
    )
    issues = store.find_all(
        NarrationScriptIssue,
        script_version_id=version.id,
        for_update=for_update,
    )
    issue_payload: list[dict[str, object]] = []
    for issue in issues:
        expected = issue_severity(issue.code)
        if issue.severity != expected.value:
            raise InvalidNarrationState("persisted issue severity differs from taxonomy")
        if issue.taxonomy_version != NARRATION_REVIEW_TAXONOMY_VERSION:
            raise InvalidNarrationState("persisted issue taxonomy version changed")
        if issue.evidence_digest is not None:
            require_sha256(issue.evidence_digest, field="issue evidence_digest")
        issue_payload.append(_issue_payload(issue))
    issue_payload.sort(
        key=lambda item: (
            str(item["code"]),
            str(item["segment_id"] or ""),
            str(item["evidence_digest"] or ""),
        )
    )
    payload = _immutable_payload(
        script_id=script.id,
        parent_version_id=version.parent_version_id,
        source_content_hash=script.content_hash,
        settings_fingerprint=version.settings_fingerprint,
        analyzer_fingerprint=version.analyzer_fingerprint,
        rules_fingerprint=version.rules_fingerprint,
        requested_model_fingerprint=version.requested_model_fingerprint,
        actual_model_fingerprint=version.actual_model_fingerprint,
        effective_policy=version.effective_policy,
        scenes=[_scene_payload(item) for item in scenes],
        segments=[_segment_payload(item) for item in segments],
        issues=issue_payload,
    )
    return canonical_sha256(payload), issues


def _request_covers_script(
    store: NarrationStore, request: NarrationRequest, script: NarrationScript
) -> bool:
    if request.intent in {"create", "update"}:
        return (
            request.document_id == script.document_id
            and request.source_revision_id == script.revision_id
            and request.source_content_hash == script.content_hash
        )
    if request.intent == "batch":
        return any(
            source.document_id == script.document_id
            and source.revision_id == script.revision_id
            and source.content_hash == script.content_hash
            for source in store.find_all(NarrationRequestSource, request_id=request.id)
        )
    return False


def _is_typed_script_version(
    store: NarrationStore,
    version_id: UUID,
) -> bool:
    version = store.get(NarrationScriptVersion, version_id)
    segments = store.find_all(
        NarrationSegment,
        script_version_id=version_id,
    )
    current_typed = bool(segments) and all(
        type(segment.casting_json) is dict
        and segment.casting_json.get("contract_version")
        == NARRATION_CASTING_DECISION_VERSION
        and type(segment.evidence_json) is dict
        and segment.evidence_json.get("contract_version")
        == NARRATION_SEGMENT_EVIDENCE_VERSION
        for segment in segments
    )
    carries_typed_marker = any(
        (
            type(segment.casting_json) is dict
            and "contract_version" in segment.casting_json
        )
        or (
            type(segment.evidence_json) is dict
            and "contract_version" in segment.evidence_json
        )
        for segment in segments
    )
    has_deterministic_typed_identity = bool(
        version is not None and _has_deterministic_typed_identity(version)
    )
    if current_typed and has_deterministic_typed_identity:
        return True
    if carries_typed_marker or has_deterministic_typed_identity:
        raise InvalidNarrationState(
            "script contains an unknown or mixed typed storage contract"
        )
    return False


def load_script_version_for_read(
    store: NarrationStore,
    version_id: UUID,
) -> NarrationScriptContract | LegacyScriptVersionRead:
    """Read typed and legacy rows without ever rewriting legacy storage."""

    if _is_typed_script_version(store, version_id):
        return load_script_contract(store, version_id)
    version = require_row(
        store.get(NarrationScriptVersion, version_id), label="script version"
    )
    script = require_row(
        store.get(NarrationScript, version.script_id), label="script"
    )
    require_local_novel(store, script.novel_id)
    document = require_row(
        store.get(Document, script.document_id), label="document"
    )
    revision = require_row(
        store.get(DocumentRevision, script.revision_id), label="revision"
    )
    if (
        document.novel_id != script.novel_id
        or revision.document_id != script.document_id
        or revision.content_hash != script.content_hash
    ):
        raise StaleNarrationInput("legacy script source guard changed")
    persisted_hash, issue_rows = _persisted_version_hash(
        store, version, script, for_update=False
    )
    if persisted_hash != version.immutable_hash:
        raise StaleNarrationInput(
            "legacy script children differ from the immutable hash"
        )
    try:
        state = ScriptVersionState(version.state)
        policy = ScriptReviewPolicy(version.effective_policy)
    except ValueError as error:
        raise InvalidNarrationState(
            "legacy script state/policy is unknown"
        ) from error
    for field_name, value in (
        ("legacy source_content_hash", script.content_hash),
        ("legacy settings_fingerprint", version.settings_fingerprint),
        ("legacy analyzer_fingerprint", version.analyzer_fingerprint),
        ("legacy rules_fingerprint", version.rules_fingerprint),
    ):
        require_sha256(value, field=field_name)
    if (
        (version.requested_model_fingerprint is None)
        != (version.actual_model_fingerprint is None)
        or (
            version.requested_model_fingerprint is not None
            and version.requested_model_fingerprint
            != version.actual_model_fingerprint
        )
    ):
        raise InvalidNarrationState(
            "legacy requested/actual model fingerprints differ"
        )
    approval = _approval_from_version(version)
    scene_rows = store.find_all(
        NarrationScene,
        script_version_id=version.id,
        order_by=("ordinal",),
    )
    segment_rows = store.find_all(
        NarrationSegment,
        script_version_id=version.id,
        order_by=("ordinal",),
    )
    if not segment_rows or [row.ordinal for row in segment_rows] != list(
        range(len(segment_rows))
    ):
        raise InvalidNarrationState(
            "legacy script segment ordinals are not readable"
        )
    if [row.ordinal for row in scene_rows] != list(range(len(scene_rows))):
        raise InvalidNarrationState(
            "legacy script scene ordinals are not readable"
        )
    warnings = sum(row.severity == "warning" for row in issue_rows)
    blockers = sum(row.severity == "blocker" for row in issue_rows)
    if (warnings, blockers) != (version.warning_count, version.blocker_count):
        raise StaleNarrationInput(
            "legacy script issue counts differ from persisted evidence"
        )
    return LegacyScriptVersionRead(
        script_id=script.id,
        script_version_id=version.id,
        novel_id=script.novel_id,
        document_id=script.document_id,
        revision_id=script.revision_id,
        source_content_hash=script.content_hash,
        source_length_utf16=utf16_length(revision.content_markdown),
        version_number=version.version_number,
        parent_version_id=version.parent_version_id,
        state=state,
        effective_policy=policy,
        settings_fingerprint=version.settings_fingerprint,
        analyzer_fingerprint=version.analyzer_fingerprint,
        rules_fingerprint=version.rules_fingerprint,
        requested_model_fingerprint=version.requested_model_fingerprint,
        actual_model_fingerprint=version.actual_model_fingerprint,
        immutable_hash=version.immutable_hash,
        warning_count=warnings,
        blocker_count=blockers,
        scenes=tuple(
            ScriptSceneInput(
                scene_id=row.id,
                ordinal=row.ordinal,
                source_start=row.source_start,
                source_end=row.source_end,
                boundary_source=row.boundary_source,
                local_hash=row.local_hash,
                title=row.title,
            )
            for row in scene_rows
        ),
        segments=tuple(
            ScriptSegmentInput(
                segment_id=row.id,
                scene_id=row.scene_id,
                ordinal=row.ordinal,
                segment_kind=row.segment_kind,
                paragraph_ordinal=row.paragraph_ordinal,
                source_block_key=row.source_block_key,
                source_start_utf16=row.source_start_utf16,
                source_end_utf16=row.source_end_utf16,
                source_text=row.source_text,
                spoken_text=row.spoken_text,
                local_hash=row.local_hash,
                anchor_before_hash=row.anchor_before_hash,
                anchor_after_hash=row.anchor_after_hash,
                speaker_kind=row.speaker_kind,
                character_id=row.character_id,
                anonymous_speaker_id=row.anonymous_speaker_id,
                casting_json=canonical_payload(row.casting_json),
                evidence_json=canonical_payload(row.evidence_json),
                confidence=row.confidence,
                emotion=row.emotion,
                expression=row.expression,
                pause_before_ms=row.pause_before_ms,
                pause_after_ms=row.pause_after_ms,
                manual_override=row.manual_override,
            )
            for row in segment_rows
        ),
        issues=tuple(
            LegacyScriptIssueSnapshot(
                code=row.code,
                severity=ReviewIssueSeverity(row.severity),
                segment_id=row.segment_id,
                evidence_summary=row.evidence_summary,
                evidence_digest=row.evidence_digest,
            )
            for row in sorted(
                issue_rows,
                key=lambda item: (
                    item.code,
                    str(item.segment_id or ""),
                    item.evidence_digest or "",
                ),
            )
        ),
        approval=approval,
    )


def freeze_script_version(
    store: NarrationStore,
    version_id: UUID,
    *,
    request_id: UUID,
    actor_type: str,
    actor_id: str,
    approved_at: datetime | None = None,
) -> NarrationScriptVersion:
    """Freeze through request -> version -> script deterministic locking.

    The initial unlocked reads are identity discovery only.  No authority is
    consumed until the generation request is locked first and both discovered
    rows are subsequently locked and revalidated.
    """

    located_version = require_row(
        store.get(NarrationScriptVersion, version_id),
        label="script version",
    )
    located_script = require_row(
        store.get(NarrationScript, located_version.script_id),
        label="script",
    )
    located_identity = (
        located_version.script_id,
        located_script.novel_id,
        located_script.document_id,
        located_script.revision_id,
        located_script.content_hash,
    )
    request = require_generation_request(
        store,
        request_id,
        novel_id=located_script.novel_id,
        for_update=True,
    )
    version = require_row(
        store.get(NarrationScriptVersion, version_id, for_update=True),
        label="script version",
    )
    script = require_row(
        store.get(NarrationScript, version.script_id, for_update=True),
        label="script",
    )
    locked_identity = (
        version.script_id,
        script.novel_id,
        script.document_id,
        script.revision_id,
        script.content_hash,
    )
    if locked_identity != located_identity or request.novel_id != script.novel_id:
        raise StaleNarrationInput(
            "script identity changed while freeze locks were acquired"
        )
    actor = require_nonempty(actor_id, field="actor_id")
    if version.state == "approved":
        approved = load_script_contract(store, version_id, for_update=True)
        if (
            approved.approval is not None
            and approved.approval.request_id == request_id
            and approved.approval.actor_type.value == actor_type
            and approved.approval.actor_id == actor
        ):
            return version
        raise InvalidNarrationState("approved script version is terminal")
    contract = load_script_contract(store, version_id, for_update=True)
    if request.state not in {"analyzing", "review_required"}:
        raise InvalidNarrationState(
            "generation request is not in a reviewable state"
        )
    if request.effective_policy != version.effective_policy:
        raise InvalidNarrationState(
            "request and script review policies differ"
        )
    if request.settings_fingerprint != version.settings_fingerprint:
        raise StaleNarrationInput(
            "request settings differ from analyzed script"
        )
    if not _request_covers_script(store, request, script):
        raise StaleNarrationInput(
            "request source does not cover the analyzed script revision"
        )
    parent = classify_parent_review(
        store, script.id, version.parent_version_id
    )
    try:
        context = ReviewRequestContext(
            request_id=request.id,
            intent=ReviewIntent(request.intent),
            allows_edition=bool(request.allows_edition),
            effective_policy=ScriptReviewPolicy(request.effective_policy),
            force_review=bool(request.force_review),
            verified_manual_review_parent=(
                parent.verified_manual_review_parent
            ),
            verified_non_review_parent=(
                parent.verified_non_review_parent
            ),
        )
        decision = decide_script_review(contract, context)
        frozen_at = approved_at or utc_now()
        if decision.disposition is ReviewDisposition.AUTO_FREEZE:
            frozen = auto_freeze_script(
                contract,
                context,
                actor_type=ApprovalActorType(actor_type),
                actor_id=actor,
                approved_at=frozen_at,
            )
        elif decision.disposition is ReviewDisposition.REVIEW_REQUIRED:
            if actor_type != ApprovalActorType.OWNER.value:
                raise InvalidNarrationState(
                    "manual approval requires the owner actor"
                )
            frozen = manual_freeze_script(
                contract,
                context,
                owner_actor_id=actor,
                approved_at=frozen_at,
            )
        else:
            raise InvalidNarrationState(
                "analyze_only request cannot freeze a script"
            )
    except (ReviewStateError, ScriptContractError, ValueError) as error:
        raise InvalidNarrationState(str(error)) from error
    if frozen.approval is None:
        raise InvalidNarrationState("frozen script lacks approval audit")
    version.warning_count = frozen.warning_count
    version.blocker_count = frozen.blocker_count
    version.approval_kind = frozen.approval.kind.value
    version.approval_request_id = frozen.approval.request_id
    version.approval_request_allows_edition = True
    version.approved_actor_type = frozen.approval.actor_type.value
    version.approved_actor_id = frozen.approval.actor_id
    version.approved_at = frozen.approval.approved_at
    version.state = frozen.state.value
    store.flush()
    reloaded = load_script_contract(store, version.id, for_update=True)
    if reloaded.approval != frozen.approval:
        raise StaleNarrationInput(
            "script approval audit changed during persistence"
        )
    return version


def approve_script_version(
    store: NarrationStore,
    version_id: UUID,
    *,
    request_id: UUID,
    actor_type: str,
    actor_id: str,
) -> NarrationScriptVersion:
    if _is_typed_script_version(store, version_id):
        return freeze_script_version(
            store,
            version_id,
            request_id=request_id,
            actor_type=actor_type,
            actor_id=actor_id,
        )
    version = require_row(
        store.get(NarrationScriptVersion, version_id, for_update=True),
        label="script version",
    )
    if version.state == "approved":
        if version.approval_request_id == request_id:
            return version
        raise InvalidNarrationState("approved script version is terminal")
    if version.state not in {"analyzed", "review_required"}:
        raise InvalidNarrationState("script version is not ready for approval")
    script = require_row(store.get(NarrationScript, version.script_id), label="script")
    request = require_generation_request(
        store, request_id, novel_id=script.novel_id, for_update=True
    )
    if request.state not in {"analyzing", "review_required"}:
        raise InvalidNarrationState("generation request is not in a reviewable state")
    if request.effective_policy != version.effective_policy:
        raise InvalidNarrationState("request and script review policies differ")
    if request.settings_fingerprint != version.settings_fingerprint:
        raise StaleNarrationInput("request settings differ from analyzed script")
    if not _request_covers_script(store, request, script):
        raise StaleNarrationInput("request source does not cover the analyzed script revision")
    persisted_hash, issues = _persisted_version_hash(
        store, version, script, for_update=True
    )
    if persisted_hash != version.immutable_hash:
        raise StaleNarrationInput("script children differ from the frozen immutable hash")
    blockers = sum(issue.severity == "blocker" for issue in issues)
    warnings = sum(issue.severity == "warning" for issue in issues)
    if blockers != version.blocker_count or warnings != version.warning_count:
        raise StaleNarrationInput("script issue counts differ from the immutable version")
    if blockers:
        raise InvalidNarrationState("script blockers must be resolved in a new version")
    parent = classify_parent_review(
        store, script.id, version.parent_version_id
    )
    if (
        request.force_review
        or version.effective_policy == "always_review"
        or parent.verified_manual_review_parent
    ):
        if actor_type != "owner" or not actor_id:
            raise InvalidNarrationState("manual approval requires the owner actor")
        approval_kind = "manual_after_review"
    else:
        if actor_type not in {"system", "service"} or not actor_id:
            raise InvalidNarrationState("automatic approval requires an auditable system actor")
        approval_kind = "auto_no_blockers"
    version.warning_count = warnings
    version.blocker_count = blockers
    version.approval_kind = approval_kind
    version.approval_request_id = request.id
    version.approval_request_allows_edition = True
    version.approved_actor_type = actor_type
    version.approved_actor_id = actor_id
    version.approved_at = utc_now()
    version.state = "approved"
    store.flush()
    return version


def derive_script_status(
    store: NarrationStore,
    version_id: UUID,
    *,
    current_revision_id: UUID,
    current_content_hash: str,
    current_settings_fingerprint: str,
) -> str:
    version = require_row(store.get(NarrationScriptVersion, version_id), label="script version")
    script = require_row(store.get(NarrationScript, version.script_id), label="script")
    if script.revision_id != current_revision_id or script.content_hash != current_content_hash:
        return "working_copy_diverged"
    if version.settings_fingerprint != current_settings_fingerprint:
        return "superseded"
    return "current" if version.state == "approved" else version.state


__all__ = [
    "CreateScriptDraft",
    "LegacyScriptIssueSnapshot",
    "LegacyScriptVersionRead",
    "ParentReviewClassification",
    "ReserveScriptIdentity",
    "SCRIPT_ANALYZER_FINGERPRINT",
    "SCRIPT_ANALYZER_VERSION",
    "SCRIPT_RULES_FINGERPRINT",
    "ScriptSceneInput",
    "ScriptSegmentInput",
    "ScriptVersionAllocation",
    "approve_script_version",
    "build_script_authority",
    "classify_parent_review",
    "create_script_draft",
    "derive_script_status",
    "freeze_script_version",
    "load_script_contract",
    "load_script_version_for_read",
    "persist_script_contract",
    "reserve_script_identity",
]
