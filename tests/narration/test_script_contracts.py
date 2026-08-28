from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from backend.narration.contracts import (
    BLOCKER_CODES,
    NARRATION_REVIEW_TAXONOMY_VERSION,
    WARNING_CODES,
    WORKFLOW_FAILURE_CODES,
    ConfidenceLevel,
    ReviewIssue,
    ReviewIssueSeverity,
    UnknownTaxonomyCodeError,
)
from backend.narration.fingerprints import canonical_json_bytes
from backend.narration import script_versions as persisted_scripts
from backend.narration.script_versions import ScriptSceneInput, ScriptSegmentInput
from backend.narration.script_contracts import (
    ANONYMOUS_SPEAKER_STABLE_KEY_VERSION,
    NARRATION_CASTING_DECISION_VERSION,
    NARRATION_SCRIPT_CONTRACT_VERSION,
    NARRATION_SEGMENT_EVIDENCE_VERSION,
    OVERRIDE_PROVENANCE_VERSION,
    SOURCE_RANGE_SEMANTICS,
    SCRIPT_STATE_TRANSITIONS,
    UTF16_OFFSET_UNIT,
    AnonymousScopeKind,
    AnonymousSpeakerIdentity,
    ApprovalActorType,
    AttributionEvidence,
    AttributionOrigin,
    CastingDecision,
    CastingDecisionOrigin,
    CastingRuleAuthorityRecord,
    CastingTargetKind,
    CastingTargetRef,
    CloudAuthorityRecord,
    Delivery,
    Emotion,
    NarrationScriptContract,
    OverrideKind,
    OverrideProvenance,
    SceneBoundarySource,
    SceneContract,
    ScriptApproval,
    ScriptApprovalKind,
    ScriptAuthorityContext,
    ScriptContractError,
    ScriptIssueContract,
    ScriptReviewPolicy,
    ScriptVersionState,
    SegmentContract,
    SegmentKind,
    SourceBlockKind,
    SpeakerKind,
    SpeakerRef,
    Utf16Range,
    derive_anonymous_speaker_id,
    derive_anonymous_stable_key,
    derive_group_key,
    derive_scene_id,
    derive_segment_id,
    derive_source_block_key,
    ensure_script_transition,
    initial_materialized_state,
    script_contract_from_dict as _script_contract_from_dict,
    script_contract_to_dict,
    script_immutable_hash,
    script_immutable_payload,
    speaker_target_hash,
    text_sha256,
    utf16_length,
    utf16_slice,
    validate_source_mapping,
    validate_authorized_references,
)

FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "narration"
    / "script-contract-v1.json"
)

NOVEL_ID = UUID("11111111-1111-4111-8111-111111111111")
DOCUMENT_ID = UUID("22222222-2222-4222-8222-222222222222")
REVISION_ID = UUID("33333333-3333-4333-8333-333333333333")
SCRIPT_ID = UUID("44444444-4444-4444-8444-444444444444")
SCRIPT_VERSION_ID = UUID("55555555-5555-4555-8555-555555555555")
CHARACTER_ID = UUID("66666666-6666-4666-8666-666666666666")
PROFILE_ID = UUID("77777777-7777-4777-8777-777777777777")
BINDING_ID = UUID("88888888-8888-4888-8888-888888888888")
POOL_ID = UUID("99999999-9999-4999-8999-999999999999")
SLOT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _example_payload() -> dict[str, object]:
    return copy.deepcopy(_fixture()["examples"][0])


def _authority(
    script: NarrationScriptContract | None = None,
    *,
    manual_review_parent_ids: frozenset[UUID] = frozenset(),
    verified_historical_anonymous_ids: frozenset[UUID] = frozenset(),
    casting_targets: frozenset[CastingTargetRef] | None = None,
    trust_cloud: bool = True,
    trust_overrides: bool = True,
) -> ScriptAuthorityContext:
    """Build server-owned test authority; production must load this from storage."""

    if script is None:
        return ScriptAuthorityContext(
            novel_id=NOVEL_ID,
            document_id=DOCUMENT_ID,
            revision_id=REVISION_ID,
            script_id=SCRIPT_ID,
            script_version_id=SCRIPT_VERSION_ID,
            version_number=1,
            state=ScriptVersionState.REVIEW_REQUIRED,
            effective_policy=ScriptReviewPolicy.BLOCKERS_ONLY,
            analyzer_fingerprint="a" * 64,
            rules_fingerprint="b" * 64,
            settings_fingerprint="c" * 64,
            requested_model_fingerprint=None,
            actual_model_fingerprint=None,
            approval=None,
            character_ids=frozenset({CHARACTER_ID}),
            casting_targets=frozenset(
                {
                    CastingTargetRef(
                        CastingTargetKind.PROFILE,
                        profile_id=PROFILE_ID,
                    )
                }
            ),
        )

    parent_ids = (
        frozenset({script.parent_version_id})
        if script.parent_version_id is not None
        else frozenset()
    )
    character_ids = {
        character_id
        for segment in script.segments
        for character_id in (
            segment.speaker.character_id,
            *segment.attribution.candidate_character_ids,
            *(target.character_id for target in segment.casting.candidate_targets),
        )
        if character_id is not None
    }
    group_keys = {
        segment.speaker.group_key
        for segment in script.segments
        if segment.speaker.group_key is not None
    }
    derived_casting_targets = frozenset(
        target
        for segment in script.segments
        for target in segment.casting.candidate_targets
    )
    casting_rule_records = frozenset(
        CastingRuleAuthorityRecord(
            decision=segment.casting,
            segment_id=segment.segment_id,
            source_local_hash=segment.local_hash,
            speaker_target_hash=speaker_target_hash(
                segment.speaker,
                segment.casting,
            ),
        )
        for segment in script.segments
        if segment.casting.origin is CastingDecisionOrigin.CASTING_RULE
    )
    cloud_records = frozenset(
        CloudAuthorityRecord(
            attribution=segment.attribution,
            model_fingerprint=script.actual_model_fingerprint,
            segment_id=segment.segment_id,
            source_local_hash=segment.local_hash,
            speaker_target_hash=speaker_target_hash(
                segment.speaker,
                segment.casting,
            ),
        )
        for segment in script.segments
        if trust_cloud
        and segment.attribution.origin is AttributionOrigin.CLOUD_ASSISTED
        and script.actual_model_fingerprint is not None
    )
    override_provenances = frozenset(
        segment.attribution.override_provenance
        for segment in script.segments
        if trust_overrides
        and segment.attribution.override_provenance is not None
    )
    return ScriptAuthorityContext(
        novel_id=script.novel_id,
        document_id=script.document_id,
        revision_id=script.revision_id,
        script_id=script.script_id,
        script_version_id=script.script_version_id,
        version_number=script.version_number,
        state=script.state,
        effective_policy=script.effective_policy,
        analyzer_fingerprint=script.analyzer_fingerprint,
        rules_fingerprint=script.rules_fingerprint,
        settings_fingerprint=script.settings_fingerprint,
        requested_model_fingerprint=script.requested_model_fingerprint,
        actual_model_fingerprint=script.actual_model_fingerprint,
        approval=script.approval,
        parent_version_ids=parent_ids,
        manual_review_parent_ids=manual_review_parent_ids,
        non_review_parent_ids=parent_ids - manual_review_parent_ids,
        character_ids=frozenset(character_ids),
        anonymous_speakers=frozenset(script.anonymous_speakers),
        verified_historical_anonymous_ids=(
            verified_historical_anonymous_ids
        ),
        group_keys=frozenset(group_keys),
        casting_targets=(
            derived_casting_targets
            if casting_targets is None
            else casting_targets
        ),
        casting_rule_records=casting_rule_records,
        cloud_records=cloud_records,
        override_provenances=override_provenances,
    )


def script_contract_from_dict(value: object) -> NarrationScriptContract:
    source_text = _fixture()["x-example-source-text"]
    assert type(source_text) is str
    return _script_contract_from_dict(
        value,
        authority=_authority(),
        source_text=source_text,
    )


def _assert_json_schema(
    value: object,
    schema: Mapping[str, object],
    *,
    root: Mapping[str, object],
) -> None:
    reference = schema.get("$ref")
    if reference is not None:
        assert type(reference) is str and reference.startswith("#/$defs/")
        target = root["$defs"][reference.removeprefix("#/$defs/")]
        _assert_json_schema(value, target, root=root)
        return
    alternatives = schema.get("anyOf")
    if alternatives is not None:
        errors: list[AssertionError] = []
        for candidate in alternatives:
            try:
                _assert_json_schema(value, candidate, root=root)
                return
            except AssertionError as error:
                errors.append(error)
        raise AssertionError(f"value matches no anyOf branch: {errors}")
    if "const" in schema:
        assert value == schema["const"]
    if "enum" in schema:
        assert value in schema["enum"]
    expected_type = schema.get("type")
    if expected_type == "object":
        assert type(value) is dict
        required = set(schema.get("required", ()))
        properties = schema.get("properties", {})
        assert required.issubset(value)
        if schema.get("additionalProperties") is False:
            assert set(value).issubset(properties)
        for key, item in value.items():
            if key in properties:
                _assert_json_schema(item, properties[key], root=root)
    elif expected_type == "array":
        assert type(value) is list
        if "maxItems" in schema:
            assert len(value) <= schema["maxItems"]
        if schema.get("uniqueItems") is True:
            canonical = [canonical_json_bytes(item) for item in value]
            assert len(canonical) == len(set(canonical))
        item_schema = schema.get("items")
        if item_schema is not None:
            for item in value:
                _assert_json_schema(item, item_schema, root=root)
    elif expected_type == "string":
        assert type(value) is str
        if "minLength" in schema:
            assert len(value) >= schema["minLength"]
        if "maxLength" in schema:
            assert len(value) <= schema["maxLength"]
        if "pattern" in schema:
            assert re.fullmatch(schema["pattern"], value) is not None
    elif expected_type == "integer":
        assert type(value) is int
        if "minimum" in schema:
            assert value >= schema["minimum"]
    elif expected_type == "boolean":
        assert type(value) is bool
    elif expected_type == "null":
        assert value is None


