"""Run the VM34 writing/vector closed-loop E2E on one fresh synthetic novel.

The script uses only PawApp public HTTP contracts.  It never reads or prints the
embedding credential, never mutates an existing novel, and performs exactly
three real chapter-body generation calls.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_BASE = "http://127.0.0.1:18088/api/ai-novel-world-2026"
LIVE_CONFIRMATION = "VM34-LIVE-3-CALLS"
CONSENT_SCOPES = [
    "formal_manuscript",
    "formal_planning",
    "author_secrets",
    "bound_private_assets",
]


def visible_length(value: str) -> int:
    return len("".join(value.split()))


class Client:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def call(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        query: dict[str, Any] | None = None,
        timeout: float = 300,
        expected: tuple[int, ...] = (200, 201, 202),
    ) -> Any:
        url = self.base_url + path
        if query:
            url += "?" + urlencode(
                {key: value for key, value in query.items() if value is not None}
            )
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
        request = Request(
            url,
            data=body,
            method=method,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - local lab
                raw = response.read()
                if response.status not in expected:
                    raise RuntimeError(f"unexpected HTTP {response.status}: {path}")
                return json.loads(raw) if raw else None
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} -> {error.code}: {detail}") from error


def wait_for_index(client: Client, novel_id: str, *, previous_version: int | None) -> dict[str, Any]:
    deadline = time.monotonic() + 420
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = client.call("GET", f"/novels/{novel_id}/semantic-index/status")
        version = last.get("index_version")
        ready = last.get("state") == "ready" and last.get("sync_state") == "current"
        advanced = previous_version is None or (isinstance(version, int) and version > previous_version)
        if ready and advanced:
            assert last.get("authority_digest") == last.get("published_digest")
            return last
        if last.get("state") == "partial_failed":
            raise AssertionError(f"semantic refresh failed: {last.get('error_summary')}")
        time.sleep(2)
    raise TimeoutError(f"semantic refresh did not converge: {last}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument(
        "--confirm-live",
        help=(
            "Required acknowledgement for the three real chapter-generation calls: "
            f"{LIVE_CONFIRMATION}"
        ),
    )
    args = parser.parse_args()
    if args.confirm_live != LIVE_CONFIRMATION:
        parser.error(
            "live E2E is disabled by default; pass "
            f"--confirm-live {LIVE_CONFIRMATION} only after acquiring the cloud lock"
        )
    client = Client(args.base_url)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report: dict[str, Any] = {
        "schema_version": "vm34-writing-chain-e2e/1",
        "title": f"潮声档案室（VM34·{stamp}）",
        "chapter_visible_lengths": [],
        "index_versions": [],
        "semantic_hit_counts": [],
    }

    health = client.call("GET", "/health")
    config = client.call("GET", "/embedding-config")
    assert health["status"] == "ready" and health["vector_retrieval_enabled"] is True
    assert config["api_key_configured"] is True
    assert config["requested_dimension"] == 2048
    assert config["active_generation"]["state"] == "active"
    assert config["active_generation"]["dimension"] == 2048

    novel = client.call(
        "POST",
        "/novels",
        {
            "title": report["title"],
            "description": (
                "独立合成实验小说，仅用于验证 VM34 三章真实生成、"
                "人物改名、隐藏身份、固定私有素材、增量索引与未来信息隔离。"
            ),
        },
    )
    novel_id = novel["id"]
    report["novel_id"] = novel_id
    timeline = client.call("GET", f"/novels/{novel_id}/timelines")["items"][0]
    timeline_id = timeline["id"]

    protagonist = client.call(
        "POST",
        f"/novels/{novel_id}/characters",
        {
            "role_type": "main",
            "name": "林渡",
            "description": "潮声档案室记录员，习惯把事实、推测和人物所知分开。",
            "details": {"theme": "记录与身份"},
        },
    )
    instances = client.call(
        "GET", f"/novels/{novel_id}/character-instances", query={"character_id": protagonist["id"]}
    )
    instance = instances[0]
    current_novel = client.call("GET", f"/novels/{novel_id}")
    client.call(
        "PUT",
        f"/novels/{novel_id}/character-instances/{instance['id']}/profile",
        {
            "expected_story_ledger_version": current_novel["story_ledger_version"],
            "expected_instance_version": instance["version"],
            "operation_key": f"vm34-profile-{stamp}",
            "source_kind": "manual",
            "profile": {
                "schema_version": "character-instance-profile/1",
                "public_identity": "潮声档案室记录员",
                "true_identity": "海灯编码原始设计者的孩子",
                "cover_identity": "临时档案整理员",
                "birth_year": 2004,
                "birth_calendar_id": "gregorian",
                "occupation": "记录员",
                "personality": "审慎、不让推测冒充事实",
                "goals": ["追查潮声中的未来归档信号"],
                "flaws": ["过度独自承担"],
                "secrets": ["真名是林砥，此信息在第二章前不向其他人物公开"],
                "growth_direction": "从孤立保存证据到建立可复核的同盟",
            },
        },
    )

    client.call(
        "PATCH",
        f"/novels/{novel_id}/outline",
        {
            "expected_head_version": 0,
            "idempotency_key": f"vm34-outline-{stamp}",
            "source_kind": "manual",
            "target_chapter_count": 3,
            "background_text": "2041年海港，档案室会在大潮时收到来自未来的声音档案。",
            "plot_text": "林渡用三次可复核的调查追查海灯编码，并在证据充分后改回真名林砥。",
            "highlight_text": "叙事先后与世界事件顺序分离，未来章节不得泄漏。",
            "character_revision_refs": [],
            "change_set": {"vm34": True},
        },
    )
    client.call(
        "PATCH",
        f"/novels/{novel_id}/story-settings",
        {
            "expected_head_version": 0,
            "idempotency_key": f"vm34-setting-{stamp}",
            "source_kind": "manual",
            "schema_id": "vm34-tide-archive",
            "schema_version": 1,
            "settings": {
                "calendar_id": "gregorian",
                "current_story_year": 2041,
                "rule": "未来声纹只是证据，不会自动改写已确认事实。",
                "author_secret": "海灯编码的第七位与林砥的出生记录相同。",
            },
            "change_set": {"vm34": True},
        },
    )
    asset = client.call(
        "POST",
        "/private-assets",
        {
            "asset_type": "plot",
            "title": f"VM34 固定海灯规则·{stamp}",
            "content": (
                "必须遵守：每次读取未来声纹都要记录原始时间、读取人和当时知情范围；"
                "不得把作者知道的隐藏身份表述为人物已知。"
            ),
        },
    )
    client.call(
        "PUT",
        f"/novels/{novel_id}/asset-bindings",
        {
            "expected_binding_versions": {},
            "selections": [
                {
                    "asset_id": asset["id"],
                    "asset_version_id": asset["current_version_id"],
                    "usage_policy": "required",
                    "position": 0,
                }
            ],
            "operation_key": f"vm34-binding-{stamp}",
        },
    )

    consent = client.call(
        "PUT",
        f"/novels/{novel_id}/embedding-consent",
        {
            "action": "grant",
            "expected_version": 0,
            "notice_version": "novel-embedding-consent/2",
            "acknowledged_scopes": CONSENT_SCOPES,
        },
    )
    assert consent["state"] == "granted" and consent["writing_query_authorized"] is True
    initial_status = wait_for_index(client, novel_id, previous_version=None)
    index_version = int(initial_status["index_version"])
    report["index_versions"].append(index_version)

    tree = client.call("GET", f"/novels/{novel_id}/tree")
    volume = tree[0]
    seed_document = volume["documents"][0]
    chapter_specs = (
        (
            "潮声里的第七码",
            "林渡收到来自明日的声纹档案，证据标记为「青铜七码」；她只记录可核实事实，不揭露真实身份。",
        ),
        (
            "旧名与海灯",
            "调查者必须从上章的「青铜七码」继续追查；证据充分后，林渡改回真名林砥，但稳定 ID 和旧记录不变。",
        ),
        (
            "银色鲸铃",
            "从前两章的证据闭环；本章首次出现唯一标记「银色鲸铃」，它在前两章的检索截止点必须不可见。",
        ),
    )
    documents: list[dict[str, Any]] = []
    revisions: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    for index, (title, outline) in enumerate(chapter_specs, start=1):
        if index == 1:
            document = client.call(
                "PUT",
                f"/novels/{novel_id}/documents/{seed_document['id']}",
                {"expected_version": seed_document["version"], "title": title},
            )
        else:
            document = client.call(
                "POST",
                f"/novels/{novel_id}/documents",
                {"title": title, "kind": "chapter", "volume_id": volume["id"]},
            )
        required_name = "林渡" if index == 1 else "林砥"
        brief = client.call(
            "PUT",
            f"/documents/{document['id']}/chapter-brief",
            {
                "expected_version": 0,
                "target_word_count": 2000,
                "expectation_text": "完整小说正文，记录事实、推测与知情边界，不输出纲要或说明。",
                "outline_text": outline,
                "forbidden_text": "禁止提前泄漏后续章节专属标记，禁止静默改写旧记录。",
                "role_constraints": {"required": [required_name]},
            },
        )
        generated = client.call(
            "POST",
            f"/documents/{document['id']}/generation-jobs/body",
            {
                "expected_brief_version": brief["version"],
                "force_new": True,
                "asset_ids": [],
                "preset_id": None,
            },
            timeout=420,
        )
        assert generated["state"] == "ready", generated.get("failure_message")
        assert generated["candidate"] is not None
        assert generated["requested_visible_character_count"] == 2000
        output_length = int(generated["output_visible_character_count"])
        assert 1700 <= output_length <= 2300
        snapshot = generated["generation_context_snapshot"]
        assert snapshot["schema_version"] == "chapter-generation-input/4"
        assert snapshot["writing_context"]["schema_version"] == "writing-context-snapshot/1"
        retrieval = snapshot["writing_context"]["retrieval"]
        assert retrieval["schema_version"] == "semantic-search/2"
        if index > 1:
            assert retrieval["hits"], f"chapter {index} did not retrieve earlier evidence"
        adopted = client.call(
            "POST",
            f"/candidates/{generated['candidate']['id']}/adopt",
            {"expected_draft_version": generated["base_draft_version"]},
        )
        revision = adopted["revision"]
        report["chapter_visible_lengths"].append(output_length)
        report["semantic_hit_counts"].append(len(retrieval["hits"]))
        report.setdefault("retrieval_modes", []).append(retrieval["mode"])
        report.setdefault("provider_request_ids_present", []).append(
            bool(retrieval.get("provider_request_id"))
        )
        documents.append(document)
        revisions.append(revision)
        snapshots.append(snapshot)

        status = wait_for_index(client, novel_id, previous_version=index_version)
        index_version = int(status["index_version"])
        report["index_versions"].append(index_version)

        if index == 1:
            renamed = client.call(
                "PUT",
                f"/novels/{novel_id}/characters/{protagonist['id']}",
                {
                    "expected_version": protagonist["version"],
                    "role_type": "main",
                    "name": "林砥",
                    "description": protagonist["description"],
                    "details_patch": {"rename_reason": "证据确认后恢复真名"},
                },
            )
            assert renamed["id"] == protagonist["id"]

    # A later chapter may exist in the index, but a chapter-two cutoff must not
    # expose the chapter-three-only marker.
    future_search = client.call(
        "POST",
        f"/novels/{novel_id}/semantic-search",
        {
            "schema_version": "semantic-search/2",
            "query": "银色鲸铃是在哪一章首次出现的？",
            "retrieval_purpose": "chapter_body",
            "timeline_id": timeline_id,
            "narrative_sequence": 3,
            "story_sequence_cutoff": 2,
            "perspective": {"kind": "author", "character_instance_id": None},
            "corpora": ["manuscript"],
            "top_k": 10,
        },
    )
    chapter_three_revision_id = revisions[2]["id"]
    assert all(hit.get("source_revision_id") != chapter_three_revision_id for hit in future_search["hits"])
    report["future_leak_count"] = sum(
        hit.get("source_revision_id") == chapter_three_revision_id for hit in future_search["hits"]
    )

    current_novel = client.call("GET", f"/novels/{novel_id}")
    current_timeline = client.call("GET", f"/novels/{novel_id}/timelines")["items"][0]
    branch = client.call(
        "POST",
        f"/novels/{novel_id}/timelines/{timeline_id}/fork",
        {
            "expected_story_ledger_version": current_novel["story_ledger_version"],
            "expected_source_timeline_version": current_timeline["version"],
            "timeline_key": f"vm34-branch-{stamp}",
            "name": "VM34 兄弟线干扰",
            "fork_story_sequence": 2,
            "fork_anchor": {"purpose": "isolation-e2e"},
        },
    )
    report["branch_timeline_id"] = branch["timeline"]["id"] if "timeline" in branch else branch["id"]
    report["active_generation_id"] = config["active_generation"]["id"]
    report["active_dimension"] = 2048
    report["consent_notice_version"] = consent["notice_version"]
    report["writing_query_authorized"] = consent["writing_query_authorized"]
    report["final_index_state"] = client.call(
        "GET", f"/novels/{novel_id}/semantic-index/status"
    )["state"]
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
