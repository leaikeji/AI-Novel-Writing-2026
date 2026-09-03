from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.models import (
    GenericVoicePackVersion,
    GenericVoicePackVersionSlot,
    GenericVoicePool,
    GenericVoiceSlot,
    VoiceCastingRule,
)
from backend.narration.contracts import LOCAL_WORKSPACE_ID
from backend.narration.edition_service import _require_active_generic_slot
from backend.narration.script_analysis import (
    _explicit_casting_attributes,
    _generic_slot_shape,
)
from backend.narration.casting import automatic_generic_casting_rule_id
from backend.narration import schemas as wire
from backend.narration.script_contracts import (
    CastingDecision,
    CastingDecisionOrigin,
    CastingTargetKind,
    CastingTargetRef,
    SegmentKind,
    SpeakerKind,
)
from backend.narration.script_versions import _is_server_automatic_pool_decision
from backend.narration.services import (
    NarrationScopeMismatch,
    voice_activation_evidence_is_usable,
)


class _Store:
    def __init__(self, *, pack_state: str = "active") -> None:
        self.novel_id = uuid4()
        self.pack_id = uuid4()
        self.pool = SimpleNamespace(
            id=uuid4(),
            novel_id=self.novel_id,
            version_number=1,
            status="active",
            source_pack_version_id=self.pack_id,
            language="zh-CN",
        )
        self.version_id = uuid4()
        self.slot = SimpleNamespace(
            id=uuid4(),
            pool_id=self.pool.id,
            slot_key="neutral_young",
            voice_version_id=self.version_id,
            enabled=True,
        )
        self.pack = SimpleNamespace(
            id=self.pack_id,
            workspace_id=LOCAL_WORKSPACE_ID,
            language="zh-CN",
            state=pack_state,
            validated_slot_count=24,
        )
        self.source_slot = SimpleNamespace(
            pack_version_id=self.pack_id,
            slot_key=self.slot.slot_key,
            voice_version_id=self.version_id,
            state="validated",
            rights_approved=True,
            quality_approved=True,
        )

    def get(self, model, identifier, *, for_update=False):
        if model is VoiceCastingRule:
            return None
        if model is GenericVoicePool and identifier == self.pool.id:
            return self.pool
        if model is GenericVoicePackVersion and identifier == self.pack.id:
            return self.pack
        return None

    def find_all(self, model, **filters):
        assert filters.pop("for_update") is True
        if (
            model is GenericVoicePackVersionSlot
            and filters == {
                "pack_version_id": self.pack.id,
                "slot_key": self.slot.slot_key,
            }
        ):
            return [self.source_slot]
        return []


def test_generic_slot_requires_the_current_active_source_pack() -> None:
    current = _Store()
    assert _require_active_generic_slot(
        current,
        novel_id=current.novel_id,
        slot=current.slot,
        expected_pool_id=current.pool.id,
    ) is current.pool

    retired = _Store(pack_state="retired_for_new_use")
    with pytest.raises(NarrationScopeMismatch, match="no longer active"):
        _require_active_generic_slot(
            retired,
            novel_id=retired.novel_id,
            slot=retired.slot,
            expected_pool_id=retired.pool.id,
        )


def test_generic_voice_activation_evidence_is_usable_only_in_its_frozen_shape() -> None:
    version = SimpleNamespace(
        source_type="generated",
        activation_basis="generic_voice_pack_generation",
        validation_basis="machine_validated",
        quality_state="accepted",
        model_run_id=uuid4(),
        reference_asset_id=uuid4(),
        description_digest_key_id="sha256-public-v1",
        description_digest="a" * 64,
        preset_key=None,
        model_id="OpenMOSS-Team/MOSS-VoiceGenerator",
        model_revision="97521ec2b6f3ec5026ac1f5751f8fc302d82c2d4",
        locked_actor=None,
        locked_at=None,
    )
    rights = SimpleNamespace(
        source_kind="voice_generator",
        purpose="private_novel_narration",
        commercial_use=False,
        redistribution=False,
        voice_cloning=False,
        subject_consent_reference=None,
    )

    assert voice_activation_evidence_is_usable(version, rights) is True
    version.activation_basis = "character_one_click_generation"
    assert voice_activation_evidence_is_usable(version, rights) is True
    rights.redistribution = True
    assert voice_activation_evidence_is_usable(version, rights) is False


