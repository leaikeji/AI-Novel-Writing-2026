from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from backend.narration.cloud_analysis import (
    CLOUD_CONSENT_DATA_SCOPE,
    CLOUD_CONSENT_NOTICE_VERSION,
    CLOUD_CONSENT_PURPOSE,
    BoundSpeakerCandidate,
    CloudAnalysisFailure,
    CloudAnalysisFailureCode,
    CloudAnalysisScope,
    CloudConsentSnapshot,
    CloudSourceSegment,
    HmacDigestKey,
    analyze_cloud_window,
    analyze_uncertain_segments,
    build_minimal_cloud_windows,
    cloud_request_for_window,
)
from backend.narration.contracts import ConfidenceLevel
from backend.narration.fingerprints import canonical_json_bytes
from backend.narration.script_contracts import (
    AttributionOrigin,
    CastingDecision,
    CastingDecisionOrigin,
    CastingTargetKind,
    CastingTargetRef,
    CloudAuthorityRecord,
    SpeakerKind,
    SpeakerRef,
    speaker_target_hash,
    text_sha256,
)
from backend.narration.speaker_model import (
    MAX_CONTEXT_CHARACTERS,
    ModelIdentity,
    SpeakerEvidenceCode,
    SpeakerModelCandidate,
    SpeakerModelContractError,
    SpeakerModelDecision,
    SpeakerModelUnavailableError,
    TrustedSpeakerModelReply,
    parse_speaker_model_response,
    speaker_model_decision_to_json,
    speaker_model_decision_to_payload,
    speaker_model_request_from_payload,
    speaker_model_request_to_json,
    speaker_model_request_to_payload,
)

NOVEL_ID = UUID("11111111-1111-4111-8111-111111111111")
DOCUMENT_ID = UUID("22222222-2222-4222-8222-222222222222")
REVISION_ID = UUID("33333333-3333-4333-8333-333333333333")
CONSENT_ID = UUID("44444444-4444-4444-8444-444444444444")
CHARACTER_ID = UUID("55555555-5555-4555-8555-555555555555")
BINDING_ID = UUID("66666666-6666-4666-8666-666666666666")
PROFILE_ID = UUID("77777777-7777-4777-8777-777777777777")
MODEL_RUN_ID = UUID("88888888-8888-4888-8888-888888888888")
MODEL_FINGERPRINT = "a" * 64
HMAC_SECRET = b"cloud-analysis-test-key-material!!"


def _identity(*, fingerprint: str = MODEL_FINGERPRINT) -> ModelIdentity:
    return ModelIdentity("fake-provider", "fake-speaker-model", fingerprint)


def _scope() -> CloudAnalysisScope:
    return CloudAnalysisScope(NOVEL_ID, DOCUMENT_ID, REVISION_ID)


def _consent(
    *,
    active: bool = True,
    novel_id: UUID = NOVEL_ID,
    provider_id: str = "fake-provider",
    model_id: str = "fake-speaker-model",
) -> CloudConsentSnapshot:
    return CloudConsentSnapshot(
        consent_id=CONSENT_ID,
        novel_id=novel_id,
        version=3,
        active=active,
        provider_id=provider_id,
        model_id=model_id,
    )


def _digest_key() -> HmacDigestKey:
    return HmacDigestKey("tts-cloud-test-key-v1", HMAC_SECRET)


def _narrator_candidate() -> BoundSpeakerCandidate:
    speaker = SpeakerRef(SpeakerKind.NARRATOR)
    target = CastingTargetRef(CastingTargetKind.PROFILE, profile_id=PROFILE_ID)
    return BoundSpeakerCandidate(
        model_candidate=SpeakerModelCandidate(
            speaker=speaker,
            display_name="旁白",
            aliases=(),
            role_hint="叙述者",
        ),
        casting=CastingDecision(
            candidate_targets=(target,),
            final_target=target,
            origin=CastingDecisionOrigin.NARRATOR_SETTING,
        ),
    )


