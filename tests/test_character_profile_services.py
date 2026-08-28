from __future__ import annotations

from copy import deepcopy

import pytest

from backend.character_profile_services import (
    EXISTING_PERSONALITY_WARNING,
    LIMITED_SAMPLE_WARNING,
    CharacterProfileValidationError,
    build_character_profile_snapshot,
    calculate_character_profile_completion_status,
    normalize_character_profile_output,
    validate_character_profile_apply_plan,
)


CHARACTER_ID = "00000000-0000-0000-0000-000000000101"
OTHER_CHARACTER_ID = "00000000-0000-0000-0000-000000000102"
NOVEL_ID = "00000000-0000-0000-0000-000000000001"
OUTLINE_ID = "00000000-0000-0000-0000-000000000002"
REVISION_A = "00000000-0000-0000-0000-000000000201"
REVISION_B = "00000000-0000-0000-0000-000000000202"
CHAPTER_A = "00000000-0000-0000-0000-000000000301"
CHAPTER_B = "00000000-0000-0000-0000-000000000302"


def make_snapshot(
    *,
    personality: str = "",
    chapter_count: int = 2,
    include_second_character: bool = False,
) -> dict:
    details = {
        "core_flaw": "过度相信程序正义，面对灰色选择时容易迟疑。",
        "core_motivation": "查清被抹去的案卷。",
        "secret": "不得进入模型快照",
    }
    if personality:
        details["personality"] = personality
    characters = [
        {
            "id": CHARACTER_ID,
            "version": 2,
            "name": "江述",
            "role_type": "main",
            "description": "刑警江述重事实，也会因无辜者受伤而迟疑。",
            "details": details,
            "position": 1000,
            "lifecycle_state": "active",
        },
        {
            "id": "archived",
            "version": 1,
            "name": "旧角色",
            "details": {},
            "position": 10,
            "lifecycle_state": "archived",
        },
    ]
    if include_second_character:
        characters.append(
            {
                "id": OTHER_CHARACTER_ID,
                "version": 3,
                "name": "林青瓷",
                "role_type": "supporting",
                "description": "面对威胁时倾向先保护证据。",
                "details": {},
                "position": 2000,
                "lifecycle_state": "active",
            }
        )
    revisions = [
        {
            "id": REVISION_A,
            "document_id": CHAPTER_A,
            "title": "第一章",
            "position": 1000,
            "content_text": "江述把案卷压在桌上，坚持先核对每个时间戳。",
        },
        {
            "id": REVISION_B,
            "document_id": CHAPTER_B,
            "title": "第二章",
            "position": 2000,
            "content_text": "证人受伤后，江述停下追问，选择先叫救护车。",
        },
    ][:chapter_count]
    return build_character_profile_snapshot(
        novel={"id": NOVEL_ID, "title": "刑侦1988", "genre": "悬疑"},
        outline={
            "id": OUTLINE_ID,
            "background_text": "1988年的县城档案馆里，一份卷宗被人为抹去。",
            "plot_text": "江述会在追查真相与保护证人之间不断作出选择。",
        },
        characters=characters,
        story_facts=[
            {
                "id": "fact-1",
                "fact_type": "character_state",
                "status": "active",
                "subject": "江述",
                "predicate": "行动",
                "object_text": "坚持复核时间戳",
                "source_revision_id": REVISION_A,
                "details": {"source_text": "江述把案卷压在桌上，坚持先核对每个时间戳。"},
            },
            {
                "id": "ignored-relationship",
                "fact_type": "relationship",
                "status": "active",
                "subject": "江述",
            },
        ],
        chapter_revisions=revisions,
    )


def designed_payload(snapshot: dict, *, personality: str | None = None) -> dict:
    character = snapshot["characters"][0]
    return {
        "characters": [
            {
                "character_id": character["id"],
                "base_version": character["base_version"],
                "status": "candidate",
                "personality": personality
                or "重事实、守程序，面对无辜者受伤时却会放慢追查。",
                "basis": "designed",
                "confidence": 82,
                "evidence": [
                    {
                        "source_type": "character",
                        "source_id": character["id"],
                        "quote": "过度相信程序正义，面对灰色选择时容易迟疑。",
                    }
                ],
                "warnings": [],
            }
        ]
    }


def ready_job(snapshot: dict, output: dict) -> dict:
    return {
        "id": "job-1",
        "kind": "character_profile_completion",
        "state": "ready",
        "input_snapshot": snapshot,
        "output_json": output,
        "requested_provider_id": "provider-a",
        "requested_model_id": "model-a",
        "actual_provider_id": "provider-a",
        "actual_model_id": "model-a",
        "attempt": 1,
        "created_at": "2026-08-26T10:00:00+08:00",
    }


