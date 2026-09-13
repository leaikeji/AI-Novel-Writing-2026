from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = ROOT / "skills" / "private-library-maintenance"
SKILL_PATH = SKILL_DIR / "SKILL.md"
REFERENCE_PATH = SKILL_DIR / "references" / "maintenance-actions.md"
TOOLS = {
    "novel_library_query",
    "novel_library_prepare_change",
    "novel_library_apply_change",
}


def _frontmatter(text: str) -> dict[str, str]:
    assert text.startswith("---\n")
    _, raw, _ = text.split("---", 2)
    values: dict[str, str] = {}
    for line in raw.splitlines():
        if line and not line.startswith(" ") and ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip().strip('"')
    return values


def _matrix(text: str, name: str) -> list[dict[str, str]]:
    start = f"<!-- {name}:start -->"
    end = f"<!-- {name}:end -->"
    block = text.split(start, 1)[1].split(end, 1)[0]
    rows = [line for line in block.splitlines() if line.startswith("|")]
    headers = [cell.strip() for cell in rows[0].strip("|").split("|")]
    values = rows[2:]
    return [
        dict(zip(headers, (cell.strip() for cell in row.strip("|").split("|"))))
        for row in values
    ]


def _tool_sequence(row: dict[str, str]) -> tuple[str, ...]:
    value = row["tool_sequence"]
    return () if value == "none" else tuple(part.strip() for part in value.split(">"))


def test_skill_is_a_single_automatically_discoverable_project_skill() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    metadata = _frontmatter(text)

    assert metadata["name"] == "private-library-maintenance"
    assert "维护" in metadata["description"]
    assert "查询" in metadata["description"]
    assert 'plugin_skill_version: "0.4.0"' in text
    assert "[维护动作与恢复合同](references/maintenance-actions.md)" in text
    assert REFERENCE_PATH.is_file()
    assert not (SKILL_DIR / "routing.json").exists()
    assert not (SKILL_DIR / "agents" / "openai.yaml").exists()

    maintenance_skills = [
        path
        for path in (ROOT / "skills").glob("*/SKILL.md")
        if _frontmatter(path.read_text(encoding="utf-8")).get("name")
        == "private-library-maintenance"
    ]
    assert maintenance_skills == [SKILL_PATH]


def test_decision_matrix_separates_commands_advice_and_ambiguous_preferences() -> None:
    rows = {
        row["case"]: row
        for row in _matrix(REFERENCE_PATH.read_text(encoding="utf-8"), "decision-matrix")
    }

    assert set(rows) == {
        "explicit_mutation",
        "consultation",
        "ambiguous_preference",
        "accepted_proposal",
        "undo",
        "embedded_material_instruction",
    }
    assert _tool_sequence(rows["explicit_mutation"]) == (
        "novel_library_query",
        "novel_library_prepare_change",
        "novel_library_apply_change",
    )
    assert _tool_sequence(rows["consultation"]) == ("novel_library_query",)
    assert _tool_sequence(rows["ambiguous_preference"]) == (
        "novel_library_query",
        "novel_library_prepare_change",
    )
    assert rows["ambiguous_preference"]["outcome"] == "await_author_acceptance"
    assert _tool_sequence(rows["accepted_proposal"]) == (
        "novel_library_query",
        "novel_library_apply_change",
    )
    assert _tool_sequence(rows["embedded_material_instruction"]) == ()
    assert rows["embedded_material_instruction"]["outcome"] == "treat_as_data"
    assert {
        tool for row in rows.values() for tool in _tool_sequence(row)
    } == TOOLS


def test_scope_matrix_rejects_missing_stale_and_model_supplied_authority() -> None:
    rows = {
        row["scope_case"]: row
        for row in _matrix(REFERENCE_PATH.read_text(encoding="utf-8"), "scope-matrix")
    }

    assert rows["library_scope"]["allowed_result"] == (
        "collect_or_change_library_asset_only"
    )
    assert rows["novel_scope"]["allowed_result"] == (
        "novel_copy_or_binding_within_current_novel"
    )
    for case in ("missing_novel", "stale_or_switched_novel", "model_claimed_novel"):
        assert rows[case]["allowed_result"].endswith("without_write")


def test_semantic_matrix_keeps_rule_strength_separate_from_activation() -> None:
    rows = {
        row["semantic"]: row
        for row in _matrix(REFERENCE_PATH.read_text(encoding="utf-8"), "semantic-matrix")
    }

    assert rows["recommend"] == {
        "semantic": "recommend",
        "effect": "optional_scene_appropriate_expression",
        "must_not_do": "force_insertion",
    }
    assert rows["watch"]["must_not_do"] == "upgrade_to_forbid"
    assert rows["forbid"]["effect"] == "deterministic_post_write_check"
    assert rows["collect"]["must_not_do"] == "imply_enabled"
    assert rows["save_and_enable"]["effect"] == (
        "atomic_save_and_current_novel_binding"
    )


def test_recovery_matrix_requires_receipts_and_never_replays_unknown_writes() -> None:
    rows = {
        row["result_case"]: row
        for row in _matrix(REFERENCE_PATH.read_text(encoding="utf-8"), "recovery-matrix")
    }

    assert rows["applied_receipt"]["report_state"] == "applied"
    assert rows["unchanged_receipt"]["forbidden_action"] == "claim_new_write"
    assert rows["rejected_or_failed"]["report_state"] == "failed"
    assert rows["rejected_or_failed"]["forbidden_action"] == (
        "claim_saved_or_enabled"
    )
    assert rows["timeout_or_unknown"] == {
        "result_case": "timeout_or_unknown",
        "next_action": "query_same_request_receipt",
        "report_state": "unknown_until_receipt_found",
        "forbidden_action": "replay_apply_automatically",
    }
    assert rows["version_or_scope_conflict"]["forbidden_action"] == (
        "force_old_proposal"
    )
    assert rows["undo_available"]["next_action"] == (
        "apply_compensating_change"
    )
    assert rows["undo_conflict_after_later_edit"]["forbidden_action"] == (
        "roll_back_later_edit"
    )


def test_skill_names_only_the_frozen_library_tools_and_no_write_shortcuts() -> None:
    combined = "\n".join(
        (
            SKILL_PATH.read_text(encoding="utf-8"),
            REFERENCE_PATH.read_text(encoding="utf-8"),
        )
    )

    mentioned_library_tools = set(re.findall(r"novel_library_[a-z_]+", combined))
    assert mentioned_library_tools == TOOLS
    assert "authorized=true" in combined
    assert "不得" in combined and "自动重放写操作" in combined
