from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest

from backend.narration.contracts import (
    APP_ID,
    BLOCKER_CODES,
    LOCAL_OWNER_ID,
    LOCAL_WORKSPACE_ID,
    NARRATION_REVIEW_TAXONOMY_VERSION,
    WARNING_CODES,
    WORKFLOW_FAILURE_CODES,
    AdapterCapabilities,
    AdapterKind,
    CancellationGranularity,
    ContractError,
    ModelFingerprint,
    NanoDecodeParametersV2,
    NarrationRequestScope,
    ReferenceAudioInput,
    ReviewIssue,
    ReviewIssueSeverity,
    SynthesisRequest,
    SynthesisResult,
    UnknownTaxonomyCodeError,
    ensure_workflow_failure_code,
    issue_severity,
)
from backend.narration.runtime import canonical_sidecar_synthesis_metadata
from backend.narration.fingerprints import (
    FingerprintContractError,
    canonical_fingerprint,
    canonical_json_bytes,
    edition_fingerprint,
    model_fingerprint_sha256,
    render_fingerprint,
    scope_fingerprint,
)

FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "narration"
    / "review-taxonomy-v1.json"
)


def _model_fingerprint() -> ModelFingerprint:
    return ModelFingerprint(
        adapter_contract_version="moss-nano-tts-adapter/1",
        model_name="OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX",
        model_revision="f52645cb467506d8e18e746ddd59482685b74e58",
        artifact_tree_sha256="a" * 64,
        runtime_name="onnxruntime",
        runtime_version="1.24.3",
        execution_backend="onnx-cpu",
        protocol_version="moss-nano-sidecar/1",
        deployment_topology="linux-arm64-private-sidecar",
        parameters={"threads": 4, "streaming": True},
    )


def test_nano_decode_v2_is_fixed_point_bounded_and_full_mode_only() -> None:
    parameters = NanoDecodeParametersV2(
        text_temperature_milli=1_100,
        audio_top_p_milli=900,
    )
    request = SynthesisRequest(
        request_id=uuid4(),
        scope=NarrationRequestScope.fixed_local(),
        text="高级参数契约测试。",
        voice="onnx.Zhiming",
        seed=1234,
        sample_mode="full",
        max_new_frames=375,
        decode_parameters=parameters,
    )

    payload = json.loads(
        canonical_sidecar_synthesis_metadata(
            request_id=request.request_id,
            scope=request.scope,
            requested_model_fingerprint_sha256="0" * 64,
            text=request.text,
            voice=request.voice,
            seed=request.seed,
            sample_mode=request.sample_mode,
            max_new_frames=request.max_new_frames,
            decode_parameters=request.decode_parameters,
        )
    )

    assert payload["decode_parameters"] == dict(parameters.wire_payload())
    assert all(
        not isinstance(value, float)
        for value in payload["decode_parameters"].values()
    )
    with pytest.raises(ContractError, match="full mode"):
        replace(request, sample_mode="fixed")
    with pytest.raises(ContractError, match="text_temperature"):
        NanoDecodeParametersV2(text_temperature_milli=99)


def test_fixed_scope_matches_accepted_uuidv5_values_and_rejects_override() -> None:
    scope = NarrationRequestScope.fixed_local().ensure_fixed_local()
    assert scope.owner_id == uuid5(
        NAMESPACE_URL, "app://ai-novel-world-2026/local-owner/v1"
    )
    assert scope.workspace_id == uuid5(
        NAMESPACE_URL, "app://ai-novel-world-2026/local-workspace/v1"
    )
    assert scope.owner_id == LOCAL_OWNER_ID
    assert scope.workspace_id == LOCAL_WORKSPACE_ID
    assert scope.app_id == APP_ID
    assert scope.is_local_only is True
    with pytest.raises(ContractError, match="fixed server-side"):
        replace(scope, owner_id=uuid4()).ensure_fixed_local()