def test_snapshot_is_deterministic_bounded_and_allowlisted() -> None:
    snapshot = make_snapshot()

    assert snapshot["schema_version"] == "character-profile-completion-v1"
    assert [item["id"] for item in snapshot["characters"]] == [CHARACTER_ID]
    assert snapshot["characters"][0]["details"] == {
        "core_flaw": "过度相信程序正义，面对灰色选择时容易迟疑。",
        "core_motivation": "查清被抹去的案卷。",
    }
    assert len(snapshot["story_facts"]) == 1
    assert {item["source_id"] for item in snapshot["chapter_evidence"]} == {
        REVISION_A,
        REVISION_B,
    }
    assert all(
        sum(not character.isspace() for character in item["excerpt"]) <= 400
        for item in snapshot["chapter_evidence"]
    )
    assert make_snapshot() == snapshot


def test_snapshot_rejects_duplicate_active_character_ids() -> None:
    character = {
        "id": CHARACTER_ID,
        "version": 1,
        "name": "江述",
        "lifecycle_state": "active",
    }
    with pytest.raises(CharacterProfileValidationError, match="重复"):
        build_character_profile_snapshot(
            novel={"id": NOVEL_ID},
            outline=None,
            characters=[character, character],
        )


def test_empty_character_snapshot_can_report_ineligible() -> None:
    snapshot = build_character_profile_snapshot(
        novel={"id": NOVEL_ID},
        outline=None,
        characters=[],
    )

    status = calculate_character_profile_completion_status(snapshot)

    assert status["eligible"] is False
    assert status["state"] == "ineligible"
    with pytest.raises(CharacterProfileValidationError, match="没有可补全"):
        normalize_character_profile_output(snapshot, {"characters": []})


def test_normalizer_accepts_designed_candidate_and_adds_existing_warning() -> None:
    snapshot = make_snapshot(personality="谨慎克制，面对风险时会先保护证据。")

    output = normalize_character_profile_output(snapshot, designed_payload(snapshot))

    assert output["characters"][0]["status"] == "candidate"
    assert EXISTING_PERSONALITY_WARNING in output["characters"][0]["warnings"]


def test_normalizer_requires_complete_character_coverage() -> None:
    snapshot = make_snapshot(include_second_character=True)

    with pytest.raises(CharacterProfileValidationError, match="每个角色"):
        normalize_character_profile_output(snapshot, designed_payload(snapshot))


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda item: item.update(character_id="outside"), "当前小说之外"),
        (lambda item: item.update(base_version=99), "base_version"),
        (lambda item: item.update(personality="聪明善良冷静勇敢"), "倾向或矛盾"),
        (lambda item: item["evidence"][0].update(quote="模型自行概括的句子"), "逐字命中"),
        (lambda item: item["evidence"][0].update(source_id="outside"), "不属于输入快照"),
    ],
)
def test_normalizer_rejects_unsafe_candidate(mutator, message: str) -> None:
    snapshot = make_snapshot()
    payload = designed_payload(snapshot)
    mutator(payload["characters"][0])

    with pytest.raises(CharacterProfileValidationError, match=message):
        normalize_character_profile_output(snapshot, payload)


def test_normalizer_rejects_duplicate_character_id() -> None:
    snapshot = make_snapshot()
    payload = designed_payload(snapshot)
    payload["characters"].append(deepcopy(payload["characters"][0]))

    with pytest.raises(CharacterProfileValidationError, match="重复"):
        normalize_character_profile_output(snapshot, payload)


def test_normalizer_rejects_evidence_owned_by_another_character() -> None:
    snapshot = make_snapshot(include_second_character=True)
    payload = designed_payload(snapshot)
    payload["characters"][0]["evidence"] = [
        {
            "source_type": "character",
            "source_id": OTHER_CHARACTER_ID,
            "quote": "面对威胁时倾向先保护证据。",
        }
    ]
    payload["characters"].append(
        {
            "character_id": OTHER_CHARACTER_ID,
            "base_version": 3,
            "status": "insufficient_evidence",
            "warnings": [],
        }
    )

    with pytest.raises(CharacterProfileValidationError, match="当前候选角色"):
        normalize_character_profile_output(snapshot, payload)