@pytest.mark.parametrize(
    ("label", "kind", "expected_gender", "expected_age"),
    (
        ("男童", SpeakerKind.ANONYMOUS, wire.CastingGender.MALE, wire.CastingAgeBand.CHILD),
        ("青年女性", SpeakerKind.ANONYMOUS, wire.CastingGender.FEMALE, wire.CastingAgeBand.YOUNG_ADULT),
        ("中年男性", SpeakerKind.ANONYMOUS, wire.CastingGender.MALE, wire.CastingAgeBand.MIDDLE_AGED),
        ("老年女性", SpeakerKind.ANONYMOUS, wire.CastingGender.FEMALE, wire.CastingAgeBand.ELDERLY),
        ("中性声音", SpeakerKind.ANONYMOUS, wire.CastingGender.NEUTRAL, wire.CastingAgeBand.UNKNOWN),
        ("男人们", SpeakerKind.GROUP, wire.CastingGender.MALE, wire.CastingAgeBand.UNKNOWN),
    ),
)
def test_explicit_generic_casting_evidence_is_literal_and_deterministic(
    label: str,
    kind: SpeakerKind,
    expected_gender: wire.CastingGender,
    expected_age: wire.CastingAgeBand,
) -> None:
    attributes = _explicit_casting_attributes(
        label=label,
        segment_kind=SegmentKind.DIALOGUE,
        speaker_kind=kind,
    )

    assert attributes.gender is expected_gender
    assert attributes.age_band is expected_age
    assert attributes.context_kind is (
        wire.CastingContextKind.GROUP
        if kind is SpeakerKind.GROUP
        else wire.CastingContextKind.DIALOGUE
    )


def test_frozen_taxonomy_categories_derive_six_required_slot_shapes() -> None:
    assert _generic_slot_shape(
        slot_key="male_child_bright", category="male_child"
    )[1:3] == (
        (wire.CastingGender.MALE,),
        (wire.CastingAgeBand.CHILD,),
    )
    assert _generic_slot_shape(
        slot_key="female_young_gentle", category="female_young_adult"
    )[1:3] == (
        (wire.CastingGender.FEMALE,),
        (wire.CastingAgeBand.YOUNG_ADULT,),
    )
    assert _generic_slot_shape(
        slot_key="male_middle_authoritative", category="male_middle_aged"
    )[1:3] == (
        (wire.CastingGender.MALE,),
        (wire.CastingAgeBand.MIDDLE_AGED,),
    )
    group = _generic_slot_shape(
        slot_key="crowd_male", category="male_group"
    )
    assert group[0] == (
        wire.CastingSpeakerKind.GROUP,
        wire.CastingSpeakerKind.UNKNOWN,
    )
    assert group[3] == (wire.CastingContextKind.GROUP,)


def test_script_authority_recognizes_only_reconstructible_automatic_pool_rule() -> None:
    store = _Store()
    target = CastingTargetRef(
        kind=CastingTargetKind.GENERIC_SLOT,
        pool_id=store.pool.id,
        slot_id=store.slot.id,
    )
    decision = CastingDecision(
        candidate_targets=(target,),
        final_target=target,
        origin=CastingDecisionOrigin.CASTING_RULE,
        rule_id=automatic_generic_casting_rule_id(
            novel_id=store.novel_id,
            pool_id=store.pool.id,
            pool_version=1,
        ),
        rule_version=1,
    )

    assert _is_server_automatic_pool_decision(
        store,
        novel_id=store.novel_id,
        casting=decision,
        historical_read=False,
    )

    forged = CastingDecision(
        candidate_targets=(target,),
        final_target=target,
        origin=CastingDecisionOrigin.CASTING_RULE,
        rule_id=uuid4(),
        rule_version=1,
    )
    assert not _is_server_automatic_pool_decision(
        store,
        novel_id=store.novel_id,
        casting=forged,
        historical_read=False,
    )