def test_taxonomy_fixture_exactly_matches_public_constants() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture["schema_version"] == NARRATION_REVIEW_TAXONOMY_VERSION
    assert tuple(item["code"] for item in fixture["warnings"]) == WARNING_CODES
    assert tuple(item["code"] for item in fixture["blockers"]) == BLOCKER_CODES
    assert tuple(item["code"] for item in fixture["workflow_failures"]) == (
        WORKFLOW_FAILURE_CODES
    )
    assert len(set(WARNING_CODES + BLOCKER_CODES + WORKFLOW_FAILURE_CODES)) == 25
    assert fixture["unknown_code_policy"]["review_issue"] == "reject_fail_closed"


@pytest.mark.parametrize("code", WARNING_CODES)
def test_warning_severity_is_server_owned(code: str) -> None:
    assert issue_severity(code) is ReviewIssueSeverity.WARNING
    ReviewIssue(code=code, severity=ReviewIssueSeverity.WARNING)
    with pytest.raises(ContractError, match="server-owned"):
        ReviewIssue(code=code, severity=ReviewIssueSeverity.BLOCKER)


@pytest.mark.parametrize("code", BLOCKER_CODES)
def test_blocker_severity_is_server_owned(code: str) -> None:
    assert issue_severity(code) is ReviewIssueSeverity.BLOCKER
    ReviewIssue(code=code, severity=ReviewIssueSeverity.BLOCKER)


@pytest.mark.parametrize("code", WORKFLOW_FAILURE_CODES)
def test_workflow_failures_are_not_review_issues(code: str) -> None:
    assert ensure_workflow_failure_code(code) == code
    with pytest.raises(UnknownTaxonomyCodeError):
        issue_severity(code)


def test_unknown_taxonomy_code_and_version_fail_closed() -> None:
    with pytest.raises(UnknownTaxonomyCodeError):
        issue_severity("W_FUTURE_UNFROZEN")
    with pytest.raises(UnknownTaxonomyCodeError):
        ensure_workflow_failure_code("F_FUTURE_UNFROZEN")
    with pytest.raises(ContractError, match="version"):
        ReviewIssue(
            code=WARNING_CODES[0],
            severity=ReviewIssueSeverity.WARNING,
            taxonomy_version="narration-review-taxonomy/2",
        )


def test_capabilities_reject_inconsistent_or_visible_fake_claims() -> None:
    with pytest.raises(ContractError, match="cancel granularity"):
        AdapterCapabilities(
            adapter_kind=AdapterKind.MOSS_NANO_TTS,
            supports_warmup=True,
            supports_synthesis=True,
            supports_cancel=False,
            cancellation_granularity=CancellationGranularity.SEGMENT_BOUNDARY,
            supports_reference_audio=False,
            supports_streaming_response_bytes=True,
            supports_voice_design=False,
            max_inference_concurrency=1,
        )
    with pytest.raises(ContractError, match="test doubles"):
        AdapterCapabilities(
            adapter_kind=AdapterKind.MOSS_NANO_TTS,
            supports_warmup=True,
            supports_synthesis=True,
            supports_cancel=True,
            cancellation_granularity=CancellationGranularity.SEGMENT_BOUNDARY,
            supports_reference_audio=False,
            supports_streaming_response_bytes=True,
            supports_voice_design=False,
            max_inference_concurrency=1,
            is_test_double=True,
            product_visible=True,
            production_ready=True,
        )


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("supports_warmup", 1),
        ("supports_synthesis", "false"),
        ("product_visible", "false"),
        ("production_ready", 1),
        ("max_inference_concurrency", True),
        ("adapter_kind", "moss_nano_tts"),
        ("cancellation_granularity", "segment_boundary"),
    ],
)
def test_capabilities_reject_non_exact_runtime_types(
    field_name: str,
    invalid_value: object,
) -> None:
    valid = AdapterCapabilities(
        adapter_kind=AdapterKind.MOSS_NANO_TTS,
        supports_warmup=True,
        supports_synthesis=True,
        supports_cancel=True,
        cancellation_granularity=CancellationGranularity.SEGMENT_BOUNDARY,
        supports_reference_audio=True,
        supports_streaming_response_bytes=True,
        supports_voice_design=False,
        max_inference_concurrency=1,
    )
    with pytest.raises(ContractError):
        replace(valid, **{field_name: invalid_value})


