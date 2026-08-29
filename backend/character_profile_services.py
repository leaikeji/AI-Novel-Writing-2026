"""Pure domain rules for evidence-backed character personality completion.

The module deliberately has no database or QwenPaw imports.  ORM adapters build
plain records, call these functions, then perform locking and persistence in a
separate transaction.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .model_execution import ModelEvidencePolicyError, candidate_actual_identity


SNAPSHOT_SCHEMA_VERSION = "character-profile-completion-v1"
CHARACTER_DETAIL_ALLOWLIST = (
    "personality",
    "core_flaw",
    "core_motivation",
    "growth_direction",
    "identity",
)
EVIDENCE_SOURCE_TYPES = {"character", "outline", "chapter", "story_fact"}
BASIS_TYPES = {"designed", "mixed", "observed"}
RESULT_STATUSES = {"candidate", "insufficient_evidence"}
JOB_STATES = {"running", "ready", "failed"}
LIMITED_SAMPLE_WARNING = "样本有限：正文行为证据不足两个不同正式章节"
EXISTING_PERSONALITY_WARNING = "已有人工值：默认保留，替换需要作者明确确认"

_BEHAVIOUR_MARKERS = (
    "会",
    "倾向",
    "面对",
    "压力",
    "选择",
    "回避",
    "坚持",
    "宁愿",
    "容易",
    "习惯",
    "克制",
    "迟疑",
    "矛盾",
    "但",
    "却",
    "同时",
    "一旦",
    "即使",
)


class CharacterProfileValidationError(ValueError):
    """Raised when a snapshot, model result, status record, or apply plan is unsafe."""


def _clean_string(value: Any, *, field: str, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise CharacterProfileValidationError(f"{field} 必须是字符串")
    cleaned = value.strip()
    if required and not cleaned:
        raise CharacterProfileValidationError(f"{field} 不能为空")
    return cleaned


def _stable_id(value: Any, *, field: str) -> str:
    text = _clean_string(str(value) if value is not None else "", field=field, required=True)
    if len(text) > 240:
        raise CharacterProfileValidationError(f"{field} 过长")
    return text


def _positive_version(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise CharacterProfileValidationError(f"{field} 必须是正整数")
    try:
        version = int(value)
    except (TypeError, ValueError) as error:
        raise CharacterProfileValidationError(f"{field} 必须是正整数") from error
    if version < 1:
        raise CharacterProfileValidationError(f"{field} 必须是正整数")
    return version


def _bounded_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _canonical_hash(value: Mapping[str, Any]) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _record_sort_key(record: Mapping[str, Any]) -> tuple[int, str]:
    try:
        position = int(record.get("position") or 0)
    except (TypeError, ValueError):
        position = 0
    return position, str(record.get("id") or record.get("source_id") or "")


def _source_text(record: Mapping[str, Any]) -> str:
    candidates = (
        record.get("content_text"),
        record.get("text"),
        record.get("content"),
    )
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


def _chapter_window(text: str, name_start: int, name_length: int) -> str:
    """Return a deterministic window of at most 400 visible characters."""

    start = max(0, name_start - 190)
    end = min(len(text), name_start + name_length + 190)
    window = text[start:end].strip()
    while sum(not character.isspace() for character in window) > 400:
        if name_start - start > end - (name_start + name_length):
            start += 1
        else:
            end -= 1
        window = text[start:end].strip()
    return window


def build_character_profile_snapshot(
    *,
    novel: Mapping[str, Any],
    outline: Mapping[str, Any] | None,
    characters: Iterable[Mapping[str, Any]],
    story_facts: Iterable[Mapping[str, Any]] = (),
    chapter_revisions: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build the bounded, deterministic v1 model input from parsed records.

    ``chapter_revisions`` must contain adopted formal revision text.  Working
    copies and draft candidates are intentionally not accepted through a
    separate fallback field.
    """

    novel_id = _stable_id(novel.get("id"), field="novel.id")
    normalized_novel = {
        "id": novel_id,
        "title": _bounded_text(novel.get("title"), 240),
        "genre": _bounded_text(novel.get("genre"), 120),
        "subgenre": _bounded_text(novel.get("subgenre"), 120),
    }

    outline_record = dict(outline or {})
    normalized_outline = {
        "source_id": _stable_id(
            outline_record.get("id") or f"outline:{novel_id}",
            field="outline.source_id",
        ),
        "background": _bounded_text(
            outline_record.get("background")
            or outline_record.get("background_text"),
            8_000,
        ),
        "main_plot": _bounded_text(
            outline_record.get("main_plot") or outline_record.get("plot_text"),
            16_000,
        ),
    }

    normalized_characters: list[dict[str, Any]] = []
    seen_character_ids: set[str] = set()
    for record in sorted((dict(item) for item in characters), key=_record_sort_key):
        if str(record.get("lifecycle_state") or "active") != "active":
            continue
        character_id = _stable_id(record.get("id"), field="character.id")
        if character_id in seen_character_ids:
            raise CharacterProfileValidationError("characters 包含重复 character_id")
        seen_character_ids.add(character_id)
        details = record.get("details")
        if details is None:
            details = {}
        if not isinstance(details, Mapping):
            raise CharacterProfileValidationError("character.details 必须是对象")
        normalized_details = {
            key: _bounded_text(details.get(key), 2_000)
            for key in CHARACTER_DETAIL_ALLOWLIST
            if details.get(key) is not None and str(details.get(key)).strip()
        }
        normalized_characters.append(
            {
                "id": character_id,
                "base_version": _positive_version(
                    record.get("version"), field=f"character[{character_id}].version"
                ),
                "name": _clean_string(
                    record.get("name"),
                    field=f"character[{character_id}].name",
                    required=True,
                ),
                "role_type": _bounded_text(record.get("role_type"), 30),
                "description": _bounded_text(record.get("description"), 4_000),
                "details": normalized_details,
                "position": int(record.get("position") or 0),
            }
        )
    character_ids = {item["id"] for item in normalized_characters}
    character_names = {item["name"]: item["id"] for item in normalized_characters}
    normalized_facts: list[dict[str, Any]] = []
    for record in sorted((dict(item) for item in story_facts), key=_record_sort_key):
        if str(record.get("status") or "active") not in {"active", "source_restored"}:
            continue
        if str(record.get("fact_type") or "") != "character_state":
            continue
        details = record.get("details") if isinstance(record.get("details"), Mapping) else {}
        character_id_value = record.get("character_id") or details.get("character_id")
        if character_id_value is None:
            character_id_value = character_names.get(str(record.get("subject") or "").strip())
        character_id = str(character_id_value or "").strip()
        if character_id not in character_ids:
            continue
        fact_id = _stable_id(record.get("id"), field="story_fact.id")
        normalized_facts.append(
            {
                "id": fact_id,
                "character_id": character_id,
                "subject": _bounded_text(record.get("subject"), 240),
                "predicate": _bounded_text(record.get("predicate"), 240),
                "object": _bounded_text(record.get("object") or record.get("object_text"), 1_000),
                "source_text": _bounded_text(details.get("source_text"), 600),
                "source_revision_id": (
                    str(record.get("source_revision_id"))
                    if record.get("source_revision_id") is not None
                    else None
                ),
            }
        )
        if len(normalized_facts) >= 300:
            break

    revisions = sorted((dict(item) for item in chapter_revisions), key=_record_sort_key)
    normalized_chapter_evidence: list[dict[str, Any]] = []
    total_visible = 0
    omitted_windows = 0
    for character in normalized_characters:
        accepted_for_character = 0
        name = character["name"]
        for revision in revisions:
            text = _source_text(revision)
            if not text:
                continue
            source_id = _stable_id(
                revision.get("revision_id") or revision.get("id"),
                field="chapter_revision.id",
            )
            chapter_id = _stable_id(
                revision.get("chapter_id") or revision.get("document_id"),
                field="chapter_revision.chapter_id",
            )
            for match in re.finditer(re.escape(name), text):
                if accepted_for_character >= 8:
                    omitted_windows += 1
                    continue
                excerpt = _chapter_window(text, match.start(), len(name))
                excerpt_visible = sum(not item.isspace() for item in excerpt)
                if total_visible + excerpt_visible > 16_000:
                    omitted_windows += 1
                    continue
                normalized_chapter_evidence.append(
                    {
                        "source_id": source_id,
                        "chapter_id": chapter_id,
                        "character_id": character["id"],
                        "title": _bounded_text(revision.get("title"), 240),
                        "position": int(revision.get("position") or 0),
                        "excerpt": excerpt,
                    }
                )
                total_visible += excerpt_visible
                accepted_for_character += 1

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "novel": normalized_novel,
        "outline": normalized_outline,
        "characters": normalized_characters,
        "story_facts": normalized_facts,
        "chapter_evidence": normalized_chapter_evidence,
        "truncation": {
            "chapter_window_limit_per_character": 8,
            "chapter_window_visible_character_limit": 400,
            "task_chapter_evidence_visible_character_limit": 16_000,
            "omitted_chapter_windows": omitted_windows,
        },
    }


