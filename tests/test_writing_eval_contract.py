from __future__ import annotations

import ast
from collections import Counter
import hashlib
import inspect
import json
from pathlib import Path

import pytest

from backend import writing_eval_contract as contract


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "tests" / "fixtures" / "writing_skill_eval" / "cases.json"
EVIDENCE_ROOT = (
    ROOT
    / "docs"
    / "开发文档"
    / "证据"
    / "悬疑刑侦写作A-B-2026-08-27"
)
MANIFEST_PATH = EVIDENCE_ROOT / "manifest.json"
OVERLAY_PATH = EVIDENCE_ROOT / "candidate-overlay.md"
API_PATH = ROOT / "backend" / "writing_eval_api.py"
TARGET_CASE_IDS = {"CF-01", "SP-02", "DS-01", "GP-02"}


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_case_projection(case: dict, mode: str) -> dict:
    constraints = case["hard_constraints"]
    return {
        "title": case["title"],
        "source_text": case["source_text"],
        "request": case["request"],
        "pov": constraints["pov"],
        "target_chars": constraints["target_chars"],
        "required_anchors": constraints["required_anchors"],
        "forbidden_additions": constraints["forbidden_additions"],
        "knowledge_boundaries": constraints["knowledge_boundaries"],
        "required_state_changes": constraints["required_state_changes"],
        "mode": mode,
    }


def test_frozen_hashes_and_four_case_payloads_match_authoritative_inputs() -> None:
    suite = _load_json(CASES_PATH)
    manifest = _load_json(MANIFEST_PATH)
    fixture_cases = {case["id"]: case for case in suite["cases"]}

    assert _sha256_file(CASES_PATH) == contract.SOURCE_SUITE_SHA256
    assert _sha256_file(CASES_PATH) == manifest["source_suite"]["sha256"]
    assert _sha256_file(OVERLAY_PATH) == contract.CANDIDATE_OVERLAY_SHA256
    assert _sha256_file(OVERLAY_PATH) == manifest["candidate_overlay"]["sha256"]
    assert set(contract._CASES) == TARGET_CASE_IDS
    assert set(manifest["source_suite"]["case_ids"]) == TARGET_CASE_IDS

    for case_id in TARGET_CASE_IDS:
        assert contract._CASES[case_id] == _fixture_case_projection(
            fixture_cases[case_id], manifest["candidate_modes"][case_id]
        )


def test_sixteen_assignments_match_manifest_and_form_a_complete_matrix() -> None:
    manifest = _load_json(MANIFEST_PATH)
    public = contract.experiment_contract(contract.EXPERIMENT_ID)

    assert public["sample_ids"] == list(manifest["assignment_key"])
    assert public["blind_pairs"] == manifest["blind_pairs"]
    assert len(public["sample_ids"]) == 16
    assert len(set(public["sample_ids"])) == 16

    observed: list[tuple[str, str, int]] = []
    for sample_id, expected in manifest["assignment_key"].items():
        sample = contract.build_sample(contract.EXPERIMENT_ID, sample_id)
        identity = (sample.case_id, sample.variant, sample.attempt)
        observed.append(identity)
        assert identity == (
            expected["case_id"],
            expected["variant"],
            expected["attempt"],
        )

    assert Counter(case_id for case_id, _, _ in observed) == {
        case_id: 4 for case_id in TARGET_CASE_IDS
    }
    assert set(observed) == {
        (case_id, variant, attempt)
        for case_id in TARGET_CASE_IDS
        for variant in ("A", "B")
        for attempt in (1, 2)
    }


@pytest.mark.parametrize(
    ("experiment_id", "sample_id", "error_code"),
    (
        ("unknown-experiment", "X01", "experiment_not_found"),
        (contract.EXPERIMENT_ID, "X00", "sample_not_found"),
        (contract.EXPERIMENT_ID, "free-form", "sample_not_found"),
    ),
)
def test_unknown_experiment_or_sample_ids_are_rejected(
    experiment_id: str, sample_id: str, error_code: str
) -> None:
    with pytest.raises(contract.WritingEvalContractError) as raised:
        contract.build_sample(experiment_id, sample_id)
    assert raised.value.code == error_code


def test_unknown_case_id_is_rejected_by_deterministic_checker() -> None:
    with pytest.raises(contract.WritingEvalContractError) as raised:
        contract.deterministic_output_checks("unknown-case", "正文")
    assert raised.value.code == "case_not_found"


def test_attempts_reuse_the_same_prompt_and_ab_diff_is_only_the_overlay() -> None:
    samples = {
        sample_id: contract.build_sample(contract.EXPERIMENT_ID, sample_id)
        for sample_id in contract.experiment_contract(contract.EXPERIMENT_ID)[
            "sample_ids"
        ]
    }

    by_identity = {
        (sample.case_id, sample.variant, sample.attempt): sample
        for sample in samples.values()
    }
    for case_id in TARGET_CASE_IDS:
        for variant in ("A", "B"):
            assert (
                by_identity[(case_id, variant, 1)].prompt
                == by_identity[(case_id, variant, 2)].prompt
            )
        for attempt in (1, 2):
            sample_a = by_identity[(case_id, "A", attempt)]
            sample_b = by_identity[(case_id, "B", attempt)]
            mode = contract._CASES[case_id]["mode"]
            prompt_prefix = sample_a.prompt.removesuffix(
                "\n" + contract._FINAL_REQUIREMENT
            )
            expected_b = (
                prompt_prefix
                + f"\n\n{contract._OVERLAY_COMMON}\n"
                + f"- 本题的信息释放规则：{contract._MODE_RULES[mode]}\n\n"
                + contract._FINAL_REQUIREMENT
            )

            assert sample_a.base_prompt == sample_a.prompt
            assert sample_b.base_prompt == sample_a.prompt
            assert sample_b.prompt == expected_b


