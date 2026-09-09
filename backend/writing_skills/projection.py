"""Pure, task-specific projections; callers retain scope/version authorization.

Only pass the existing outline snapshot's ``model_context`` here. In particular,
this module never accepts an audit envelope or fetches additional story data.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal

from .contracts import Scope, SourceItem, Task, TaskModelInputProjectionV1, canonical_hash
from .middleware import NativeTaskRoute


def chapter_projection(scope: Scope, snapshot: Mapping[str, Any],
                       task_prompt: str, *, required_ids: tuple[str, ...] = ()) -> TaskModelInputProjectionV1:
    """Project the exact existing chapter prompt plus its visible genre fields.

    The caller supplies a server-built snapshot and its actual prompt, not a
    second story query. Full-prompt identity remains frozen even when routing's
    bounded view is truncated. Audit/unused snapshot fields never enter sources.
    """
    novel, chapter, brief = snapshot["novel"], snapshot["chapter"], snapshot["brief"]
    if (scope.kind != "novel" or str(scope.scope_id) != novel["id"]
            or str(scope.document_id) != chapter["document_id"]):
        raise ValueError("chapter projection scope mismatch")
    classification = {key: novel.get(key, "") for key in ("genre", "subgenre")}
    if any(not isinstance(value, str) for value in classification.values()):
        raise ValueError("genre fields must be text")
    # Typed labels may not silently influence routing unless generation sees
    # the same labels. Older snapshots with no classification remain compatible.
    if any(classification.values()) and (
        "分类资料：" + json.dumps(classification, ensure_ascii=False, sort_keys=True)
    ) not in task_prompt:
        raise ValueError("classification absent from generation prompt")
    sources = [SourceItem(key=key, text=value, kind=key)
               for key, value in classification.items() if value]
    if required_ids:
        sources.insert(0, SourceItem(key="author_method_requirements", kind="author_request",
            text=json.dumps({"required_method_ids": list(required_ids)}, ensure_ascii=False, sort_keys=True)))
    remaining = 80000 - sum(len(source.text) for source in sources)
    clipped = task_prompt[:remaining]
    for offset in range(0, len(clipped), 40000):
        sources.append(SourceItem(key=f"task_prompt.{offset // 40000}",
                                  text=clipped[offset:offset + 40000], kind="content"))
    return TaskModelInputProjectionV1(
        scope=scope, task="chapter_body", intent="write",
        source_version=canonical_hash({"brief_version": brief["version"],
            "draft_version": chapter["base_draft_version"],
            "revision_id": chapter["base_revision_id"], "content_hash": chapter["base_content_hash"]}),
        visibility_key=canonical_hash(task_prompt), sources=tuple(sources),
        truncated=len(clipped) != len(task_prompt),
    )


def chapter_routing_projection(scope: Scope, snapshot: Mapping[str, Any], *,
                               required_ids: tuple[str, ...] = ()) -> TaskModelInputProjectionV1:
    """Project story inputs without transient length-validation feedback.

    Length retries must use their first attempt's frozen method packet. The
    calibration instruction remains in the generation prompt and job snapshot,
    but cannot silently cause a second route/Skill selection. The budget ledger
    is removed only while rebuilding this projection because it binds the full
    generation prompt, including the calibration feedback.
    """
    routing_snapshot = dict(snapshot)
    routing_snapshot.pop("length_control", None)
    routing_snapshot.pop("prompt_budget_ledger", None)
    # Local import avoids the existing services -> writing_skills dependency at
    # module import time while still using the one authoritative prompt builder.
    from ..services import build_chapter_generation_prompt
    task_prompt = build_chapter_generation_prompt(routing_snapshot)
    return chapter_projection(scope, routing_snapshot, task_prompt, required_ids=required_ids)


def native_projection(
    scope: Scope,
    snapshot: Mapping[str, Any],
    user_text: str,
    route: NativeTaskRoute,
    *,
    genre: str = "",
    subgenre: str = "",
    required_ids: tuple[str, ...] = (),
) -> TaskModelInputProjectionV1:
    """Project only the current native request plus server-verified labels.

    The page snapshot supplies scope/version evidence and model-visible page
    data, while the current text is the only free-form routing content.  Genre
    fields must be loaded from the authorized novel row by the caller.  No
    term from the title or prose is promoted to a mechanism source.
    """

    novel = snapshot.get("novel")
    draft = snapshot.get("creationDraft")
    document = snapshot.get("document")
    if scope.kind == "creation_draft":
        if (
            not isinstance(draft, Mapping)
            or str(scope.scope_id) != str(draft.get("id"))
            or scope.document_id is not None
            or novel is not None
        ):
            raise ValueError("native creation draft scope mismatch")
    elif scope.kind == "novel":
        if not isinstance(novel, Mapping) or str(scope.scope_id) != str(novel.get("id")):
            raise ValueError("native novel scope mismatch")
        if scope.document_id is not None and (
            not isinstance(document, Mapping)
            or str(scope.document_id) != str(document.get("id"))
        ):
            raise ValueError("native document scope mismatch")
    else:
        raise ValueError("unsupported native scope")
    if not isinstance(user_text, str) or not user_text.strip():
        raise ValueError("native current user text is required")
    if not isinstance(genre, str) or not isinstance(subgenre, str):
        raise ValueError("native classification must be text")
    sources: list[SourceItem] = []
    if required_ids:
        sources.append(SourceItem(
            key="author_method_requirements",
            kind="author_request",
            text=_json_text(
                {"required_method_ids": list(required_ids)},
                label="native method requirements",
            ),
        ))
    if genre:
        sources.append(SourceItem(key="genre", kind="genre", text=genre))
    if subgenre:
        sources.append(SourceItem(key="subgenre", kind="subgenre", text=subgenre))
    sources.append(SourceItem(key="current_user_request", kind="content", text=user_text))
    stable_page = {
        "context_revision": snapshot.get("contextRevision"),
        "page": snapshot.get("page"),
        "creation_draft": snapshot.get("creationDraft"),
        "document": snapshot.get("document"),
        "selection": snapshot.get("selection"),
        "genre": genre,
        "subgenre": subgenre,
    }
    return TaskModelInputProjectionV1(
        scope=scope,
        task=route.task,
        intent=route.intent,
        operation=route.operation,
        source_version=canonical_hash(stable_page),
        visibility_key=canonical_hash({
            "current_user_request": user_text,
            "snapshot": stable_page,
        }),
        sources=tuple(sources),
    )

_BASE = (
    "novel_title", "audience", "genre", "subgenre", "idea", "template_name",
    "template_data", "target_chapter_count",
)
_PREREQUISITES = {
    "outline_background": (),
    "outline_characters": ("background_text",),
    "outline_plot": ("background_text", "characters"),
    "outline_highlight": ("background_text", "characters", "plot_text"),
}
_TARGETS = {
    "outline_background": "background_text",
    "outline_characters": "characters",
    "outline_plot": "plot_text",
    "outline_highlight": "highlight_text",
}

_CREATIVE_TASKS: dict[str, Task] = {
    "novel_template": "novel_template",
    "novel_naming": "novel_naming",
    "outline_background": "outline_background",
    "outline_characters": "outline_characters",
    "outline_plot": "outline_plot",
    "outline_highlight": "outline_highlight",
    "chapter_storyline_recommendation": "chapter_storyline_recommendation",
    "chapter_outline": "chapter_outline",
    "character_profile_completion": "character_profile_completion",
    "review": "review",
    "selection_edit": "selection_edit",
}
_CREATIVE_EXCLUDED = frozenset({"novel_cover", "relationship_graph"})
_CREATIVE_TRANSIENT_FIELDS: dict[str, frozenset[str]] = {
    "chapter_outline": frozenset({"rewrite_attempt", "rewrite_requirement"}),
}


def _json_text(value: Any, *, label: str) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} contains non-JSON content") from error


def _creative_classification(snapshot: Mapping[str, Any]) -> dict[str, str]:
    """Read only explicit prompt-visible genre fields, never infer from prose."""

    nested = snapshot.get("novel")
    nested_novel = nested if isinstance(nested, Mapping) else {}
    result: dict[str, str] = {}
    for key in ("genre", "subgenre"):
        values = [value for value in (snapshot.get(key), nested_novel.get(key))
                  if value not in (None, "")]
        if any(not isinstance(value, str) for value in values):
            raise ValueError("genre fields must be text")
        distinct = {value for value in values}
        if len(distinct) > 1:
            raise ValueError("conflicting genre fields")
        if distinct:
            result[key] = next(iter(distinct))
    return result


def _bounded_prompt_sources(
    prompt: str,
    *,
    classification: Mapping[str, str],
    required_ids: tuple[str, ...],
) -> tuple[tuple[SourceItem, ...], bool]:
    if not isinstance(prompt, str):
        raise ValueError("task_prompt must be text")
    sources: list[SourceItem] = []
    if required_ids:
        sources.append(SourceItem(
            key="author_method_requirements",
            kind="author_request",
            text=_json_text(
                {"required_method_ids": list(required_ids)},
                label="method requirements",
            ),
        ))
    sources.extend(SourceItem(key=key, kind=key, text=value)
                   for key, value in classification.items())
    remaining = 80000 - sum(len(item.text) for item in sources)
    clipped = prompt[:remaining]
    for offset in range(0, len(clipped), 40000):
        sources.append(SourceItem(
            key=f"task_prompt.{offset // 40000}",
            kind="content",
            text=clipped[offset:offset + 40000],
        ))
    return tuple(sources), len(clipped) != len(prompt)


def creative_projection(
    scope: Scope,
    kind: str,
    input_snapshot: Mapping[str, Any],
    task_prompt: str,
    *,
    required_ids: tuple[str, ...] = (),
) -> TaskModelInputProjectionV1:
    """Project an existing creative helper's exact model-visible input.

    Cover generation and relationship/fact extraction are intentionally not
    writing-method tasks. Outline stages reuse their stricter allowlist so the
    audit envelope and a fresh target can never influence routing. Chapter
    outline validation retries retain their feedback in the generation prompt
    but route from the first attempt's stable story input.
    """

    if kind in _CREATIVE_EXCLUDED:
        raise ValueError("creative kind is excluded from writing methods")
    task = _CREATIVE_TASKS.get(kind)
    if task is None:
        raise ValueError("unsupported creative kind")
    if not isinstance(input_snapshot, Mapping):
        raise ValueError("creative input snapshot must be an object")
    if kind in _PREREQUISITES:
        if scope.kind != "novel":
            raise ValueError("outline writing method requires novel scope")
        model_context = input_snapshot.get("model_context")
        if not isinstance(model_context, Mapping):
            raise ValueError("outline model_context is required")
        intent = input_snapshot.get("intent")
        if intent not in ("fresh", "refine"):
            raise ValueError("outline intent is invalid")
        exploration = input_snapshot.get("exploration_direction")
        author_request = _json_text(
            {
                **({"exploration_direction": exploration} if exploration else {}),
                **({"required_method_ids": list(required_ids)} if required_ids else {}),
            },
            label="outline author request",
        ) if exploration or required_ids else ""
        stable = outline_projection(
            scope,
            task,
            intent,
            model_context,
            canonical_hash({
                "kind": kind,
                "intent": intent,
                "model_context": model_context,
                "exploration_direction": exploration,
            }),
            canonical_hash({
                "kind": kind,
                "intent": intent,
                "model_context": model_context,
                "exploration_direction": exploration,
            }),
            author_request,
        )
        return stable
    if kind in {"novel_template", "novel_naming"}:
        if scope.kind != "creation_draft" or scope.document_id is not None:
            raise ValueError("novel creation helper requires creation_draft scope")
    elif scope.kind != "novel":
        raise ValueError("creative writing method requires novel scope")

    # Verify the caller supplied the same prompt the existing generation path
    # produces. No secondary story query or alternate prompt is accepted.
    from ..creative_services import build_creative_generation_prompt
    expected_prompt = build_creative_generation_prompt({
        "kind": kind,
        "input_snapshot": dict(input_snapshot),
    })
    if task_prompt != expected_prompt:
        raise ValueError("creative generation prompt mismatch")
    routing_snapshot = {
        key: value for key, value in input_snapshot.items()
        if key not in _CREATIVE_TRANSIENT_FIELDS.get(kind, frozenset())
    }
    routing_prompt = build_creative_generation_prompt({
        "kind": kind,
        "input_snapshot": routing_snapshot,
    })
    classification = _creative_classification(routing_snapshot)
    sources, truncated = _bounded_prompt_sources(
        routing_prompt,
        classification=classification,
        required_ids=required_ids,
    )
    operation = str(routing_snapshot.get("operation") or "") if kind == "selection_edit" else ""
    intent: Literal["fresh", "write", "review"] = (
        "review" if kind == "review" or operation == "review"
        else "fresh" if kind in {"novel_template", "novel_naming", "chapter_storyline_recommendation", "chapter_outline"}
        else "write"
    )
    return TaskModelInputProjectionV1(
        scope=scope,
        task=task,
        intent=intent,
        operation=operation,
        source_version=canonical_hash({"kind": kind, "input_snapshot": routing_snapshot}),
        visibility_key=canonical_hash(routing_prompt),
        sources=sources,
        truncated=truncated,
    )


def outline_projection(
    scope: Scope,
    task: Task,
    intent: Literal["fresh", "refine"],
    model_context: Mapping[str, Any],
    source_version: str,
    visibility_key: str,
    author_request: str = "",
) -> TaskModelInputProjectionV1:
    """Reapply ``build_outline_generation_snapshot``'s task/intent allowlist.

    Unknown top-level fields are ignored; a complete model/audit envelope is
    rejected to make accidental use of the wrong input explicit. Nested values
    are only accepted under upstream-approved structured content fields. They
    remain content, never authoritative genre/mechanism labels or instructions.
    """
    if task not in _PREREQUISITES or intent not in ("fresh", "refine"):
        raise ValueError("unsupported outline task or intent")
    if "audit_context" in model_context or "model_context" in model_context:
        raise ValueError("pass only task-approved model_context, not its envelope")
    fields = (*_BASE, *_PREREQUISITES[task])
    if intent == "refine":
        fields += (_TARGETS[task],)
    sources: list[SourceItem] = []
    remaining = 80000
    truncated = False

    def append(key: str, text: str, kind: str) -> None:
        nonlocal remaining, truncated
        if not text:
            return
        limit = min(40000, remaining)
        clipped = text[:limit]
        truncated |= len(clipped) != len(text)
        if clipped:
            sources.append(SourceItem(key=key, text=clipped, kind=kind))
            remaining -= len(clipped)

    # Preserve the explicit request before optional story content under pressure.
    if not isinstance(author_request, str):
        raise ValueError("author_request must be text")
    append("author_request", author_request, "author_request")
    for field in fields:
        value = model_context.get(field)
        if value in (None, "", [], {}):
            continue
        kind = field if field in ("genre", "subgenre") else "content"
        if kind != "content" and not isinstance(value, str):
            raise ValueError("genre fields must be text")
        if isinstance(value, str):
            text = value
        else:
            # Do not stringify arbitrary application/ORM objects with repr().
            try:
                text = json.dumps(value, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":"), allow_nan=False)
            except (TypeError, ValueError) as error:
                raise ValueError("model_context contains non-JSON content") from error
        append(field, text, kind)
    return TaskModelInputProjectionV1(
        scope=scope, task=task, intent=intent, source_version=source_version,
        visibility_key=visibility_key, sources=tuple(sources), truncated=truncated,
    )