def _immutable_hash_for(stub: object) -> str:
    return hashlib.sha256(
        canonical_json_bytes(script_immutable_payload(stub))  # type: ignore[arg-type]
    ).hexdigest()


def _rebuild_contract(
    script: NarrationScriptContract, **changes: object
) -> NarrationScriptContract:
    payload = {
        item.name: getattr(script, item.name)
        for item in fields(NarrationScriptContract)
        if item.name != "immutable_hash"
    }
    payload.update(changes)
    return NarrationScriptContract(
        **payload,  # type: ignore[arg-type]
        immutable_hash=_immutable_hash_for(SimpleNamespace(**payload)),
    )


def _make_contract(
    *,
    state: ScriptVersionState = ScriptVersionState.ANALYZED,
    policy: ScriptReviewPolicy = ScriptReviewPolicy.BLOCKERS_ONLY,
    speaker: SpeakerRef | None = None,
    casting: CastingDecision | None = None,
    confidence: ConfidenceLevel = ConfidenceLevel.HIGH,
    attribution: AttributionEvidence | None = None,
    anonymous_speakers: tuple[AnonymousSpeakerIdentity, ...] = (),
    issues: tuple[ScriptIssueContract, ...] = (),
    approval: ScriptApproval | None = None,
    requested_model_fingerprint: str | None = None,
    actual_model_fingerprint: str | None = None,
    parent_version_id: UUID | None = None,
) -> NarrationScriptContract:
    source = "夜🌙。"
    source_range = Utf16Range(0, utf16_length(source))
    source_hash = text_sha256(source)
    scene = SceneContract(
        scene_id=derive_scene_id(
            script_version_id=SCRIPT_VERSION_ID,
            ordinal=0,
            source_range=source_range,
            local_hash=source_hash,
        ),
        ordinal=0,
        source_range_utf16=source_range,
        boundary_source=SceneBoundarySource.DOCUMENT_START,
        local_hash=source_hash,
    )
    block_key = derive_source_block_key(
        script_version_id=SCRIPT_VERSION_ID,
        block_kind=SourceBlockKind.PARAGRAPH,
        paragraph_ordinal=0,
        block_hash=source_hash,
        anchor_before_hash=None,
        anchor_after_hash=None,
    )
    speaker_ref = speaker or SpeakerRef(SpeakerKind.NARRATOR)
    if casting is not None:
        casting_decision = casting
    elif speaker_ref.kind is SpeakerKind.CHARACTER:
        target = CastingTargetRef(
            CastingTargetKind.CHARACTER_BINDING,
            binding_id=BINDING_ID,
            character_id=speaker_ref.character_id,
        )
        casting_decision = CastingDecision(
            candidate_targets=(target,),
            final_target=target,
            origin=CastingDecisionOrigin.CHARACTER_BINDING,
        )
    elif speaker_ref.kind is SpeakerKind.ANONYMOUS:
        target = CastingTargetRef(
            CastingTargetKind.ANONYMOUS_BINDING,
            anonymous_speaker_id=speaker_ref.anonymous_speaker_id,
        )
        casting_decision = CastingDecision(
            candidate_targets=(target,),
            final_target=target,
            origin=CastingDecisionOrigin.ANONYMOUS_BINDING,
        )
    else:
        target = CastingTargetRef(
            CastingTargetKind.PROFILE, profile_id=PROFILE_ID
        )
        casting_decision = CastingDecision(
            candidate_targets=(target,),
            final_target=target,
            origin=CastingDecisionOrigin.NARRATOR_SETTING,
        )
    attribution_evidence = attribution or AttributionEvidence(
        AttributionOrigin.LOCAL_RULE,
        ("narration.paragraph",),
        (
            (speaker_ref.character_id,)
            if speaker_ref.character_id is not None
            else ()
        ),
    )
    segment = SegmentContract(
        segment_id=derive_segment_id(
            script_version_id=SCRIPT_VERSION_ID,
            ordinal=0,
            source_block_key=block_key,
            segment_ordinal_in_block=0,
            local_hash=source_hash,
        ),
        ordinal=0,
        scene_id=scene.scene_id,
        segment_kind=SegmentKind.NARRATION,
        source_block_kind=SourceBlockKind.PARAGRAPH,
        paragraph_ordinal=0,
        segment_ordinal_in_block=0,
        source_block_key=block_key,
        source_block_hash=source_hash,
        source_range_utf16=source_range,
        source_text=source,
        spoken_text=source,
        local_hash=source_hash,
        anchor_before_hash=None,
        anchor_after_hash=None,
        inheritance_anchor_before_hash=None,
        inheritance_anchor_after_hash=None,
        speaker=speaker_ref,
        casting=casting_decision,
        confidence=confidence,
        emotion=Emotion.NEUTRAL,
        emotion_confidence=ConfidenceLevel.HIGH,
        delivery=Delivery.NORMAL,
        attribution=attribution_evidence,
        manual_override=attribution_evidence.origin
        in {
            AttributionOrigin.MANUAL_OVERRIDE,
            AttributionOrigin.INHERITED_OVERRIDE,
        },
    )
    warning_count = sum(
        item.severity is ReviewIssueSeverity.WARNING for item in issues
    )
    blocker_count = sum(
        item.severity is ReviewIssueSeverity.BLOCKER for item in issues
    )
    base = dict(
        script_id=SCRIPT_ID,
        script_version_id=SCRIPT_VERSION_ID,
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
        revision_id=REVISION_ID,
        source_content_hash=source_hash,
        source_length_utf16=utf16_length(source),
        version_number=1,
        parent_version_id=parent_version_id,
        state=state,
        effective_policy=policy,
        analyzer_fingerprint="a" * 64,
        rules_fingerprint="b" * 64,
        settings_fingerprint="c" * 64,
        requested_model_fingerprint=requested_model_fingerprint,
        actual_model_fingerprint=actual_model_fingerprint,
        anonymous_speakers=anonymous_speakers,
        scenes=(scene,),
        segments=(segment,),
        issues=issues,
        warning_count=warning_count,
        blocker_count=blocker_count,
        approval=approval,
        schema_version=NARRATION_SCRIPT_CONTRACT_VERSION,
        taxonomy_version=NARRATION_REVIEW_TAXONOMY_VERSION,
    )
    stub = SimpleNamespace(**base)
    return NarrationScriptContract(
        **base,
        immutable_hash=_immutable_hash_for(stub),
    )


