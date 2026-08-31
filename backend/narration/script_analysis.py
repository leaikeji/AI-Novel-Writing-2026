"""T3-GATE orchestration for deterministic local narration-script analysis.

This module joins the already-frozen T3 segmentation, scene, speaker,
expression, casting, review, and typed-persistence components.  It deliberately
contains no model, network, media, Edition, or render work and does not
reimplement any of those components' decision rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID

from pydantic import ValidationError

from ..models import (
    CharacterAlias,
    CharacterVoiceBinding,
    Document,
    DocumentRevision,
    NarrationRequest,
    NarrationRequestSource,
    NarrationSettingsSnapshot,
    NovelCharacter,
    VoiceProfile,
    VoiceProfileVersion,
    VoiceRightsRecord,
)

from . import schemas as wire
from .aliases import (
    AliasSource,
    CharacterAliasRecord,
    build_character_alias_index,
    normalize_character_alias,
)
from .casting import (
    CastingAttributes,
    CastingInventory,
    CastingRequest,
    CastingScopeKind,
    CharacterBindingSnapshot,
    NarratorSelectionSnapshot,
    VoiceVersionSnapshot,
    resolve_casting,
)
from .contracts import (
    LOCAL_OWNER_ID,
    LOCAL_WORKSPACE_ID,
    NARRATION_REVIEW_TAXONOMY_VERSION,
    ReviewIssueSeverity,
)
from .expression import (
    ExpressionContext,
    classify_expression,
)
from .requests import RequestSource, advance_request_state, source_set_hash
from .scenes import (
    build_scene_contracts,
    scene_ids_for_source_ranges,
)
from .script_contracts import (
    NARRATION_SCRIPT_CONTRACT_VERSION,
    NarrationScriptContract,
    ScriptIssueContract,
    ScriptReviewPolicy,
    SegmentContract,
    initial_materialized_state,
    script_immutable_payload,
)
from .script_versions import (
    SCRIPT_ANALYZER_FINGERPRINT,
    SCRIPT_ANALYZER_VERSION,
    SCRIPT_RULES_FINGERPRINT,
    ReserveScriptIdentity,
    freeze_script_version,
    load_script_contract,
    persist_script_contract,
    reserve_script_identity,
)
from .segmentation import SourceFormat, segment_source
from .services import (
    IdempotencyConflict,
    InvalidNarrationState,
    NarrationScopeMismatch,
    NarrationServiceError,
    NarrationStore,
    StaleNarrationInput,
    canonical_sha256,
    canonical_payload,
    require_local_novel,
    require_nonempty,
    require_row,
    require_same_novel,
    require_sha256,
    utc_now,
    voice_activation_evidence_is_usable,
)
from .snapshots import SETTINGS_SNAPSHOT_SCHEMA_VERSION
from .speaker_rules import (
    SpeakerRuleContext,
    attribute_speaker_local,
)
from .voices import _rights_state


@dataclass(frozen=True, slots=True)
class AnalyzeNarrationScript:
    """Server-scoped input for one document/revision analysis action."""

    request_id: UUID
    document_id: UUID
    revision_id: UUID
    content_hash: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class _AnalysisContext:
    request: NarrationRequest
    document: Document
    revision: DocumentRevision
    settings: wire.NarrationSettingsValues


def _stored_request_sources(
    store: NarrationStore,
    request: NarrationRequest,
) -> tuple[RequestSource, ...]:
    return tuple(
        RequestSource(
            document_id=row.document_id,
            revision_id=row.revision_id,
            content_hash=row.content_hash,
            position=row.position,
        )
        for row in store.find_all(
            NarrationRequestSource,
            request_id=request.id,
            order_by=("position",),
            for_update=True,
        )
    )


def _snapshot_settings(
    store: NarrationStore,
    *,
    request: NarrationRequest,
) -> wire.NarrationSettingsValues:
    snapshot = require_row(
        store.find_one(
            NarrationSettingsSnapshot,
            owner_id=LOCAL_OWNER_ID,
            workspace_id=LOCAL_WORKSPACE_ID,
            fingerprint=request.settings_fingerprint,
        ),
        label="narration settings snapshot",
    )
    if (
        snapshot.novel_id != request.novel_id
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
        raise InvalidNarrationState("narration settings snapshot has an unknown shape")
    resolved = payload["resolved_settings"]
    if type(resolved) is not dict or set(resolved) != {
        "script_review_policy",
        "analysis_mode",
        "narrator_profile_id",
        "narrator_version_id",
        "settings",
        "scope_overrides",
    }:
        raise InvalidNarrationState("resolved narration settings have an unknown shape")
    if resolved["analysis_mode"] != wire.AnalysisMode.LOCAL_RULES_ONLY.value:
        raise InvalidNarrationState(
            "cloud-assisted script analysis remains HOLD at T3-GATE"
        )
    if resolved["scope_overrides"]:
        raise InvalidNarrationState(
            "volume/chapter narration overrides remain HOLD at T3-GATE"
        )
    stored = resolved["settings"]
    if type(stored) is not dict:
        raise InvalidNarrationState("narration settings payload must be an object")
    settings_payload = dict(stored)
    playback = settings_payload.get("playback")
    if type(playback) is not dict or set(playback) != {"playback_rate", "volume"}:
        raise InvalidNarrationState("narration playback snapshot is malformed")
    try:
        settings_payload["playback"] = {
            "playback_rate": float(playback["playback_rate"]),
            "volume": float(playback["volume"]),
        }
    except (TypeError, ValueError) as error:
        raise InvalidNarrationState(
            "narration playback snapshot is malformed"
        ) from error
    narrator_profile_id = resolved["narrator_profile_id"]
    narrator_version_id = resolved["narrator_version_id"]
    if (narrator_profile_id is None) != (narrator_version_id is None):
        raise InvalidNarrationState("narrator snapshot identity is incomplete")
    settings_payload.update(
        {
            "narrator": (
                None
                if narrator_profile_id is None
                else {
                    "profile_id": narrator_profile_id,
                    "version_id": narrator_version_id,
                }
            ),
            "script_review_policy": resolved["script_review_policy"],
            "analysis_mode": resolved["analysis_mode"],
        }
    )
    try:
        values = wire.NarrationSettingsValues.model_validate(settings_payload)
    except ValidationError as error:
        raise InvalidNarrationState(
            "narration settings snapshot violates the frozen wire contract"
        ) from error
    if values.script_review_policy.value != request.effective_policy:
        raise StaleNarrationInput("request review policy differs from settings snapshot")
    if (
        not values.text_rules.read_chapter_title
        or values.text_rules.read_author_notes
        or values.text_rules.read_section_breaks
        or values.text_rules.first_person_mode is not wire.FirstPersonVoiceMode.NARRATOR
        or values.text_rules.first_person_character_id is not None
        or values.text_rules.inner_monologue_mode
        is not wire.InnerMonologueVoiceMode.CHARACTER
        or values.casting.unknown_speaker_action
        is not wire.UnknownSpeakerAction.BLOCK
    ):
        raise InvalidNarrationState(
            "configured advanced narration text rules remain HOLD at T3-GATE"
        )
    return values


def _require_analysis_context(
    store: NarrationStore,
    command: AnalyzeNarrationScript,
) -> _AnalysisContext:
    if type(command) is not AnalyzeNarrationScript:
        raise NarrationServiceError("command must be AnalyzeNarrationScript")
    require_sha256(command.content_hash, field="content_hash")
    require_nonempty(command.idempotency_key, field="idempotency_key")
    request = require_row(
        store.get(NarrationRequest, command.request_id, for_update=True),
        label="narration request",
    )
    if (
        request.owner_id != LOCAL_OWNER_ID
        or request.workspace_id != LOCAL_WORKSPACE_ID
    ):
        raise NarrationScopeMismatch("narration request is outside fixed local scope")
    require_local_novel(store, request.novel_id)
    document = require_row(
        store.get(Document, command.document_id, for_update=True),
        label="document",
    )
    require_same_novel(document.novel_id, request.novel_id, label="document")
    revision = require_row(
        store.get(DocumentRevision, command.revision_id), label="revision"
    )
    if (
        revision.document_id != document.id
        or revision.content_hash != command.content_hash
    ):
        raise StaleNarrationInput("analysis source differs from immutable revision")

    sources = _stored_request_sources(store, request)
    if (
        request.sources_sealed_at is None
        or request.source_count != len(sources)
        or request.source_set_hash != source_set_hash(sources)
    ):
        raise IdempotencyConflict("narration request source manifest changed")
    direct_match = (
        request.document_id == command.document_id
        and request.source_revision_id == command.revision_id
        and request.source_content_hash == command.content_hash
    )
    child_match = any(
        item.document_id == command.document_id
        and item.revision_id == command.revision_id
        and item.content_hash == command.content_hash
        for item in sources
    )
    if not (direct_match or child_match):
        raise NarrationScopeMismatch(
            "narration request does not authorize this immutable source"
        )
    if request.state not in {"created", "analyzing", "analyzed", "review_required"}:
        raise InvalidNarrationState("narration request is not analyzable")
    settings = _snapshot_settings(store, request=request)
    return _AnalysisContext(
        request=request,
        document=document,
        revision=revision,
        settings=settings,
    )


def _voice_snapshot(
    store: NarrationStore,
    *,
    novel_id: UUID,
    profile_id: UUID,
    version_id: UUID,
) -> VoiceVersionSnapshot | None:
    profile = store.get(VoiceProfile, profile_id)
    version = store.get(VoiceProfileVersion, version_id)
    if profile is None or version is None:
        return None
    if (
        profile.owner_id != LOCAL_OWNER_ID
        or profile.workspace_id != LOCAL_WORKSPACE_ID
        or profile.novel_id not in {None, novel_id}
        or version.owner_id != LOCAL_OWNER_ID
        or version.workspace_id != LOCAL_WORKSPACE_ID
        or version.profile_id != profile.id
    ):
        raise NarrationScopeMismatch("voice snapshot is outside fixed local scope")
    rights = store.get(VoiceRightsRecord, version.rights_record_id)
    rights_state = None
    voice_cloning_permitted = False
    activation_evidence_usable = False
    rights_record_id = version.rights_record_id
    if rights is not None:
        if (
            rights.owner_id != LOCAL_OWNER_ID
            or rights.workspace_id != LOCAL_WORKSPACE_ID
            or rights.novel_id not in {None, novel_id}
        ):
            raise NarrationScopeMismatch("voice rights are outside fixed local scope")
        rights_state = _rights_state(store, rights, at=utc_now())
        voice_cloning_permitted = bool(rights.voice_cloning)
        activation_evidence_usable = voice_activation_evidence_is_usable(
            version,
            rights,
        )
    try:
        return VoiceVersionSnapshot(
            profile_id=profile.id,
            version_id=version.id,
            version_number=version.version_number,
            fingerprint=version.fingerprint,
            profile_novel_id=profile.novel_id,
            profile_status=wire.VoiceProfileStatus(profile.status),
            source_type=wire.VoiceSourceType(version.source_type),
            version_state=wire.VoiceVersionState(version.state),
            quality_state=wire.VoiceQualityState(version.quality_state),
            activation_evidence_usable=activation_evidence_usable,
            rights_record_id=rights_record_id,
            rights_state=rights_state,
            voice_cloning_permitted=voice_cloning_permitted,
        )
    except ValueError as error:
        raise InvalidNarrationState("voice snapshot contains an unknown state") from error


def _casting_inventory(
    store: NarrationStore,
    *,
    novel_id: UUID,
    settings: wire.NarrationSettingsValues,
) -> CastingInventory:
    narrator_selections: tuple[NarratorSelectionSnapshot, ...] = ()
    if settings.narrator is not None:
        narrator_selections = (
            NarratorSelectionSnapshot(
                novel_id=novel_id,
                scope_kind=CastingScopeKind.NOVEL,
                scope_id=novel_id,
                profile_id=settings.narrator.profile_id,
                version_id=settings.narrator.version_id,
                voice=_voice_snapshot(
                    store,
                    novel_id=novel_id,
                    profile_id=settings.narrator.profile_id,
                    version_id=settings.narrator.version_id,
                ),
            ),
        )
    bindings: list[CharacterBindingSnapshot] = []
    for row in store.find_all(
        CharacterVoiceBinding,
        novel_id=novel_id,
        order_by=("character_id",),
    ):
        if row.binding_policy not in {"dedicated", "inherited"}:
            continue
        if row.profile_id is None or row.voice_version_id is None:
            raise InvalidNarrationState("character voice binding is incomplete")
        bindings.append(
            CharacterBindingSnapshot(
                novel_id=novel_id,
                binding_id=row.id,
                character_id=row.character_id,
                policy=wire.CharacterVoiceBindingPolicy(row.binding_policy),
                profile_id=row.profile_id,
                version_id=row.voice_version_id,
                voice=_voice_snapshot(
                    store,
                    novel_id=novel_id,
                    profile_id=row.profile_id,
                    version_id=row.voice_version_id,
                ),
            )
        )
    return CastingInventory(
        narrator_selections=narrator_selections,
        character_bindings=tuple(bindings),
    )


def _alias_index(
    store: NarrationStore,
    *,
    novel_id: UUID,
):
    characters = store.find_all(
        NovelCharacter,
        novel_id=novel_id,
        order_by=("position",),
    )
    active = tuple(row for row in characters if row.lifecycle_state == "active")
    allowed_ids = frozenset(row.id for row in active)
    records: list[CharacterAliasRecord] = []
    seen: set[tuple[UUID, str, AliasSource, bool]] = set()

    def append_record(record: CharacterAliasRecord) -> None:
        key = (record.character_id, record.alias, record.source, record.active)
        if key not in seen:
            seen.add(key)
            records.append(record)

    for character in active:
        if 0 < len(character.name) <= 80:
            append_record(
                CharacterAliasRecord(
                    character_id=character.id,
                    alias=character.name,
                    source=AliasSource.CANONICAL_NAME,
                )
            )
    for row in store.find_all(
        CharacterAlias,
        novel_id=novel_id,
        order_by=("normalized_alias", "character_id"),
    ):
        if row.character_id not in allowed_ids or not (0 < len(row.alias) <= 80):
            continue
        try:
            source = AliasSource(row.source)
        except ValueError as error:
            raise InvalidNarrationState("character alias source is unknown") from error
        if row.normalized_alias != normalize_character_alias(row.alias):
            raise StaleNarrationInput("character alias normalization changed")
        append_record(
            CharacterAliasRecord(
                character_id=row.character_id,
                alias=row.alias,
                source=source,
                active=row.lifecycle_state in {"active", "conflicted"},
            )
        )
    return build_character_alias_index(records, allowed_character_ids=allowed_ids)


def _canonical_issues(
    issues: list[ScriptIssueContract],
) -> tuple[ScriptIssueContract, ...]:
    by_key: dict[tuple[object, ...], ScriptIssueContract] = {}
    for issue in issues:
        key = (issue.code, issue.segment_id, issue.evidence_digest)
        previous = by_key.get(key)
        if previous is not None and previous != issue:
            raise InvalidNarrationState(
                "duplicate review issue key contains conflicting evidence"
            )
        by_key[key] = issue
    return tuple(
        sorted(
            by_key.values(),
            key=lambda issue: (
                issue.code,
                str(issue.segment_id) if issue.segment_id else "",
                issue.evidence_digest or "",
            ),
        )
    )


def _materialize_contract(
    store: NarrationStore,
    *,
    context: _AnalysisContext,
    allocation: object,
) -> NarrationScriptContract:
    segmentation = segment_source(
        script_version_id=allocation.script_version_id,
        source_text=context.revision.content_markdown,
        source_format=SourceFormat.MARKDOWN,
    )
    if segmentation.source_content_hash != context.revision.content_hash:
        raise StaleNarrationInput("revision content differs from its content hash")
    if not segmentation.segments:
        raise InvalidNarrationState("empty source cannot materialize a narration script")
    scenes = build_scene_contracts(
        script_version_id=allocation.script_version_id,
        source_text=context.revision.content_markdown,
        source_segment_ranges_utf16=tuple(
            segment.source_range_utf16 for segment in segmentation.segments
        ),
    )
    scene_ids = scene_ids_for_source_ranges(
        scenes=scenes,
        source_ranges_utf16=tuple(
            segment.source_range_utf16 for segment in segmentation.segments
        ),
    )
    aliases = _alias_index(store, novel_id=context.request.novel_id)
    inventory = _casting_inventory(
        store,
        novel_id=context.request.novel_id,
        settings=context.settings,
    )
    scene_characters: dict[UUID, set[UUID]] = {
        scene.scene_id: set() for scene in scenes
    }
    previous_speaker = None
    previous_paragraph: int | None = None
    used_voice_ids: dict[UUID, set[UUID]] = {
        scene.scene_id: set() for scene in scenes
    }
    used_slot_ids: dict[UUID, set[UUID]] = {
        scene.scene_id: set() for scene in scenes
    }
    segments: list[SegmentContract] = []
    issues: list[ScriptIssueContract] = []
    materialized = segmentation.segments

    for index, source_segment in enumerate(materialized):
        scene_id = scene_ids[index]
        same_scene_as_previous = bool(
            index and scene_ids[index - 1] == scene_id
        )
        same_paragraph_as_previous = bool(
            same_scene_as_previous
            and materialized[index - 1].paragraph_ordinal
            == source_segment.paragraph_ordinal
        )
        before = (
            materialized[index - 1].source_text[-1000:]
            if same_paragraph_as_previous
            else ""
        )
        same_paragraph_as_next = bool(
            index + 1 < len(materialized)
            and scene_ids[index + 1] == scene_id
            and materialized[index + 1].paragraph_ordinal
            == source_segment.paragraph_ordinal
        )
        after = (
            materialized[index + 1].source_text[:1000]
            if same_paragraph_as_next
            else ""
        )
        if not same_scene_as_previous:
            previous_speaker = None
            previous_paragraph = None
        same_paragraph = (
            previous_paragraph is not None
            and previous_paragraph == source_segment.paragraph_ordinal
        )
        speaker = attribute_speaker_local(
            SpeakerRuleContext(
                segment_kind=source_segment.segment_kind,
                source_text=source_segment.source_text,
                cue_before=before,
                cue_after=after,
                scene_character_ids=frozenset(scene_characters[scene_id]),
                previous_speaker=previous_speaker,
                same_paragraph_continuation=same_paragraph,
            ),
            aliases=aliases,
        )
        if speaker.speaker.character_id is not None:
            scene_characters[scene_id].add(speaker.speaker.character_id)
        casting = resolve_casting(
            CastingRequest(
                novel_id=context.request.novel_id,
                segment_id=source_segment.segment_id,
                source_local_hash=source_segment.local_hash,
                segment_kind=source_segment.segment_kind,
                speaker=speaker.speaker,
                chapter_id=context.document.id,
                volume_id=context.document.volume_id,
                scene_id=scene_id,
                attributes=CastingAttributes(),
                same_scene_voice_deduplication=(
                    context.settings.casting.same_scene_voice_deduplication
                ),
                used_voice_version_ids=frozenset(used_voice_ids[scene_id]),
                used_slot_ids=frozenset(used_slot_ids[scene_id]),
            ),
            inventory,
        )
        if casting.resolved_voice is not None:
            used_voice_ids[scene_id].add(casting.resolved_voice.version_id)
            if casting.resolved_voice.slot_id is not None:
                used_slot_ids[scene_id].add(casting.resolved_voice.slot_id)
        expression = classify_expression(
            ExpressionContext(
                segment_kind=source_segment.segment_kind,
                source_text=source_segment.source_text,
                spoken_text=source_segment.spoken_text,
                cue_before=before,
                cue_after=after,
            )
        )
        next_segment = materialized[index + 1] if index + 1 < len(materialized) else None
        if next_segment is None:
            pause_after_ms = 0
        elif next_segment.paragraph_ordinal == source_segment.paragraph_ordinal:
            pause_after_ms = context.settings.timing.sentence_gap_ms
        elif scene_ids[index + 1] != scene_id:
            pause_after_ms = context.settings.timing.section_gap_ms
        else:
            pause_after_ms = context.settings.timing.paragraph_gap_ms
        segments.append(
            SegmentContract(
                segment_id=source_segment.segment_id,
                ordinal=source_segment.ordinal,
                scene_id=scene_id,
                segment_kind=source_segment.segment_kind,
                source_block_kind=source_segment.source_block_kind,
                paragraph_ordinal=source_segment.paragraph_ordinal,
                segment_ordinal_in_block=source_segment.segment_ordinal_in_block,
                source_block_key=source_segment.source_block_key,
                source_block_hash=source_segment.source_block_hash,
                source_range_utf16=source_segment.source_range_utf16,
                source_text=source_segment.source_text,
                spoken_text=source_segment.spoken_text,
                local_hash=source_segment.local_hash,
                anchor_before_hash=source_segment.anchor_before_hash,
                anchor_after_hash=source_segment.anchor_after_hash,
                inheritance_anchor_before_hash=None,
                inheritance_anchor_after_hash=None,
                speaker=speaker.speaker,
                casting=casting.decision,
                confidence=speaker.confidence,
                emotion=expression.emotion,
                emotion_confidence=expression.emotion_confidence,
                delivery=expression.delivery,
                attribution=speaker.attribution,
                pause_before_ms=0,
                pause_after_ms=pause_after_ms,
                manual_override=False,
            )
        )
        issues.extend(speaker.to_script_issues(segment_id=source_segment.segment_id))
        issues.extend(casting.issues)
        previous_speaker = speaker.speaker
        previous_paragraph = source_segment.paragraph_ordinal

    canonical_issues = _canonical_issues(issues)
    warning_count = sum(
        issue.severity is ReviewIssueSeverity.WARNING for issue in canonical_issues
    )
    blocker_count = sum(
        issue.severity is ReviewIssueSeverity.BLOCKER for issue in canonical_issues
    )
    policy = ScriptReviewPolicy(context.request.effective_policy)
    base = {
        "script_id": allocation.script_id,
        "script_version_id": allocation.script_version_id,
        "novel_id": context.request.novel_id,
        "document_id": context.document.id,
        "revision_id": context.revision.id,
        "source_content_hash": context.revision.content_hash,
        "source_length_utf16": segmentation.source_length_utf16,
        "version_number": allocation.version_number,
        "parent_version_id": allocation.parent_version_id,
        "state": initial_materialized_state(policy, blocker_count=blocker_count),
        "effective_policy": policy,
        "analyzer_fingerprint": SCRIPT_ANALYZER_FINGERPRINT,
        "rules_fingerprint": SCRIPT_RULES_FINGERPRINT,
        "settings_fingerprint": context.request.settings_fingerprint,
        "requested_model_fingerprint": None,
        "actual_model_fingerprint": None,
        "anonymous_speakers": (),
        "scenes": scenes,
        "segments": tuple(segments),
        "issues": canonical_issues,
        "warning_count": warning_count,
        "blocker_count": blocker_count,
        "approval": None,
        "schema_version": NARRATION_SCRIPT_CONTRACT_VERSION,
        "taxonomy_version": NARRATION_REVIEW_TAXONOMY_VERSION,
    }
    immutable_hash = canonical_sha256(
        script_immutable_payload(SimpleNamespace(**base))
    )
    return NarrationScriptContract(**base, immutable_hash=immutable_hash)


def _analysis_version_key(command: AnalyzeNarrationScript) -> str:
    return "analysis-" + canonical_sha256(
        {
            "request_id": str(command.request_id),
            "idempotency_key": command.idempotency_key,
        }
    )


def _finish_request(
    store: NarrationStore,
    *,
    request: NarrationRequest,
    contract: NarrationScriptContract,
) -> None:
    if request.state != "analyzing":
        return
    new_state = (
        "review_required"
        if contract.state.value == "review_required"
        else "analyzed"
    )
    advance_request_state(
        store,
        request.id,
        expected_version=request.version,
        new_state=new_state,
        novel_id=request.novel_id,
        actor="narration-script-analyzer",
    )


def _bind_request_review_pointer(
    store: NarrationStore,
    *,
    request: NarrationRequest,
    contract: NarrationScriptContract,
) -> None:
    """Bind the server-owned candidate without guessing for completed legacy rows."""

    if request.document_id != contract.document_id:
        raise NarrationScopeMismatch(
            "narration request review candidate belongs to another document"
        )
    if (
        request.review_script_id is None
        and request.current_review_version_id is None
    ):
        if request.state not in {"created", "analyzing"}:
            raise InvalidNarrationState(
                "completed legacy narration request has no review candidate pointer"
            )
        request.review_script_id = contract.script_id
        request.current_review_version_id = contract.script_version_id
        request.version += 1
        request.updated_at = utc_now()
        store.flush()
        return
    if (
        request.review_script_id != contract.script_id
        or request.current_review_version_id != contract.script_version_id
    ):
        raise IdempotencyConflict(
            "narration request already points at another review candidate"
        )


def analyze_narration_script(
    store: NarrationStore,
    command: AnalyzeNarrationScript,
) -> NarrationScriptContract:
    """Analyze, persist, reload, and (only when legal) auto-freeze one script.

    The caller owns one authoritative transaction.  No Edition or media row is
    created here.  HTTP manual corrections/approval/reanalysis remain HOLD in
    the adapter until their action-key persistence contract exists.
    """

    context = _require_analysis_context(store, command)
    if context.request.state == "created":
        context = _AnalysisContext(
            request=advance_request_state(
                store,
                context.request.id,
                expected_version=context.request.version,
                new_state="analyzing",
                novel_id=context.request.novel_id,
                actor="narration-script-analyzer",
            ),
            document=context.document,
            revision=context.revision,
            settings=context.settings,
        )
    elif context.request.state not in {"analyzing", "analyzed", "review_required"}:
        raise InvalidNarrationState("narration request is not analyzable")

    allocation = reserve_script_identity(
        store,
        ReserveScriptIdentity(
            novel_id=context.request.novel_id,
            document_id=context.document.id,
            revision_id=context.revision.id,
            content_hash=context.revision.content_hash,
            idempotency_key=_analysis_version_key(command),
        ),
    )
    if allocation.existing:
        if (
            context.request.review_script_id == allocation.script_id
            and context.request.current_review_version_id is not None
        ):
            contract = load_script_contract(
                store,
                context.request.current_review_version_id,
            )
        else:
            contract = load_script_contract(store, allocation.script_version_id)
        _bind_request_review_pointer(
            store,
            request=context.request,
            contract=contract,
        )
        _finish_request(store, request=context.request, contract=contract)
        return contract
    if context.request.state in {"analyzed", "review_required"}:
        raise InvalidNarrationState(
            "a completed narration request may only replay its original analysis"
        )

    contract = _materialize_contract(
        store,
        context=context,
        allocation=allocation,
    )
    persisted = persist_script_contract(store, allocation, contract)
    if (
        context.request.intent != "analyze_only"
        and contract.state.value == "analyzed"
        and contract.blocker_count == 0
        and contract.effective_policy is ScriptReviewPolicy.BLOCKERS_ONLY
    ):
        freeze_script_version(
            store,
            persisted.id,
            request_id=context.request.id,
            actor_type="service",
            actor_id="narration-script-analyzer",
        )
        contract = load_script_contract(store, persisted.id)
    _bind_request_review_pointer(
        store,
        request=context.request,
        contract=contract,
    )
    _finish_request(store, request=context.request, contract=contract)
    return contract


__all__ = [
    "SCRIPT_ANALYZER_FINGERPRINT",
    "SCRIPT_ANALYZER_VERSION",
    "SCRIPT_RULES_FINGERPRINT",
    "AnalyzeNarrationScript",
    "analyze_narration_script",
]
