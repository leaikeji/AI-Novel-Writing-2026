from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from uuid import UUID, uuid4

import pytest

from backend.narration.contracts import LOCAL_WORKSPACE_ID
from backend.narration.generic_voice_generation import (
    GENERIC_VOICE_DESIGN_PATH,
    GENERIC_VOICE_JOB_KIND,
    GenericVoiceCompletionEvidence,
    GenericVoiceGenerationError,
    GenericVoiceGenerationService,
    GenericVoiceGenerationState,
    ensure_generation_transition,
    load_generic_voice_design_catalog,
    parse_generic_voice_design_catalog,
)
from backend.narration.runtime import EXPECTED_PRODUCTION_MODEL_FINGERPRINT_SHA256
from backend.narration.voice_generator_runtime import (
    EXPECTED_AUDIO_PARAMETERS,
    EXPECTED_RUNTIME_FINGERPRINT,
)
from backend.narration.voice_pool import load_voice_pool_catalog


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _evidence(
    service: GenericVoiceGenerationService,
    *,
    slot_key: str = "female_child_bright",
) -> tuple[object, GenericVoiceCompletionEvidence]:
    command_id = uuid4()
    plan = service.plan(
        command_id=command_id,
        slot_key=slot_key,
        workspace_id=LOCAL_WORKSPACE_ID,
        language="zh-CN",
    )
    evidence = GenericVoiceCompletionEvidence(
        command_id=command_id,
        workspace_id=LOCAL_WORKSPACE_ID,
        slot_key=slot_key,
        design_fingerprint=plan.design_fingerprint,
        request_id=plan.request.request_id,
        request_digest=plan.request.request_digest,
        profile_id=uuid4(),
        voice_version_id=uuid4(),
        profile_novel_id=None,
        language="zh-CN",
        source_kind="voice_generator",
        generator_model_fingerprint=EXPECTED_RUNTIME_FINGERPRINT,
        nano_model_fingerprint=EXPECTED_PRODUCTION_MODEL_FINGERPRINT_SHA256,
        reference_audio_sha256=_digest("reference"),
        validation_audio_sha256=_digest("validation"),
        rights_approved=True,
        quality_approved=True,
    )
    return plan, evidence


def test_design_catalog_exactly_covers_frozen_taxonomy_with_unique_designs() -> None:
    taxonomy = load_voice_pool_catalog()
    catalog = load_generic_voice_design_catalog(taxonomy=taxonomy)

    assert catalog.language == "zh-CN"
    assert catalog.usage_scope == "workspace_library_private_use"
    assert catalog.source_kind == "voice_generator"
    assert catalog.taxonomy_sha256 == taxonomy.catalog_sha256
    assert len(catalog.slots) == 24
    assert tuple(item.slot_key for item in catalog.slots) == tuple(
        item.slot_key for item in taxonomy.slots
    )
    assert len({item.seed for item in catalog.slots}) == 24
    assert len({item.instruction_sha256 for item in catalog.slots}) == 24
    assert len({item.design_fingerprint for item in catalog.slots}) == 24
    assert all(1 <= len(item.instruction) <= 1_200 for item in catalog.slots)
    # Seed 550012 deterministically exhausted the frozen 256-step product
    # bound in two real MPS runs; keep the replacement identity stable.
    assert next(
        item.seed for item in catalog.slots if item.slot_key == "male_young_warm"
    ) == 551012
    crowd_male = next(
        item for item in catalog.slots if item.slot_key == "crowd_male"
    )
    assert crowd_male.seed == 551024
    assert "单人声线" in crowd_male.instruction
    assert "不模拟多人合声" in crowd_male.instruction
    assert "语速偏快" in crowd_male.instruction
    assert "不拖腔" in crowd_male.instruction

    serialized = GENERIC_VOICE_DESIGN_PATH.read_text(encoding="utf-8").lower()
    assert "http://" not in serialized
    assert "https://" not in serialized
    assert ".wav" not in serialized
    assert "reference_audio" not in serialized


def test_design_catalog_fails_closed_on_shape_taxonomy_order_and_seed_drift() -> None:
    raw = json.loads(GENERIC_VOICE_DESIGN_PATH.read_text(encoding="utf-8"))

    unknown = {**raw, "unexpected": True}
    with pytest.raises(GenericVoiceGenerationError, match="unexpected shape"):
        parse_generic_voice_design_catalog(unknown)

    wrong_taxonomy = {**raw, "taxonomy_sha256": "0" * 64}
    with pytest.raises(GenericVoiceGenerationError) as taxonomy_failure:
        parse_generic_voice_design_catalog(wrong_taxonomy)
    assert taxonomy_failure.value.code == "GENERIC_VOICE_PACK_VERSION_CONFLICT"

    reordered = deepcopy(raw)
    reordered["slots"][0], reordered["slots"][1] = (
        reordered["slots"][1],
        reordered["slots"][0],
    )
    with pytest.raises(GenericVoiceGenerationError) as order_failure:
        parse_generic_voice_design_catalog(reordered)
    assert order_failure.value.code == "GENERIC_VOICE_PACK_INCOMPLETE"

    duplicate_seed = deepcopy(raw)
    duplicate_seed["slots"][1]["seed"] = duplicate_seed["slots"][0]["seed"]
    with pytest.raises(GenericVoiceGenerationError, match="seeds must be unique"):
        parse_generic_voice_design_catalog(duplicate_seed)