def test_fixture_is_a_versioned_closed_schema_matching_all_frozen_enums() -> None:
    fixture = _fixture()
    assert fixture["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert fixture["additionalProperties"] is False
    properties = fixture["properties"]
    assert properties["schema_version"]["const"] == NARRATION_SCRIPT_CONTRACT_VERSION
    assert (
        properties["taxonomy_version"]["const"]
        == NARRATION_REVIEW_TAXONOMY_VERSION
    )
    assert tuple(properties["state"]["enum"]) == tuple(
        item.value for item in ScriptVersionState
    )
    assert tuple(properties["effective_policy"]["enum"]) == tuple(
        item.value for item in ScriptReviewPolicy
    )
    assert tuple(fixture["$defs"]["segment"]["properties"]["segment_kind"]["enum"]) == tuple(
        item.value for item in SegmentKind
    )
    assert tuple(fixture["$defs"]["speaker"]["properties"]["kind"]["enum"]) == tuple(
        item.value for item in SpeakerKind
    )
    assert tuple(
        fixture["$defs"]["segment"]["properties"]["source_block_kind"]["enum"]
    ) == tuple(item.value for item in SourceBlockKind)
    assert tuple(
        fixture["$defs"]["scene"]["properties"]["boundary_source"]["enum"]
    ) == tuple(item.value for item in SceneBoundarySource)
    assert tuple(
        fixture["$defs"]["anonymous_speaker"]["properties"]["scope_kind"]["enum"]
    ) == tuple(item.value for item in AnonymousScopeKind)
    assert tuple(
        fixture["$defs"]["attribution"]["properties"]["origin"]["enum"]
    ) == tuple(item.value for item in AttributionOrigin)
    assert tuple(
        fixture["$defs"]["casting_target"]["properties"]["kind"]["enum"]
    ) == tuple(item.value for item in CastingTargetKind)
    assert tuple(
        fixture["$defs"]["casting"]["properties"]["origin"]["enum"]
    ) == tuple(item.value for item in CastingDecisionOrigin)
    assert tuple(
        fixture["$defs"]["override_provenance"]["properties"]["kind"]["enum"]
    ) == tuple(item.value for item in OverrideKind)
    assert tuple(
        fixture["$defs"]["segment"]["properties"]["confidence"]["enum"]
    ) == tuple(item.value for item in ConfidenceLevel)
    assert tuple(
        fixture["$defs"]["segment"]["properties"]["emotion"]["enum"]
    ) == tuple(item.value for item in Emotion)
    assert tuple(
        fixture["$defs"]["segment"]["properties"]["delivery"]["enum"]
    ) == tuple(item.value for item in Delivery)
    assert tuple(
        fixture["$defs"]["approval"]["properties"]["kind"]["enum"]
    ) == tuple(item.value for item in ScriptApprovalKind)
    assert tuple(
        fixture["$defs"]["approval"]["properties"]["actor_type"]["enum"]
    ) == tuple(item.value for item in ApprovalActorType)
    assert (
        fixture["$defs"]["casting"]["properties"]["contract_version"]["const"]
        == NARRATION_CASTING_DECISION_VERSION
    )
    assert (
        fixture["$defs"]["override_provenance"]["properties"][
            "contract_version"
        ]["const"]
        == OVERRIDE_PROVENANCE_VERSION
    )
    assert tuple(fixture["$defs"]["issue"]["properties"]["code"]["enum"]) == (
        WARNING_CODES + BLOCKER_CODES
    )
    assert fixture["x-offset-contract"] == {
        "unit": UTF16_OFFSET_UNIT,
        "range_semantics": SOURCE_RANGE_SEMANTICS,
        "surrogate_pair_boundary": "reject",
        "synthetic_source_range": "must_be_null",
        "source_coverage": (
            "source-bound segment ranges and source block spans completely "
            "partition the authoritative revision without gaps, overlap, or "
            "interleaving"
        ),
        "structural_text": (
            "newlines and markup remain in source_text/source ranges but may "
            "be omitted from spoken_text"
        ),
        "grapheme_cluster_boundary": (
            "not part of the offset protocol; segmentation must avoid "
            "user-visible partial graphemes"
        ),
    }


def test_fixture_state_machine_exactly_matches_runtime_contract() -> None:
    expected = {
        state.value: [target.value for target in sorted(targets, key=lambda item: item.value)]
        for state, targets in SCRIPT_STATE_TRANSITIONS.items()
    }
    actual = {
        state: sorted(targets)
        for state, targets in _fixture()["x-state-machine"].items()
    }
    assert actual == expected
    assert _fixture()["x-approval-invariants"]["approved_is_terminal"] is True
    assert _fixture()["x-id-contract"]["authority"] == "server"


def test_fixture_example_round_trips_and_maps_exact_utf16_source() -> None:
    fixture = _fixture()
    script = script_contract_from_dict(fixture["examples"][0])
    assert script_contract_to_dict(script) == fixture["examples"][0]
    validate_source_mapping(fixture["x-example-source-text"], script)
    assert script.state is ScriptVersionState.REVIEW_REQUIRED
    assert script.blocker_count == 3
    assert script.warning_count == 0
    assert script.segments[-1].segment_kind is SegmentKind.SYNTHETIC_PAUSE
    assert script.segments[-1].source_range_utf16 is None
    assert script.immutable_hash == script_immutable_hash(script)


def test_runtime_wire_projection_satisfies_the_frozen_json_schema() -> None:
    fixture = _fixture()
    script = script_contract_from_dict(fixture["examples"][0])
    _assert_json_schema(
        script_contract_to_dict(script),
        fixture,
        root=fixture,
    )


def test_utf16_offsets_cover_astral_combining_and_punctuation_without_splitting() -> None:
    text = "A🌙e\u0301。"
    assert utf16_length(text) == 6
    assert utf16_slice(text, Utf16Range(1, 3)) == "🌙"
    assert utf16_slice(text, Utf16Range(3, 5)) == "e\u0301"
    assert utf16_slice(text, Utf16Range(5, 6)) == "。"
    with pytest.raises(ScriptContractError, match="surrogate pair"):
        utf16_slice(text, Utf16Range(2, 3))
    with pytest.raises(ScriptContractError, match="outside"):
        utf16_slice(text, Utf16Range(6, 7))
    with pytest.raises(ScriptContractError, match="unpaired"):
        utf16_length("\ud800")


def test_source_mapping_rejects_hash_length_and_slice_drift() -> None:
    fixture = _fixture()
    script = script_contract_from_dict(fixture["examples"][0])
    with pytest.raises(ScriptContractError, match="hash differs"):
        validate_source_mapping(fixture["x-example-source-text"].replace("谁", "他"), script)
    with pytest.raises(ScriptContractError, match="length differs"):
        validate_source_mapping(fixture["x-example-source-text"] + "。", script)

    payload = _example_payload()
    payload["segments"][0]["source_text"] = "夜色。"
    with pytest.raises(ScriptContractError, match="local_hash"):
        script_contract_from_dict(payload)

    with pytest.raises(ScriptContractError, match="hash differs"):
        _script_contract_from_dict(
            _example_payload(),
            authority=_authority(),
            source_text="夜🌙。\n“他？”",
        )


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("unexpected",), True, "invalid keys"),
        (("source_length_utf16",), True, "integer"),
        (("script_id",), "44444444-4444-4444-8444-44444444444A", "canonical lowercase"),
        (("schema_version",), "narration-script/2", "unknown narration script"),
        (("state",), "future_state", "unknown value"),
    ],
)
def test_wire_parser_rejects_unknown_fields_coercion_and_future_values(
    path: tuple[str, ...], value: object, message: str
) -> None:
    payload = _example_payload()
    if path == ("unexpected",):
        payload[path[0]] = value
    else:
        payload[path[0]] = value
    with pytest.raises(ScriptContractError, match=message):
        script_contract_from_dict(payload)


def test_nested_unknown_fields_and_noncanonical_uuid_fail_closed() -> None:
    payload = _example_payload()
    payload["segments"][0]["speaker"]["future"] = "not-allowed"
    with pytest.raises(ScriptContractError, match="invalid keys"):
        script_contract_from_dict(payload)

    payload = _example_payload()
    payload["segments"][0]["segment_id"] = payload["segments"][0][
        "segment_id"
    ].upper()
    with pytest.raises(ScriptContractError, match="canonical lowercase"):
        script_contract_from_dict(payload)


def test_version_scoped_source_block_scene_and_segment_ids_are_deterministic() -> None:
    local_hash = text_sha256("一段话")
    block = derive_source_block_key(
        script_version_id=SCRIPT_VERSION_ID,
        block_kind=SourceBlockKind.PARAGRAPH,
        paragraph_ordinal=3,
        block_hash=local_hash,
        anchor_before_hash=None,
        anchor_after_hash="f" * 64,
    )
    assert block == derive_source_block_key(
        script_version_id=SCRIPT_VERSION_ID,
        block_kind=SourceBlockKind.PARAGRAPH,
        paragraph_ordinal=3,
        block_hash=local_hash,
        anchor_before_hash=None,
        anchor_after_hash="f" * 64,
    )
    other_version = uuid4()
    assert block != derive_source_block_key(
        script_version_id=other_version,
        block_kind=SourceBlockKind.PARAGRAPH,
        paragraph_ordinal=3,
        block_hash=local_hash,
        anchor_before_hash=None,
        anchor_after_hash="f" * 64,
    )
    source_range = Utf16Range(0, 3)
    scene_id = derive_scene_id(
        script_version_id=SCRIPT_VERSION_ID,
        ordinal=0,
        source_range=source_range,
        local_hash=local_hash,
    )
    segment_id = derive_segment_id(
        script_version_id=SCRIPT_VERSION_ID,
        ordinal=0,
        source_block_key=block,
        segment_ordinal_in_block=0,
        local_hash=local_hash,
    )
    assert scene_id != segment_id
    assert scene_id != derive_scene_id(
        script_version_id=other_version,
        ordinal=0,
        source_range=source_range,
        local_hash=local_hash,
    )


def test_anonymous_and_group_keys_are_normalized_stable_and_scope_bound() -> None:
    scene_id = uuid4()
    evidence_hash = text_sha256("descriptor evidence")
    left = derive_anonymous_stable_key(
        novel_id=NOVEL_ID,
        scope_kind=AnonymousScopeKind.SCENE,
        scope_id=scene_id,
        label="  Ａlice  ",
        evidence_hash=evidence_hash,
    )
    right = derive_anonymous_stable_key(
        novel_id=NOVEL_ID,
        scope_kind=AnonymousScopeKind.SCENE,
        scope_id=scene_id,
        label="alice",
        evidence_hash=evidence_hash,
    )
    assert left == right
    assert derive_anonymous_speaker_id(novel_id=NOVEL_ID, stable_key=left) == (
        derive_anonymous_speaker_id(novel_id=NOVEL_ID, stable_key=right)
    )
    assert left != derive_anonymous_stable_key(
        novel_id=NOVEL_ID,
        scope_kind=AnonymousScopeKind.SCENE,
        scope_id=uuid4(),
        label="alice",
        evidence_hash=evidence_hash,
    )
    group = derive_group_key(
        novel_id=NOVEL_ID,
        scene_id=scene_id,
        label="围观者",
        evidence_hash=evidence_hash,
    )
    assert group.startswith("grp1_")