def test_model_fingerprint_parameters_are_scalar_and_cannot_drift() -> None:
    source = {"threads": 4, "streaming": True, "label": "cpu", "optional": None}
    fingerprint = replace(_model_fingerprint(), parameters=source)
    before = model_fingerprint_sha256(fingerprint)
    source["threads"] = 8
    assert model_fingerprint_sha256(fingerprint) == before
    assert fingerprint.parameters["threads"] == 4

    for invalid in ({"nested": [1]}, {"nested": {"x": 1}}, {"nested": 1.5}):
        with pytest.raises(ContractError, match="scalar"):
            replace(_model_fingerprint(), parameters=invalid)


def test_adapter_health_rejects_string_status() -> None:
    from backend.narration.contracts import AdapterHealth

    with pytest.raises(ContractError, match="AdapterHealthStatus"):
        AdapterHealth(
            status="healthy",  # type: ignore[arg-type]
            capabilities_sha256="a" * 64,
            model_fingerprint_sha256=None,
        )


def test_reference_and_output_hashes_are_actual_bytes_hashes() -> None:
    reference_bytes = b"RIFF-reference"
    reference = ReferenceAudioInput(
        audio_bytes=reference_bytes,
        actual_sha256=hashlib.sha256(reference_bytes).hexdigest(),
    )
    assert reference.audio_bytes == reference_bytes
    with pytest.raises(ContractError, match="does not match"):
        replace(reference, actual_sha256="0" * 64)

    output_bytes = b"RIFF-output"
    result = SynthesisResult(
        request_id=uuid4(),
        audio_bytes=output_bytes,
        actual_output_sha256=hashlib.sha256(output_bytes).hexdigest(),
        sample_rate_hz=48_000,
        channels=2,
        sample_width_bytes=2,
        model_fingerprint=_model_fingerprint(),
        worker_generation=1,
    )
    with pytest.raises(ContractError, match="does not match"):
        replace(result, actual_output_sha256="0" * 64)


def test_canonical_json_is_order_stable_and_unicode_nfc() -> None:
    left = {"z": [1, True], "name": "e\u0301"}
    right = {"name": "\u00e9", "z": [1, True]}
    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert edition_fingerprint(left) == edition_fingerprint(right)
    assert render_fingerprint(left) == render_fingerprint(right)
    assert edition_fingerprint(left) != render_fingerprint(left)


@pytest.mark.parametrize("bad", [b"private", 1.5, {1: "bad"}, {"a": {1, 2}}])
def test_canonical_json_rejects_ambiguous_input_types(bad: object) -> None:
    with pytest.raises(FingerprintContractError):
        canonical_json_bytes(bad)


def test_canonical_json_rejects_duplicate_keys_after_unicode_normalization() -> None:
    with pytest.raises(FingerprintContractError, match="duplicate keys"):
        canonical_json_bytes({"\u00e9": 1, "e\u0301": 2})


def test_unknown_fingerprint_version_fails_closed() -> None:
    with pytest.raises(FingerprintContractError, match="unknown"):
        canonical_fingerprint("narration-render-fingerprint/2", {"text": "x"})


def test_model_and_scope_fingerprints_are_stable_and_schema_separated() -> None:
    model = _model_fingerprint()
    assert model_fingerprint_sha256(model) == model_fingerprint_sha256(model)
    assert len(scope_fingerprint(NarrationRequestScope.fixed_local())) == 64
    assert model_fingerprint_sha256(model) != scope_fingerprint(
        NarrationRequestScope.fixed_local()
    )