def _character_candidate() -> BoundSpeakerCandidate:
    speaker = SpeakerRef(SpeakerKind.CHARACTER, character_id=CHARACTER_ID)
    target = CastingTargetRef(
        CastingTargetKind.CHARACTER_BINDING,
        binding_id=BINDING_ID,
        character_id=CHARACTER_ID,
    )
    return BoundSpeakerCandidate(
        model_candidate=SpeakerModelCandidate(
            speaker=speaker,
            display_name="林遥",
            aliases=("小林", "林遥"),
            role_hint="当前场景人物",
        ),
        casting=CastingDecision(
            candidate_targets=(target,),
            final_target=target,
            origin=CastingDecisionOrigin.CHARACTER_BINDING,
        ),
    )


def _segment(
    ordinal: int,
    text: str,
    *,
    uncertain: bool,
    segment_id: UUID | None = None,
) -> CloudSourceSegment:
    return CloudSourceSegment(
        segment_id=segment_id or uuid4(),
        ordinal=ordinal,
        source_text=text,
        source_local_hash=text_sha256(text),
        needs_cloud_analysis=uncertain,
        candidates=(
            (_character_candidate(), _narrator_candidate()) if uncertain else ()
        ),
        scene_hint="雨夜门廊" if uncertain else None,
        previous_speaker=SpeakerRef(SpeakerKind.NARRATOR) if uncertain else None,
    )


def _character_decision(segment_id: UUID) -> SpeakerModelDecision:
    return SpeakerModelDecision(
        segment_id=segment_id,
        speaker=SpeakerRef(SpeakerKind.CHARACTER, character_id=CHARACTER_ID),
        confidence=ConfidenceLevel.HIGH,
        evidence_codes=(
            SpeakerEvidenceCode.ALIAS_MATCH,
            SpeakerEvidenceCode.EXPLICIT_SPEECH_TAG,
        ),
    )