@pytest.mark.parametrize(
    "speaker",
    [
        SpeakerRef(SpeakerKind.NARRATOR),
        SpeakerRef(SpeakerKind.CHARACTER, character_id=CHARACTER_ID),
        SpeakerRef(
            SpeakerKind.ANONYMOUS,
            anonymous_speaker_id=UUID("77777777-7777-4777-8777-777777777777"),
        ),
        SpeakerRef(SpeakerKind.GROUP, group_key="grp1_" + "a" * 64),
        SpeakerRef(SpeakerKind.UNKNOWN),
    ],
)
def test_each_speaker_discriminator_accepts_only_its_identity_shape(
    speaker: SpeakerRef,
) -> None:
    assert speaker.kind in SpeakerKind


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": SpeakerKind.NARRATOR, "character_id": CHARACTER_ID},
        {"kind": SpeakerKind.CHARACTER},
        {
            "kind": SpeakerKind.CHARACTER,
            "character_id": CHARACTER_ID,
            "anonymous_speaker_id": uuid4(),
        },
        {"kind": SpeakerKind.ANONYMOUS},
        {"kind": SpeakerKind.GROUP, "group_key": "free-form"},
        {"kind": SpeakerKind.UNKNOWN, "group_key": "grp1_" + "a" * 64},
    ],
)
def test_speaker_identity_shape_rejects_ambiguous_or_model_invented_ids(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(ScriptContractError):
        SpeakerRef(**kwargs)  # type: ignore[arg-type]


def test_attribution_origin_freezes_cloud_and_manual_evidence_shape() -> None:
    with pytest.raises(ScriptContractError, match="requires rule_codes"):
        AttributionEvidence(AttributionOrigin.LOCAL_RULE)
    with pytest.raises(ScriptContractError, match="requires consent"):
        AttributionEvidence(AttributionOrigin.CLOUD_ASSISTED)
    cloud = AttributionEvidence(
        AttributionOrigin.CLOUD_ASSISTED,
        consent_id=uuid4(),
        model_run_id=uuid4(),
        input_digest_key_id="tts-test-key-v1",
        input_digest="a" * 64,
        output_digest="b" * 64,
    )
    cloud_warning = (
        ScriptIssueContract(
            "W_CLOUD_ASSISTED_USED",
            ReviewIssueSeverity.WARNING,
            segment_id=_make_contract().segments[0].segment_id,
        ),
    )
    with pytest.raises(ScriptContractError, match="model fingerprints"):
        _make_contract(attribution=cloud, issues=cloud_warning)
    assert _make_contract(
        attribution=cloud,
        issues=cloud_warning,
        requested_model_fingerprint="d" * 64,
        actual_model_fingerprint="d" * 64,
    ).segments[0].attribution is cloud
    with pytest.raises(ScriptContractError, match="server warning"):
        _make_contract(
            attribution=cloud,
            requested_model_fingerprint="d" * 64,
            actual_model_fingerprint="d" * 64,
        )
    with pytest.raises(ScriptContractError, match="must match"):
        _make_contract(
            attribution=cloud,
            issues=cloud_warning,
            requested_model_fingerprint="d" * 64,
            actual_model_fingerprint="e" * 64,
        )
    with pytest.raises(ScriptContractError, match="both present or absent"):
        _make_contract(requested_model_fingerprint="d" * 64)


def test_cloud_attribution_requires_exact_server_run_and_model_authority() -> None:
    cloud = AttributionEvidence(
        AttributionOrigin.CLOUD_ASSISTED,
        consent_id=uuid4(),
        model_run_id=uuid4(),
        input_digest_key_id="tts-test-key-v1",
        input_digest="a" * 64,
        output_digest="b" * 64,
    )
    cloud_warning = (
        ScriptIssueContract(
            "W_CLOUD_ASSISTED_USED",
            ReviewIssueSeverity.WARNING,
            segment_id=_make_contract().segments[0].segment_id,
        ),
    )
    script = _make_contract(
        attribution=cloud,
        issues=cloud_warning,
        requested_model_fingerprint="d" * 64,
        actual_model_fingerprint="d" * 64,
    )
    validate_authorized_references(script, _authority(script))
    with pytest.raises(ScriptContractError, match="cloud attribution.*authority"):
        validate_authorized_references(
            script,
            _authority(script, trust_cloud=False),
        )

    wrong_run = replace(cloud, model_run_id=uuid4())
    wrong_record = CloudAuthorityRecord(
        attribution=wrong_run,
        model_fingerprint="d" * 64,
        segment_id=script.segments[0].segment_id,
        source_local_hash=script.segments[0].local_hash,
        speaker_target_hash=speaker_target_hash(
            script.segments[0].speaker,
            script.segments[0].casting,
        ),
    )
    with pytest.raises(ScriptContractError, match="cloud attribution.*authority"):
        validate_authorized_references(
            script,
            replace(
                _authority(script),
                cloud_records=frozenset({wrong_record}),
            ),
        )
    with pytest.raises(ScriptContractError, match="actual model fingerprint"):
        replace(
            _authority(script),
            cloud_records=frozenset(
                {
                    CloudAuthorityRecord(
                        attribution=cloud,
                        model_fingerprint="e" * 64,
                        segment_id=script.segments[0].segment_id,
                        source_local_hash=script.segments[0].local_hash,
                        speaker_target_hash=speaker_target_hash(
                            script.segments[0].speaker,
                            script.segments[0].casting,
                        ),
                    )
                }
            ),
        )

    with pytest.raises(ValueError):
        SceneBoundarySource("cloud_assisted")

    second_character_id = uuid4()
    candidate_ids = tuple(
        sorted(
            (CHARACTER_ID, second_character_id),
            key=lambda value: str(value),
        )
    )
    bound_cloud = replace(cloud, candidate_character_ids=candidate_ids)
    first_target = CastingTargetRef(
        CastingTargetKind.CHARACTER_BINDING,
        binding_id=BINDING_ID,
        character_id=CHARACTER_ID,
    )
    second_target = CastingTargetRef(
        CastingTargetKind.CHARACTER_BINDING,
        binding_id=uuid4(),
        character_id=second_character_id,
    )
    trusted_script = _make_contract(
        speaker=SpeakerRef(
            SpeakerKind.CHARACTER,
            character_id=CHARACTER_ID,
        ),
        casting=CastingDecision(
            candidate_targets=(first_target,),
            final_target=first_target,
            origin=CastingDecisionOrigin.CHARACTER_BINDING,
        ),
        attribution=bound_cloud,
        issues=cloud_warning,
        requested_model_fingerprint="d" * 64,
        actual_model_fingerprint="d" * 64,
    )
    trusted_authority = replace(
        _authority(trusted_script),
        casting_targets=frozenset({first_target, second_target}),
    )
    forged_decision_script = _make_contract(
        speaker=SpeakerRef(
            SpeakerKind.CHARACTER,
            character_id=second_character_id,
        ),
        casting=CastingDecision(
            candidate_targets=(second_target,),
            final_target=second_target,
            origin=CastingDecisionOrigin.CHARACTER_BINDING,
        ),
        attribution=bound_cloud,
        issues=cloud_warning,
        requested_model_fingerprint="d" * 64,
        actual_model_fingerprint="d" * 64,
    )
    with pytest.raises(ScriptContractError, match="cloud attribution.*authority"):
        _script_contract_from_dict(
            script_contract_to_dict(forged_decision_script),
            authority=trusted_authority,
            source_text="夜🌙。",
        )


def test_casting_decision_is_typed_versioned_and_never_freezes_voice_version() -> None:
    character_target = CastingTargetRef(
        CastingTargetKind.CHARACTER_BINDING,
        binding_id=BINDING_ID,
        character_id=CHARACTER_ID,
    )
    decision = CastingDecision(
        candidate_targets=(character_target,),
        final_target=character_target,
        origin=CastingDecisionOrigin.CHARACTER_BINDING,
    )
    script = _make_contract(
        speaker=SpeakerRef(SpeakerKind.CHARACTER, character_id=CHARACTER_ID),
        casting=decision,
    )
    casting_payload = script_contract_to_dict(script)["segments"][0]["casting"]
    assert casting_payload["contract_version"] == "narration-casting-decision/1"
    assert "voice_version_id" not in canonical_json_bytes(casting_payload).decode()

    with pytest.raises(ScriptContractError, match="fields do not match"):
        CastingTargetRef(
            CastingTargetKind.CHARACTER_BINDING,
            character_id=CHARACTER_ID,
        )
    with pytest.raises(ScriptContractError, match="one of candidate"):
        CastingDecision(
            candidate_targets=(),
            final_target=character_target,
            origin=CastingDecisionOrigin.CHARACTER_BINDING,
        )
    with pytest.raises(ScriptContractError, match="origin differs"):
        _make_contract(
            speaker=SpeakerRef(
                SpeakerKind.CHARACTER,
                character_id=CHARACTER_ID,
            ),
            casting=CastingDecision(
                candidate_targets=(
                    CastingTargetRef(
                        CastingTargetKind.PROFILE,
                        profile_id=PROFILE_ID,
                    ),
                ),
                final_target=CastingTargetRef(
                    CastingTargetKind.PROFILE,
                    profile_id=PROFILE_ID,
                ),
                origin=CastingDecisionOrigin.NARRATOR_SETTING,
            ),
        )
    with pytest.raises(ScriptContractError, match="manual casting requires"):
        _make_contract(
            casting=CastingDecision(
                candidate_targets=(
                    CastingTargetRef(
                        CastingTargetKind.PROFILE,
                        profile_id=PROFILE_ID,
                    ),
                ),
                final_target=CastingTargetRef(
                    CastingTargetKind.PROFILE,
                    profile_id=PROFILE_ID,
                ),
                origin=CastingDecisionOrigin.MANUAL_OVERRIDE,
            )
        )


def test_casting_authority_rejects_individually_valid_cross_paired_ids() -> None:
    second_character_id = uuid4()
    second_binding_id = uuid4()
    forged_target = CastingTargetRef(
        CastingTargetKind.CHARACTER_BINDING,
        binding_id=BINDING_ID,
        character_id=second_character_id,
    )
    script = _make_contract(
        speaker=SpeakerRef(
            SpeakerKind.CHARACTER,
            character_id=second_character_id,
        ),
        casting=CastingDecision(
            candidate_targets=(forged_target,),
            final_target=forged_target,
            origin=CastingDecisionOrigin.CHARACTER_BINDING,
        ),
    )
    authorized_targets = frozenset(
        {
            CastingTargetRef(
                CastingTargetKind.CHARACTER_BINDING,
                binding_id=BINDING_ID,
                character_id=CHARACTER_ID,
            ),
            CastingTargetRef(
                CastingTargetKind.CHARACTER_BINDING,
                binding_id=second_binding_id,
                character_id=second_character_id,
            ),
        }
    )
    authority = replace(
        _authority(script),
        character_ids=frozenset({CHARACTER_ID, second_character_id}),
        casting_targets=authorized_targets,
    )
    with pytest.raises(ScriptContractError, match="target relation.*authority"):
        validate_authorized_references(script, authority)
    with pytest.raises(ScriptContractError, match="target relation.*authority"):
        _script_contract_from_dict(
            script_contract_to_dict(script),
            authority=authority,
            source_text="夜🌙。",
        )

    second_pool_id = uuid4()
    second_slot_id = uuid4()
    forged_slot = CastingTargetRef(
        CastingTargetKind.GENERIC_SLOT,
        pool_id=POOL_ID,
        slot_id=second_slot_id,
    )
    slot_script = _make_contract(
        casting=CastingDecision(
            candidate_targets=(forged_slot,),
            final_target=forged_slot,
            origin=CastingDecisionOrigin.CASTING_RULE,
            rule_id=uuid4(),
            rule_version=1,
        )
    )
    authorized_slots = frozenset(
        {
            CastingTargetRef(
                CastingTargetKind.GENERIC_SLOT,
                pool_id=POOL_ID,
                slot_id=SLOT_ID,
            ),
            CastingTargetRef(
                CastingTargetKind.GENERIC_SLOT,
                pool_id=second_pool_id,
                slot_id=second_slot_id,
            ),
        }
    )
    with pytest.raises(ScriptContractError, match="target relation.*authority"):
        validate_authorized_references(
            slot_script,
            replace(
                _authority(slot_script),
                casting_targets=authorized_slots,
            ),
        )
    with pytest.raises(ScriptContractError, match="target relation.*authority"):
        _script_contract_from_dict(
            script_contract_to_dict(slot_script),
            authority=replace(
                _authority(slot_script),
                casting_targets=authorized_slots,
            ),
            source_text="夜🌙。",
        )


def test_casting_authority_rejects_wrong_rule_version_pair() -> None:
    rule_id = uuid4()
    profile_target = CastingTargetRef(
        CastingTargetKind.PROFILE,
        profile_id=PROFILE_ID,
    )
    script = _make_contract(
        casting=CastingDecision(
            candidate_targets=(profile_target,),
            final_target=profile_target,
            origin=CastingDecisionOrigin.CASTING_RULE,
            rule_id=rule_id,
            rule_version=1,
        )
    )
    authority = _authority(script)
    trusted_record = next(iter(authority.casting_rule_records))
    wrong_version_record = replace(
        trusted_record,
        decision=replace(
            trusted_record.decision,
            rule_version=2,
        ),
    )
    with pytest.raises(ScriptContractError, match="rule decision.*authority"):
        validate_authorized_references(
            script,
            replace(
                authority,
                casting_rule_records=frozenset({wrong_version_record}),
            ),
        )

    second_profile_target = CastingTargetRef(
        CastingTargetKind.PROFILE,
        profile_id=uuid4(),
    )
    forged_target_script = _make_contract(
        casting=CastingDecision(
            candidate_targets=(second_profile_target,),
            final_target=second_profile_target,
            origin=CastingDecisionOrigin.CASTING_RULE,
            rule_id=rule_id,
            rule_version=1,
        )
    )
    with pytest.raises(ScriptContractError, match="rule decision.*authority"):
        _script_contract_from_dict(
            script_contract_to_dict(forged_target_script),
            authority=replace(
                authority,
                casting_targets=frozenset(
                    {profile_target, second_profile_target}
                ),
            ),
            source_text="夜🌙。",
        )


def test_unresolved_casting_is_a_blocker_and_cannot_enter_approved_content() -> None:
    unresolved = CastingDecision(
        candidate_targets=(),
        final_target=None,
        origin=CastingDecisionOrigin.UNRESOLVED,
    )
    with pytest.raises(ScriptContractError, match="B_CASTING_TARGET_UNRESOLVED"):
        _make_contract(casting=unresolved)

    segment_id = _make_contract().segments[0].segment_id
    blocker = ScriptIssueContract(
        "B_CASTING_TARGET_UNRESOLVED",
        ReviewIssueSeverity.BLOCKER,
        segment_id=segment_id,
    )
    script = _make_contract(
        state=ScriptVersionState.REVIEW_REQUIRED,
        casting=unresolved,
        issues=(blocker,),
    )
    assert script.blocker_count == 1


def test_server_authority_rejects_foreign_root_character_and_model_ids() -> None:
    script = _make_contract(
        speaker=SpeakerRef(SpeakerKind.CHARACTER, character_id=CHARACTER_ID),
    )
    validate_authorized_references(script, _authority(script))
    with pytest.raises(ScriptContractError, match="character_id.*authority"):
        validate_authorized_references(
            script,
            replace(
                _authority(script),
                character_ids=frozenset(),
                casting_targets=frozenset(),
            ),
        )

    with pytest.raises(ScriptContractError, match="script_version_id.*authority"):
        source_text = _fixture()["x-example-source-text"]
        assert type(source_text) is str
        _script_contract_from_dict(
            _example_payload(),
            authority=replace(_authority(), script_version_id=uuid4()),
            source_text=source_text,
        )


def test_state_version_and_approval_audit_are_exact_server_authority() -> None:
    approval = ScriptApproval(
        ScriptApprovalKind.AUTO_NO_BLOCKERS,
        uuid4(),
        ApprovalActorType.SERVICE,
        "narration-service",
        datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc),
    )
    script = _make_contract(
        state=ScriptVersionState.APPROVED,
        approval=approval,
    )
    authority = _authority(script)
    validate_authorized_references(script, authority)

    forged_approval = replace(
        approval,
        actor_id="forged-service",
        approved_at=datetime(2026, 8, 26, 12, 1, tzinfo=timezone.utc),
    )
    with pytest.raises(ScriptContractError, match="approval.*authority"):
        validate_authorized_references(
            script,
            replace(authority, approval=forged_approval),
        )
    with pytest.raises(ScriptContractError, match="version_number.*authority"):
        validate_authorized_references(
            script,
            replace(authority, version_number=2),
        )
    with pytest.raises(ScriptContractError, match="state.*authority"):
        validate_authorized_references(
            script,
            replace(
                authority,
                state=ScriptVersionState.ANALYZED,
                approval=None,
            ),
        )

    forged_wire = script_contract_to_dict(script)
    forged_wire["version_number"] = 2
    with pytest.raises(ScriptContractError, match="version_number.*authority"):
        _script_contract_from_dict(
            forged_wire,
            authority=authority,
            source_text="夜🌙。",
        )

    forged_wire = script_contract_to_dict(script)
    forged_wire["state"] = ScriptVersionState.FAILED.value
    forged_wire["approval"] = None
    with pytest.raises(ScriptContractError, match="state.*authority"):
        _script_contract_from_dict(
            forged_wire,
            authority=authority,
            source_text="夜🌙。",
        )

    for field_name, forged_value in (
        ("actor_id", "forged-service"),
        ("approved_at", "2099-01-01T00:00:00+00:00"),
    ):
        forged_wire = script_contract_to_dict(script)
        forged_approval_wire = forged_wire["approval"]
        assert type(forged_approval_wire) is dict
        forged_approval_wire[field_name] = forged_value
        with pytest.raises(ScriptContractError, match="approval.*authority"):
            _script_contract_from_dict(
                forged_wire,
                authority=authority,
                source_text="夜🌙。",
            )