def test_each_b_prompt_contains_only_its_current_mode_rule() -> None:
    for sample_id in contract.experiment_contract(contract.EXPERIMENT_ID)["sample_ids"]:
        sample = contract.build_sample(contract.EXPERIMENT_ID, sample_id)
        if sample.variant != "B":
            continue
        current_mode = contract._CASES[sample.case_id]["mode"]
        current_rule = contract._MODE_RULES[current_mode]

        assert sample.prompt.count(current_rule) == 1
        for mode, rule in contract._MODE_RULES.items():
            if mode != current_mode:
                assert rule not in sample.prompt
        for mode in contract._MODE_RULES:
            assert mode not in sample.prompt


def test_trusted_envelope_precedes_untrusted_text_and_forbids_tools_and_persistence() -> None:
    required_header_lines = {
        "kind=chapter_generation",
        f"contract={contract.GENERATION_CONTRACT_VERSION}",
        f"research_experiment={contract.EXPERIMENT_ID}",
        f"research_contract={contract.PROMPT_CONTRACT_VERSION}",
        f"rights_basis={contract.RIGHTS_BASIS}",
        "persistence=none",
        "tools=forbidden",
        "output=final-prose-only",
    }

    for sample_id in contract.experiment_contract(contract.EXPERIMENT_ID)["sample_ids"]:
        sample = contract.build_sample(contract.EXPERIMENT_ID, sample_id)
        header, untrusted_material = sample.prompt.split("\n\n", 1)
        header_lines = set(header.splitlines()[1:])

        assert header.startswith("【AI小说世界2026 PawApp可信任务封套】\n")
        assert header_lines == required_header_lines
        assert sample.prompt.count("【AI小说世界2026 PawApp可信任务封套】") == 1
        assert "【题面】" in untrusted_material
        assert contract._CASES[sample.case_id]["source_text"] in untrusted_material
        assert sample.prompt.endswith(contract._FINAL_REQUIREMENT)

    public = contract.experiment_contract(contract.EXPERIMENT_ID)
    assert public["server_persistence"] == "none"
    assert public["arbitrary_prompt_allowed"] is False


def test_generation_endpoint_accepts_no_body_and_has_no_persistence_calls() -> None:
    tree = ast.parse(API_PATH.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "writing_evaluation_generate"
    )
    argument_names = [argument.arg for argument in function.args.args]
    assert argument_names == [
        "experiment_id",
        "sample_id",
        "response",
        "ctx",
        "configured_model",
        "postflight_model_probe",
    ]

    chat_stream_calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "chat_stream"
    ]
    assert len(chat_stream_calls) == 1
    assert {
        keyword.arg for keyword in chat_stream_calls[0].keywords
    } == {"skill", "session_id"}

    forbidden_calls = {
        "add",
        "commit",
        "execute",
        "flush",
        "open",
        "write",
        "write_bytes",
        "write_text",
    }
    observed_forbidden = {
        node.func.attr
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in forbidden_calls
    }
    assert observed_forbidden == set()


@pytest.mark.parametrize("case_id", sorted(TARGET_CASE_IDS))
def test_nfc_non_whitespace_length_boundaries_are_inclusive(case_id: str) -> None:
    target = contract._CASES[case_id]["target_chars"]
    minimum = target["min"]
    maximum = target["max"]

    assert contract.deterministic_output_checks(case_id, "字" * minimum)[
        "length_pass"
    ] is True
    assert contract.deterministic_output_checks(case_id, "字" * (minimum - 1))[
        "length_pass"
    ] is False
    assert contract.deterministic_output_checks(case_id, "字" * maximum)[
        "length_pass"
    ] is True
    assert contract.deterministic_output_checks(case_id, "字" * (maximum + 1))[
        "length_pass"
    ] is False


def test_length_count_uses_nfc_and_ignores_unicode_whitespace() -> None:
    # The decomposed final character becomes one code point under NFC. Unicode
    # spaces, tabs and newlines are excluded from the frozen length count.
    output = "字" * 499 + "e\u0301" + " \n\t\u3000"
    checks = contract.deterministic_output_checks("CF-01", output)

    assert checks["non_whitespace_chars"] == 500
    assert checks["length_pass"] is True


@pytest.mark.parametrize(
    ("output", "flag"),
    (
        ("```text\n正文\n```", "markdown_fence"),
        ("# 标题\n正文", "markdown_heading"),
        ('{"正文":"内容"}', "json_or_xml_wrapper"),
        ('["正文"]', "json_or_xml_wrapper"),
        ("<正文>内容</正文>", "json_or_xml_wrapper"),
        ("分析：先说明写法，再给正文。", "analysis_prefix"),
    ),
)
def test_explicit_non_prose_wrappers_are_detected(output: str, flag: str) -> None:
    checks = contract.deterministic_output_checks("CF-01", output)
    assert checks["wrapper_flags"][flag] is True


def test_anchor_hits_remain_candidates_and_never_claim_semantic_pass() -> None:
    output = "铜钥匙、受潮纸图、九格电、十二点十分。"
    checks = contract.deterministic_output_checks("CF-01", output)

    assert all(checks["required_anchor_hits"].values())
    assert checks["semantic_review_required"] is True
    assert "anchors_pass" not in checks
    assert "semantic_pass" not in checks


def test_contract_module_does_not_expose_arbitrary_prompt_parameters() -> None:
    parameters = inspect.signature(contract.build_sample).parameters
    assert list(parameters) == ["experiment_id", "sample_id"]
