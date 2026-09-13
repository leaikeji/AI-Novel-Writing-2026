from __future__ import annotations

from uuid import uuid4

from backend.private_library.lexicon_contracts import LexiconEntry
from backend.private_library.lexicon_service import (
    EffectiveLexiconPolicy,
    EffectiveLexiconRule,
    effective_policy_snapshot,
)
from backend.services import _lexicon_prompt_text
from backend.creative_services import build_creative_generation_prompt


def _rule(index: int, action: str) -> EffectiveLexiconRule:
    return EffectiveLexiconRule(
        asset_id=uuid4(),
        asset_version_id=uuid4(),
        entry=LexiconEntry(
            entry_id=f"entry_{index:04d}",
            term=f"词语{index}",
            action=action,
            note=f"说明{index}",
        ),
        position=index,
    )


def test_prompt_separates_semantics_and_never_truncates_forbid_rules() -> None:
    rules = tuple(
        [*(_rule(index, "recommend") for index in range(31))]
        + [_rule(100, "watch"), _rule(101, "forbid"), _rule(102, "forbid")]
    )
    policy = EffectiveLexiconPolicy(
        novel_id=uuid4(),
        rules=rules,
        conflicts=(),
        rules_hash="a" * 64,
    )
    rendered = _lexicon_prompt_text({
        "lexicon_policy": effective_policy_snapshot(policy),
    })
    assert "推荐表达" in rendered
    assert "另有1条推荐按首发预算未进入本次提示" in rendered
    assert "慎用表达" in rendered and "连续1000个可见字符内达到3次" in rendered
    assert "禁用表达" in rendered
    assert "词语101" in rendered and "词语102" in rendered
    assert "不是情节事实" in rendered
    assert "a" * 64 not in rendered


def test_prompt_without_enabled_lexicon_is_explicit() -> None:
    assert _lexicon_prompt_text({}) == "- 本书未启用结构化用词规则"


def test_selection_edit_prompt_receives_the_same_structured_word_rules() -> None:
    policy = EffectiveLexiconPolicy(
        novel_id=uuid4(),
        rules=(_rule(1, "forbid"), _rule(2, "watch")),
        conflicts=(),
        rules_hash="b" * 64,
    )
    prompt = build_creative_generation_prompt({
        "kind": "selection_edit",
        "input_snapshot": {
            "operation": "polish",
            "lexicon_policy": effective_policy_snapshot(policy),
        },
    })

    assert "结构化用词规则由服务端按本书固定版本生成" in prompt
    assert "词语1" in prompt and "禁用表达" in prompt
    assert "词语2" in prompt and "慎用表达" in prompt
    assert "b" * 64 not in prompt