def test_manual_and_inherited_overrides_freeze_owner_and_match_provenance() -> None:
    base = _make_contract()
    target_hash = speaker_target_hash(
        base.segments[0].speaker, base.segments[0].casting
    )
    manual = AttributionEvidence(
        AttributionOrigin.MANUAL_OVERRIDE,
        override_provenance=OverrideProvenance(
            kind=OverrideKind.MANUAL_CURRENT,
            action_id=uuid4(),
            owner_actor_id="owner-1",
            recorded_at=datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc),
            source_local_hash=base.segments[0].local_hash,
            source_anchor_before_hash=None,
            source_anchor_after_hash=None,
            speaker_target_hash=target_hash,
        ),
    )
    assert _make_contract(attribution=manual).segments[0].manual_override is True

    source_version_id = uuid4()
    source_segment_id = uuid4()
    inherited = AttributionEvidence(
        AttributionOrigin.INHERITED_OVERRIDE,
        override_provenance=OverrideProvenance(
            kind=OverrideKind.INHERITED,
            action_id=uuid4(),
            owner_actor_id="owner-1",
            recorded_at=datetime(2026, 8, 26, 12, 5, tzinfo=timezone.utc),
            source_script_version_id=source_version_id,
            source_segment_id=source_segment_id,
            source_immutable_hash="d" * 64,
            source_local_hash=base.segments[0].local_hash,
            source_anchor_before_hash=None,
            source_anchor_after_hash=None,
            speaker_target_hash=target_hash,
        ),
    )
    warning = ScriptIssueContract(
        "W_MANUAL_OVERRIDE_INHERITED",
        ReviewIssueSeverity.WARNING,
        segment_id=base.segments[0].segment_id,
    )
    inherited_script = _make_contract(
        attribution=inherited,
        issues=(warning,),
    )
    assert inherited_script.warning_count == 1
    validate_authorized_references(
        inherited_script,
        _authority(inherited_script),
    )
    with pytest.raises(ScriptContractError, match="override provenance.*authority"):
        validate_authorized_references(
            inherited_script,
            _authority(inherited_script, trust_overrides=False),
        )
    with pytest.raises(ScriptContractError, match="server warning"):
        _make_contract(attribution=inherited)
    with pytest.raises(ScriptContractError, match="UTC datetime"):
        replace(
            manual.override_provenance,
            recorded_at=datetime(2026, 8, 26, 20, 0),
        )