def _require_snapshot(snapshot: Mapping[str, Any]) -> None:
    if snapshot.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise CharacterProfileValidationError("角色卡补全快照版本无效")
    if not isinstance(snapshot.get("characters"), list):
        raise CharacterProfileValidationError("角色卡补全快照缺少 characters")


def _evidence_catalog(snapshot: Mapping[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    catalog: dict[tuple[str, str], dict[str, Any]] = {}
    for character in snapshot.get("characters") or []:
        if not isinstance(character, Mapping):
            continue
        source_id = str(character.get("id") or "")
        details = character.get("details") if isinstance(character.get("details"), Mapping) else {}
        texts = [
            str(character.get("description") or ""),
            *(str(details.get(key) or "") for key in CHARACTER_DETAIL_ALLOWLIST),
        ]
        catalog[("character", source_id)] = {
            "texts": texts,
            "character_id": source_id,
            "chapter_id": None,
        }
    outline = snapshot.get("outline")
    if isinstance(outline, Mapping):
        source_id = str(outline.get("source_id") or "")
        catalog[("outline", source_id)] = {
            "texts": [str(outline.get("background") or ""), str(outline.get("main_plot") or "")],
            "chapter_id": None,
        }
    for fact in snapshot.get("story_facts") or []:
        if not isinstance(fact, Mapping):
            continue
        source_id = str(fact.get("id") or "")
        catalog[("story_fact", source_id)] = {
            "texts": [
                str(fact.get("subject") or ""),
                str(fact.get("predicate") or ""),
                str(fact.get("object") or ""),
                str(fact.get("source_text") or ""),
            ],
            "character_id": str(fact.get("character_id") or ""),
            "chapter_id": str(fact.get("source_revision_id") or "") or None,
        }
    for chapter in snapshot.get("chapter_evidence") or []:
        if not isinstance(chapter, Mapping):
            continue
        key = ("chapter", str(chapter.get("source_id") or ""))
        entry = catalog.setdefault(
            key,
            {"texts": [], "texts_by_character": {}, "chapter_ids": set()},
        )
        excerpt = str(chapter.get("excerpt") or "")
        character_id = str(chapter.get("character_id") or "")
        entry["texts"].append(excerpt)
        entry["texts_by_character"].setdefault(character_id, []).append(excerpt)
        entry["chapter_ids"].add(str(chapter.get("chapter_id") or ""))
    return catalog


def _normalize_warnings(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise CharacterProfileValidationError("warnings 必须是数组")
    normalized: list[str] = []
    for item in value:
        warning = _clean_string(item, field="warning", required=True)
        if len(warning) > 240:
            raise CharacterProfileValidationError("warning 不能超过240个字符")
        if warning not in normalized:
            normalized.append(warning)
    return normalized[:10]


def _normalize_confidence(value: Any) -> int:
    if isinstance(value, bool):
        raise CharacterProfileValidationError("confidence 必须是0到100的整数")
    try:
        confidence = int(value)
    except (TypeError, ValueError) as error:
        raise CharacterProfileValidationError("confidence 必须是0到100的整数") from error
    if confidence < 0 or confidence > 100:
        raise CharacterProfileValidationError("confidence 必须是0到100的整数")
    return confidence


def _normalize_evidence(
    value: Any,
    *,
    catalog: Mapping[tuple[str, str], Mapping[str, Any]],
    character_id: str,
    required: bool,
) -> tuple[list[dict[str, str]], set[str], set[str]]:
    if value is None and not required:
        return [], set(), set()
    if not isinstance(value, list):
        raise CharacterProfileValidationError("evidence 必须是数组")
    if required and not 1 <= len(value) <= 5:
        raise CharacterProfileValidationError("candidate 必须包含1到5条证据")
    if len(value) > 5:
        raise CharacterProfileValidationError("evidence 不能超过5条")
    normalized: list[dict[str, str]] = []
    source_types: set[str] = set()
    observed_chapters: set[str] = set()
    for raw in value:
        if not isinstance(raw, Mapping):
            raise CharacterProfileValidationError("evidence 项必须是对象")
        source_type = _clean_string(raw.get("source_type"), field="evidence.source_type", required=True)
        source_id = _stable_id(raw.get("source_id"), field="evidence.source_id")
        quote = _clean_string(raw.get("quote"), field="evidence.quote", required=True)
        if source_type not in EVIDENCE_SOURCE_TYPES:
            raise CharacterProfileValidationError("evidence.source_type 无效")
        if len(quote) > 600:
            raise CharacterProfileValidationError("evidence.quote 不能超过600个字符")
        source = catalog.get((source_type, source_id))
        if source is None:
            raise CharacterProfileValidationError("evidence 来源不属于输入快照")
        if source_type in {"character", "story_fact"} and str(
            source.get("character_id") or ""
        ) != character_id:
            raise CharacterProfileValidationError("evidence 来源不属于当前候选角色")
        searchable_texts = source.get("texts") or []
        if source_type == "chapter":
            searchable_texts = (source.get("texts_by_character") or {}).get(
                character_id,
                [],
            )
        if not any(quote in text for text in searchable_texts):
            raise CharacterProfileValidationError("evidence.quote 无法在输入快照中逐字命中")
        normalized.append(
            {"source_type": source_type, "source_id": source_id, "quote": quote}
        )
        source_types.add(source_type)
        if source_type == "chapter":
            observed_chapters.update(
                str(item) for item in source.get("chapter_ids") or [] if str(item)
            )
        elif source_type == "story_fact" and source.get("chapter_id"):
            observed_chapters.add(str(source["chapter_id"]))
    return normalized, source_types, observed_chapters


def _normalize_personality(value: Any) -> str:
    personality = _clean_string(value, field="personality", required=True)
    visible_count = sum(not character.isspace() for character in personality)
    if not 8 <= visible_count <= 120:
        raise CharacterProfileValidationError("personality 必须包含8到120个可见字符")
    if re.search(r"[\u3400-\u9fff\uf900-\ufaff]", personality) is None:
        raise CharacterProfileValidationError("personality 必须包含中文行为描述")
    if not any(marker in personality for marker in _BEHAVIOUR_MARKERS):
        raise CharacterProfileValidationError("personality 必须包含可指导人物选择的倾向或矛盾")
    return personality


def normalize_character_profile_output(
    snapshot: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Normalize one complete batch result and verify every quoted source."""

    _require_snapshot(snapshot)
    raw_characters = payload.get("characters")
    if not isinstance(raw_characters, list):
        raise CharacterProfileValidationError("模型结果缺少 characters 数组")
    snapshot_characters = {
        str(item.get("id")): item
        for item in snapshot.get("characters") or []
        if isinstance(item, Mapping)
    }
    if not snapshot_characters:
        raise CharacterProfileValidationError("没有可补全的活跃角色")
    catalog = _evidence_catalog(snapshot)
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in raw_characters:
        if not isinstance(raw, Mapping):
            raise CharacterProfileValidationError("characters 项必须是对象")
        character_id = _stable_id(raw.get("character_id"), field="character_id")
        if character_id in seen_ids:
            raise CharacterProfileValidationError("模型结果包含重复 character_id")
        seen_ids.add(character_id)
        snapshot_character = snapshot_characters.get(character_id)
        if snapshot_character is None:
            raise CharacterProfileValidationError("模型结果包含当前小说之外的角色")
        base_version = _positive_version(raw.get("base_version"), field="base_version")
        if base_version != int(snapshot_character.get("base_version") or 0):
            raise CharacterProfileValidationError("模型角色 base_version 与输入快照不一致")
        status = _clean_string(raw.get("status"), field="status", required=True)
        if status not in RESULT_STATUSES:
            raise CharacterProfileValidationError("模型角色 status 无效")
        warnings = _normalize_warnings(raw.get("warnings"))
        existing_personality = str(
            (snapshot_character.get("details") or {}).get("personality") or ""
        ).strip()
        if existing_personality and EXISTING_PERSONALITY_WARNING not in warnings:
            warnings.append(EXISTING_PERSONALITY_WARNING)

        item: dict[str, Any] = {
            "character_id": character_id,
            "base_version": base_version,
            "status": status,
            "warnings": warnings,
        }
        if status == "insufficient_evidence":
            if raw.get("personality") not in (None, ""):
                raise CharacterProfileValidationError(
                    "insufficient_evidence 不能包含 personality"
                )
            if raw.get("basis") is not None:
                basis = _clean_string(raw.get("basis"), field="basis", required=True)
                if basis not in BASIS_TYPES:
                    raise CharacterProfileValidationError("basis 无效")
                item["basis"] = basis
            if raw.get("confidence") is not None:
                item["confidence"] = _normalize_confidence(raw.get("confidence"))
            evidence, _, _ = _normalize_evidence(
                raw.get("evidence"),
                catalog=catalog,
                character_id=character_id,
                required=False,
            )
            item["evidence"] = evidence
            normalized.append(item)
            continue

        personality = _normalize_personality(raw.get("personality"))
        basis = _clean_string(raw.get("basis"), field="basis", required=True)
        if basis not in BASIS_TYPES:
            raise CharacterProfileValidationError("basis 无效")
        confidence = _normalize_confidence(raw.get("confidence"))
        evidence, source_types, observed_chapters = _normalize_evidence(
            raw.get("evidence"),
            catalog=catalog,
            character_id=character_id,
            required=True,
        )
        has_designed = bool(source_types & {"character", "outline"})
        has_observed = bool(source_types & {"chapter", "story_fact"})
        if basis == "designed" and (not has_designed or has_observed):
            raise CharacterProfileValidationError("designed 只能使用设定型证据")
        if basis == "mixed" and (not has_designed or not has_observed):
            raise CharacterProfileValidationError("mixed 必须同时包含设定与正文观察证据")
        if basis == "observed":
            if has_designed or len(observed_chapters) < 2:
                raise CharacterProfileValidationError(
                    "observed 必须覆盖至少两个不同正式章节且不能混入设定证据"
                )
        if basis == "mixed" and len(observed_chapters) < 2:
            if LIMITED_SAMPLE_WARNING not in warnings:
                warnings.append(LIMITED_SAMPLE_WARNING)
        item.update(
            {
                "personality": personality,
                "basis": basis,
                "confidence": confidence,
                "evidence": evidence,
            }
        )
        normalized.append(item)

    missing_ids = set(snapshot_characters) - seen_ids
    if missing_ids:
        raise CharacterProfileValidationError(
            "模型结果必须为输入快照中的每个角色返回候选或证据不足状态"
        )
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "characters": sorted(normalized, key=lambda item: item["character_id"]),
    }


def _job_snapshot_matches(job: Mapping[str, Any], snapshot: Mapping[str, Any]) -> bool:
    job_snapshot = job.get("input_snapshot")
    if isinstance(job_snapshot, Mapping):
        return _canonical_hash(job_snapshot) == _canonical_hash(snapshot)
    digest = str(job.get("snapshot_hash") or "")
    return bool(digest) and digest == _canonical_hash(snapshot)


def _record_time_key(record: Mapping[str, Any]) -> tuple[str, int, str]:
    try:
        attempt = int(record.get("attempt") or 0)
    except (TypeError, ValueError):
        attempt = 0
    return (
        str(record.get("created_at") or record.get("completed_at") or ""),
        attempt,
        str(record.get("id") or ""),
    )


def _job_snapshot_after_batch_matches(
    job: Mapping[str, Any],
    batch: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> bool:
    job_snapshot = job.get("input_snapshot")
    result_versions = batch.get("result_versions")
    after_snapshot = batch.get("after_snapshot")
    if not isinstance(job_snapshot, Mapping) or not isinstance(result_versions, Mapping):
        return False
    projected = json.loads(json.dumps(job_snapshot, ensure_ascii=False))
    projected_characters = {
        str(item.get("id") or ""): item
        for item in projected.get("characters") or []
        if isinstance(item, dict)
    }
    for character_id, version in result_versions.items():
        projected_character = projected_characters.get(str(character_id))
        if projected_character is None:
            return False
        projected_character["base_version"] = int(version)
        batch_details = (
            after_snapshot.get(str(character_id))
            if isinstance(after_snapshot, Mapping)
            else None
        )
        if isinstance(batch_details, Mapping):
            projected_character["details"] = {
                key: _bounded_text(batch_details.get(key), 2_000)
                for key in CHARACTER_DETAIL_ALLOWLIST
                if batch_details.get(key) is not None
                and str(batch_details.get(key)).strip()
            }
    return _canonical_hash(projected) == _canonical_hash(snapshot)


def calculate_character_profile_completion_status(
    snapshot: Mapping[str, Any],
    *,
    jobs: Iterable[Mapping[str, Any]] = (),
    apply_batches: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Derive the persisted UI state without relying on in-memory modal state."""

    _require_snapshot(snapshot)
    snapshot_hash = _canonical_hash(snapshot)
    characters = [item for item in snapshot.get("characters") or [] if isinstance(item, Mapping)]
    outline = snapshot.get("outline") if isinstance(snapshot.get("outline"), Mapping) else {}
    designed_source_count = sum(
        bool(str(item.get("description") or "").strip())
        or any(str(value or "").strip() for value in (item.get("details") or {}).values())
        for item in characters
    ) + int(bool(str(outline.get("background") or "").strip() or str(outline.get("main_plot") or "").strip()))
    eligible = bool(characters) and designed_source_count > 0
    job_rows = sorted((dict(item) for item in jobs), key=_record_time_key, reverse=True)
    matching_job = next((item for item in job_rows if _job_snapshot_matches(item, snapshot)), None)
    latest_job = job_rows[0] if job_rows else None
    batch_rows = sorted((dict(item) for item in apply_batches), key=_record_time_key, reverse=True)

    jobs_by_id = {str(item.get("id") or ""): item for item in job_rows}
    completed_batch = None
    completed_job = None
    for batch in batch_rows:
        candidate_job = jobs_by_id.get(str(batch.get("generation_job_id") or ""))
        if candidate_job is None:
            continue
        if _job_snapshot_after_batch_matches(candidate_job, batch, snapshot):
            completed_batch = batch
            completed_job = candidate_job
            break

    state = "never"
    stale = False
    if not eligible:
        state = "ineligible"
    elif completed_batch is not None and completed_job is not None:
        state = "applied"
        matching_job = completed_job
    elif matching_job is not None:
        job_state = str(matching_job.get("state") or "")
        if job_state not in JOB_STATES:
            raise CharacterProfileValidationError("character profile job state 无效")
        state = job_state
        if job_state == "ready":
            matching_job_id = str(matching_job.get("id") or "")
            if any(
                str(batch.get("generation_job_id") or "") == matching_job_id
                and str(batch.get("state") or "") in {"applied", "restored"}
                for batch in batch_rows
            ):
                state = "applied"
    elif latest_job is not None:
        state = "stale"
        stale = True

    return {
        "eligible": eligible,
        "state": state,
        "stale": stale,
        "input_hash": snapshot_hash,
        "source_summary": {
            "characters": len(characters),
            "designed_sources": designed_source_count,
            "story_facts": len(snapshot.get("story_facts") or []),
            "chapters": len(
                {
                    str(item.get("chapter_id") or "")
                    for item in snapshot.get("chapter_evidence") or []
                    if isinstance(item, Mapping) and item.get("chapter_id")
                }
            ),
            "chapter_windows": len(snapshot.get("chapter_evidence") or []),
        },
        "job": matching_job,
        "latest_job": latest_job,
        "apply_batch": completed_batch,
    }


def validate_character_profile_apply_plan(
    snapshot: Mapping[str, Any],
    normalized_output: Mapping[str, Any],
    *,
    decisions: Sequence[Mapping[str, Any]],
    current_characters: Iterable[Mapping[str, Any]],
    job: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate author-explicit decisions and return a transaction-ready plan.

    The caller must repeat these checks while holding all target rows in stable
    UUID order.  This function plans a batch; it does not mutate any input.
    """

    _require_snapshot(snapshot)
    if not isinstance(decisions, Sequence) or isinstance(decisions, (str, bytes)):
        raise CharacterProfileValidationError("decisions 必须是显式选择数组")
    if not 1 <= len(decisions) <= 200:
        raise CharacterProfileValidationError("必须显式选择1到200个角色")
    if str(job.get("kind") or "") != "character_profile_completion":
        raise CharacterProfileValidationError("应用任务类型无效")
    if str(job.get("state") or "") != "ready":
        raise CharacterProfileValidationError("角色卡补全任务尚未就绪")
    if not _job_snapshot_matches(job, snapshot):
        raise CharacterProfileValidationError("生成任务输入快照已过期")
    requested_provider = _clean_string(
        job.get("requested_provider_id"), field="requested_provider_id", required=True
    )
    requested_model = _clean_string(
        job.get("requested_model_id"), field="requested_model_id", required=True
    )
    evidence = job.get("model_evidence")
    if isinstance(evidence, Mapping):
        try:
            candidate_actual_identity(
                evidence,
                requested_provider_id=requested_provider,
                requested_model_id=requested_model,
            )
        except ModelEvidencePolicyError as error:
            raise CharacterProfileValidationError(str(error)) from error
    else:
        actual_provider = _clean_string(
            job.get("actual_provider_id"), field="actual_provider_id", required=True
        )
        actual_model = _clean_string(
            job.get("actual_model_id"), field="actual_model_id", required=True
        )
        if (requested_provider, requested_model) != (actual_provider, actual_model):
            raise CharacterProfileValidationError("requested/actual 模型证据不一致")
    if job.get("output_json") != normalized_output:
        raise CharacterProfileValidationError("应用结果不是生成任务已核验的 output_json")
    revalidated_output = normalize_character_profile_output(snapshot, normalized_output)
    if revalidated_output != normalized_output:
        raise CharacterProfileValidationError("应用结果未使用规范化的角色卡候选结构")

    candidates = {
        str(item.get("character_id")): item
        for item in normalized_output.get("characters") or []
        if isinstance(item, Mapping)
    }
    snapshot_characters = {
        str(item.get("id")): item
        for item in snapshot.get("characters") or []
        if isinstance(item, Mapping)
    }
    current_by_id = {
        str(item.get("id")): item
        for item in current_characters
        if isinstance(item, Mapping)
    }
    planned: list[dict[str, Any]] = []
    seen: set[str] = set()
    before_snapshot: dict[str, Any] = {}
    after_snapshot: dict[str, Any] = {}
    base_versions: dict[str, int] = {}
    for raw in decisions:
        if not isinstance(raw, Mapping):
            raise CharacterProfileValidationError("decision 必须是对象")
        character_id = _stable_id(raw.get("character_id"), field="decision.character_id")
        if character_id in seen:
            raise CharacterProfileValidationError("decisions 包含重复 character_id")
        seen.add(character_id)
        if set(raw) - {"character_id", "base_version", "replace_existing"}:
            raise CharacterProfileValidationError("decision 包含非冻结字段")
        base_version = _positive_version(raw.get("base_version"), field="decision.base_version")
        replace_existing = raw.get("replace_existing", False)
        if not isinstance(replace_existing, bool):
            raise CharacterProfileValidationError("replace_existing 必须是布尔值")
        candidate = candidates.get(character_id)
        if candidate is None or candidate.get("status") != "candidate":
            raise CharacterProfileValidationError("只能应用 status=candidate 的角色")
        snapshot_character = snapshot_characters.get(character_id)
        current = current_by_id.get(character_id)
        if snapshot_character is None or current is None:
            raise CharacterProfileValidationError("应用角色不属于当前小说或已不存在")
        if str(current.get("lifecycle_state") or "active") != "active":
            raise CharacterProfileValidationError("已归档角色不能应用性格候选")
        versions = {
            base_version,
            int(candidate.get("base_version") or 0),
            int(snapshot_character.get("base_version") or 0),
            int(current.get("version") or 0),
        }
        if len(versions) != 1:
            raise CharacterProfileValidationError("角色版本冲突，整批不能应用")
        current_details = current.get("details") if isinstance(current.get("details"), Mapping) else {}
        before_personality = str(current_details.get("personality") or "").strip()
        next_personality = str(candidate.get("personality") or "").strip()
        if not next_personality:
            raise CharacterProfileValidationError("候选缺少 personality")
        if before_personality == next_personality:
            raise CharacterProfileValidationError("候选与当前 personality 相同，无需应用")
        if before_personality and not replace_existing:
            raise CharacterProfileValidationError(
                "替换当前非空人工 personality 必须显式 replace_existing=true"
            )
        before_snapshot[character_id] = {"personality": before_personality}
        after_snapshot[character_id] = {"personality": next_personality}
        base_versions[character_id] = base_version
        planned.append(
            {
                "character_id": character_id,
                "base_version": base_version,
                "replace_existing": replace_existing,
                "personality": next_personality,
            }
        )

    return {
        "generation_job_id": _stable_id(job.get("id"), field="job.id"),
        "decisions": sorted(planned, key=lambda item: item["character_id"]),
        "before_snapshot": before_snapshot,
        "after_snapshot": after_snapshot,
        "base_versions": base_versions,
    }