class FakeSpeakerModel:
    def __init__(
        self,
        response_json: str,
        *,
        actual_identity: ModelIdentity | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.response_json = response_json
        self.actual_identity = actual_identity or _identity()
        self.failure = failure
        self.calls: list[tuple[str, ModelIdentity]] = []

    async def analyze_speaker(
        self,
        *,
        request_json: str,
        requested_identity: ModelIdentity,
    ) -> TrustedSpeakerModelReply:
        self.calls.append((request_json, requested_identity))
        if self.failure is not None:
            raise self.failure
        return TrustedSpeakerModelReply(
            actual_identity=self.actual_identity,
            response_json=self.response_json,
        )


class FakeGuard:
    def __init__(
        self,
        *,
        consent_answers: list[bool] | None = None,
        source_answers: list[bool] | None = None,
    ) -> None:
        self.consent_answers = list(consent_answers or [])
        self.source_answers = list(source_answers or [])
        self.consent_checks = 0
        self.source_checks: list[tuple[UUID, str]] = []

    def consent_is_active(self, **_: object) -> bool:
        self.consent_checks += 1
        return self.consent_answers.pop(0) if self.consent_answers else True

    def source_is_current(
        self,
        *,
        segment_id: UUID,
        source_local_hash: str,
        **_: object,
    ) -> bool:
        self.source_checks.append((segment_id, source_local_hash))
        return self.source_answers.pop(0) if self.source_answers else True


def _one_window() -> tuple[CloudSourceSegment, object]:
    target = _segment(0, "“你终于来了。”林遥说。", uncertain=True)
    return target, build_minimal_cloud_windows((target,))[0]


def _assert_failure(error: pytest.ExceptionInfo[CloudAnalysisFailure], code: str) -> None:
    assert error.value.code.value == code
    assert "林遥" not in str(error.value)
    assert "你终于来了" not in str(error.value)


def test_minimal_windows_only_target_uncertain_segments_and_overlap_context() -> None:
    previous_text = "前" * (MAX_CONTEXT_CHARACTERS + 40)
    following_text = "后" * (MAX_CONTEXT_CHARACTERS + 40)
    previous = _segment(0, previous_text, uncertain=False)
    first = _segment(1, "第一句不确定对白。", uncertain=True)
    second = _segment(2, "第二句不确定对白。", uncertain=True)
    following = _segment(3, following_text, uncertain=False)

    windows = build_minimal_cloud_windows((previous, first, second, following))

    assert tuple(item.target.segment_id for item in windows) == (
        first.segment_id,
        second.segment_id,
    )
    assert windows[0].context_before == (previous,)
    assert windows[0].context_after == (second,)
    assert windows[1].context_before == (first,)
    assert windows[1].context_after == (following,)

    first_request = cloud_request_for_window(windows[0])
    second_request = cloud_request_for_window(windows[1])
    assert first_request.context_before[0].text == previous_text[-MAX_CONTEXT_CHARACTERS:]
    assert first_request.context_before[0].truncated is True
    assert second_request.context_after[0].text == following_text[:MAX_CONTEXT_CHARACTERS]
    assert second_request.context_after[0].truncated is True
    assert first_request.target.text == first.source_text
    assert first_request.target.truncated is False


def test_strict_request_schema_has_only_the_frozen_privacy_minimal_fields() -> None:
    before = _segment(0, "雨声盖住脚步。", uncertain=False)
    target = _segment(1, "“你终于来了。”林遥说。", uncertain=True)
    after = _segment(2, "门外无人回应。", uncertain=False)
    request = cloud_request_for_window(
        build_minimal_cloud_windows((before, target, after))[0]
    )
    payload = speaker_model_request_to_payload(request)
    request_json = speaker_model_request_to_json(request)

    assert set(payload) == {
        "schema_version",
        "template_version",
        "task",
        "target",
        "context_before",
        "context_after",
        "scene_hint",
        "previous_speaker",
        "candidates",
    }
    assert set(payload["target"]) == {"segment_id", "text", "truncated"}
    assert len(payload["context_before"]) == 1
    assert len(payload["context_after"]) == 1
    assert len(payload["candidates"]) == 2
    assert all(
        set(candidate) == {"speaker", "display_name", "aliases", "role_hint"}
        for candidate in payload["candidates"]
    )
    forbidden = {
        "novel_id",
        "document_id",
        "revision_id",
        "consent_id",
        "model_run_id",
        "source_local_hash",
        "requested_model_fingerprint",
        "actual_model_fingerprint",
        "reference_audio",
        "full_character_card",
    }
    assert all(field not in request_json for field in forbidden)
    assert speaker_model_request_from_payload(json.loads(request_json)) == (
        speaker_model_request_from_payload(payload)
    )

    payload["unexpected"] = True
    with pytest.raises(SpeakerModelContractError, match="unknown or missing"):
        speaker_model_request_from_payload(payload)


@pytest.mark.asyncio
async def test_authorized_success_binds_exact_t3a_authority_and_hmac_evidence() -> None:
    before = _segment(0, "雨声盖住脚步。", uncertain=False)
    target = _segment(1, "“你终于来了。”林遥说。", uncertain=True)
    after = _segment(2, "门外无人回应。", uncertain=False)
    window = build_minimal_cloud_windows((before, target, after))[0]
    decision = _character_decision(target.segment_id)
    adapter = FakeSpeakerModel(speaker_model_decision_to_json(decision))
    guard = FakeGuard()
    digest_key = _digest_key()

    result = await analyze_cloud_window(
        scope=_scope(),
        window=window,
        consent=_consent(),
        model_run_id=MODEL_RUN_ID,
        requested_identity=_identity(),
        digest_key=digest_key,
        guard=guard,
        adapter=adapter,
    )

    assert len(adapter.calls) == 1
    request_json, requested = adapter.calls[0]
    assert requested == _identity()
    assert result.requested_identity == result.actual_identity == _identity()
    assert result.speaker == decision.speaker
    assert result.casting == _character_candidate().casting
    assert result.attribution.origin is AttributionOrigin.CLOUD_ASSISTED
    assert result.attribution.consent_id == CONSENT_ID
    assert result.attribution.model_run_id == MODEL_RUN_ID
    assert result.attribution.candidate_character_ids == (CHARACTER_ID,)
    assert result.attribution.input_digest_key_id == digest_key.key_id
    assert result.attribution.input_digest == hmac.new(
        HMAC_SECRET,
        request_json.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    assert result.attribution.input_digest != hashlib.sha256(
        request_json.encode("utf-8")
    ).hexdigest()
    assert result.attribution.output_digest == hmac.new(
        HMAC_SECRET,
        canonical_json_bytes(speaker_model_decision_to_payload(decision)),
        hashlib.sha256,
    ).hexdigest()
    assert type(result.authority) is CloudAuthorityRecord
    assert result.authority.segment_id == target.segment_id
    assert result.authority.source_local_hash == target.source_local_hash
    assert result.authority.model_fingerprint == MODEL_FINGERPRINT
    assert result.authority.speaker_target_hash == speaker_target_hash(
        result.speaker, result.casting
    )
    assert guard.consent_checks == 2
    assert guard.source_checks == [
        (before.segment_id, before.source_local_hash),
        (target.segment_id, target.source_local_hash),
        (after.segment_id, after.source_local_hash),
    ] * 2
    assert "actual_model" not in adapter.response_json
    assert HMAC_SECRET.decode("ascii") not in repr(result)


@pytest.mark.asyncio
async def test_inactive_or_stale_consent_makes_zero_model_calls() -> None:
    target, window = _one_window()
    adapter = FakeSpeakerModel(
        speaker_model_decision_to_json(_character_decision(target.segment_id))
    )

    with pytest.raises(CloudAnalysisFailure) as inactive:
        await analyze_cloud_window(
            scope=_scope(),
            window=window,
            consent=_consent(active=False),
            model_run_id=MODEL_RUN_ID,
            requested_identity=_identity(),
            digest_key=_digest_key(),
            guard=FakeGuard(),
            adapter=adapter,
        )
    _assert_failure(inactive, "F_CONSENT_REVOKED_BEFORE_CALL")
    assert adapter.calls == []

    with pytest.raises(CloudAnalysisFailure) as stale:
        await analyze_cloud_window(
            scope=_scope(),
            window=window,
            consent=_consent(),
            model_run_id=MODEL_RUN_ID,
            requested_identity=_identity(),
            digest_key=_digest_key(),
            guard=FakeGuard(consent_answers=[False]),
            adapter=adapter,
        )
    _assert_failure(stale, "F_CONSENT_REVOKED_BEFORE_CALL")
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_consent_model_or_novel_scope_mismatch_makes_zero_calls() -> None:
    target, window = _one_window()
    adapter = FakeSpeakerModel(
        speaker_model_decision_to_json(_character_decision(target.segment_id))
    )
    for consent in (
        _consent(model_id="other-model"),
        _consent(novel_id=uuid4()),
    ):
        with pytest.raises(CloudAnalysisFailure) as error:
            await analyze_cloud_window(
                scope=_scope(),
                window=window,
                consent=consent,
                model_run_id=MODEL_RUN_ID,
                requested_identity=_identity(),
                digest_key=_digest_key(),
                guard=FakeGuard(),
                adapter=adapter,
            )
        _assert_failure(error, "F_SCOPE_VIOLATION")
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_no_uncertain_segment_requires_no_consent_and_no_model_call() -> None:
    certain = _segment(0, "这是明确旁白。", uncertain=False)
    adapter = FakeSpeakerModel("not used")
    guard = FakeGuard(consent_answers=[False])

    result = await analyze_uncertain_segments(
        scope=_scope(),
        segments=(certain,),
        consent=_consent(active=False),
        model_run_ids={},
        requested_identity=_identity(),
        digest_key=_digest_key(),
        guard=guard,
        adapter=adapter,
    )

    assert result == ()
    assert adapter.calls == []
    assert guard.consent_checks == 0


@pytest.mark.asyncio
async def test_requested_actual_identity_mismatch_is_discarded_without_fallback() -> None:
    target, window = _one_window()
    adapter = FakeSpeakerModel(
        speaker_model_decision_to_json(_character_decision(target.segment_id)),
        actual_identity=_identity(fingerprint="b" * 64),
    )

    with pytest.raises(CloudAnalysisFailure) as error:
        await analyze_cloud_window(
            scope=_scope(),
            window=window,
            consent=_consent(),
            model_run_id=MODEL_RUN_ID,
            requested_identity=_identity(),
            digest_key=_digest_key(),
            guard=FakeGuard(),
            adapter=adapter,
        )

    _assert_failure(error, "F_MODEL_IDENTITY_MISMATCH")
    assert len(adapter.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response_json",
    [
        "{}",
        '{"schema_version":"narration-cloud-speaker-response/1",'
        '"schema_version":"narration-cloud-speaker-response/1"}',
        '{"schema_version":NaN}',
        json.dumps(
            {
                **speaker_model_decision_to_payload(
                    _character_decision(UUID("99999999-9999-4999-8999-999999999999"))
                ),
                "model_id": "self-reported-model",
            }
        ),
    ],
)
async def test_malformed_duplicate_nonfinite_or_extra_response_is_schema_failure(
    response_json: str,
) -> None:
    _target, window = _one_window()
    adapter = FakeSpeakerModel(response_json)

    with pytest.raises(CloudAnalysisFailure) as error:
        await analyze_cloud_window(
            scope=_scope(),
            window=window,
            consent=_consent(),
            model_run_id=MODEL_RUN_ID,
            requested_identity=_identity(),
            digest_key=_digest_key(),
            guard=FakeGuard(),
            adapter=adapter,
        )

    _assert_failure(error, "F_MODEL_OUTPUT_SCHEMA_INVALID")
    assert len(adapter.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign_kind", ["segment", "character"])
async def test_foreign_segment_or_character_id_is_scope_failure(
    foreign_kind: str,
) -> None:
    target, window = _one_window()
    if foreign_kind == "segment":
        decision = _character_decision(uuid4())
    else:
        decision = replace(
            _character_decision(target.segment_id),
            speaker=SpeakerRef(SpeakerKind.CHARACTER, character_id=uuid4()),
        )
    adapter = FakeSpeakerModel(speaker_model_decision_to_json(decision))

    with pytest.raises(CloudAnalysisFailure) as error:
        await analyze_cloud_window(
            scope=_scope(),
            window=window,
            consent=_consent(),
            model_run_id=MODEL_RUN_ID,
            requested_identity=_identity(),
            digest_key=_digest_key(),
            guard=FakeGuard(),
            adapter=adapter,
        )

    _assert_failure(error, "F_SCOPE_VIOLATION")
    assert len(adapter.calls) == 1


@pytest.mark.asyncio
async def test_source_change_before_call_is_zero_io_and_late_change_discards_reply() -> None:
    target, window = _one_window()
    response = speaker_model_decision_to_json(_character_decision(target.segment_id))
    before_adapter = FakeSpeakerModel(response)
    with pytest.raises(CloudAnalysisFailure) as before:
        await analyze_cloud_window(
            scope=_scope(),
            window=window,
            consent=_consent(),
            model_run_id=MODEL_RUN_ID,
            requested_identity=_identity(),
            digest_key=_digest_key(),
            guard=FakeGuard(source_answers=[False]),
            adapter=before_adapter,
        )
    _assert_failure(before, "F_INPUT_FINGERPRINT_CHANGED")
    assert before_adapter.calls == []

    late_adapter = FakeSpeakerModel(response)
    with pytest.raises(CloudAnalysisFailure) as late:
        await analyze_cloud_window(
            scope=_scope(),
            window=window,
            consent=_consent(),
            model_run_id=MODEL_RUN_ID,
            requested_identity=_identity(),
            digest_key=_digest_key(),
            guard=FakeGuard(source_answers=[True, False]),
            adapter=late_adapter,
        )
    _assert_failure(late, "F_INPUT_FINGERPRINT_CHANGED")
    assert len(late_adapter.calls) == 1


@pytest.mark.asyncio
async def test_consent_revoked_during_call_discards_late_reply() -> None:
    target, window = _one_window()
    adapter = FakeSpeakerModel(
        speaker_model_decision_to_json(_character_decision(target.segment_id))
    )

    with pytest.raises(CloudAnalysisFailure) as error:
        await analyze_cloud_window(
            scope=_scope(),
            window=window,
            consent=_consent(),
            model_run_id=MODEL_RUN_ID,
            requested_identity=_identity(),
            digest_key=_digest_key(),
            guard=FakeGuard(consent_answers=[True, False]),
            adapter=adapter,
        )

    _assert_failure(error, "F_CONSENT_REVOKED_BEFORE_CALL")
    assert len(adapter.calls) == 1


@pytest.mark.asyncio
async def test_adapter_unavailable_and_runtime_failures_are_safe_and_classified() -> None:
    target, window = _one_window()
    base = dict(
        scope=_scope(),
        window=window,
        consent=_consent(),
        model_run_id=MODEL_RUN_ID,
        requested_identity=_identity(),
        digest_key=_digest_key(),
        guard=FakeGuard(),
    )
    with pytest.raises(CloudAnalysisFailure) as missing:
        await analyze_cloud_window(**base, adapter=None)
    _assert_failure(missing, "F_ADAPTER_UNAVAILABLE")

    unavailable_adapter = FakeSpeakerModel(
        "unused", failure=SpeakerModelUnavailableError("provider canary secret")
    )
    with pytest.raises(CloudAnalysisFailure) as unavailable:
        await analyze_cloud_window(**base, adapter=unavailable_adapter)
    _assert_failure(unavailable, "F_ADAPTER_UNAVAILABLE")
    assert "provider canary secret" not in str(unavailable.value)
    assert unavailable.value.__cause__ is None

    runtime_adapter = FakeSpeakerModel(
        "unused", failure=RuntimeError("private target canary")
    )
    with pytest.raises(CloudAnalysisFailure) as runtime:
        await analyze_cloud_window(**base, adapter=runtime_adapter)
    _assert_failure(runtime, "F_ANALYZER_RUNTIME")
    assert "private target canary" not in str(runtime.value)
    assert runtime.value.__cause__ is None


@pytest.mark.asyncio
async def test_unknown_is_safe_unresolved_decision_with_exact_authority() -> None:
    target, window = _one_window()
    decision = SpeakerModelDecision(
        segment_id=target.segment_id,
        speaker=SpeakerRef(SpeakerKind.UNKNOWN),
        confidence=ConfidenceLevel.UNKNOWN,
        evidence_codes=(SpeakerEvidenceCode.INSUFFICIENT_EVIDENCE,),
    )
    adapter = FakeSpeakerModel(speaker_model_decision_to_json(decision))

    result = await analyze_cloud_window(
        scope=_scope(),
        window=window,
        consent=_consent(),
        model_run_id=MODEL_RUN_ID,
        requested_identity=_identity(),
        digest_key=_digest_key(),
        guard=FakeGuard(),
        adapter=adapter,
    )

    assert result.speaker.kind is SpeakerKind.UNKNOWN
    assert result.casting.origin is CastingDecisionOrigin.UNRESOLVED
    assert result.casting.final_target is None
    assert result.authority.speaker_target_hash == speaker_target_hash(
        result.speaker, result.casting
    )


@pytest.mark.asyncio
async def test_batch_requires_exact_unique_model_run_mapping_and_calls_only_targets() -> None:
    certain = _segment(0, "这是明确旁白。", uncertain=False)
    first = _segment(1, "第一句不确定对白。", uncertain=True)
    second = _segment(2, "第二句不确定对白。", uncertain=True)
    run_one = uuid4()
    run_two = uuid4()
    responses = {
        first.segment_id: speaker_model_decision_to_json(
            _character_decision(first.segment_id)
        ),
        second.segment_id: speaker_model_decision_to_json(
            _character_decision(second.segment_id)
        ),
    }

    class PerTargetFake(FakeSpeakerModel):
        async def analyze_speaker(
            self, *, request_json: str, requested_identity: ModelIdentity
        ) -> TrustedSpeakerModelReply:
            self.calls.append((request_json, requested_identity))
            request = speaker_model_request_from_payload(json.loads(request_json))
            return TrustedSpeakerModelReply(
                actual_identity=self.actual_identity,
                response_json=responses[request.target.segment_id],
            )

    adapter = PerTargetFake("unused")
    results = await analyze_uncertain_segments(
        scope=_scope(),
        segments=(certain, first, second),
        consent=_consent(),
        model_run_ids={first.segment_id: run_one, second.segment_id: run_two},
        requested_identity=_identity(),
        digest_key=_digest_key(),
        guard=FakeGuard(),
        adapter=adapter,
    )
    assert tuple(item.segment_id for item in results) == (
        first.segment_id,
        second.segment_id,
    )
    assert tuple(item.model_run_id for item in results) == (run_one, run_two)
    assert len(adapter.calls) == 2

    with pytest.raises(CloudAnalysisFailure) as missing:
        await analyze_uncertain_segments(
            scope=_scope(),
            segments=(certain, first, second),
            consent=_consent(),
            model_run_ids={first.segment_id: run_one},
            requested_identity=_identity(),
            digest_key=_digest_key(),
            guard=FakeGuard(),
            adapter=adapter,
        )
    _assert_failure(missing, "F_SCOPE_VIOLATION")
    assert len(adapter.calls) == 2

    with pytest.raises(CloudAnalysisFailure) as duplicate_run:
        await analyze_uncertain_segments(
            scope=_scope(),
            segments=(certain, first, second),
            consent=_consent(),
            model_run_ids={first.segment_id: run_one, second.segment_id: run_one},
            requested_identity=_identity(),
            digest_key=_digest_key(),
            guard=FakeGuard(),
            adapter=adapter,
        )
    _assert_failure(duplicate_run, "F_SCOPE_VIOLATION")
    assert len(adapter.calls) == 2


def test_contract_versions_consent_shape_and_response_identity_are_frozen() -> None:
    consent = _consent()
    assert consent.purpose == CLOUD_CONSENT_PURPOSE
    assert consent.data_scope == CLOUD_CONSENT_DATA_SCOPE
    assert consent.notice_version == CLOUD_CONSENT_NOTICE_VERSION

    decision = _character_decision(uuid4())
    parsed = parse_speaker_model_response(speaker_model_decision_to_json(decision))
    assert parsed == decision
    payload = speaker_model_decision_to_payload(parsed)
    assert set(payload) == {
        "schema_version",
        "segment_id",
        "speaker",
        "confidence",
        "evidence_codes",
    }
    assert "actual_model" not in payload


def test_hmac_key_and_bound_candidate_fail_closed() -> None:
    with pytest.raises(ValueError, match="at least 32"):
        HmacDigestKey("short-key", b"too-short")
    with pytest.raises(ValueError, match="bound"):
        BoundSpeakerCandidate(
            model_candidate=_character_candidate().model_candidate,
            casting=_narrator_candidate().casting,
        )
    with pytest.raises(ValueError, match="source_local_hash"):
        replace(
            _segment(0, "原始句段。", uncertain=True),
            source_local_hash="f" * 64,
        )