def test_historical_scene_scoped_anonymous_identity_can_be_reused_safely() -> None:
    historical_scene_id = uuid4()
    stable_key = derive_anonymous_stable_key(
        novel_id=NOVEL_ID,
        scope_kind=AnonymousScopeKind.SCENE,
        scope_id=historical_scene_id,
        label="门外女人",
        evidence_hash="e" * 64,
    )
    anonymous_id = derive_anonymous_speaker_id(
        novel_id=NOVEL_ID, stable_key=stable_key
    )
    identity = AnonymousSpeakerIdentity(
        anonymous_id,
        ANONYMOUS_SPEAKER_STABLE_KEY_VERSION,
        stable_key,
        "匿名女性",
        AnonymousScopeKind.SCENE,
        historical_scene_id,
        ConfidenceLevel.HIGH,
    )
    target = CastingTargetRef(
        CastingTargetKind.ANONYMOUS_BINDING,
        anonymous_speaker_id=anonymous_id,
    )
    script = _make_contract(
        speaker=SpeakerRef(
            SpeakerKind.ANONYMOUS,
            anonymous_speaker_id=anonymous_id,
        ),
        casting=CastingDecision(
            candidate_targets=(target,),
            final_target=target,
            origin=CastingDecisionOrigin.ANONYMOUS_BINDING,
        ),
        anonymous_speakers=(identity,),
    )
    assert script.anonymous_speakers[0].scope_id == historical_scene_id
    with pytest.raises(ScriptContractError, match="historical scene anonymous"):
        validate_authorized_references(script, _authority(script))
    validate_authorized_references(
        script,
        _authority(
            script,
            verified_historical_anonymous_ids=frozenset({anonymous_id}),
        ),
    )
    with pytest.raises(ScriptContractError, match="authorized identity snapshot"):
        replace(
            _authority(script),
            verified_historical_anonymous_ids=frozenset({uuid4()}),
        )


def test_manual_override_flag_and_origin_cannot_drift() -> None:
    payload = _example_payload()
    payload["segments"][0]["manual_override"] = True
    with pytest.raises(ScriptContractError, match="manual_override"):
        script_contract_from_dict(payload)
    payload = _example_payload()
    payload["segments"][0]["attribution"]["origin"] = "manual_override"
    payload["segments"][0]["attribution"]["rule_codes"] = []
    with pytest.raises(ScriptContractError, match="override_provenance"):
        script_contract_from_dict(payload)


def test_synthetic_segments_never_fabricate_body_ranges_or_spoken_pause_text() -> None:
    payload = _example_payload()
    pause = payload["segments"][-1]
    pause["source_range_utf16"] = {"start": 0, "end_exclusive": 1}
    with pytest.raises(ScriptContractError, match="must not fabricate"):
        script_contract_from_dict(payload)

    payload = _example_payload()
    payload["segments"][-1]["spoken_text"] = "停顿"
    payload["segments"][-1]["local_hash"] = text_sha256("")
    with pytest.raises(ScriptContractError, match="synthetic_pause"):
        script_contract_from_dict(payload)


def test_confidence_and_unknown_speaker_require_server_owned_taxonomy_rows() -> None:
    medium_payload = _example_payload()
    medium_payload["segments"][0]["confidence"] = "medium"
    with pytest.raises(ScriptContractError, match="medium speaker confidence"):
        script_contract_from_dict(medium_payload)

    unknown_payload = _example_payload()
    unknown_payload["issues"] = [
        item
        for item in unknown_payload["issues"]
        if item["code"] != "B_SPEAKER_UNKNOWN"
    ]
    unknown_payload["blocker_count"] = 2
    with pytest.raises(ScriptContractError, match="unknown speaker"):
        script_contract_from_dict(unknown_payload)

    low_payload = _example_payload()
    low_payload["issues"] = [
        item
        for item in low_payload["issues"]
        if item["code"] != "B_SPEAKER_LOW_CONFIDENCE"
    ]
    low_payload["blocker_count"] = 2
    with pytest.raises(ScriptContractError, match="low/unknown"):
        script_contract_from_dict(low_payload)


def test_issue_severity_counts_and_references_are_server_owned() -> None:
    with pytest.raises(ScriptContractError, match="server-owned"):
        ScriptIssueContract(
            "B_SPEAKER_UNKNOWN", ReviewIssueSeverity.WARNING
        )
    with pytest.raises(UnknownTaxonomyCodeError):
        ScriptIssueContract(
            WORKFLOW_FAILURE_CODES[0], ReviewIssueSeverity.BLOCKER
        )

    payload = _example_payload()
    payload["blocker_count"] = 1
    with pytest.raises(ScriptContractError, match="recomputed"):
        script_contract_from_dict(payload)
    payload = _example_payload()
    payload["issues"][0]["segment_id"] = str(uuid4())
    with pytest.raises(ScriptContractError, match="unknown segment"):
        script_contract_from_dict(payload)


def test_materialized_state_and_approval_invariants_are_fail_closed() -> None:
    assert _make_contract().state is ScriptVersionState.ANALYZED
    approval = ScriptApproval(
        ScriptApprovalKind.AUTO_NO_BLOCKERS,
        uuid4(),
        ApprovalActorType.SERVICE,
        "narration-service",
        datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc),
    )
    approved = _make_contract(
        state=ScriptVersionState.APPROVED, approval=approval
    )
    assert approved.approval is approval
    assert SCRIPT_STATE_TRANSITIONS[ScriptVersionState.APPROVED] == frozenset()

    with pytest.raises(ScriptContractError, match="only approved"):
        _make_contract(approval=approval)
    with pytest.raises(ScriptContractError, match="zero blockers"):
        _make_contract(
            state=ScriptVersionState.APPROVED,
            issues=(
                ScriptIssueContract(
                    "B_VOICE_MISSING", ReviewIssueSeverity.BLOCKER
                ),
            ),
            approval=approval,
        )
    with pytest.raises(ScriptContractError, match="requires the owner actor"):
        ScriptApproval(
            ScriptApprovalKind.MANUAL_AFTER_REVIEW,
            uuid4(),
            ApprovalActorType.SERVICE,
            "service",
            datetime.now(timezone.utc),
        )


def test_corrected_blocker_child_stays_review_required_and_freezes_manually() -> None:
    parent_version_id = uuid4()
    corrected = _make_contract(
        state=ScriptVersionState.REVIEW_REQUIRED,
        policy=ScriptReviewPolicy.BLOCKERS_ONLY,
        parent_version_id=parent_version_id,
    )
    assert corrected.parent_version_id == parent_version_id
    with pytest.raises(ScriptContractError, match="classify every parent"):
        replace(
            _authority(corrected),
            non_review_parent_ids=frozenset(),
        )
    with pytest.raises(ScriptContractError, match="manual-review parent"):
        validate_authorized_references(corrected, _authority(corrected))
    validate_authorized_references(
        corrected,
        _authority(
            corrected,
            manual_review_parent_ids=frozenset({parent_version_id}),
        ),
    )

    approval = ScriptApproval(
        ScriptApprovalKind.MANUAL_AFTER_REVIEW,
        uuid4(),
        ApprovalActorType.OWNER,
        "owner-1",
        datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc),
    )
    approved = _make_contract(
        state=ScriptVersionState.APPROVED,
        policy=ScriptReviewPolicy.BLOCKERS_ONLY,
        parent_version_id=parent_version_id,
        approval=approval,
    )
    assert approved.approval is approval
    with pytest.raises(ScriptContractError, match="verified review parent"):
        validate_authorized_references(approved, _authority(approved))
    validate_authorized_references(
        approved,
        _authority(
            approved,
            manual_review_parent_ids=frozenset({parent_version_id}),
        ),
    )

    auto_approval = ScriptApproval(
        ScriptApprovalKind.AUTO_NO_BLOCKERS,
        uuid4(),
        ApprovalActorType.SERVICE,
        "narration-service",
        datetime(2026, 8, 26, 12, 1, tzinfo=timezone.utc),
    )
    auto_approved_child = _make_contract(
        state=ScriptVersionState.APPROVED,
        policy=ScriptReviewPolicy.BLOCKERS_ONLY,
        parent_version_id=parent_version_id,
        approval=auto_approval,
    )
    with pytest.raises(ScriptContractError, match="requires manual_after_review"):
        validate_authorized_references(
            auto_approved_child,
            _authority(
                auto_approved_child,
                manual_review_parent_ids=frozenset({parent_version_id}),
            ),
        )

    analyzed_child = _make_contract(parent_version_id=parent_version_id)
    with pytest.raises(ScriptContractError, match="cannot bypass manual review"):
        validate_authorized_references(
            analyzed_child,
            _authority(
                analyzed_child,
                manual_review_parent_ids=frozenset({parent_version_id}),
            ),
        )

    with pytest.raises(ScriptContractError, match="corrected child"):
        _make_contract(
            state=ScriptVersionState.APPROVED,
            policy=ScriptReviewPolicy.BLOCKERS_ONLY,
            approval=approval,
        )


