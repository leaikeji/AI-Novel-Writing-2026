from backend.writing_skills.contracts import CapabilityCatalog, MethodSelection, SkillInjectionPacketV1
from backend.writing_skills.evidence import method_details
from .test_composer import block, make_plan


def test_display_uses_frozen_bytes_and_omits_method_and_story_text():
    text = '---\nname: prose-writing\nmetadata:\n  plugin_skill_version: "0.3.0"\n---\n# 冻结旧版正文方法\n绝不返回的长方法内容'
    primary = block(text=text)
    packet = SkillInjectionPacketV1(plan=make_plan(CapabilityCatalog(capabilities=()), selected=(),
        reasons=("author_generic_only", "不该公开的任意正文")), blocks=(primary,), estimated_tokens=10)
    detail = method_details(packet)
    assert detail.methods[0].version == "0.3.0"
    assert detail.methods[0].display_name == "冻结旧版正文方法"
    assert detail.methods[0].body_sha256 == primary.sha256
    assert detail.reasons == ("author_generic_only",)
    assert "绝不返回" not in detail.model_dump_json()


def test_metadata_never_invents_versions_or_loads_an_omitted_selection():
    packet = SkillInjectionPacketV1(plan=make_plan(CapabilityCatalog(capabilities=()), selected=(
        MethodSelection(skill_id="omitted", evidence_refs=("genre",)),)),
        blocks=(block(text="legacy primary without metadata"),), omitted_ids=("omitted",), estimated_tokens=3)
    detail = method_details(packet)
    assert len(detail.methods) == 1
    assert detail.methods[0].version is None
    assert detail.methods[0].skill_id == "prose-writing"