def test_insufficient_evidence_is_explicit_and_has_no_personality() -> None:
    snapshot = make_snapshot()
    payload = {
        "characters": [
            {
                "character_id": CHARACTER_ID,
                "base_version": 2,
                "status": "insufficient_evidence",
                "warnings": ["资料不足"],
            }
        ]
    }

    output = normalize_character_profile_output(snapshot, payload)

    assert output["characters"][0]["evidence"] == []
    assert "personality" not in output["characters"][0]


def test_insufficient_evidence_cannot_smuggle_personality() -> None:
    snapshot = make_snapshot()
    payload = {
        "characters": [
            {
                "character_id": CHARACTER_ID,
                "base_version": 2,
                "status": "insufficient_evidence",
                "personality": "虽然资料不足，但模型仍会猜测。",
            }
        ]
    }

    with pytest.raises(CharacterProfileValidationError, match="不能包含"):
        normalize_character_profile_output(snapshot, payload)


def test_single_chapter_mixed_candidate_gets_limited_sample_warning() -> None:
    snapshot = make_snapshot(chapter_count=1)
    payload = designed_payload(snapshot)
    item = payload["characters"][0]
    item["basis"] = "mixed"
    item["evidence"].append(
        {
            "source_type": "chapter",
            "source_id": REVISION_A,
            "quote": "江述把案卷压在桌上，坚持先核对每个时间戳。",
        }
    )

    output = normalize_character_profile_output(snapshot, payload)

    assert LIMITED_SAMPLE_WARNING in output["characters"][0]["warnings"]


def test_observed_requires_two_distinct_formal_chapters() -> None:
    snapshot = make_snapshot(chapter_count=1)
    payload = designed_payload(snapshot)
    item = payload["characters"][0]
    item["basis"] = "observed"
    item["evidence"] = [
        {
            "source_type": "chapter",
            "source_id": REVISION_A,
            "quote": "江述把案卷压在桌上，坚持先核对每个时间戳。",
        }
    ]

    with pytest.raises(CharacterProfileValidationError, match="至少两个"):
        normalize_character_profile_output(snapshot, payload)


def test_observed_accepts_two_distinct_formal_chapters() -> None:
    snapshot = make_snapshot(chapter_count=2)
    payload = designed_payload(snapshot)
    item = payload["characters"][0]
    item["basis"] = "observed"
    item["evidence"] = [
        {
            "source_type": "chapter",
            "source_id": REVISION_A,
            "quote": "坚持先核对每个时间戳",
        },
        {
            "source_type": "chapter",
            "source_id": REVISION_B,
            "quote": "选择先叫救护车",
        },
    ]

    output = normalize_character_profile_output(snapshot, payload)

    assert output["characters"][0]["basis"] == "observed"


def test_designed_rejects_chapter_evidence() -> None:
    snapshot = make_snapshot()
    payload = designed_payload(snapshot)
    payload["characters"][0]["evidence"] = [
        {
            "source_type": "chapter",
            "source_id": REVISION_A,
            "quote": "坚持先核对每个时间戳",
        }
    ]

    with pytest.raises(CharacterProfileValidationError, match="设定型"):
        normalize_character_profile_output(snapshot, payload)


def test_status_matrix_never_running_ready_applied_and_stale() -> None:
    snapshot = make_snapshot()
    output = normalize_character_profile_output(snapshot, designed_payload(snapshot))
    job = ready_job(snapshot, output)

    assert calculate_character_profile_completion_status(snapshot)["state"] == "never"
    running = {**job, "state": "running"}
    assert calculate_character_profile_completion_status(snapshot, jobs=[running])["state"] == "running"
    assert calculate_character_profile_completion_status(snapshot, jobs=[job])["state"] == "ready"
    applied = calculate_character_profile_completion_status(
        snapshot,
        jobs=[job],
        apply_batches=[
            {
                "generation_job_id": "job-1",
                "state": "applied",
                "result_versions": {CHARACTER_ID: 2},
            }
        ],
    )
    assert applied["state"] == "applied"
    changed_snapshot = deepcopy(snapshot)
    changed_snapshot["characters"][0]["base_version"] = 3
    stale = calculate_character_profile_completion_status(changed_snapshot, jobs=[job])
    assert stale["state"] == "stale"
    assert stale["stale"] is True