def test_auto_approval_cannot_bypass_always_review() -> None:
    approval = ScriptApproval(
        ScriptApprovalKind.AUTO_NO_BLOCKERS,
        uuid4(),
        ApprovalActorType.SERVICE,
        "narration-service",
        datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(ScriptContractError, match="only valid for blockers_only"):
        _make_contract(
            state=ScriptVersionState.APPROVED,
            policy=ScriptReviewPolicy.ALWAYS_REVIEW,
            approval=approval,
        )


def test_script_failed_state_keeps_failure_reason_request_owned() -> None:
    assert _make_contract(state=ScriptVersionState.FAILED).state is (
        ScriptVersionState.FAILED
    )
    payload = _example_payload()
    payload["failure_code"] = "F_ANALYZER_RUNTIME"
    with pytest.raises(ScriptContractError, match="invalid keys"):
        script_contract_from_dict(payload)
    assert tuple(_fixture()["x-workflow-failure-contract"]["codes"]) == (
        WORKFLOW_FAILURE_CODES
    )
    assert _fixture()["x-workflow-failure-contract"]["owner"] == (
        "narration_request"
    )


def test_state_transition_table_is_exact_and_approved_failed_are_terminal() -> None:
    for current, targets in SCRIPT_STATE_TRANSITIONS.items():
        for target in ScriptVersionState:
            if target in targets:
                ensure_script_transition(current, target)
            else:
                with pytest.raises(ScriptContractError, match="illegal"):
                    ensure_script_transition(current, target)
    assert initial_materialized_state(
        ScriptReviewPolicy.BLOCKERS_ONLY, blocker_count=0
    ) is ScriptVersionState.ANALYZED
    assert initial_materialized_state(
        ScriptReviewPolicy.BLOCKERS_ONLY, blocker_count=1
    ) is ScriptVersionState.REVIEW_REQUIRED
    assert initial_materialized_state(
        ScriptReviewPolicy.ALWAYS_REVIEW, blocker_count=0
    ) is ScriptVersionState.REVIEW_REQUIRED


def test_scene_segment_block_ordinals_ranges_and_ids_cannot_be_rebound() -> None:
    payload = _example_payload()
    payload["segments"][1]["ordinal"] = 3
    with pytest.raises(ScriptContractError, match="contiguous"):
        script_contract_from_dict(payload)

    payload = _example_payload()
    payload["segments"][0]["segment_id"] = str(uuid4())
    with pytest.raises(ScriptContractError, match="version-scoped ID"):
        script_contract_from_dict(payload)

    payload = _example_payload()
    payload["segments"][0]["source_block_key"] = "sb1_" + "0" * 64
    payload["segments"][0]["segment_id"] = str(
        derive_segment_id(
            script_version_id=UUID(payload["script_version_id"]),
            ordinal=payload["segments"][0]["ordinal"],
            source_block_key=payload["segments"][0]["source_block_key"],
            segment_ordinal_in_block=payload["segments"][0][
                "segment_ordinal_in_block"
            ],
            local_hash=payload["segments"][0]["local_hash"],
        )
    )
    with pytest.raises(ScriptContractError, match="version-scoped key"):
        script_contract_from_dict(payload)

    payload = _example_payload()
    payload["segments"][1]["source_range_utf16"] = {
        "start": 2,
        "end_exclusive": 6,
    }
    payload["segments"][1]["source_text"] = "🌙。\n"
    payload["segments"][1]["local_hash"] = text_sha256("🌙。\n")
    with pytest.raises(ScriptContractError, match="overlap|version-scoped ID"):
        script_contract_from_dict(payload)


def test_anonymous_identity_must_be_same_scope_and_match_stable_uuid() -> None:
    stable_key = derive_anonymous_stable_key(
        novel_id=NOVEL_ID,
        scope_kind=AnonymousScopeKind.CHAPTER,
        scope_id=DOCUMENT_ID,
        label="门外女人",
        evidence_hash="e" * 64,
    )
    identity = AnonymousSpeakerIdentity(
        derive_anonymous_speaker_id(novel_id=NOVEL_ID, stable_key=stable_key),
        ANONYMOUS_SPEAKER_STABLE_KEY_VERSION,
        stable_key,
        "匿名女性",
        AnonymousScopeKind.CHAPTER,
        DOCUMENT_ID,
        ConfidenceLevel.HIGH,
    )
    assert identity.scope_id == DOCUMENT_ID
    with pytest.raises(ScriptContractError, match="algorithm"):
        replace(identity, stable_key_algorithm="anonymous-speaker-stable-key/2")


def test_immutable_hash_and_frozen_dataclasses_reject_mutation() -> None:
    script = _make_contract()
    assert script.immutable_hash == script_immutable_hash(script)
    with pytest.raises(FrozenInstanceError):
        script.version_number = 2  # type: ignore[misc]
    payload = script_contract_to_dict(script)
    payload["immutable_hash"] = "0" * 64
    with pytest.raises(ScriptContractError, match="immutable_hash"):
        script_contract_from_dict(payload)


def test_immutable_projection_exactly_bridges_the_existing_persistence_contract() -> None:
    script = script_contract_from_dict(_example_payload())
    projection = script_immutable_payload(script)

    scene_inputs = [
        ScriptSceneInput(
            scene_id=scene.scene_id,
            ordinal=scene.ordinal,
            source_start=(
                scene.source_range_utf16.start
                if scene.source_range_utf16
                else None
            ),
            source_end=(
                scene.source_range_utf16.end_exclusive
                if scene.source_range_utf16
                else None
            ),
            boundary_source=scene.boundary_source.value,
            local_hash=scene.local_hash,
            title=scene.title,
        )
        for scene in script.scenes
    ]
    expected_scenes = [
        persisted_scripts._scene_payload(item) for item in scene_inputs
    ]
    assert projection["scenes"] == expected_scenes

    projected_segments = projection["segments"]
    assert type(projected_segments) is list
    segment_inputs: list[ScriptSegmentInput] = []
    for segment, projected in zip(
        script.segments, projected_segments, strict=True
    ):
        assert type(projected) is dict
        assert type(projected["casting"]) is dict
        assert type(projected["evidence"]) is dict
        source_range = segment.source_range_utf16
        segment_inputs.append(
            ScriptSegmentInput(
                segment_id=segment.segment_id,
                ordinal=segment.ordinal,
                segment_kind=segment.segment_kind.value,
                source_block_key=segment.source_block_key,
                source_text=segment.source_text,
                spoken_text=segment.spoken_text,
                local_hash=segment.local_hash,
                speaker_kind=segment.speaker.kind.value,
                casting_json=projected["casting"],
                evidence_json=projected["evidence"],
                confidence=segment.confidence.value,
                pause_before_ms=segment.pause_before_ms,
                pause_after_ms=segment.pause_after_ms,
                manual_override=segment.manual_override,
                scene_id=segment.scene_id,
                paragraph_ordinal=segment.paragraph_ordinal,
                source_start_utf16=(source_range.start if source_range else None),
                source_end_utf16=(
                    source_range.end_exclusive if source_range else None
                ),
                anchor_before_hash=segment.anchor_before_hash,
                anchor_after_hash=segment.anchor_after_hash,
                character_id=segment.speaker.character_id,
                anonymous_speaker_id=segment.speaker.anonymous_speaker_id,
                emotion=segment.emotion.value,
                expression=segment.delivery.value,
            )
        )
    expected_segments = [
        persisted_scripts._segment_payload(item) for item in segment_inputs
    ]
    assert projected_segments == expected_segments

    issue_inputs = [
        ReviewIssue(
            code=issue.code,
            severity=issue.severity,
            evidence_digest=issue.evidence_digest,
            segment_id=issue.segment_id,
        )
        for issue in script.issues
    ]
    expected_issues = sorted(
        (persisted_scripts._issue_payload(item) for item in issue_inputs),
        key=lambda item: (
            str(item["code"]),
            str(item["segment_id"] or ""),
            str(item["evidence_digest"] or ""),
        ),
    )
    expected = persisted_scripts._immutable_payload(
        script_id=script.script_id,
        parent_version_id=script.parent_version_id,
        source_content_hash=script.source_content_hash,
        settings_fingerprint=script.settings_fingerprint,
        analyzer_fingerprint=script.analyzer_fingerprint,
        rules_fingerprint=script.rules_fingerprint,
        requested_model_fingerprint=script.requested_model_fingerprint,
        actual_model_fingerprint=script.actual_model_fingerprint,
        effective_policy=script.effective_policy.value,
        scenes=expected_scenes,
        segments=expected_segments,
        issues=expected_issues,
    )
    assert projection == expected
    assert script.immutable_hash == hashlib.sha256(
        canonical_json_bytes(expected)
    ).hexdigest()
    assert projected_segments[0]["casting"]["contract_version"] == (
        NARRATION_CASTING_DECISION_VERSION
    )
    assert projected_segments[0]["evidence"]["contract_version"] == (
        NARRATION_SEGMENT_EVIDENCE_VERSION
    )


def test_content_hash_exclusions_are_explicit_and_do_not_create_a_second_hash() -> None:
    script = _make_contract()
    approval = ScriptApproval(
        ScriptApprovalKind.AUTO_NO_BLOCKERS,
        uuid4(),
        ApprovalActorType.SERVICE,
        "narration-service",
        datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc),
    )
    approved = replace(
        script,
        state=ScriptVersionState.APPROVED,
        approval=approval,
        version_number=2,
    )
    assert approved.immutable_hash == script.immutable_hash

    issue = ScriptIssueContract(
        "W_GENERIC_VOICE_FALLBACK",
        ReviewIssueSeverity.WARNING,
        segment_id=script.segments[0].segment_id,
        evidence_summary="使用通用声音 A",
        evidence_digest="e" * 64,
    )
    with_summary = _make_contract(issues=(issue,))
    changed_summary = replace(
        with_summary,
        issues=(replace(issue, evidence_summary="使用通用声音 B"),),
    )
    assert changed_summary.immutable_hash == with_summary.immutable_hash