def test_service_builds_exact_existing_voice_generator_request() -> None:
    service = GenericVoiceGenerationService()
    command_id = UUID("10000000-0000-4000-8000-000000000001")
    design = service.design_for("male_middle_authoritative")

    plan = service.plan(
        command_id=command_id,
        slot_key=design.slot_key,
        workspace_id=LOCAL_WORKSPACE_ID,
        language="zh-CN",
    )

    assert plan.command_id == command_id
    assert plan.job_kind == GENERIC_VOICE_JOB_KIND
    assert plan.design_fingerprint == design.design_fingerprint
    assert plan.request.request_id == command_id
    assert plan.request.language == "zh-CN"
    assert plan.request.seed == design.seed
    assert plan.request.instruction_digest == design.instruction_sha256
    assert plan.request.audio_parameters == EXPECTED_AUDIO_PARAMETERS
    assert plan.request.runtime_identity.fingerprint == EXPECTED_RUNTIME_FINGERPRINT


def test_service_rejects_nonlocal_scope_language_and_unknown_slot() -> None:
    service = GenericVoiceGenerationService()

    with pytest.raises(GenericVoiceGenerationError) as scope_failure:
        service.plan(
            command_id=uuid4(),
            slot_key="female_child_bright",
            workspace_id=uuid4(),
            language="zh-CN",
        )
    assert scope_failure.value.code == "GENERIC_VOICE_PACK_SCOPE_MISMATCH"

    with pytest.raises(GenericVoiceGenerationError) as language_failure:
        service.plan(
            command_id=uuid4(),
            slot_key="female_child_bright",
            workspace_id=LOCAL_WORKSPACE_ID,
            language="en",
        )
    assert language_failure.value.code == "GENERIC_VOICE_PACK_LANGUAGE_UNAVAILABLE"

    with pytest.raises(GenericVoiceGenerationError, match="frozen taxonomy"):
        service.design_for("not_a_slot")


def test_completion_closes_request_models_scope_and_machine_approval() -> None:
    service = GenericVoiceGenerationService()
    plan, evidence = _evidence(service)

    slot = service.validate(plan=plan, evidence=evidence)

    assert slot.slot_key == evidence.slot_key
    assert slot.workspace_id == LOCAL_WORKSPACE_ID
    assert slot.profile_novel_id is None
    assert slot.generator_model_fingerprint == EXPECTED_RUNTIME_FINGERPRINT
    assert slot.nano_model_fingerprint == EXPECTED_PRODUCTION_MODEL_FINGERPRINT_SHA256
    assert slot.rights_approved
    assert slot.quality_approved
    assert not slot.rejected


def test_reuse_requires_identical_design_and_still_approved_slot() -> None:
    service = GenericVoiceGenerationService()
    plan, evidence = _evidence(service)
    slot = service.validate(plan=plan, evidence=evidence)

    assert service.reuse(slot_key=slot.slot_key, existing=slot) is slot

    values = {
        name: getattr(slot, name)
        for name in type(slot).__dataclass_fields__
    }
    values["design_fingerprint"] = "0" * 64
    with pytest.raises(GenericVoiceGenerationError) as failure:
        service.reuse(slot_key=slot.slot_key, existing=type(slot)(**values))
    assert failure.value.code == "GENERIC_VOICE_PACK_VERSION_CONFLICT"


@pytest.mark.parametrize(
    ("field_name", "replacement", "expected_code"),
    [
        ("request_digest", "0" * 64, "GENERIC_VOICE_PACK_VERSION_CONFLICT"),
        ("workspace_id", uuid4(), "GENERIC_VOICE_PACK_VERSION_CONFLICT"),
        (
            "generator_model_fingerprint",
            "0" * 64,
            "GENERIC_VOICE_PACK_GENERATION_FAILED",
        ),
        (
            "nano_model_fingerprint",
            "0" * 64,
            "GENERIC_VOICE_PACK_GENERATION_FAILED",
        ),
    ],
)
def test_completion_rejects_identity_drift(
    field_name: str,
    replacement: object,
    expected_code: str,
) -> None:
    service = GenericVoiceGenerationService()
    plan, evidence = _evidence(service)
    values = {
        name: getattr(evidence, name)
        for name in GenericVoiceCompletionEvidence.__dataclass_fields__
    }
    values[field_name] = replacement
    drifted = GenericVoiceCompletionEvidence(**values)

    with pytest.raises(GenericVoiceGenerationError) as failure:
        service.validate(plan=plan, evidence=drifted)
    assert failure.value.code == expected_code


@pytest.mark.parametrize("field_name", ["rights_approved", "quality_approved"])
def test_completion_rejects_unapproved_evidence(field_name: str) -> None:
    service = GenericVoiceGenerationService()
    plan, evidence = _evidence(service)
    values = {
        name: getattr(evidence, name)
        for name in GenericVoiceCompletionEvidence.__dataclass_fields__
    }
    values[field_name] = False

    with pytest.raises(GenericVoiceGenerationError) as failure:
        service.validate(
            plan=plan,
            evidence=GenericVoiceCompletionEvidence(**values),
        )
    assert failure.value.code == "GENERIC_VOICE_PACK_GENERATION_FAILED"


def test_generation_state_machine_is_monotonic_with_explicit_retry() -> None:
    assert (
        ensure_generation_transition(
            GenericVoiceGenerationState.PENDING,
            GenericVoiceGenerationState.GENERATING,
        )
        is GenericVoiceGenerationState.GENERATING
    )
    assert (
        ensure_generation_transition(
            GenericVoiceGenerationState.GENERATING,
            GenericVoiceGenerationState.FAILED,
        )
        is GenericVoiceGenerationState.FAILED
    )
    assert (
        ensure_generation_transition(
            GenericVoiceGenerationState.FAILED,
            GenericVoiceGenerationState.GENERATING,
        )
        is GenericVoiceGenerationState.GENERATING
    )
    with pytest.raises(GenericVoiceGenerationError):
        ensure_generation_transition(
            GenericVoiceGenerationState.VALIDATED,
            GenericVoiceGenerationState.GENERATING,
        )