def test_status_keeps_applied_state_after_personality_write_increments_version() -> None:
    snapshot = make_snapshot()
    output = normalize_character_profile_output(snapshot, designed_payload(snapshot))
    job = ready_job(snapshot, output)
    applied_snapshot = deepcopy(snapshot)
    applied_snapshot["characters"][0]["base_version"] = 3
    applied_snapshot["characters"][0]["details"]["personality"] = output["characters"][0][
        "personality"
    ]

    status = calculate_character_profile_completion_status(
        applied_snapshot,
        jobs=[job],
        apply_batches=[
            {
                "generation_job_id": "job-1",
                "state": "applied",
                "result_versions": {CHARACTER_ID: 3},
                "after_snapshot": {
                    CHARACTER_ID: {
                        "personality": output["characters"][0]["personality"],
                        "core_flaw": "过度相信程序正义，面对灰色选择时容易迟疑。",
                        "core_motivation": "查清被抹去的案卷。",
                    }
                },
            }
        ],
    )

    assert status["state"] == "applied"
    assert status["job"]["id"] == "job-1"


def test_status_exposes_matching_failure_and_ineligible_source() -> None:
    snapshot = make_snapshot()
    failed = {**ready_job(snapshot, {}), "state": "failed"}
    assert calculate_character_profile_completion_status(snapshot, jobs=[failed])["state"] == "failed"

    no_source = deepcopy(snapshot)
    no_source["outline"]["background"] = ""
    no_source["outline"]["main_plot"] = ""
    no_source["characters"][0]["description"] = ""
    no_source["characters"][0]["details"] = {}
    assert calculate_character_profile_completion_status(no_source)["state"] == "ineligible"


def test_apply_plan_accepts_explicit_empty_to_nonempty_decision() -> None:
    snapshot = make_snapshot()
    output = normalize_character_profile_output(snapshot, designed_payload(snapshot))
    plan = validate_character_profile_apply_plan(
        snapshot,
        output,
        decisions=[
            {"character_id": CHARACTER_ID, "base_version": 2, "replace_existing": False}
        ],
        current_characters=[
            {
                "id": CHARACTER_ID,
                "version": 2,
                "lifecycle_state": "active",
                "details": {"core_flaw": "必须保留"},
            }
        ],
        job=ready_job(snapshot, output),
    )

    assert plan["base_versions"] == {CHARACTER_ID: 2}
    assert plan["before_snapshot"][CHARACTER_ID] == {"personality": ""}
    assert plan["after_snapshot"][CHARACTER_ID]["personality"].startswith("重事实")


def test_apply_plan_requires_explicit_replace_for_existing_personality() -> None:
    snapshot = make_snapshot(personality="谨慎克制，面对风险时会先保护证据。")
    output = normalize_character_profile_output(snapshot, designed_payload(snapshot))

    with pytest.raises(CharacterProfileValidationError, match="replace_existing=true"):
        validate_character_profile_apply_plan(
            snapshot,
            output,
            decisions=[{"character_id": CHARACTER_ID, "base_version": 2}],
            current_characters=[
                {
                    "id": CHARACTER_ID,
                    "version": 2,
                    "lifecycle_state": "active",
                    "details": {"personality": "谨慎克制，面对风险时会先保护证据。"},
                }
            ],
            job=ready_job(snapshot, output),
        )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda job, current, decisions, output: current[0].update(version=3), "版本冲突"),
        (lambda job, current, decisions, output: job.update(actual_model_id="model-b"), "模型证据"),
        (lambda job, current, decisions, output: job.update(state="running"), "尚未就绪"),
        (
            lambda job, current, decisions, output: (
                output["characters"][0].update(status="insufficient_evidence"),
                output["characters"][0].pop("personality"),
                output["characters"][0].pop("basis"),
                output["characters"][0].pop("confidence"),
            ),
            "status=candidate",
        ),
        (lambda job, current, decisions, output: decisions.append(deepcopy(decisions[0])), "重复"),
    ],
)
def test_apply_plan_rejects_unsafe_batch(change, message: str) -> None:
    snapshot = make_snapshot()
    output = normalize_character_profile_output(snapshot, designed_payload(snapshot))
    job = ready_job(snapshot, output)
    current = [
        {
            "id": CHARACTER_ID,
            "version": 2,
            "lifecycle_state": "active",
            "details": {},
        }
    ]
    decisions = [{"character_id": CHARACTER_ID, "base_version": 2}]
    change(job, current, decisions, output)
    if job.get("output_json") is not output:
        job["output_json"] = output

    with pytest.raises(CharacterProfileValidationError, match=message):
        validate_character_profile_apply_plan(
            snapshot,
            output,
            decisions=decisions,
            current_characters=current,
            job=job,
        )