def test_exact_runtime_types_reject_bool_as_int_and_string_as_enum() -> None:
    with pytest.raises(ScriptContractError, match="integer"):
        Utf16Range(True, 2)  # type: ignore[arg-type]
    with pytest.raises(ScriptContractError, match="SpeakerKind"):
        SpeakerRef("narrator")  # type: ignore[arg-type]
    with pytest.raises(ScriptContractError, match="boolean"):
        replace(_make_contract().segments[0], manual_override=1)  # type: ignore[arg-type]


def test_runtime_uuid_rules_match_frozen_rfc_variant_v1_to_v5_schema() -> None:
    with pytest.raises(ScriptContractError, match="RFC-4122"):
        SpeakerRef(
            SpeakerKind.CHARACTER,
            character_id=UUID("00000000-0000-0000-0000-000000000000"),
        )


def test_unicode_surrogates_and_non_nfc_spoken_text_fail_closed() -> None:
    with pytest.raises(ScriptContractError, match="unpaired Unicode surrogate"):
        utf16_slice("\ud800", Utf16Range(0, 1))

    payload = _example_payload()
    payload["segments"][0]["spoken_text"] = "e\u0301"
    with pytest.raises(ScriptContractError, match="Unicode NFC"):
        script_contract_from_dict(payload)


def test_source_mapping_validates_scene_block_anchors_and_real_source_coverage() -> None:
    script = _make_contract()
    cut_scene = SceneContract(
        scene_id=derive_scene_id(
            script_version_id=SCRIPT_VERSION_ID,
            ordinal=0,
            source_range=Utf16Range(0, 2),
            local_hash=text_sha256("夜"),
        ),
        ordinal=0,
        source_range_utf16=Utf16Range(0, 2),
        boundary_source=SceneBoundarySource.DOCUMENT_START,
        local_hash=text_sha256("夜"),
    )
    cut_script = _rebuild_contract(
        script,
        scenes=(cut_scene,),
        segments=(replace(script.segments[0], scene_id=None),),
    )
    with pytest.raises(ScriptContractError, match="surrogate pair"):
        validate_source_mapping("夜🌙。", cut_script)

    forged = replace(
        script.segments[0],
        source_block_hash="f" * 64,
        source_block_key=derive_source_block_key(
            script_version_id=SCRIPT_VERSION_ID,
            block_kind=script.segments[0].source_block_kind,
            paragraph_ordinal=script.segments[0].paragraph_ordinal,
            block_hash="f" * 64,
            anchor_before_hash=script.segments[0].anchor_before_hash,
            anchor_after_hash=script.segments[0].anchor_after_hash,
        ),
    )
    forged = replace(
        forged,
        segment_id=derive_segment_id(
            script_version_id=script.script_version_id,
            ordinal=forged.ordinal,
            source_block_key=forged.source_block_key,
            segment_ordinal_in_block=forged.segment_ordinal_in_block,
            local_hash=forged.local_hash,
        ),
    )
    forged_script = _rebuild_contract(script, segments=(forged,))
    with pytest.raises(ScriptContractError, match="block .* hash"):
        validate_source_mapping("夜🌙。", forged_script)

    fixture_script = script_contract_from_dict(_example_payload())
    pause = replace(fixture_script.segments[-1], scene_id=None, ordinal=0)
    pause = replace(
        pause,
        segment_id=derive_segment_id(
            script_version_id=fixture_script.script_version_id,
            ordinal=0,
            source_block_key=pause.source_block_key,
            segment_ordinal_in_block=pause.segment_ordinal_in_block,
            local_hash=pause.local_hash,
        ),
    )
    synthetic_only = _rebuild_contract(
        fixture_script,
        scenes=(),
        segments=(pause,),
        issues=(),
        warning_count=0,
        blocker_count=0,
        state=ScriptVersionState.ANALYZED,
    )
    with pytest.raises(ScriptContractError, match="source-bound"):
        validate_source_mapping(_fixture()["x-example-source-text"], synthetic_only)

    with pytest.raises(ScriptContractError, match="cannot use.*synthetic"):
        replace(
            script.segments[0],
            source_block_kind=SourceBlockKind.SYNTHETIC,
        )


def test_source_mapping_rejects_partial_coverage_and_interleaved_blocks() -> None:
    source = "夜🌙。"
    script = _make_contract()
    partial_range = Utf16Range(0, 3)
    partial_text = utf16_slice(source, partial_range)
    partial_hash = text_sha256(partial_text)
    partial_key = derive_source_block_key(
        script_version_id=script.script_version_id,
        block_kind=SourceBlockKind.PARAGRAPH,
        paragraph_ordinal=0,
        block_hash=partial_hash,
        anchor_before_hash=None,
        anchor_after_hash=None,
    )
    partial_segment = replace(
        script.segments[0],
        segment_id=derive_segment_id(
            script_version_id=script.script_version_id,
            ordinal=0,
            source_block_key=partial_key,
            segment_ordinal_in_block=0,
            local_hash=partial_hash,
        ),
        source_block_key=partial_key,
        source_block_hash=partial_hash,
        source_range_utf16=partial_range,
        source_text=partial_text,
        spoken_text=partial_text,
        local_hash=partial_hash,
    )
    partial_script = _rebuild_contract(
        script,
        segments=(partial_segment,),
    )
    with pytest.raises(ScriptContractError, match="completely partition"):
        validate_source_mapping(source, partial_script)
    with pytest.raises(ScriptContractError, match="completely partition"):
        _script_contract_from_dict(
            script_contract_to_dict(partial_script),
            authority=_authority(partial_script),
            source_text=source,
        )

    block_a_hash = text_sha256("夜。")
    block_b_hash = text_sha256("🌙")
    block_a_key = derive_source_block_key(
        script_version_id=script.script_version_id,
        block_kind=SourceBlockKind.PARAGRAPH,
        paragraph_ordinal=0,
        block_hash=block_a_hash,
        anchor_before_hash=None,
        anchor_after_hash=None,
    )
    block_b_key = derive_source_block_key(
        script_version_id=script.script_version_id,
        block_kind=SourceBlockKind.PARAGRAPH,
        paragraph_ordinal=1,
        block_hash=block_b_hash,
        anchor_before_hash=None,
        anchor_after_hash=None,
    )

    def split_segment(
        *,
        ordinal: int,
        source_range: Utf16Range,
        paragraph_ordinal: int,
        segment_ordinal_in_block: int,
        block_key: str,
        block_hash: str,
    ) -> SegmentContract:
        segment_text = utf16_slice(source, source_range)
        local_hash = text_sha256(segment_text)
        return replace(
            script.segments[0],
            segment_id=derive_segment_id(
                script_version_id=script.script_version_id,
                ordinal=ordinal,
                source_block_key=block_key,
                segment_ordinal_in_block=segment_ordinal_in_block,
                local_hash=local_hash,
            ),
            ordinal=ordinal,
            paragraph_ordinal=paragraph_ordinal,
            segment_ordinal_in_block=segment_ordinal_in_block,
            source_block_key=block_key,
            source_block_hash=block_hash,
            source_range_utf16=source_range,
            source_text=segment_text,
            spoken_text=segment_text,
            local_hash=local_hash,
        )

    interleaved_script = _rebuild_contract(
        script,
        segments=(
            split_segment(
                ordinal=0,
                source_range=Utf16Range(0, 1),
                paragraph_ordinal=0,
                segment_ordinal_in_block=0,
                block_key=block_a_key,
                block_hash=block_a_hash,
            ),
            split_segment(
                ordinal=1,
                source_range=Utf16Range(1, 3),
                paragraph_ordinal=1,
                segment_ordinal_in_block=0,
                block_key=block_b_key,
                block_hash=block_b_hash,
            ),
            split_segment(
                ordinal=2,
                source_range=Utf16Range(3, 4),
                paragraph_ordinal=0,
                segment_ordinal_in_block=1,
                block_key=block_a_key,
                block_hash=block_a_hash,
            ),
        ),
    )
    with pytest.raises(ScriptContractError, match="one contiguous source sequence"):
        validate_source_mapping(source, interleaved_script)
    with pytest.raises(ScriptContractError, match="one contiguous source sequence"):
        _script_contract_from_dict(
            script_contract_to_dict(interleaved_script),
            authority=_authority(interleaved_script),
            source_text=source,
        )

    first_reverse_hash = text_sha256("夜")
    second_reverse_hash = text_sha256("🌙。")
    first_reverse_key = derive_source_block_key(
        script_version_id=script.script_version_id,
        block_kind=SourceBlockKind.PARAGRAPH,
        paragraph_ordinal=1,
        block_hash=first_reverse_hash,
        anchor_before_hash=None,
        anchor_after_hash=None,
    )
    second_reverse_key = derive_source_block_key(
        script_version_id=script.script_version_id,
        block_kind=SourceBlockKind.PARAGRAPH,
        paragraph_ordinal=0,
        block_hash=second_reverse_hash,
        anchor_before_hash=None,
        anchor_after_hash=None,
    )
    reversed_paragraphs = _rebuild_contract(
        script,
        segments=(
            split_segment(
                ordinal=0,
                source_range=Utf16Range(0, 1),
                paragraph_ordinal=1,
                segment_ordinal_in_block=0,
                block_key=first_reverse_key,
                block_hash=first_reverse_hash,
            ),
            split_segment(
                ordinal=1,
                source_range=Utf16Range(1, 4),
                paragraph_ordinal=0,
                segment_ordinal_in_block=0,
                block_key=second_reverse_key,
                block_hash=second_reverse_hash,
            ),
        ),
    )
    with pytest.raises(ScriptContractError, match="paragraph ordinals"):
        _script_contract_from_dict(
            script_contract_to_dict(reversed_paragraphs),
            authority=_authority(reversed_paragraphs),
            source_text=source,
        )
