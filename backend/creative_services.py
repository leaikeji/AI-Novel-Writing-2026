"""Domain services for the complete long-form creation workflow."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    AssetPreset,
    AssetPresetItem,
    ChapterBrief,
    ChapterCreationDraft,
    CharacterRelationship,
    CharacterRelationshipRevision,
    CreativeGenerationJob,
    Document,
    DocumentRevision,
    DocumentWorkingCopy,
    Foreshadow,
    IntelligenceProposal,
    IntelligenceProposalItem,
    Novel,
    NovelCharacter,
    NovelCreationDraft,
    NovelExport,
    OutlineDraft,
    PrivateAsset,
    RelationshipGraphPosition,
    RelationshipGraphView,
    StoryFact,
    Storyline,
    Volume,
)
from .services import (
    DomainError,
    NotFoundError,
    ValidationError,
    _document_payload,
    _lock_generation_attempt,
    _new_document,
    _normalize_role_constraints,
    _require_document,
    _require_novel,
    _revision_payload,
    content_hash,
    get_document,
    get_novel,
    markdown_to_text,
    visible_character_count,
)


PRIVATE_ASSET_TYPES = {"plot", "writing_style", "vocabulary", "idea"}
ROLE_TYPES = {"main", "supporting"}
RELATIONSHIP_DIRECTIONALITIES = {"directed", "undirected"}
RELATIONSHIP_KINDS = {
    "family",
    "colleague",
    "mentor",
    "ally",
    "enemy",
    "romance",
    "other",
}
RELATIONSHIP_STATUSES = {"active", "resolved", "archived"}
STORYLINE_TYPES = {"main", "support", "romance", "faction"}
STORYLINE_STATUSES = {"active", "paused", "completed", "archived"}
FORESHADOW_STATUSES = {"planned", "active", "resolved", "dropped"}
CREATIVE_GENERATION_KINDS = {
    "novel_template",
    "novel_naming",
    "novel_cover",
    "outline_background",
    "outline_characters",
    "outline_plot",
    "outline_highlight",
    "chapter_storyline_recommendation",
    "chapter_outline",
    "relationship_graph",
    "review",
}


class EntityConflictError(DomainError):
    def __init__(self, current: dict[str, Any]):
        super().__init__("entity version conflict")
        self.current = current


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _clean_title(value: str, label: str = "标题") -> str:
    title = value.strip()
    if not title:
        raise ValidationError(f"{label}不能为空")
    if len(title) > 240:
        raise ValidationError(f"{label}不能超过240个字符")
    return title


def _next_position(session: Session, model: Any, novel_id: UUID) -> int:
    current = session.scalar(select(func.max(model.position)).where(model.novel_id == novel_id))
    return int(current or 0) + 1000


def _require_volume(session: Session, novel_id: UUID, volume_id: UUID) -> Volume:
    volume = session.get(Volume, volume_id)
    if volume is None or volume.novel_id != novel_id:
        raise ValidationError("分卷不属于当前小说")
    return volume


def _creation_draft_payload(draft: NovelCreationDraft) -> dict[str, Any]:
    return {
        "id": str(draft.id),
        "draft_key": draft.draft_key,
        "step": draft.step,
        "state": draft.state,
        "version": draft.version,
        "data": draft.data_json,
        "completed_novel_id": str(draft.completed_novel_id) if draft.completed_novel_id else None,
        "created_at": _iso(draft.created_at),
        "updated_at": _iso(draft.updated_at),
    }


def get_or_create_novel_creation_draft(
    session: Session, draft_key: str
) -> dict[str, Any]:
    key = draft_key.strip()
    if not key or len(key) > 120:
        raise ValidationError("建书草稿键无效")
    draft = session.scalar(
        select(NovelCreationDraft).where(NovelCreationDraft.draft_key == key)
    )
    if draft is None:
        draft = NovelCreationDraft(id=uuid4(), draft_key=key, data_json={})
        session.add(draft)
        session.commit()
    return _creation_draft_payload(draft)


def get_novel_creation_draft(session: Session, draft_id: UUID) -> dict[str, Any]:
    draft = session.get(NovelCreationDraft, draft_id)
    if draft is None:
        raise NotFoundError(f"novel creation draft {draft_id} not found")
    return _creation_draft_payload(draft)


def update_novel_creation_draft(
    session: Session,
    draft_id: UUID,
    *,
    expected_version: int,
    step: int,
    data_patch: dict[str, Any],
) -> dict[str, Any]:
    draft = session.scalar(
        select(NovelCreationDraft)
        .where(NovelCreationDraft.id == draft_id)
        .with_for_update()
    )
    if draft is None:
        raise NotFoundError(f"novel creation draft {draft_id} not found")
    if draft.version != expected_version:
        raise EntityConflictError(_creation_draft_payload(draft))
    if draft.state == "completed":
        raise ValidationError("已完成的建书草稿不能修改")
    if not 0 <= step <= 6:
        raise ValidationError("建书步骤必须在0到6之间")
    merged = dict(draft.data_json or {})
    merged.update(data_patch)
    if len(json.dumps(merged, ensure_ascii=False, default=str)) > 200_000:
        raise ValidationError("建书草稿内容过大")
    draft.data_json = merged
    draft.step = step
    draft.version += 1
    session.commit()
    return _creation_draft_payload(draft)


def complete_novel_creation_draft(
    session: Session, draft_id: UUID, *, expected_version: int
) -> dict[str, Any]:
    draft = session.scalar(
        select(NovelCreationDraft)
        .where(NovelCreationDraft.id == draft_id)
        .with_for_update()
    )
    if draft is None:
        raise NotFoundError(f"novel creation draft {draft_id} not found")
    if draft.state == "completed" and draft.completed_novel_id:
        return {"draft": _creation_draft_payload(draft), "novel": get_novel(session, draft.completed_novel_id)}
    if draft.version != expected_version:
        raise EntityConflictError(_creation_draft_payload(draft))
    data = dict(draft.data_json or {})
    if data.get("writing_type", "long") != "long":
        raise ValidationError("当前闭环只允许创建长篇小说")
    audience = str(data.get("audience", "")).strip()
    if audience not in {"male", "female"}:
        raise ValidationError("请选择小说受众")
    genre = str(data.get("genre", "")).strip()
    if not genre:
        raise ValidationError("请选择小说题材")
    idea = str(data.get("idea", "")).strip()
    if not idea:
        raise ValidationError("请填写或生成创作思路")
    template_key = str(data.get("template_key", "")).strip()
    template_name = str(data.get("template_name", "")).strip()
    if not template_key and not template_name:
        raise ValidationError("请选择创作模板")
    title = _clean_title(str(data.get("title", "")), "小说名称")
    author_name = str(data.get("author_name", "")).strip()
    if not author_name:
        raise ValidationError("请填写作者名称")
    if len(author_name) > 120:
        raise ValidationError("作者名称不能超过120个字符")
    cover_mode = str(data.get("cover_mode", "system"))
    if cover_mode not in {"ai", "system", "upload"}:
        raise ValidationError("请选择有效封面方式")
    novel = Novel(
        id=uuid4(),
        title=title,
        author_name=author_name,
        description=str(data.get("description", "")).strip(),
        writing_type="long",
        audience=audience,
        genre=genre,
        subgenre=str(data.get("subgenre", "")).strip(),
        idea=idea,
        template_key=template_key or None,
        template_name=template_name,
        template_data=dict(data.get("template_data") or {}),
        cover_mode=cover_mode,
        cover_image_data=str(data.get("cover_image_data", "")),
    )
    # Keep the book empty after creation, matching the reference flow: the
    # author explicitly creates and names the first volume from the chapter page.
    session.add(novel)
    session.flush()
    draft.state = "completed"
    draft.step = 6
    draft.completed_novel_id = novel.id
    draft.version += 1
    session.commit()
    return {"draft": _creation_draft_payload(draft), "novel": get_novel(session, novel.id)}


def _asset_payload(asset: PrivateAsset) -> dict[str, Any]:
    return {
        "id": str(asset.id),
        "asset_type": asset.asset_type,
        "title": asset.title,
        "content": asset.content,
        "version": asset.version,
        "archived": asset.archived,
        "created_at": _iso(asset.created_at),
        "updated_at": _iso(asset.updated_at),
    }


def list_private_assets(
    session: Session, *, asset_type: str | None = None, include_archived: bool = False
) -> list[dict[str, Any]]:
    if asset_type is not None and asset_type not in PRIVATE_ASSET_TYPES:
        raise ValidationError("私有库资料类型无效")
    statement = select(PrivateAsset)
    if asset_type:
        statement = statement.where(PrivateAsset.asset_type == asset_type)
    if not include_archived:
        statement = statement.where(PrivateAsset.archived.is_(False))
    assets = session.scalars(statement.order_by(PrivateAsset.created_at, PrivateAsset.id)).all()
    return [_asset_payload(asset) for asset in assets]


def create_private_asset(
    session: Session, *, asset_type: str, title: str, content: str
) -> dict[str, Any]:
    if asset_type not in PRIVATE_ASSET_TYPES:
        raise ValidationError("私有库资料类型无效")
    asset = PrivateAsset(
        id=uuid4(), asset_type=asset_type, title=_clean_title(title), content=content.strip()
    )
    session.add(asset)
    session.commit()
    return _asset_payload(asset)


def update_private_asset(
    session: Session,
    asset_id: UUID,
    *,
    expected_version: int,
    title: str,
    content: str,
) -> dict[str, Any]:
    asset = session.scalar(
        select(PrivateAsset).where(PrivateAsset.id == asset_id).with_for_update()
    )
    if asset is None:
        raise NotFoundError(f"private asset {asset_id} not found")
    if asset.version != expected_version:
        raise EntityConflictError(_asset_payload(asset))
    asset.title = _clean_title(title)
    asset.content = content.strip()
    asset.version += 1
    session.commit()
    return _asset_payload(asset)


def archive_private_asset(
    session: Session, asset_id: UUID, *, expected_version: int
) -> dict[str, Any]:
    asset = session.scalar(
        select(PrivateAsset).where(PrivateAsset.id == asset_id).with_for_update()
    )
    if asset is None:
        raise NotFoundError(f"private asset {asset_id} not found")
    if asset.version != expected_version:
        raise EntityConflictError(_asset_payload(asset))
    asset.archived = True
    asset.version += 1
    session.commit()
    return _asset_payload(asset)


def _preset_payload(session: Session, preset: AssetPreset) -> dict[str, Any]:
    rows = session.execute(
        select(AssetPresetItem, PrivateAsset)
        .join(PrivateAsset, PrivateAsset.id == AssetPresetItem.asset_id)
        .where(AssetPresetItem.preset_id == preset.id)
        .order_by(AssetPresetItem.position)
    ).all()
    return {
        "id": str(preset.id),
        "title": preset.title,
        "description": preset.description,
        "version": preset.version,
        "archived": preset.archived,
        "assets": [_asset_payload(asset) for _, asset in rows],
        "created_at": _iso(preset.created_at),
        "updated_at": _iso(preset.updated_at),
    }


def list_asset_presets(session: Session, *, include_archived: bool = False) -> list[dict[str, Any]]:
    statement = select(AssetPreset)
    if not include_archived:
        statement = statement.where(AssetPreset.archived.is_(False))
    presets = session.scalars(statement.order_by(AssetPreset.created_at, AssetPreset.id)).all()
    return [_preset_payload(session, preset) for preset in presets]


def _validated_assets(session: Session, asset_ids: Iterable[UUID]) -> list[PrivateAsset]:
    ids = list(dict.fromkeys(asset_ids))
    if not ids:
        return []
    assets = session.scalars(
        select(PrivateAsset).where(PrivateAsset.id.in_(ids), PrivateAsset.archived.is_(False))
    ).all()
    by_id = {asset.id: asset for asset in assets}
    if set(ids) != set(by_id):
        raise ValidationError("预设中包含不存在或已删除的私有库资料")
    return [by_id[item_id] for item_id in ids]


def create_asset_preset(
    session: Session, *, title: str, description: str, asset_ids: list[UUID]
) -> dict[str, Any]:
    assets = _validated_assets(session, asset_ids)
    preset = AssetPreset(
        id=uuid4(), title=_clean_title(title, "预设名称"), description=description.strip()
    )
    session.add(preset)
    session.flush()
    session.add_all(
        AssetPresetItem(id=uuid4(), preset_id=preset.id, asset_id=asset.id, position=index * 1000)
        for index, asset in enumerate(assets, start=1)
    )
    session.commit()
    return _preset_payload(session, preset)


def update_asset_preset(
    session: Session,
    preset_id: UUID,
    *,
    expected_version: int,
    title: str,
    description: str,
    asset_ids: list[UUID],
) -> dict[str, Any]:
    preset = session.scalar(
        select(AssetPreset).where(AssetPreset.id == preset_id).with_for_update()
    )
    if preset is None:
        raise NotFoundError(f"asset preset {preset_id} not found")
    if preset.version != expected_version:
        raise EntityConflictError(_preset_payload(session, preset))
    assets = _validated_assets(session, asset_ids)
    old_items = session.scalars(
        select(AssetPresetItem).where(AssetPresetItem.preset_id == preset.id)
    ).all()
    for item in old_items:
        session.delete(item)
    session.flush()
    session.add_all(
        AssetPresetItem(id=uuid4(), preset_id=preset.id, asset_id=asset.id, position=index * 1000)
        for index, asset in enumerate(assets, start=1)
    )
    preset.title = _clean_title(title, "预设名称")
    preset.description = description.strip()
    preset.version += 1
    session.commit()
    return _preset_payload(session, preset)


def archive_asset_preset(
    session: Session, preset_id: UUID, *, expected_version: int
) -> dict[str, Any]:
    preset = session.scalar(
        select(AssetPreset).where(AssetPreset.id == preset_id).with_for_update()
    )
    if preset is None:
        raise NotFoundError(f"asset preset {preset_id} not found")
    if preset.version != expected_version:
        raise EntityConflictError(_preset_payload(session, preset))
    preset.archived = True
    preset.version += 1
    session.commit()
    return _preset_payload(session, preset)


def snapshot_private_assets(
    session: Session, *, asset_ids: list[UUID], preset_id: UUID | None = None
) -> list[dict[str, Any]]:
    combined = list(asset_ids)
    if preset_id is not None:
        preset = session.get(AssetPreset, preset_id)
        if preset is None or preset.archived:
            raise ValidationError("资料预设不存在或已删除")
        combined.extend(
            session.scalars(
                select(AssetPresetItem.asset_id)
                .where(AssetPresetItem.preset_id == preset_id)
                .order_by(AssetPresetItem.position)
            ).all()
        )
    return [_asset_payload(asset) for asset in _validated_assets(session, combined)]


def _outline_payload(draft: OutlineDraft) -> dict[str, Any]:
    return {
        "id": str(draft.id),
        "novel_id": str(draft.novel_id),
        "step": draft.step,
        "state": draft.state,
        "version": draft.version,
        "target_chapter_count": draft.target_chapter_count,
        "background_text": draft.background_text,
        "characters": draft.characters_json,
        "plot_text": draft.plot_text,
        "highlight_text": draft.highlight_text,
        "created_at": _iso(draft.created_at),
        "updated_at": _iso(draft.updated_at),
    }


def get_or_create_outline_draft(session: Session, novel_id: UUID) -> dict[str, Any]:
    _require_novel(session, novel_id)
    draft = session.scalar(select(OutlineDraft).where(OutlineDraft.novel_id == novel_id))
    if draft is None:
        draft = OutlineDraft(id=uuid4(), novel_id=novel_id)
        session.add(draft)
        session.commit()
    return _outline_payload(draft)


def update_outline_draft(
    session: Session,
    novel_id: UUID,
    *,
    expected_version: int,
    step: int,
    target_chapter_count: int | None = None,
    background_text: str | None = None,
    characters: list[dict[str, Any]] | None = None,
    plot_text: str | None = None,
    highlight_text: str | None = None,
) -> dict[str, Any]:
    draft = session.scalar(
        select(OutlineDraft).where(OutlineDraft.novel_id == novel_id).with_for_update()
    )
    if draft is None:
        raise NotFoundError(f"outline draft for novel {novel_id} not found")
    if draft.version != expected_version:
        raise EntityConflictError(_outline_payload(draft))
    if not 1 <= step <= 5:
        raise ValidationError("大纲步骤必须在1到5之间")
    if target_chapter_count is not None:
        if not 10 <= target_chapter_count <= 10_000:
            raise ValidationError("目标章节数必须在10到10000之间")
        draft.target_chapter_count = target_chapter_count
    if background_text is not None:
        draft.background_text = background_text.strip()
    if characters is not None:
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in characters[:200]:
            name = str(item.get("name", "")).strip()
            role_type = str(item.get("role_type", "supporting"))
            if not name or name in seen:
                continue
            if role_type not in ROLE_TYPES:
                role_type = "supporting"
            seen.add(name)
            normalized.append(
                {
                    "name": name,
                    "role_type": role_type,
                    "description": str(item.get("description", "")).strip(),
                    "details": dict(item.get("details") or {}),
                }
            )
        draft.characters_json = normalized
    if plot_text is not None:
        draft.plot_text = plot_text.strip()
    if highlight_text is not None:
        draft.highlight_text = highlight_text.strip()
    draft.step = step
    draft.state = "draft"
    draft.version += 1
    session.commit()
    return _outline_payload(draft)


def _character_payload(
    character: NovelCharacter, *, required_next_chapter: bool = False
) -> dict[str, Any]:
    return {
        "id": str(character.id),
        "novel_id": str(character.novel_id),
        "role_type": character.role_type,
        "name": character.name,
        "description": character.description,
        "details": character.details,
        "lifecycle_state": character.lifecycle_state,
        "archived_at": _iso(character.archived_at),
        "required_next_chapter": required_next_chapter,
        "position": character.position,
        "version": character.version,
        "created_at": _iso(character.created_at),
        "updated_at": _iso(character.updated_at),
    }


def complete_outline_draft(
    session: Session, novel_id: UUID, *, expected_version: int
) -> dict[str, Any]:
    novel = session.scalar(select(Novel).where(Novel.id == novel_id).with_for_update())
    if novel is None:
        raise NotFoundError(f"novel {novel_id} not found")
    draft = session.scalar(
        select(OutlineDraft).where(OutlineDraft.novel_id == novel_id).with_for_update()
    )
    if draft is None:
        raise NotFoundError(f"outline draft for novel {novel_id} not found")
    if draft.version != expected_version:
        raise EntityConflictError(_outline_payload(draft))
    if not draft.background_text or not draft.plot_text or not draft.highlight_text:
        raise ValidationError("故事背景、主要情节和亮点简介必须填写完整")
    if not draft.characters_json:
        raise ValidationError("大纲至少需要一个角色")
    if not any(item.get("role_type") == "main" for item in draft.characters_json):
        raise ValidationError("大纲至少需要一个主角")

    existing_rows = session.scalars(
        select(NovelCharacter)
        .where(NovelCharacter.novel_id == novel_id)
        .order_by(NovelCharacter.position)
        .with_for_update()
    ).all()
    existing = {item.name: item for item in existing_rows}
    # Move all current rows to collision-free temporary positions before
    # reapplying the outline order. This keeps repeated outline completion and
    # renamed roles safe under the (novel_id, position) unique constraint.
    for index, character in enumerate(existing_rows, start=1):
        character.position = -(index * 1000)
    session.flush()
    outlined_names: set[str] = set()
    for index, item in enumerate(draft.characters_json, start=1):
        name = str(item["name"])
        outlined_names.add(name)
        character = existing.get(name)
        if character is None:
            character = NovelCharacter(
                id=uuid4(), novel_id=novel_id, name=name, position=index * 1000
            )
            session.add(character)
        else:
            character.version += 1
            character.position = index * 1000
        character.lifecycle_state = "active"
        character.archived_at = None
        character.role_type = str(item.get("role_type", "supporting"))
        character.description = str(item.get("description", ""))
        character.details = dict(item.get("details") or {})
    remaining = [item for item in existing_rows if item.name not in outlined_names]
    for offset, character in enumerate(remaining, start=len(draft.characters_json) + 1):
        character.position = offset * 1000

    novel.outline_target_chapters = draft.target_chapter_count
    novel.background = draft.background_text
    novel.main_plot = draft.plot_text
    novel.highlight = draft.highlight_text
    novel.description = draft.highlight_text
    novel.version += 1
    main_line = session.scalar(
        select(Storyline).where(
            Storyline.novel_id == novel_id,
            Storyline.storyline_type == "main",
        )
    )
    if main_line is None:
        session.add(
            Storyline(
                id=uuid4(),
                novel_id=novel_id,
                storyline_type="main",
                title="故事主线",
                description=draft.plot_text,
                position=_next_position(session, Storyline, novel_id),
            )
        )
    else:
        main_line.description = draft.plot_text
        main_line.version += 1
    draft.state = "completed"
    draft.step = 5
    draft.version += 1
    session.commit()
    characters = list_novel_characters(session, novel_id)
    return {"outline": _outline_payload(draft), "novel": get_novel(session, novel_id), "characters": characters}


def list_novel_characters(session: Session, novel_id: UUID) -> list[dict[str, Any]]:
    _require_novel(session, novel_id)
    characters = session.scalars(
        select(NovelCharacter)
        .where(
            NovelCharacter.novel_id == novel_id,
            NovelCharacter.lifecycle_state == "active",
        )
        .order_by(NovelCharacter.position)
    ).all()
    latest_source_revision_id = session.scalar(
        select(StoryFact.source_revision_id)
        .where(
            StoryFact.novel_id == novel_id,
            StoryFact.status.in_(("active", "source_restored")),
            StoryFact.source_revision_id.is_not(None),
        )
        .order_by(StoryFact.created_at.desc(), StoryFact.id.desc())
        .limit(1)
    )
    required_names: set[str] = set()
    if latest_source_revision_id is not None:
        candidate_facts = session.scalars(
            select(StoryFact).where(
                StoryFact.novel_id == novel_id,
                StoryFact.source_revision_id == latest_source_revision_id,
                StoryFact.status.in_(("active", "source_restored")),
                StoryFact.fact_type == "next_chapter_required_role",
            )
        ).all()
        revision = session.get(DocumentRevision, latest_source_revision_id)
        closing_text = (revision.content_text if revision is not None else "")[-900:]
        uncertainty_markers = ("可能", "或许", "也许", "大概", "预计", "推测", "概率")
        commitment_markers = (
            "一起",
            "一同",
            "共同",
            "决定",
            "约定",
            "答应",
            "明天",
            "随后",
            "前往",
            "继续",
            "必须",
            "不得不",
        )
        for fact in candidate_facts:
            details = fact.details if isinstance(fact.details, dict) else {}
            evidence = " ".join(
                (
                    fact.object_text,
                    str(details.get("source_text", "")),
                    str(details.get("reasoning_summary", "")),
                )
            )
            if any(marker in evidence for marker in uncertainty_markers):
                continue
            if not any(marker in evidence for marker in commitment_markers):
                continue
            required_names.add(fact.subject)

        # A closing joint commitment is frequently expressed with pronouns (for
        # example, “我们去查档案”).  Once at least one explicit participant has
        # survived validation, include named main characters present in the same
        # closing passage so the next-step role picker does not drop the speaker.
        if required_names:
            required_names.update(
                character.name
                for character in characters
                if character.role_type == "main" and character.name in closing_text
            )
    return [
        _character_payload(
            character, required_next_chapter=character.name in required_names
        )
        for character in characters
    ]


def create_novel_character(
    session: Session,
    novel_id: UUID,
    *,
    role_type: str,
    name: str,
    description: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    _require_novel(session, novel_id)
    if role_type not in ROLE_TYPES:
        raise ValidationError("角色类型无效")
    clean_name = _clean_title(name, "角色姓名")
    duplicate = session.scalar(
        select(NovelCharacter.id).where(
            NovelCharacter.novel_id == novel_id, NovelCharacter.name == clean_name
        )
    )
    if duplicate:
        raise ValidationError("当前小说已存在同名角色")
    character = NovelCharacter(
        id=uuid4(),
        novel_id=novel_id,
        role_type=role_type,
        name=clean_name,
        description=description.strip(),
        details=details,
        lifecycle_state="active",
        position=_next_position(session, NovelCharacter, novel_id),
    )
    session.add(character)
    session.commit()
    return _character_payload(character)


def update_novel_character(
    session: Session,
    novel_id: UUID,
    character_id: UUID,
    *,
    expected_version: int,
    role_type: str,
    name: str,
    description: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    character = session.scalar(
        select(NovelCharacter)
        .where(NovelCharacter.id == character_id, NovelCharacter.novel_id == novel_id)
        .with_for_update()
    )
    if character is None:
        raise NotFoundError(f"character {character_id} not found")
    if character.version != expected_version:
        raise EntityConflictError(_character_payload(character))
    if character.lifecycle_state != "active":
        raise ValidationError("已归档角色不能直接编辑")
    if role_type not in ROLE_TYPES:
        raise ValidationError("角色类型无效")
    clean_name = _clean_title(name, "角色姓名")
    duplicate = session.scalar(
        select(NovelCharacter.id).where(
            NovelCharacter.novel_id == novel_id,
            NovelCharacter.name == clean_name,
            NovelCharacter.id != character_id,
        )
    )
    if duplicate:
        raise ValidationError("当前小说已存在同名角色")
    character.role_type = role_type
    character.name = clean_name
    character.description = description.strip()
    character.details = details
    character.version += 1
    session.commit()
    return _character_payload(character)


def delete_novel_character(
    session: Session, novel_id: UUID, character_id: UUID, *, expected_version: int
) -> None:
    character = session.scalar(
        select(NovelCharacter)
        .where(NovelCharacter.id == character_id, NovelCharacter.novel_id == novel_id)
        .with_for_update()
    )
    if character is None:
        raise NotFoundError(f"character {character_id} not found")
    if character.version != expected_version:
        raise EntityConflictError(_character_payload(character))
    if character.lifecycle_state == "archived":
        return
    relations = session.scalars(
        select(CharacterRelationship)
        .where(
            CharacterRelationship.novel_id == novel_id,
            CharacterRelationship.archived_at.is_(None),
            (
                (CharacterRelationship.source_character_id == character_id)
                | (CharacterRelationship.target_character_id == character_id)
            ),
        )
        .with_for_update()
    ).all()
    for relation in relations:
        _archive_relationship_entity(session, relation)
    character.lifecycle_state = "archived"
    character.archived_at = datetime.now(timezone.utc)
    character.version += 1
    session.commit()


def _normalize_relationship_label(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _relationship_pair_key(source_character_id: UUID, target_character_id: UUID) -> str:
    left, right = sorted((str(source_character_id), str(target_character_id)))
    return f"{left}:{right}"


def _canonical_relationship_endpoints(
    source_character_id: UUID,
    target_character_id: UUID,
    directionality: str,
) -> tuple[UUID, UUID]:
    if source_character_id == target_character_id:
        raise ValidationError("角色不能与自己建立关系")
    if directionality not in RELATIONSHIP_DIRECTIONALITIES:
        raise ValidationError("关系方向无效")
    if directionality == "undirected" and str(source_character_id) > str(target_character_id):
        return target_character_id, source_character_id
    return source_character_id, target_character_id


def _require_relationship_characters(
    session: Session,
    novel_id: UUID,
    source_character_id: UUID,
    target_character_id: UUID,
) -> None:
    characters = session.scalars(
        select(NovelCharacter).where(
            NovelCharacter.id.in_((source_character_id, target_character_id)),
            NovelCharacter.novel_id == novel_id,
            NovelCharacter.lifecycle_state == "active",
        )
    ).all()
    if len(characters) != 2:
        raise ValidationError("关系两端角色必须属于当前小说且未归档")


def _relationship_duplicate(
    session: Session,
    *,
    novel_id: UUID,
    source_character_id: UUID,
    target_character_id: UUID,
    directionality: str,
    relation_kind: str,
    normalized_label: str,
    excluding_id: UUID | None = None,
) -> CharacterRelationship | None:
    query = select(CharacterRelationship).where(
        CharacterRelationship.novel_id == novel_id,
        CharacterRelationship.source_character_id == source_character_id,
        CharacterRelationship.target_character_id == target_character_id,
        CharacterRelationship.directionality == directionality,
        CharacterRelationship.relation_kind == relation_kind,
        CharacterRelationship.normalized_label == normalized_label,
        CharacterRelationship.archived_at.is_(None),
    )
    if excluding_id is not None:
        query = query.where(CharacterRelationship.id != excluding_id)
    return session.scalar(query)


def _relationship_payload(relation: CharacterRelationship) -> dict[str, Any]:
    return {
        "id": str(relation.id),
        "novel_id": str(relation.novel_id),
        "source_character_id": str(relation.source_character_id),
        "target_character_id": str(relation.target_character_id),
        "directionality": relation.directionality,
        "relation_kind": relation.relation_kind,
        "label": relation.label,
        "relation_type": relation.label,
        "description": relation.description,
        "status": relation.status,
        "created_by": relation.created_by,
        "manual_override": relation.manual_override,
        "confidence": relation.confidence,
        "evidence": list(relation.evidence_json or []),
        "source_generation_job_id": (
            str(relation.source_generation_job_id)
            if relation.source_generation_job_id
            else None
        ),
        "relation_pair_key": relation.relation_pair_key,
        "source_chapter_revision_id": (
            str(relation.source_chapter_revision_id)
            if relation.source_chapter_revision_id
            else None
        ),
        "proposal_item_id": str(relation.proposal_item_id) if relation.proposal_item_id else None,
        "current_revision_id": (
            str(relation.current_revision_id) if relation.current_revision_id else None
        ),
        "archived_at": _iso(relation.archived_at),
        "version": relation.version,
        "created_at": _iso(relation.created_at),
        "updated_at": _iso(relation.updated_at),
    }


def _relationship_revision_payload(
    revision: CharacterRelationshipRevision,
) -> dict[str, Any]:
    return {
        "id": str(revision.id),
        "relationship_id": str(revision.relationship_id),
        "revision_number": revision.revision_number,
        "source_character_id": str(revision.source_character_id),
        "target_character_id": str(revision.target_character_id),
        "directionality": revision.directionality,
        "relation_kind": revision.relation_kind,
        "label": revision.label,
        "description": revision.description,
        "status": revision.status,
        "change_reason": revision.change_reason,
        "changed_by": revision.changed_by,
        "manual_override": revision.manual_override,
        "confidence": revision.confidence,
        "evidence": list(revision.evidence_json or []),
        "source_generation_job_id": (
            str(revision.source_generation_job_id)
            if revision.source_generation_job_id
            else None
        ),
        "source_chapter_revision_id": (
            str(revision.source_chapter_revision_id)
            if revision.source_chapter_revision_id
            else None
        ),
        "proposal_item_id": str(revision.proposal_item_id) if revision.proposal_item_id else None,
        "created_at": _iso(revision.created_at),
    }


def _record_relationship_revision(
    session: Session,
    relation: CharacterRelationship,
    *,
    change_reason: str = "editorial",
    changed_by: str | None = None,
) -> CharacterRelationshipRevision:
    current_number = session.scalar(
        select(func.max(CharacterRelationshipRevision.revision_number)).where(
            CharacterRelationshipRevision.relationship_id == relation.id
        )
    )
    revision = CharacterRelationshipRevision(
        id=uuid4(),
        relationship_id=relation.id,
        revision_number=int(current_number or 0) + 1,
        source_character_id=relation.source_character_id,
        target_character_id=relation.target_character_id,
        directionality=relation.directionality,
        relation_kind=relation.relation_kind,
        label=relation.label,
        description=relation.description,
        status=relation.status,
        change_reason=change_reason,
        changed_by=changed_by or relation.created_by,
        manual_override=relation.manual_override,
        confidence=relation.confidence,
        evidence_json=list(relation.evidence_json or []),
        source_generation_job_id=relation.source_generation_job_id,
        source_chapter_revision_id=relation.source_chapter_revision_id,
        proposal_item_id=relation.proposal_item_id,
    )
    session.add(revision)
    session.flush()
    relation.current_revision_id = revision.id
    return revision


def _create_relationship_entity(
    session: Session,
    novel_id: UUID,
    *,
    source_character_id: UUID,
    target_character_id: UUID,
    label: str,
    directionality: str,
    relation_kind: str,
    description: str,
    created_by: str = "manual",
    manual_override: bool | None = None,
    confidence: int | None = None,
    evidence: list[str] | None = None,
    source_generation_job_id: UUID | None = None,
    source_chapter_revision_id: UUID | None = None,
    proposal_item_id: UUID | None = None,
) -> CharacterRelationship:
    if relation_kind not in RELATIONSHIP_KINDS:
        raise ValidationError("关系分类无效")
    source_character_id, target_character_id = _canonical_relationship_endpoints(
        source_character_id,
        target_character_id,
        directionality,
    )
    _require_relationship_characters(
        session,
        novel_id,
        source_character_id,
        target_character_id,
    )
    clean_label = _clean_title(label, "关系名称")
    if len(clean_label) > 80:
        raise ValidationError("关系名称不能超过80个字符")
    normalized_label = _normalize_relationship_label(clean_label)
    duplicate = _relationship_duplicate(
        session,
        novel_id=novel_id,
        source_character_id=source_character_id,
        target_character_id=target_character_id,
        directionality=directionality,
        relation_kind=relation_kind,
        normalized_label=normalized_label,
    )
    if duplicate is not None:
        raise ValidationError("相同方向、分类和名称的关系已经存在")
    relation = CharacterRelationship(
        id=uuid4(),
        novel_id=novel_id,
        source_character_id=source_character_id,
        target_character_id=target_character_id,
        directionality=directionality,
        relation_kind=relation_kind,
        label=clean_label,
        normalized_label=normalized_label,
        relation_pair_key=_relationship_pair_key(source_character_id, target_character_id),
        relation_type=clean_label,
        description=description.strip(),
        status="active",
        created_by=created_by,
        manual_override=(created_by not in {"ai_auto"} if manual_override is None else manual_override),
        confidence=confidence,
        evidence_json=list(evidence or []),
        source_generation_job_id=source_generation_job_id,
        source_chapter_revision_id=source_chapter_revision_id,
        proposal_item_id=proposal_item_id,
    )
    session.add(relation)
    session.flush()
    _record_relationship_revision(session, relation, changed_by=created_by)
    return relation


def _update_relationship_entity(
    session: Session,
    relation: CharacterRelationship,
    *,
    expected_version: int,
    source_character_id: UUID | None = None,
    target_character_id: UUID | None = None,
    label: str | None = None,
    directionality: str | None = None,
    relation_kind: str | None = None,
    description: str | None = None,
    status: str | None = None,
    changed_by: str = "manual",
    change_reason: str = "editorial",
    promote_to_manual: bool = True,
    confidence: int | None = None,
    evidence: list[str] | None = None,
    source_generation_job_id: UUID | None = None,
    source_chapter_revision_id: UUID | None = None,
    proposal_item_id: UUID | None = None,
) -> CharacterRelationship:
    if relation.version != expected_version:
        raise EntityConflictError(_relationship_payload(relation))
    next_directionality = directionality or relation.directionality
    if next_directionality not in RELATIONSHIP_DIRECTIONALITIES:
        raise ValidationError("请先明确选择有向或无向关系")
    next_kind = relation_kind or relation.relation_kind
    if next_kind not in RELATIONSHIP_KINDS:
        raise ValidationError("关系分类无效")
    next_status = status or ("active" if relation.status == "archived" else relation.status)
    if next_status not in {"active", "resolved"}:
        raise ValidationError("关系状态无效")
    next_source, next_target = _canonical_relationship_endpoints(
        source_character_id or relation.source_character_id,
        target_character_id or relation.target_character_id,
        next_directionality,
    )
    _require_relationship_characters(
        session,
        relation.novel_id,
        next_source,
        next_target,
    )
    clean_label = _clean_title(label if label is not None else relation.label, "关系名称")
    if len(clean_label) > 80:
        raise ValidationError("关系名称不能超过80个字符")
    normalized_label = _normalize_relationship_label(clean_label)
    duplicate = _relationship_duplicate(
        session,
        novel_id=relation.novel_id,
        source_character_id=next_source,
        target_character_id=next_target,
        directionality=next_directionality,
        relation_kind=next_kind,
        normalized_label=normalized_label,
        excluding_id=relation.id,
    )
    if duplicate is not None:
        raise ValidationError("相同方向、分类和名称的关系已经存在")
    relation.source_character_id = next_source
    relation.target_character_id = next_target
    relation.directionality = next_directionality
    relation.relation_kind = next_kind
    relation.label = clean_label
    relation.normalized_label = normalized_label
    relation.relation_pair_key = _relationship_pair_key(next_source, next_target)
    relation.relation_type = clean_label
    if description is not None:
        relation.description = description.strip()
    relation.status = next_status
    relation.archived_at = None
    if promote_to_manual:
        relation.created_by = "manual"
        relation.manual_override = True
    if confidence is not None:
        relation.confidence = confidence
    if evidence is not None:
        relation.evidence_json = list(evidence)
    if source_generation_job_id is not None:
        relation.source_generation_job_id = source_generation_job_id
    if source_chapter_revision_id is not None:
        relation.source_chapter_revision_id = source_chapter_revision_id
    if proposal_item_id is not None:
        relation.proposal_item_id = proposal_item_id
    relation.version += 1
    _record_relationship_revision(
        session,
        relation,
        change_reason=change_reason,
        changed_by=changed_by,
    )
    return relation


def _archive_relationship_entity(
    session: Session,
    relation: CharacterRelationship,
    *,
    expected_version: int | None = None,
    changed_by: str = "manual",
    change_reason: str = "editorial",
    promote_to_manual: bool = True,
    source_generation_job_id: UUID | None = None,
) -> CharacterRelationship:
    if expected_version is not None and relation.version != expected_version:
        raise EntityConflictError(_relationship_payload(relation))
    if relation.archived_at is not None:
        return relation
    relation.status = "archived"
    relation.archived_at = datetime.now(timezone.utc)
    if promote_to_manual:
        relation.created_by = "manual"
        relation.manual_override = True
    if source_generation_job_id is not None:
        relation.source_generation_job_id = source_generation_job_id
    relation.version += 1
    _record_relationship_revision(
        session,
        relation,
        change_reason=change_reason,
        changed_by=changed_by,
    )
    return relation


def _restore_relationship_entity(
    session: Session,
    relation: CharacterRelationship,
    *,
    expected_version: int,
    changed_by: str = "manual",
    change_reason: str = "editorial",
    promote_to_manual: bool = True,
    confidence: int | None = None,
    evidence: list[str] | None = None,
    source_generation_job_id: UUID | None = None,
) -> CharacterRelationship:
    if relation.version != expected_version:
        raise EntityConflictError(_relationship_payload(relation))
    if relation.archived_at is None:
        return relation
    if relation.directionality not in RELATIONSHIP_DIRECTIONALITIES:
        raise ValidationError("旧关系恢复前必须先确认有向或无向")
    duplicate = _relationship_duplicate(
        session,
        novel_id=relation.novel_id,
        source_character_id=relation.source_character_id,
        target_character_id=relation.target_character_id,
        directionality=relation.directionality,
        relation_kind=relation.relation_kind,
        normalized_label=relation.normalized_label,
        excluding_id=relation.id,
    )
    if duplicate is not None:
        raise ValidationError("已有相同关系，不能恢复重复项")
    _require_relationship_characters(
        session,
        relation.novel_id,
        relation.source_character_id,
        relation.target_character_id,
    )
    relation.status = "active"
    relation.archived_at = None
    if promote_to_manual:
        relation.created_by = "manual"
        relation.manual_override = True
    if confidence is not None:
        relation.confidence = confidence
    if evidence is not None:
        relation.evidence_json = list(evidence)
    if source_generation_job_id is not None:
        relation.source_generation_job_id = source_generation_job_id
    relation.version += 1
    _record_relationship_revision(
        session,
        relation,
        change_reason=change_reason,
        changed_by=changed_by,
    )
    return relation


def list_character_relationships(
    session: Session,
    novel_id: UUID,
    *,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    _require_novel(session, novel_id)
    query = select(CharacterRelationship).where(CharacterRelationship.novel_id == novel_id)
    if not include_archived:
        query = query.where(CharacterRelationship.archived_at.is_(None))
    relations = session.scalars(
        query.order_by(CharacterRelationship.created_at, CharacterRelationship.id)
    ).all()
    return [_relationship_payload(relation) for relation in relations]


def list_character_relationship_history(
    session: Session,
    novel_id: UUID,
    relationship_id: UUID,
) -> list[dict[str, Any]]:
    relation = session.get(CharacterRelationship, relationship_id)
    if relation is None or relation.novel_id != novel_id:
        raise NotFoundError(f"relationship {relationship_id} not found")
    revisions = session.scalars(
        select(CharacterRelationshipRevision)
        .where(CharacterRelationshipRevision.relationship_id == relationship_id)
        .order_by(CharacterRelationshipRevision.revision_number.desc())
    ).all()
    return [_relationship_revision_payload(revision) for revision in revisions]


def _relationship_name_key(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _relationship_known_character_mentions(
    text_value: str,
    character_names: Iterable[str],
) -> list[str]:
    """Return stable, de-duplicated known names mentioned by one source."""

    found: list[str] = []
    seen: set[str] = set()
    for name in character_names:
        clean_name = str(name or "").strip()
        key = _relationship_name_key(clean_name)
        if not clean_name or key in seen or clean_name not in text_value:
            continue
        seen.add(key)
        found.append(clean_name)
    return found


def _relationship_evidence_mentions_pair(
    evidence: Iterable[str],
    source_name: str,
    target_name: str,
) -> bool:
    return any(
        source_name in str(source_text) and target_name in str(source_text)
        for source_text in evidence
    )


def _relationship_snapshot_text(value: Any, limit: int) -> str:
    text_value = str(value or "").strip()
    if len(text_value) <= limit:
        return text_value
    return text_value[:limit].rstrip() + "…"


def build_relationship_graph_snapshot(
    session: Session,
    novel_id: UUID,
) -> dict[str, Any]:
    """Build the bounded, deterministic source of truth for graph generation.

    Automated relationship rows are deliberately excluded. Otherwise applying a
    generation would change its own input hash and cause an endless regeneration
    loop. Author-owned rows (including archived tombstones) stay in the snapshot
    so a manual correction is always stronger than later model output.
    """

    novel = _require_novel(session, novel_id)
    characters = session.scalars(
        select(NovelCharacter)
        .where(
            NovelCharacter.novel_id == novel_id,
            NovelCharacter.lifecycle_state == "active",
        )
        .order_by(NovelCharacter.position, NovelCharacter.id)
        .limit(80)
    ).all()
    character_by_id = {character.id: character for character in characters}
    character_names = [character.name for character in characters]

    document_rows = session.execute(
        select(Document, DocumentWorkingCopy)
        .join(DocumentWorkingCopy, DocumentWorkingCopy.document_id == Document.id)
        .where(Document.novel_id == novel_id, Document.kind == "chapter")
        .order_by(Document.position, Document.id)
    ).all()
    current_revision_ids = {
        working.base_revision_id
        for _, working in document_rows
        if working.base_revision_id is not None
    }

    manual_rows = session.scalars(
        select(CharacterRelationship)
        .where(
            CharacterRelationship.novel_id == novel_id,
            CharacterRelationship.manual_override.is_(True),
        )
        .order_by(CharacterRelationship.created_at, CharacterRelationship.id)
    ).all()
    author_overrides: list[dict[str, Any]] = []
    for relation in manual_rows:
        source = character_by_id.get(relation.source_character_id)
        target = character_by_id.get(relation.target_character_id)
        if source is None or target is None:
            continue
        author_overrides.append(
            {
                "source_name": source.name,
                "target_name": target.name,
                "directionality": relation.directionality,
                "relation_kind": relation.relation_kind,
                "label": relation.label,
                "description": _relationship_snapshot_text(relation.description, 1000),
                "active": relation.archived_at is None,
            }
        )

    facts = session.scalars(
        select(StoryFact)
        .where(
            StoryFact.novel_id == novel_id,
            StoryFact.fact_type == "relationship",
            StoryFact.status.in_(("active", "source_restored")),
            StoryFact.source_revision_id.in_(current_revision_ids),
        )
        .order_by(StoryFact.created_at.desc(), StoryFact.id.desc())
        .limit(300)
    ).all()
    accepted_facts: list[dict[str, Any]] = []
    for fact in facts:
        details = fact.details if isinstance(fact.details, dict) else {}
        searchable = " ".join(
            (
                fact.subject,
                fact.predicate,
                fact.object_text,
                str(details.get("source_text") or ""),
            )
        )
        mentioned = _relationship_known_character_mentions(searchable, character_names)
        if len(set(mentioned)) < 2:
            continue
        accepted_facts.append(
            {
                "subject": fact.subject,
                "predicate": fact.predicate,
                "object": _relationship_snapshot_text(fact.object_text, 900),
                "evidence": _relationship_snapshot_text(details.get("source_text"), 500),
                "status": fact.status,
            }
        )

    relevant_chapters: list[tuple[Document, DocumentWorkingCopy, str]] = []
    excluded_chapter_count = 0
    for document, working in document_rows[:1000]:
        text_value = markdown_to_text(working.content_markdown).strip()
        mentioned = _relationship_known_character_mentions(text_value, character_names)
        if len(mentioned) < 2:
            excluded_chapter_count += 1
            continue
        relevant_chapters.append((document, working, text_value))
    chapter_index = [
        {
            "id": str(document.id),
            "title": document.title,
            "position": document.position,
            "content_hash": working.content_hash,
        }
        for document, working, _ in relevant_chapters
    ]
    recent_excerpts: list[dict[str, Any]] = []
    for document, _, text_value in relevant_chapters[-12:]:
        if len(text_value) > 2600:
            text_value = text_value[:800].rstrip() + "\n…\n" + text_value[-1600:].lstrip()
        recent_excerpts.append(
            {
                "title": document.title,
                "position": document.position,
                "excerpt": text_value,
            }
        )

    return {
        "schema_version": 1,
        "novel": {
            "title": novel.title,
            "genre": novel.genre,
            "subgenre": novel.subgenre,
            "idea": _relationship_snapshot_text(novel.idea, 6000),
            "description": _relationship_snapshot_text(novel.description, 4000),
            "background": _relationship_snapshot_text(novel.background, 8000),
            "main_plot": _relationship_snapshot_text(novel.main_plot, 16_000),
            "highlight": _relationship_snapshot_text(novel.highlight, 2000),
        },
        "characters": [
            {
                "name": character.name,
                "role_type": character.role_type,
                "description": _relationship_snapshot_text(character.description, 1800),
                "details": _relationship_snapshot_text(
                    json.dumps(character.details or {}, ensure_ascii=False, sort_keys=True),
                    1800,
                ),
            }
            for character in characters
        ],
        "author_relationship_overrides": author_overrides,
        "accepted_relationship_facts": accepted_facts,
        "chapter_index": chapter_index,
        "excluded_chapter_count": excluded_chapter_count,
        "recent_chapter_excerpts": recent_excerpts,
    }


def _relationship_snapshot_hash(snapshot: dict[str, Any]) -> str:
    serialized = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return content_hash(serialized)


def get_relationship_auto_sync_status(
    session: Session,
    novel_id: UUID,
) -> dict[str, Any]:
    snapshot = build_relationship_graph_snapshot(session, novel_id)
    input_digest = _relationship_snapshot_hash(snapshot)
    current_job = session.scalar(
        select(CreativeGenerationJob)
        .where(
            CreativeGenerationJob.scope_type == "novel",
            CreativeGenerationJob.scope_id == novel_id,
            CreativeGenerationJob.kind == "relationship_graph",
            CreativeGenerationJob.input_hash == input_digest,
        )
        .order_by(CreativeGenerationJob.attempt.desc())
    )
    latest_ready = session.scalar(
        select(CreativeGenerationJob)
        .where(
            CreativeGenerationJob.scope_type == "novel",
            CreativeGenerationJob.scope_id == novel_id,
            CreativeGenerationJob.kind == "relationship_graph",
            CreativeGenerationJob.state == "ready",
        )
        .order_by(CreativeGenerationJob.completed_at.desc(), CreativeGenerationJob.created_at.desc())
    )
    active_rows = session.scalars(
        select(CharacterRelationship).where(
            CharacterRelationship.novel_id == novel_id,
            CharacterRelationship.archived_at.is_(None),
        )
    ).all()
    eligible = len(snapshot["characters"]) >= 2
    return {
        "eligible": eligible,
        "stale": eligible and (current_job is None or current_job.state != "ready"),
        "state": current_job.state if current_job is not None else "never",
        "input_hash": input_digest,
        "last_synced_at": _iso(latest_ready.completed_at) if latest_ready else None,
        "ai_relationship_count": sum(
            1 for relation in active_rows if not relation.manual_override
        ),
        "manual_relationship_count": sum(
            1 for relation in active_rows if relation.manual_override
        ),
        "source_summary": {
            "characters": len(snapshot["characters"]),
            "relationship_facts": len(snapshot["accepted_relationship_facts"]),
            "chapters": len(snapshot["chapter_index"]),
            "excluded_chapters": int(snapshot.get("excluded_chapter_count") or 0),
        },
        "job": _creative_job_payload(current_job) if current_job is not None else None,
    }


def _manual_relationship_blocks(
    manual_rows: list[CharacterRelationship],
    *,
    pair_key: str,
    relation_kind: str,
) -> bool:
    return any(
        relation.relation_pair_key == pair_key
        and (
            relation.directionality == "legacy_unspecified"
            or relation.relation_kind == "other"
            or relation.relation_kind == relation_kind
        )
        for relation in manual_rows
    )


def apply_relationship_graph_generation(
    session: Session,
    novel_id: UUID,
    job_id: UUID,
) -> dict[str, Any]:
    """Reconcile a complete model snapshot without touching author overrides."""

    job = session.scalar(
        select(CreativeGenerationJob)
        .where(
            CreativeGenerationJob.id == job_id,
            CreativeGenerationJob.novel_id == novel_id,
            CreativeGenerationJob.kind == "relationship_graph",
        )
        .with_for_update()
    )
    if job is None:
        raise NotFoundError(f"creative generation job {job_id} not found")
    if job.state != "ready":
        raise ValidationError("关系网自动分析尚未完成")

    characters = session.scalars(
        select(NovelCharacter).where(
            NovelCharacter.novel_id == novel_id,
            NovelCharacter.lifecycle_state == "active",
        )
    ).all()
    character_by_name = {
        _relationship_name_key(character.name): character for character in characters
    }
    all_rows = session.scalars(
        select(CharacterRelationship)
        .where(CharacterRelationship.novel_id == novel_id)
        .order_by(CharacterRelationship.archived_at.is_(None).desc(), CharacterRelationship.created_at)
        .with_for_update()
    ).all()
    manual_rows = [relation for relation in all_rows if relation.manual_override]
    ai_rows = [relation for relation in all_rows if not relation.manual_override]

    raw_relationships = job.output_json.get("relationships")
    if not isinstance(raw_relationships, list):
        raise ValidationError("关系网自动分析结果结构不完整")
    candidates = sorted(
        (item for item in raw_relationships if isinstance(item, dict)),
        key=lambda item: int(item.get("confidence") or 0),
        reverse=True,
    )
    matched_ids: set[UUID] = set()
    desired_slots: set[tuple[UUID, UUID, str, str]] = set()
    changes = {"created": 0, "updated": 0, "archived": 0, "skipped": 0}

    for item in candidates[:200]:
        source = character_by_name.get(_relationship_name_key(str(item.get("source_name") or "")))
        target = character_by_name.get(_relationship_name_key(str(item.get("target_name") or "")))
        directionality = str(item.get("directionality") or "")
        relation_kind = str(item.get("relation_kind") or "")
        label = str(item.get("label") or "").strip()
        description = str(item.get("description") or "").strip()
        try:
            confidence = max(0, min(int(item.get("confidence") or 0), 100))
        except (TypeError, ValueError):
            confidence = 0
        evidence = [
            str(value).strip()[:500]
            for value in item.get("evidence") or []
            if str(value).strip()
        ][:5]
        if (
            source is None
            or target is None
            or source.id == target.id
            or directionality not in RELATIONSHIP_DIRECTIONALITIES
            or relation_kind not in RELATIONSHIP_KINDS
            or not label
            or confidence < 80
            or not _relationship_evidence_mentions_pair(
                evidence,
                source.name,
                target.name,
            )
        ):
            changes["skipped"] += 1
            continue
        source_id, target_id = _canonical_relationship_endpoints(
            source.id,
            target.id,
            directionality,
        )
        pair_key = _relationship_pair_key(source_id, target_id)
        slot = (source_id, target_id, directionality, relation_kind)
        if slot in desired_slots or _manual_relationship_blocks(
            manual_rows,
            pair_key=pair_key,
            relation_kind=relation_kind,
        ):
            changes["skipped"] += 1
            continue
        desired_slots.add(slot)

        matching = [
            relation
            for relation in ai_rows
            if relation.source_character_id == source_id
            and relation.target_character_id == target_id
            and relation.directionality == directionality
            and relation.relation_kind == relation_kind
            and relation.id not in matched_ids
        ]
        relation = matching[0] if matching else None
        if relation is None:
            relation = _create_relationship_entity(
                session,
                novel_id,
                source_character_id=source_id,
                target_character_id=target_id,
                label=label,
                directionality=directionality,
                relation_kind=relation_kind,
                description=description,
                created_by="ai_auto",
                manual_override=False,
                confidence=confidence,
                evidence=evidence,
                source_generation_job_id=job.id,
            )
            ai_rows.append(relation)
            changes["created"] += 1
        else:
            semantic_changed = any(
                (
                    relation.label != label,
                    relation.description != description,
                    relation.status != "active",
                    relation.archived_at is not None,
                    relation.confidence != confidence,
                    list(relation.evidence_json or []) != evidence,
                )
            )
            if semantic_changed:
                _update_relationship_entity(
                    session,
                    relation,
                    expected_version=relation.version,
                    source_character_id=source_id,
                    target_character_id=target_id,
                    label=label,
                    directionality=directionality,
                    relation_kind=relation_kind,
                    description=description,
                    status="active",
                    changed_by="ai_auto",
                    change_reason="auto_sync",
                    promote_to_manual=False,
                    confidence=confidence,
                    evidence=evidence,
                    source_generation_job_id=job.id,
                )
                changes["updated"] += 1
            else:
                relation.source_generation_job_id = job.id
        matched_ids.add(relation.id)

    complete_snapshot = job.output_json.get("complete_snapshot") is True
    if complete_snapshot and desired_slots:
        for relation in ai_rows:
            if relation.archived_at is not None or relation.id in matched_ids:
                continue
            _archive_relationship_entity(
                session,
                relation,
                changed_by="ai_auto",
                change_reason="auto_sync",
                promote_to_manual=False,
                source_generation_job_id=job.id,
            )
            changes["archived"] += 1

    session.commit()
    return {
        "job": _creative_job_payload(job),
        "changes": changes,
        "relationships": list_character_relationships(session, novel_id),
        "status": get_relationship_auto_sync_status(session, novel_id),
    }


def _inferred_relationship_kind(value: str) -> str:
    lowered = value.casefold()
    keyword_groups = (
        ("family", ("父", "母", "兄", "弟", "姐", "妹", "夫妻", "亲属", "家人")),
        ("romance", ("恋", "爱人", "情侣", "暧昧", "婚约", "心动")),
        ("mentor", ("师父", "师徒", "导师", "教导", "传授", "引路人")),
        ("enemy", ("敌", "仇", "对手", "冲突", "背叛", "追杀")),
        ("ally", ("盟友", "同盟", "合作", "并肩", "共同调查", "互助")),
        ("colleague", ("同事", "同学", "战友", "队友", "搭档")),
    )
    for relation_kind, keywords in keyword_groups:
        if any(keyword in lowered for keyword in keywords):
            return relation_kind
    return "other"


def _inferred_relationship_label(
    relation_kind: str,
    searchable: str,
    predicate: str,
) -> str:
    if relation_kind == "ally":
        return "调查同盟" if "调查" in searchable or "档案" in searchable else "同盟"
    defaults = {
        "family": "亲属",
        "romance": "情感关系",
        "mentor": "师徒",
        "enemy": "敌对",
        "colleague": "同事",
    }
    if relation_kind in defaults:
        return defaults[relation_kind]
    cleaned = re.sub(r'["“”「」『』]', "", predicate).strip()
    return cleaned[:12] or "关联"


def sync_relationships_from_intelligence_proposal(
    session: Session,
    proposal_id: UUID,
) -> dict[str, Any]:
    """Incrementally materialize accepted chapter relationship intelligence.

    This is the normal day-to-day path: the same “同步进展” operation that writes
    the story ledger also adds or updates graph edges. It never archives missing
    edges because a single chapter is only an incremental observation.
    """

    proposal = session.get(IntelligenceProposal, proposal_id)
    if proposal is None:
        raise NotFoundError(f"intelligence proposal {proposal_id} not found")
    characters = session.scalars(
        select(NovelCharacter)
        .where(
            NovelCharacter.novel_id == proposal.novel_id,
            NovelCharacter.lifecycle_state == "active",
        )
        .order_by(NovelCharacter.position)
    ).all()
    character_by_name = {
        _relationship_name_key(character.name): character for character in characters
    }
    accepted_items = session.scalars(
        select(IntelligenceProposalItem)
        .where(
            IntelligenceProposalItem.proposal_id == proposal_id,
            IntelligenceProposalItem.item_type == "relationship",
            IntelligenceProposalItem.review_state == "accepted",
            IntelligenceProposalItem.committed_story_fact_id.is_not(None),
        )
        .order_by(IntelligenceProposalItem.position)
    ).all()
    all_rows = session.scalars(
        select(CharacterRelationship)
        .where(CharacterRelationship.novel_id == proposal.novel_id)
        .order_by(
            CharacterRelationship.archived_at.is_(None).desc(),
            CharacterRelationship.created_at,
        )
        .with_for_update()
    ).all()
    manual_rows = [relation for relation in all_rows if relation.manual_override]
    ai_rows = [relation for relation in all_rows if not relation.manual_override]
    changes = {"created": 0, "updated": 0, "skipped": 0}

    for item in accepted_items:
        payload = dict(item.suggested_payload or {})
        details = payload.get("relationship_details")
        source: NovelCharacter | None = None
        target: NovelCharacter | None = None
        directionality = "undirected"
        relation_kind = "other"
        label = str(payload.get("predicate") or "").strip()[:80]
        description = ""
        if isinstance(details, dict):
            source = character_by_name.get(
                _relationship_name_key(str(details.get("source_name") or ""))
            )
            target = character_by_name.get(
                _relationship_name_key(str(details.get("target_name") or ""))
            )
            directionality = str(details.get("directionality") or "")
            relation_kind = str(details.get("relation_kind") or "")
            label = str(details.get("label") or "").strip()[:80]
            description = str(details.get("description") or "").strip()[:2000]

        if source is None or target is None:
            searchable = " ".join(
                (
                    str(payload.get("subject") or ""),
                    str(payload.get("predicate") or ""),
                    str(payload.get("object") or ""),
                    item.source_text,
                )
            )
            mentioned = [
                character
                for character in characters
                if character.name and character.name in searchable
            ]
            if len(mentioned) == 2:
                source, target = mentioned
                relation_kind = _inferred_relationship_kind(searchable)
                directionality = "undirected"
                label = _inferred_relationship_label(
                    relation_kind,
                    searchable,
                    str(payload.get("predicate") or relation_kind),
                )

        if (
            source is None
            or target is None
            or source.id == target.id
            or directionality not in RELATIONSHIP_DIRECTIONALITIES
            or relation_kind not in RELATIONSHIP_KINDS
            or not label
            # Legacy intelligence proposals used 50 as the verified default.
            # Once an item is explicitly typed as a relationship and resolves to
            # two known characters, keep it eligible for incremental backfill.
            or item.confidence < 50
        ):
            changes["skipped"] += 1
            continue
        source_id, target_id = _canonical_relationship_endpoints(
            source.id,
            target.id,
            directionality,
        )
        pair_key = _relationship_pair_key(source_id, target_id)
        if _manual_relationship_blocks(
            manual_rows,
            pair_key=pair_key,
            relation_kind=relation_kind,
        ):
            changes["skipped"] += 1
            continue
        if not description:
            description = (
                f"{payload.get('predicate', '')}：{payload.get('object', '')}"
            ).strip("： ")[:2000]
        matching = [
            relation
            for relation in ai_rows
            if relation.source_character_id == source_id
            and relation.target_character_id == target_id
            and relation.directionality == directionality
            and relation.relation_kind == relation_kind
        ]
        relation = matching[0] if matching else None
        next_evidence = list(relation.evidence_json or []) if relation is not None else []
        if item.source_text and item.source_text not in next_evidence:
            next_evidence.append(item.source_text[:500])
        next_evidence = next_evidence[-5:]
        if relation is None:
            relation = _create_relationship_entity(
                session,
                proposal.novel_id,
                source_character_id=source_id,
                target_character_id=target_id,
                label=label,
                directionality=directionality,
                relation_kind=relation_kind,
                description=description,
                created_by="ai_auto",
                manual_override=False,
                confidence=item.confidence,
                evidence=next_evidence,
                source_chapter_revision_id=proposal.chapter_revision_id,
                proposal_item_id=item.id,
            )
            ai_rows.append(relation)
            changes["created"] += 1
            continue
        changed = any(
            (
                relation.label != label,
                relation.description != description,
                relation.status != "active",
                relation.archived_at is not None,
                relation.confidence != item.confidence,
                list(relation.evidence_json or []) != next_evidence,
                relation.source_chapter_revision_id != proposal.chapter_revision_id,
                relation.proposal_item_id != item.id,
            )
        )
        if not changed:
            continue
        _update_relationship_entity(
            session,
            relation,
            expected_version=relation.version,
            source_character_id=source_id,
            target_character_id=target_id,
            label=label,
            directionality=directionality,
            relation_kind=relation_kind,
            description=description,
            status="active",
            changed_by="ai_sync",
            change_reason="chapter_sync",
            promote_to_manual=False,
            confidence=item.confidence,
            evidence=next_evidence,
            source_chapter_revision_id=proposal.chapter_revision_id,
            proposal_item_id=item.id,
        )
        changes["updated"] += 1

    session.commit()
    return {
        "changes": changes,
        "relationships": list_character_relationships(session, proposal.novel_id),
    }


def create_character_relationship(
    session: Session,
    novel_id: UUID,
    *,
    source_character_id: UUID,
    target_character_id: UUID,
    label: str,
    directionality: str = "undirected",
    relation_kind: str = "other",
    description: str = "",
) -> dict[str, Any]:
    _require_novel(session, novel_id)
    relation = _create_relationship_entity(
        session,
        novel_id,
        source_character_id=source_character_id,
        target_character_id=target_character_id,
        label=label,
        directionality=directionality,
        relation_kind=relation_kind,
        description=description,
    )
    session.commit()
    return _relationship_payload(relation)


def update_character_relationship(
    session: Session,
    novel_id: UUID,
    relationship_id: UUID,
    *,
    expected_version: int,
    source_character_id: UUID | None = None,
    target_character_id: UUID | None = None,
    label: str | None = None,
    directionality: str | None = None,
    relation_kind: str | None = None,
    description: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    relation = session.scalar(
        select(CharacterRelationship)
        .where(
            CharacterRelationship.id == relationship_id,
            CharacterRelationship.novel_id == novel_id,
        )
        .with_for_update()
    )
    if relation is None:
        raise NotFoundError(f"relationship {relationship_id} not found")
    _update_relationship_entity(
        session,
        relation,
        expected_version=expected_version,
        source_character_id=source_character_id,
        target_character_id=target_character_id,
        label=label,
        directionality=directionality,
        relation_kind=relation_kind,
        description=description,
        status=status,
    )
    session.commit()
    return _relationship_payload(relation)


def delete_character_relationship(
    session: Session, novel_id: UUID, relationship_id: UUID, *, expected_version: int
) -> None:
    relation = session.scalar(
        select(CharacterRelationship)
        .where(
            CharacterRelationship.id == relationship_id,
            CharacterRelationship.novel_id == novel_id,
        )
        .with_for_update()
    )
    if relation is None:
        raise NotFoundError(f"relationship {relationship_id} not found")
    _archive_relationship_entity(session, relation, expected_version=expected_version)
    session.commit()


def restore_character_relationship(
    session: Session,
    novel_id: UUID,
    relationship_id: UUID,
    *,
    expected_version: int,
) -> dict[str, Any]:
    relation = session.scalar(
        select(CharacterRelationship)
        .where(
            CharacterRelationship.id == relationship_id,
            CharacterRelationship.novel_id == novel_id,
        )
        .with_for_update()
    )
    if relation is None:
        raise NotFoundError(f"relationship {relationship_id} not found")
    _restore_relationship_entity(session, relation, expected_version=expected_version)
    session.commit()
    return _relationship_payload(relation)


def batch_character_relationships(
    session: Session,
    novel_id: UUID,
    *,
    operations: list[dict[str, Any]],
) -> dict[str, Any]:
    _require_novel(session, novel_id)
    results: list[dict[str, Any]] = []
    for operation in operations:
        action = str(operation.get("action", ""))
        relationship_id = operation.get("relationship_id")
        relation: CharacterRelationship | None = None
        if action != "create":
            if relationship_id is None:
                raise ValidationError("关系批量操作缺少 relationship_id")
            relation = session.scalar(
                select(CharacterRelationship)
                .where(
                    CharacterRelationship.id == relationship_id,
                    CharacterRelationship.novel_id == novel_id,
                )
                .with_for_update()
            )
            if relation is None:
                raise NotFoundError(f"relationship {relationship_id} not found")
        if action == "create":
            source_character_id = operation.get("source_character_id")
            target_character_id = operation.get("target_character_id")
            label = operation.get("label") or operation.get("relation_type")
            if source_character_id is None or target_character_id is None or not label:
                raise ValidationError("新增关系缺少角色或关系名称")
            relation = _create_relationship_entity(
                session,
                novel_id,
                source_character_id=source_character_id,
                target_character_id=target_character_id,
                label=str(label),
                directionality=str(operation.get("directionality") or "undirected"),
                relation_kind=str(operation.get("relation_kind") or "other"),
                description=str(operation.get("description") or ""),
            )
        elif action == "update" and relation is not None:
            expected_version = operation.get("expected_version")
            if expected_version is None:
                raise ValidationError("编辑关系缺少 expected_version")
            relation = _update_relationship_entity(
                session,
                relation,
                expected_version=int(expected_version),
                source_character_id=operation.get("source_character_id"),
                target_character_id=operation.get("target_character_id"),
                label=operation.get("label") or operation.get("relation_type"),
                directionality=operation.get("directionality"),
                relation_kind=operation.get("relation_kind"),
                description=operation.get("description"),
                status=operation.get("status"),
            )
        elif action == "archive" and relation is not None:
            expected_version = operation.get("expected_version")
            if expected_version is None:
                raise ValidationError("归档关系缺少 expected_version")
            relation = _archive_relationship_entity(
                session,
                relation,
                expected_version=int(expected_version),
            )
        elif action == "restore" and relation is not None:
            expected_version = operation.get("expected_version")
            if expected_version is None:
                raise ValidationError("恢复关系缺少 expected_version")
            relation = _restore_relationship_entity(
                session,
                relation,
                expected_version=int(expected_version),
            )
        else:
            raise ValidationError("不支持的关系批量操作")
        results.append(
            {
                "client_id": operation.get("client_id"),
                "relationship": _relationship_payload(relation),
            }
        )
    session.commit()
    return {
        "operations": results,
        "relationships": list_character_relationships(session, novel_id),
    }


def _relationship_graph_view_payload(
    session: Session,
    view: RelationshipGraphView | None,
    *,
    novel_id: UUID,
) -> dict[str, Any]:
    if view is None:
        return {
            "id": None,
            "novel_id": str(novel_id),
            "name": "默认视图",
            "layout_algorithm": "force_atlas_2",
            "random_seed": f"relationship-{novel_id}",
            "zoom": 1.0,
            "pan_x": 0.0,
            "pan_y": 0.0,
            "version": 0,
            "positions": [],
            "updated_at": None,
        }
    positions = session.scalars(
        select(RelationshipGraphPosition)
        .where(RelationshipGraphPosition.view_id == view.id)
        .order_by(RelationshipGraphPosition.character_id)
    ).all()
    return {
        "id": str(view.id),
        "novel_id": str(view.novel_id),
        "name": view.name,
        "layout_algorithm": view.layout_algorithm,
        "random_seed": view.random_seed,
        "zoom": view.zoom,
        "pan_x": view.pan_x,
        "pan_y": view.pan_y,
        "version": view.version,
        "positions": [
            {
                "character_id": str(position.character_id),
                "x": position.x,
                "y": position.y,
                "pinned": position.pinned,
            }
            for position in positions
        ],
        "updated_at": _iso(view.updated_at),
    }


def get_relationship_graph_view(
    session: Session,
    novel_id: UUID,
    *,
    name: str = "默认视图",
) -> dict[str, Any]:
    _require_novel(session, novel_id)
    view = session.scalar(
        select(RelationshipGraphView).where(
            RelationshipGraphView.novel_id == novel_id,
            RelationshipGraphView.name == name,
        )
    )
    return _relationship_graph_view_payload(session, view, novel_id=novel_id)


def save_relationship_graph_view(
    session: Session,
    novel_id: UUID,
    *,
    expected_version: int,
    name: str,
    layout_algorithm: str,
    random_seed: str,
    zoom: float,
    pan_x: float,
    pan_y: float,
    positions: list[dict[str, Any]],
) -> dict[str, Any]:
    _require_novel(session, novel_id)
    view = session.scalar(
        select(RelationshipGraphView)
        .where(
            RelationshipGraphView.novel_id == novel_id,
            RelationshipGraphView.name == name,
        )
        .with_for_update()
    )
    if view is None:
        if expected_version != 0:
            raise EntityConflictError(
                _relationship_graph_view_payload(session, None, novel_id=novel_id)
            )
        view = RelationshipGraphView(
            id=uuid4(),
            novel_id=novel_id,
            name=_clean_title(name, "视图名称"),
            layout_algorithm=layout_algorithm,
            random_seed=random_seed,
            zoom=zoom,
            pan_x=pan_x,
            pan_y=pan_y,
        )
        session.add(view)
        session.flush()
    else:
        if view.version != expected_version:
            raise EntityConflictError(
                _relationship_graph_view_payload(session, view, novel_id=novel_id)
            )
        view.layout_algorithm = layout_algorithm
        view.random_seed = random_seed
        view.zoom = zoom
        view.pan_x = pan_x
        view.pan_y = pan_y
        view.version += 1
        existing_positions = session.scalars(
            select(RelationshipGraphPosition).where(
                RelationshipGraphPosition.view_id == view.id
            )
        ).all()
        for position in existing_positions:
            session.delete(position)
        session.flush()
    character_ids = [position["character_id"] for position in positions]
    if len(character_ids) != len(set(character_ids)):
        raise ValidationError("布局中存在重复角色坐标")
    if character_ids:
        known_ids = set(
            session.scalars(
                select(NovelCharacter.id).where(
                    NovelCharacter.novel_id == novel_id,
                    NovelCharacter.id.in_(character_ids),
                    NovelCharacter.lifecycle_state == "active",
                )
            ).all()
        )
        if known_ids != set(character_ids):
            raise ValidationError("布局包含不属于当前小说的角色")
    for position in positions:
        session.add(
            RelationshipGraphPosition(
                view_id=view.id,
                character_id=position["character_id"],
                x=float(position["x"]),
                y=float(position["y"]),
                pinned=bool(position.get("pinned", False)),
            )
        )
    session.commit()
    return _relationship_graph_view_payload(session, view, novel_id=novel_id)


def _storyline_payload(item: Storyline) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "novel_id": str(item.novel_id),
        "storyline_type": item.storyline_type,
        "title": item.title,
        "description": item.description,
        "status": item.status,
        "progress": item.progress,
        "position": item.position,
        "version": item.version,
        "created_at": _iso(item.created_at),
        "updated_at": _iso(item.updated_at),
    }


def _storyline_topic_from_fact(
    fact: StoryFact, character_names: list[str]
) -> tuple[str, str] | None:
    combined = f"{fact.subject}{fact.predicate}{fact.object_text}"
    romance_tokens = (
        "感情",
        "暗恋",
        "爱意",
        "重逢",
        "克制",
        "默契",
        "心动",
        "喜欢",
        "恋人",
        "亲吻",
        "告白",
    )
    if fact.fact_type == "relationship":
        if not any(token in combined for token in romance_tokens):
            return None
        participants = [name for name in character_names if name and name in combined]
        if len(participants) >= 2:
            return "romance", f"{participants[0]}与{participants[1]}感情线"
        subject = fact.subject.strip()[:18] or "人物"
        return "romance", f"{subject}感情线"

    if fact.fact_type != "storyline_event":
        return None
    topic_rules = (
        (("匿名举报", "灯塔承包权", "会议记录", "旧档案"), "灯塔承包权真相线"),
        (("家书", "旧木盒", "铁盒", "不必再寄"), "外婆家书线"),
        (("纪录片", "唐知渔", "拍摄", "机器"), "纪录片拍摄线"),
        (("深夜广播", "磁带", "录音", "晚安"), "外婆的深夜广播线"),
        (("旧电台", "频率", "传动轮", "收录机", "电容"), "旧电台修复线"),
        (("何漫", "口述史"), "何漫口述史线"),
        (("周柚", "转交", "送信"), "周柚送信线"),
        (("灯塔", "雾号", "鹤嘴岬"), "鹤嘴岬灯塔线"),
    )
    for tokens, title in topic_rules:
        if any(token in combined for token in tokens):
            return "support", title
    return None


def _should_archive_legacy_auto_storyline(
    item: Storyline,
    *,
    auto_descriptions: set[str],
    canonical_titles: set[str],
) -> bool:
    """Identify only obsolete fine-grained rows, never canonical buckets.

    Canonical aggregate rows deliberately reuse the latest source fact as
    their description.  Archiving by description alone therefore toggled each
    canonical row inactive and active again on every GET, incrementing its
    version despite no author or source change.
    """

    return (
        item.storyline_type != "main"
        and item.title not in canonical_titles
        and item.description in auto_descriptions
    )


def list_storylines(session: Session, novel_id: UUID) -> list[dict[str, Any]]:
    _require_novel(session, novel_id)
    rows = session.scalars(
        select(Storyline).where(Storyline.novel_id == novel_id).order_by(Storyline.position)
    ).all()
    # Intelligence sync writes fine-grained events to the provenance ledger.
    # The author-facing board must group those events into stable narrative
    # threads instead of creating one new "line" for every action or object.
    facts = session.scalars(
        select(StoryFact)
        .where(
            StoryFact.novel_id == novel_id,
            StoryFact.status.in_(("active", "source_restored")),
            StoryFact.fact_type.in_(("storyline_event", "relationship")),
        )
        .order_by(StoryFact.created_at)
    ).all()
    character_names = session.scalars(
        select(NovelCharacter.name)
        .where(NovelCharacter.novel_id == novel_id)
        .order_by(NovelCharacter.position)
    ).all()
    buckets: dict[tuple[str, str], list[StoryFact]] = {}
    for fact in facts:
        topic = _storyline_topic_from_fact(fact, list(character_names))
        if topic is not None:
            buckets.setdefault(topic, []).append(fact)

    auto_descriptions = {
        f"{fact.subject}{fact.predicate}：{fact.object_text}".strip("：")
        for fact in facts
    }
    canonical_titles = {title for _storyline_type, title in buckets}
    by_title: dict[str, Storyline] = {}
    for item in rows:
        by_title.setdefault(item.title, item)
    next_position = max((int(item.position or 0) for item in rows), default=0) + 1000
    changed = False

    for item in rows:
        if not _should_archive_legacy_auto_storyline(
            item,
            auto_descriptions=auto_descriptions,
            canonical_titles=canonical_titles,
        ):
            continue
        if item.status != "archived":
            item.status = "archived"
            item.version = int(item.version or 0) + 1
            changed = True

    for (storyline_type, title), topic_facts in buckets.items():
        latest = topic_facts[-1]
        description = f"{latest.subject}{latest.predicate}：{latest.object_text}".strip("：")
        progress = min(90, 10 + max(0, len(topic_facts) - 1) * 10)
        existing = by_title.get(title)
        if existing is not None:
            if (
                existing.storyline_type != storyline_type
                or existing.description != description
                or existing.status != "active"
                or int(existing.progress or 0) != progress
            ):
                existing.storyline_type = storyline_type
                existing.description = description
                existing.status = "active"
                existing.progress = progress
                existing.version = int(existing.version or 0) + 1
                changed = True
            continue
        created = Storyline(
            id=uuid4(),
            novel_id=novel_id,
            storyline_type=storyline_type,
            title=title,
            description=description,
            status="active",
            progress=progress,
            position=next_position,
            version=1,
        )
        next_position += 1000
        session.add(created)
        by_title[title] = created
        rows.append(created)
        changed = True
    if changed:
        session.commit()
    return [_storyline_payload(item) for item in rows if item.status != "archived"]


def create_storyline(
    session: Session,
    novel_id: UUID,
    *,
    storyline_type: str,
    title: str,
    description: str,
) -> dict[str, Any]:
    _require_novel(session, novel_id)
    if storyline_type not in STORYLINE_TYPES:
        raise ValidationError("故事线类型无效")
    item = Storyline(
        id=uuid4(),
        novel_id=novel_id,
        storyline_type=storyline_type,
        title=_clean_title(title, "故事线名称"),
        description=description.strip(),
        position=_next_position(session, Storyline, novel_id),
    )
    session.add(item)
    session.commit()
    return _storyline_payload(item)


def update_storyline(
    session: Session,
    novel_id: UUID,
    storyline_id: UUID,
    *,
    expected_version: int,
    storyline_type: str,
    title: str,
    description: str,
    status: str,
    progress: int,
) -> dict[str, Any]:
    item = session.scalar(
        select(Storyline)
        .where(Storyline.id == storyline_id, Storyline.novel_id == novel_id)
        .with_for_update()
    )
    if item is None:
        raise NotFoundError(f"storyline {storyline_id} not found")
    if item.version != expected_version:
        raise EntityConflictError(_storyline_payload(item))
    if storyline_type not in STORYLINE_TYPES or status not in STORYLINE_STATUSES:
        raise ValidationError("故事线类型或状态无效")
    if not 0 <= progress <= 100:
        raise ValidationError("故事线进度必须在0到100之间")
    item.storyline_type = storyline_type
    item.title = _clean_title(title, "故事线名称")
    item.description = description.strip()
    item.status = status
    item.progress = progress
    item.version += 1
    session.commit()
    return _storyline_payload(item)


def delete_storyline(
    session: Session, novel_id: UUID, storyline_id: UUID, *, expected_version: int
) -> None:
    item = session.scalar(
        select(Storyline)
        .where(Storyline.id == storyline_id, Storyline.novel_id == novel_id)
        .with_for_update()
    )
    if item is None:
        raise NotFoundError(f"storyline {storyline_id} not found")
    if item.version != expected_version:
        raise EntityConflictError(_storyline_payload(item))
    session.delete(item)
    session.commit()


def _foreshadow_payload(item: Foreshadow) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "novel_id": str(item.novel_id),
        "title": item.title,
        "content": item.content,
        "latest_progress": item.latest_progress,
        "status": item.status,
        "progress": item.progress,
        "position": item.position,
        "version": item.version,
        "created_at": _iso(item.created_at),
        "updated_at": _iso(item.updated_at),
    }


def _foreshadow_title_from_fact(fact: StoryFact) -> str:
    raw_title = fact.subject.strip()[:240] or "未命名伏笔"
    context = f"{fact.subject} {fact.predicate} {fact.object_text}"
    if "灯塔承包权" in context and ("举报" in context or "抢" in context):
        return "灯塔承包权阴谋线"
    return raw_title


def list_foreshadows(session: Session, novel_id: UUID) -> list[dict[str, Any]]:
    _require_novel(session, novel_id)
    rows = session.scalars(
        select(Foreshadow).where(Foreshadow.novel_id == novel_id).order_by(Foreshadow.position)
    ).all()
    # Intelligence extraction writes provenance-backed StoryFact rows. Mirror
    # its foreshadow items into the author-facing foreshadow board so the next
    # chapter wizard immediately sees the clues created by the previous chapter.
    facts = session.scalars(
        select(StoryFact)
        .where(
            StoryFact.novel_id == novel_id,
            StoryFact.status.in_(("active", "source_restored")),
            StoryFact.fact_type.in_(("foreshadow_new", "foreshadow_progress")),
        )
        .order_by(StoryFact.created_at)
    ).all()
    latest_source_revision_id = next(
        (fact.source_revision_id for fact in reversed(facts) if fact.source_revision_id is not None),
        None,
    )
    latest_new_facts = [
        fact
        for fact in facts
        if fact.source_revision_id == latest_source_revision_id
        and fact.fact_type == "foreshadow_new"
    ]
    latest_progress_facts = [
        fact
        for fact in facts
        if fact.source_revision_id == latest_source_revision_id
        and fact.fact_type == "foreshadow_progress"
    ]
    unresolved_markers = ("未", "尚", "仍", "待", "疑似", "身份不明", "未点出")
    unresolved_progress_facts = [
        fact
        for fact in latest_progress_facts
        if any(
            marker in f"{fact.subject}{fact.predicate}{fact.object_text}"
            for marker in unresolved_markers
        )
    ]
    latest_active_facts = [*latest_new_facts, *unresolved_progress_facts]
    all_auto_titles = {fact.subject.strip()[:240] for fact in facts if fact.subject.strip()}
    all_auto_titles.update(
        _foreshadow_title_from_fact(fact)
        for fact in facts
        if fact.fact_type == "foreshadow_new"
    )
    latest_active_titles = {
        _foreshadow_title_from_fact(fact) for fact in latest_active_facts
    }
    by_title = {item.title: item for item in rows}
    next_position = max((int(item.position or 0) for item in rows), default=0) + 1
    changed = False

    # Automatically extracted伏笔 are a projection of the latest accepted
    # chapter, not an ever-growing pile of every noun the model once noticed.
    # Retire raw noun-level cards; compact resolved history is materialized
    # below as a small number of author-readable summaries.
    for item in rows:
        if item.title in all_auto_titles and item.title not in latest_active_titles:
            if item.status != "dropped" or int(item.progress or 0) != 100:
                item.status = "dropped"
                item.progress = 100
                item.version = int(item.version or 0) + 1
                changed = True

    for fact in latest_active_facts:
        title = _foreshadow_title_from_fact(fact)
        content = f"{fact.predicate}：{fact.object_text}".strip("：")
        existing = by_title.get(title)
        if existing is not None:
            if (
                existing.content != content
                or existing.latest_progress != fact.object_text
                or existing.status != "active"
            ):
                existing.content = content
                existing.latest_progress = fact.object_text
                existing.status = "active"
                existing.progress = min(90, max(10, int(existing.progress or 0)))
                existing.version = int(existing.version or 0) + 1
                changed = True
            continue
        created = Foreshadow(
            id=uuid4(),
            novel_id=novel_id,
            title=title,
            content=content,
            latest_progress=fact.object_text,
            status="active",
            progress=10,
            position=next_position,
            version=1,
        )
        next_position += 1
        session.add(created)
        by_title[title] = created
        rows.append(created)
        changed = True

    history_text = " ".join(
        f"{fact.subject} {fact.predicate} {fact.object_text}" for fact in facts
    )
    resolved_specs: list[tuple[str, str, str]] = []
    if any(token in history_text for token in ("磁带", "录音", "深夜广播", "阿舟")):
        resolved_specs.append(
            (
                "磁带里的秘密",
                "广播磁带中反复出现的名字、声音与未寄出的内容已在后续章节得到确认。",
                "录音来源、阿舟身份与外婆留声的用意已经厘清",
            )
        )
    main_character_names = session.scalars(
        select(NovelCharacter.name)
        .where(
            NovelCharacter.novel_id == novel_id,
            NovelCharacter.role_type == "main",
        )
        .order_by(NovelCharacter.position)
    ).all()
    secret_character = next(
        (
            name
            for name in main_character_names[1:]
            if name in history_text
            and any(token in history_text for token in ("等待", "未说", "隐瞒", "旧电台"))
        ),
        None,
    )
    if secret_character:
        resolved_specs.append(
            (
                f"{secret_character}的隐瞒",
                f"{secret_character}曾经未说出口的离开、等待与守护原因已在后续章节揭开。",
                "人物旧日选择与沉默的原因已经得到回应",
            )
        )
    for title, content, latest_progress in resolved_specs[:2]:
        existing = by_title.get(title)
        if existing is None:
            existing = Foreshadow(
                id=uuid4(),
                novel_id=novel_id,
                title=title,
                content=content,
                latest_progress=latest_progress,
                status="resolved",
                progress=100,
                position=next_position,
                version=1,
            )
            next_position += 1
            session.add(existing)
            by_title[title] = existing
            rows.append(existing)
            changed = True
        elif (
            existing.content != content
            or existing.latest_progress != latest_progress
            or existing.status != "resolved"
            or int(existing.progress or 0) != 100
        ):
            existing.content = content
            existing.latest_progress = latest_progress
            existing.status = "resolved"
            existing.progress = 100
            existing.version = int(existing.version or 0) + 1
            changed = True
    if changed:
        session.commit()
    return [_foreshadow_payload(item) for item in rows if item.status != "dropped"]


def create_foreshadow(
    session: Session, novel_id: UUID, *, title: str, content: str, latest_progress: str
) -> dict[str, Any]:
    _require_novel(session, novel_id)
    item = Foreshadow(
        id=uuid4(),
        novel_id=novel_id,
        title=_clean_title(title, "伏笔名称"),
        content=content.strip(),
        latest_progress=latest_progress.strip(),
        position=_next_position(session, Foreshadow, novel_id),
    )
    session.add(item)
    session.commit()
    return _foreshadow_payload(item)


def update_foreshadow(
    session: Session,
    novel_id: UUID,
    foreshadow_id: UUID,
    *,
    expected_version: int,
    title: str,
    content: str,
    latest_progress: str,
    status: str,
    progress: int,
) -> dict[str, Any]:
    item = session.scalar(
        select(Foreshadow)
        .where(Foreshadow.id == foreshadow_id, Foreshadow.novel_id == novel_id)
        .with_for_update()
    )
    if item is None:
        raise NotFoundError(f"foreshadow {foreshadow_id} not found")
    if item.version != expected_version:
        raise EntityConflictError(_foreshadow_payload(item))
    if status not in FORESHADOW_STATUSES or not 0 <= progress <= 100:
        raise ValidationError("伏笔状态或进度无效")
    item.title = _clean_title(title, "伏笔名称")
    item.content = content.strip()
    item.latest_progress = latest_progress.strip()
    item.status = status
    item.progress = progress
    item.version += 1
    session.commit()
    return _foreshadow_payload(item)


def delete_foreshadow(
    session: Session, novel_id: UUID, foreshadow_id: UUID, *, expected_version: int
) -> None:
    item = session.scalar(
        select(Foreshadow)
        .where(Foreshadow.id == foreshadow_id, Foreshadow.novel_id == novel_id)
        .with_for_update()
    )
    if item is None:
        raise NotFoundError(f"foreshadow {foreshadow_id} not found")
    if item.version != expected_version:
        raise EntityConflictError(_foreshadow_payload(item))
    session.delete(item)
    session.commit()


def _chapter_draft_payload(draft: ChapterCreationDraft) -> dict[str, Any]:
    return {
        "id": str(draft.id),
        "draft_key": draft.draft_key,
        "novel_id": str(draft.novel_id),
        "volume_id": str(draft.volume_id) if draft.volume_id else None,
        "step": draft.step,
        "state": draft.state,
        "version": draft.version,
        "title": draft.title,
        "target_character_count": draft.target_character_count,
        "expectation_text": draft.expectation_text,
        "outline_text": draft.outline_text,
        "data": draft.data_json,
        "completed_document_id": str(draft.completed_document_id) if draft.completed_document_id else None,
        "created_at": _iso(draft.created_at),
        "updated_at": _iso(draft.updated_at),
    }


def get_or_create_chapter_creation_draft(
    session: Session, *, novel_id: UUID, volume_id: UUID | None, draft_key: str
) -> dict[str, Any]:
    _require_novel(session, novel_id)
    if volume_id:
        _require_volume(session, novel_id, volume_id)
    else:
        volume_id = session.scalar(
            select(Volume.id)
            .where(Volume.novel_id == novel_id)
            .order_by(Volume.position)
            .limit(1)
        )
        if volume_id is None:
            raise ValidationError("请先为小说创建分卷")
    key = draft_key.strip()
    if not key or len(key) > 120:
        raise ValidationError("章节草稿键无效")
    draft = session.scalar(
        select(ChapterCreationDraft).where(ChapterCreationDraft.draft_key == key)
    )
    if draft is not None:
        if draft.novel_id != novel_id:
            raise ValidationError("章节草稿键已属于其他小说")
        return _chapter_draft_payload(draft)
    draft = ChapterCreationDraft(
        id=uuid4(), draft_key=key, novel_id=novel_id, volume_id=volume_id,
        target_character_count=2500, data_json={}
    )
    session.add(draft)
    session.commit()
    return _chapter_draft_payload(draft)


def update_chapter_creation_draft(
    session: Session,
    draft_id: UUID,
    *,
    expected_version: int,
    step: int,
    title: str | None = None,
    target_character_count: int | None = None,
    expectation_text: str | None = None,
    outline_text: str | None = None,
    data_patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    draft = session.scalar(
        select(ChapterCreationDraft)
        .where(ChapterCreationDraft.id == draft_id)
        .with_for_update()
    )
    if draft is None:
        raise NotFoundError(f"chapter creation draft {draft_id} not found")
    if draft.version != expected_version:
        raise EntityConflictError(_chapter_draft_payload(draft))
    if draft.state == "completed":
        raise ValidationError("已完成的章节草稿不能修改")
    if not 1 <= step <= 6:
        raise ValidationError("章节创建步骤必须在1到6之间")
    if title is not None:
        draft.title = title.strip()
    if target_character_count is not None:
        if not 2000 <= target_character_count <= 5000:
            raise ValidationError("目标字数必须在2000到5000之间")
        draft.target_character_count = target_character_count
    if expectation_text is not None:
        draft.expectation_text = expectation_text.strip()
    if outline_text is not None:
        draft.outline_text = outline_text.strip()
    if data_patch:
        merged = dict(draft.data_json or {})
        merged.update(data_patch)
        if len(json.dumps(merged, ensure_ascii=False, default=str)) > 200_000:
            raise ValidationError("章节创建草稿内容过大")
        draft.data_json = merged
    draft.step = step
    draft.version += 1
    session.commit()
    return _chapter_draft_payload(draft)


def _ids_from_data(data: dict[str, Any], key: str) -> list[UUID]:
    values: list[UUID] = []
    for raw in data.get(key, []) or []:
        try:
            values.append(UUID(str(raw)))
        except (TypeError, ValueError):
            raise ValidationError(f"章节草稿中的 {key} 包含无效ID") from None
    return list(dict.fromkeys(values))


def _validate_chapter_references(
    session: Session, draft: ChapterCreationDraft
) -> tuple[list[NovelCharacter], list[NovelCharacter]]:
    data = dict(draft.data_json or {})
    storyline_ids = _ids_from_data(data, "storyline_ids")
    foreshadow_ids = _ids_from_data(data, "foreshadow_ids")
    required_ids = _ids_from_data(data, "required_role_ids")
    optional_ids = _ids_from_data(data, "optional_role_ids")
    if set(required_ids) & set(optional_ids):
        raise ValidationError("同一角色不能同时设为必须出场和可选出场")
    if storyline_ids:
        count = session.scalar(
            select(func.count(Storyline.id)).where(
                Storyline.id.in_(storyline_ids), Storyline.novel_id == draft.novel_id
            )
        )
        if int(count or 0) != len(storyline_ids):
            raise ValidationError("章节故事线包含其他小说或已删除数据")
    if foreshadow_ids:
        count = session.scalar(
            select(func.count(Foreshadow.id)).where(
                Foreshadow.id.in_(foreshadow_ids), Foreshadow.novel_id == draft.novel_id
            )
        )
        if int(count or 0) != len(foreshadow_ids):
            raise ValidationError("章节伏笔包含其他小说或已删除数据")
    all_role_ids = list(dict.fromkeys([*required_ids, *optional_ids]))
    characters = session.scalars(
        select(NovelCharacter).where(
            NovelCharacter.id.in_(all_role_ids), NovelCharacter.novel_id == draft.novel_id
        )
    ).all() if all_role_ids else []
    by_id = {item.id: item for item in characters}
    if set(all_role_ids) != set(by_id):
        raise ValidationError("章节角色包含其他小说或已删除数据")
    return [by_id[item_id] for item_id in required_ids], [by_id[item_id] for item_id in optional_ids]


def complete_chapter_creation_draft(
    session: Session, draft_id: UUID, *, expected_version: int
) -> dict[str, Any]:
    draft = session.scalar(
        select(ChapterCreationDraft)
        .where(ChapterCreationDraft.id == draft_id)
        .with_for_update()
    )
    if draft is None:
        raise NotFoundError(f"chapter creation draft {draft_id} not found")
    if draft.state == "completed" and draft.completed_document_id:
        return {"draft": _chapter_draft_payload(draft), "document": get_document(session, draft.completed_document_id)}
    if draft.version != expected_version:
        raise EntityConflictError(_chapter_draft_payload(draft))
    title = _clean_title(draft.title, "章节标题")
    if not draft.outline_text:
        raise ValidationError("请先生成或填写章节大纲")
    if draft.volume_id:
        _require_volume(session, draft.novel_id, draft.volume_id)
    required, optional = _validate_chapter_references(session, draft)
    position = _next_position(session, Document, draft.novel_id)
    document = _new_document(
        session,
        novel_id=draft.novel_id,
        title=title,
        kind="chapter",
        position=position,
        volume_id=draft.volume_id,
    )
    session.flush()
    session.add(
        ChapterBrief(
            id=uuid4(),
            document_id=document.id,
            version=1,
            target_word_count=draft.target_character_count,
            expectation_text=draft.expectation_text,
            outline_text=draft.outline_text,
            forbidden_text=str((draft.data_json or {}).get("forbidden_text", "")).strip(),
            role_constraints=_normalize_role_constraints(
                {
                    "required": [item.name for item in required],
                    "allowed": [item.name for item in optional],
                    "context_only": [],
                    "forbidden": [],
                }
            ),
        )
    )
    draft.state = "completed"
    draft.step = 6
    draft.completed_document_id = document.id
    draft.version += 1
    session.commit()
    return {"draft": _chapter_draft_payload(draft), "document": get_document(session, document.id)}


def _creative_job_payload(job: CreativeGenerationJob) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "scope_type": job.scope_type,
        "scope_id": str(job.scope_id),
        "novel_id": str(job.novel_id) if job.novel_id else None,
        "document_id": str(job.document_id) if job.document_id else None,
        "kind": job.kind,
        "state": job.state,
        "input_hash": job.input_hash,
        "input_snapshot": job.input_snapshot,
        "execution_agent_id": job.execution_agent_id,
        "requested_provider_id": job.requested_provider_id,
        "requested_model_id": job.requested_model_id,
        "generation_contract_version": job.generation_contract_version,
        "actual_provider_id": job.actual_provider_id,
        "actual_model_id": job.actual_model_id,
        "provider_profile": job.actual_provider_id or job.provider_profile,
        "output_json": job.output_json,
        "output_text": job.output_text,
        "target_character_count": job.target_character_count,
        "output_visible_character_count": job.output_visible_character_count,
        "attempt": job.attempt,
        "failure_message": job.failure_message,
        "created_at": _iso(job.created_at),
        "completed_at": _iso(job.completed_at),
    }


def start_creative_generation(
    session: Session,
    *,
    scope_type: str,
    scope_id: UUID,
    kind: str,
    input_snapshot: dict[str, Any],
    execution_agent_id: str,
    requested_provider_id: str,
    requested_model_id: str,
    generation_contract_version: str,
    novel_id: UUID | None = None,
    document_id: UUID | None = None,
    target_character_count: int | None = None,
    force_new: bool = False,
) -> dict[str, Any]:
    if kind not in CREATIVE_GENERATION_KINDS:
        raise ValidationError("创作生成类型无效")
    if not all(
        value.strip()
        for value in (
            execution_agent_id,
            requested_provider_id,
            requested_model_id,
            generation_contract_version,
        )
    ):
        raise ValidationError("创作生成缺少可核验的 Agent 或 requested 模型证据")
    if novel_id:
        _require_novel(session, novel_id)
    if document_id:
        document = _require_document(session, document_id)
        if novel_id and document.novel_id != novel_id:
            raise ValidationError("生成文档不属于当前小说")
    _validate_creative_generation_scope(
        session,
        scope_type=scope_type,
        scope_id=scope_id,
        kind=kind,
        novel_id=novel_id,
        document_id=document_id,
    )
    serialized = json.dumps(
        {
            "input_snapshot": input_snapshot,
            "execution_agent_id": execution_agent_id,
            "requested_provider_id": requested_provider_id,
            "requested_model_id": requested_model_id,
            "generation_contract_version": generation_contract_version,
            "target_character_count": target_character_count,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(serialized) > 500_000:
        raise ValidationError("生成输入快照不能超过500000个字符")
    input_digest = content_hash(serialized)
    attempt = 1
    _lock_generation_attempt(
        session,
        namespace=f"creative:{scope_type}:{kind}",
        scope_key=str(scope_id),
        input_hash=input_digest,
    )
    existing = session.scalar(
        select(CreativeGenerationJob)
        .where(
            CreativeGenerationJob.scope_type == scope_type,
            CreativeGenerationJob.scope_id == scope_id,
            CreativeGenerationJob.kind == kind,
            CreativeGenerationJob.input_hash == input_digest,
        )
        .order_by(CreativeGenerationJob.attempt.desc())
    )
    if existing and not force_new and existing.state in {"running", "ready"}:
        payload = _creative_job_payload(existing)
        payload["should_execute"] = False
        return payload
    if existing:
        attempt = existing.attempt + 1
    job = CreativeGenerationJob(
        id=uuid4(),
        scope_type=scope_type,
        scope_id=scope_id,
        novel_id=novel_id,
        document_id=document_id,
        kind=kind,
        state="running",
        input_hash=input_digest,
        input_snapshot=input_snapshot,
        execution_agent_id=execution_agent_id,
        requested_provider_id=requested_provider_id,
        requested_model_id=requested_model_id,
        generation_contract_version=generation_contract_version,
        target_character_count=target_character_count,
        attempt=attempt,
    )
    session.add(job)
    session.commit()
    payload = _creative_job_payload(job)
    payload["should_execute"] = True
    return payload


def _validate_creative_generation_scope(
    session: Session,
    *,
    scope_type: str,
    scope_id: UUID,
    kind: str,
    novel_id: UUID | None,
    document_id: UUID | None,
) -> None:
    if kind == "relationship_graph":
        if novel_id is None or scope_type != "novel" or scope_id != novel_id:
            raise ValidationError("关系网自动生成必须绑定当前小说")
        return
    if kind in {"novel_template", "novel_naming", "novel_cover"}:
        draft = session.get(NovelCreationDraft, scope_id)
        if scope_type != "novel_creation" or draft is None:
            raise ValidationError("建书辅助生成必须绑定当前建书草稿")
        return
    if kind.startswith("outline_"):
        draft = session.get(OutlineDraft, scope_id)
        if scope_type != "outline" or draft is None:
            raise ValidationError("大纲生成必须绑定当前大纲草稿")
        if novel_id is None or draft.novel_id != novel_id:
            raise ValidationError("大纲生成不属于当前小说")
        return
    if kind in {"chapter_storyline_recommendation", "chapter_outline"}:
        draft = session.get(ChapterCreationDraft, scope_id)
        if scope_type != "chapter_creation" or draft is None:
            raise ValidationError("章节辅助生成必须绑定当前章节创建草稿")
        if novel_id is None or draft.novel_id != novel_id:
            raise ValidationError("章节辅助生成不属于当前小说")
        return
    if kind == "review":
        if document_id is not None:
            if scope_type != "document" or scope_id != document_id:
                raise ValidationError("章节审阅必须绑定当前正文")
            return
        if novel_id is not None and scope_type == "novel" and scope_id == novel_id:
            return
        raise ValidationError("审阅生成必须绑定当前小说或正文")


def build_creative_generation_prompt(job: dict[str, Any]) -> str:
    """Build a deterministic strict-JSON prompt for a creative helper job."""

    kind = str(job["kind"])
    snapshot = dict(job.get("input_snapshot") or {})
    tasks = {
        "novel_template": (
            "根据受众和创作思路自动匹配最适合的长篇小说模板，并填写可编辑的模板设定。"
            "genre只能从现实、言情、都市、玄幻、悬疑、科幻、历史中选择；现实题材的当代生活、"
            "久别重逢和治愈故事优先使用genre=现实、template_name=现实生活、template_key=real-life。"
            "其他template_name使用2到6个中文字符，template_key使用稳定英文短横线标识。"
            "template_fields必须严格返回[\"protagonist_identity\",\"background_setting\","
            "\"core_conflict\",\"emotional_mainline\",\"style_features\"]，template_data必须完整填写这5项。"
            "template_data的每个值必须是8到18个中文可见字符的标签式短语，只保留关键信息，"
            "不得写解释、年龄、完整句子、剧情展开或句号。"
            "返回 {\"genre\":\"...\",\"template_key\":\"...\",\"template_name\":\"...\","
            "\"template_fields\":[\"...\"],\"template_data\":{\"protagonist_identity\":\"...\","
            "\"background_setting\":\"...\",\"core_conflict\":\"...\","
            "\"emotional_mainline\":\"...\",\"style_features\":\"...\"}}。"
        ),
        "novel_naming": (
            "根据受众、题材、核心创意和模板生成8个不重复的中文小说名。"
            "返回 {\"titles\":[\"书名1\",\"书名2\"]}。"
        ),
        "novel_cover": (
            "生成可供封面图模型使用的中文封面提示词、短副标题和视觉关键词。"
            "返回 {\"cover_prompt\":\"...\",\"subtitle\":\"...\",\"keywords\":[\"...\"]}。"
        ),
        "outline_background": (
            "生成具体、可连续写作的故事背景，只写一段，控制在80到180个中文可见字符。"
            "包含时代、地点、核心氛围与触发故事的关键物件，不展开人物履历、支线或逐章情节。"
            "返回 {\"background_text\":\"...\"}。"
        ),
        "outline_characters": (
            "生成4到8个主要角色和配角，至少包含1个main主角和2个supporting配角，"
            "人物动机、缺陷、秘密和成长方向必须彼此咬合。顶层只能有characters数组，"
            "即使只有一个人物也不得把人物对象直接放在顶层。返回"
            " {\"characters\":[{\"name\":\"...\",\"role_type\":\"main|supporting\","
            "\"description\":\"...\",\"details\":{}}]}。"
        ),
        "outline_plot": (
            "生成覆盖目标章节数的主要情节，控制在1200到1800个中文可见字符。"
            "按章节或连续阶段清楚写出开局、升级、关键转折、高潮和收束，确保后续可以据此逐章创作。"
            "正文内的直接引语只能使用中文全角引号‘’或“”，不得使用未转义的英文双引号破坏JSON。"
            "返回 {\"plot_text\":\"...\"}。"
        ),
        "outline_highlight": (
            "提炼作品亮点和不超过200个中文可见字符的简介。"
            "返回 {\"highlight_text\":\"...\"}。"
        ),
        "chapter_storyline_recommendation": (
            "根据小说总纲、所有候选故事线、上一章结尾和当前章节序号，选择本章最应推进的1到3条故事线。"
            "只能返回输入中真实存在的故事线ID。返回 {\"storyline_ids\":[\"...\"],\"reason\":\"...\"}。"
        ),
        "chapter_outline": (
            "结合故事线、角色、伏笔、期望情节和前文，为本章生成精简、可直接写作的章纲和简洁章节标题。"
            "标题不带章节序号；章纲严格控制在260到500个中文可见字符，用1段或4到6个短段写完。"
            "只规划当前章，禁止预演后续章节、禁止引用第几章、禁止写8个或更多场景。"
            "章纲须包含场景顺序、核心冲突、人物行动、信息揭示、伏笔推进和结尾钩子。"
            "返回 {\"title\":\"...\",\"outline_text\":\"...\"}。"
        ),
        "relationship_graph": (
            "根据角色设定、小说大纲、作者关系覆盖项、已确认章节情报和最近正文，"
            "生成当前小说完整且克制的人物关系网。source_name与target_name只能逐字使用"
            "输入characters中的真实姓名；不得创造人物，不得把临时同场或一次性动作当成稳定关系。"
            "作者关系覆盖项是最高优先级真相：active=true不得重复或冲突，active=false代表作者已删除，"
            "绝对不得复活。每对人物同一relation_kind最多一条。directionality只能是directed或"
            "undirected；师徒、影响、命令等有明确施受方的关系用directed，其余稳定双向关系用"
            "undirected。relation_kind只能从family、colleague、mentor、ally、enemy、romance、"
            "other中选择；label使用2到12个中文字符；description用一句话说明关系现状；confidence"
            "为0到100，只输出置信度不低于65的关系；evidence返回1到3条简短来源依据。"
            "relationships必须代表本次快照中的完整AI关系集合，并返回"
            " {\"complete_snapshot\":true,\"relationships\":[{\"source_name\":\"...\","
            "\"target_name\":\"...\",\"directionality\":\"directed|undirected\","
            "\"relation_kind\":\"family|colleague|mentor|ally|enemy|romance|other\","
            "\"label\":\"...\",\"description\":\"...\",\"confidence\":85,"
            "\"evidence\":[\"角色设定：...\"]}]}。没有可靠关系时也必须返回空relationships数组。"
        ),
        "review": (
            "审阅正文的连续性、人物一致性、时间地点、因果、伏笔、重复段落和系统文本污染。"
            "返回 {\"passed\":true,\"summary\":\"...\",\"issues\":[{\"severity\":\"P0|P1|P2|P3\","
            "\"type\":\"...\",\"evidence\":\"...\",\"suggestion\":\"...\"}]}。"
        ),
    }
    instruction = tasks.get(kind)
    if instruction is None:
        raise ValidationError("创作生成类型无效")
    return (
        "你是长篇小说创作流程中的结构化助手。\n"
        "只返回一个严格 JSON 对象，不要 Markdown 代码围栏、解释、状态胶囊或保存声明。\n"
        f"任务：{instruction}\n"
        "输入快照：\n"
        f"{json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}"
    )


def complete_creative_generation(
    session: Session,
    job_id: UUID,
    *,
    actual_provider_id: str,
    actual_model_id: str,
    output_text: str = "",
    output_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    job = session.scalar(
        select(CreativeGenerationJob)
        .where(CreativeGenerationJob.id == job_id)
        .with_for_update()
    )
    if job is None:
        raise NotFoundError(f"creative generation job {job_id} not found")
    if job.state != "running":
        return _creative_job_payload(job)
    job.actual_provider_id = actual_provider_id
    job.actual_model_id = actual_model_id
    if (
        actual_provider_id != job.requested_provider_id
        or actual_model_id != job.requested_model_id
    ):
        job.state = "failed"
        job.failure_message = (
            "创作回复模型与任务启动模型不一致，结果已作废："
            f"requested={job.requested_provider_id}/{job.requested_model_id}, "
            f"actual={actual_provider_id}/{actual_model_id}"
        )
        job.completed_at = datetime.now(timezone.utc)
        session.commit()
        raise ValidationError(job.failure_message)
    job.state = "ready"
    job.output_text = output_text.strip()
    job.output_json = output_json or {}
    job.output_visible_character_count = visible_character_count(job.output_text)
    job.failure_message = None
    job.completed_at = datetime.now(timezone.utc)
    session.commit()
    return _creative_job_payload(job)


def fail_creative_generation(
    session: Session,
    job_id: UUID,
    *,
    failure_message: str,
    actual_provider_id: str | None = None,
    actual_model_id: str | None = None,
) -> dict[str, Any]:
    job = session.scalar(
        select(CreativeGenerationJob)
        .where(CreativeGenerationJob.id == job_id)
        .with_for_update()
    )
    if job is None:
        raise NotFoundError(f"creative generation job {job_id} not found")
    if job.state != "running":
        return _creative_job_payload(job)
    if actual_provider_id and actual_model_id:
        job.actual_provider_id = actual_provider_id
        job.actual_model_id = actual_model_id
    job.state = "failed"
    job.failure_message = failure_message[:4000]
    job.completed_at = datetime.now(timezone.utc)
    session.commit()
    return _creative_job_payload(job)


def list_creative_generations(
    session: Session, *, scope_type: str, scope_id: UUID
) -> list[dict[str, Any]]:
    jobs = session.scalars(
        select(CreativeGenerationJob)
        .where(
            CreativeGenerationJob.scope_type == scope_type,
            CreativeGenerationJob.scope_id == scope_id,
        )
        .order_by(CreativeGenerationJob.created_at.desc(), CreativeGenerationJob.attempt.desc())
    ).all()
    return [_creative_job_payload(job) for job in jobs]


def update_volume(
    session: Session,
    novel_id: UUID,
    volume_id: UUID,
    *,
    expected_version: int,
    title: str,
) -> dict[str, Any]:
    volume = session.scalar(
        select(Volume)
        .where(Volume.id == volume_id, Volume.novel_id == novel_id)
        .with_for_update()
    )
    if volume is None:
        raise NotFoundError(f"volume {volume_id} not found")
    current = {
        "id": str(volume.id), "novel_id": str(volume.novel_id), "title": volume.title,
        "position": volume.position, "version": volume.version,
    }
    if volume.version != expected_version:
        raise EntityConflictError(current)
    volume.title = _clean_title(title, "分卷名称")
    volume.version += 1
    session.commit()
    current.update({"title": volume.title, "version": volume.version})
    return current


def update_novel_settings(
    session: Session,
    novel_id: UUID,
    *,
    expected_version: int,
    genre: str,
    subgenre: str,
    idea: str,
    template_name: str,
    template_data: dict[str, Any],
    cover_image_data: str | None = None,
) -> dict[str, Any]:
    novel = session.scalar(select(Novel).where(Novel.id == novel_id).with_for_update())
    if novel is None:
        raise NotFoundError(f"novel {novel_id} not found")
    if novel.version != expected_version:
        raise EntityConflictError(get_novel(session, novel_id))
    serialized = json.dumps(template_data, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) > 100_000:
        raise ValidationError("模板设定不能超过100000个字符")
    novel.genre = genre.strip()
    novel.subgenre = subgenre.strip()
    novel.idea = idea.strip()
    novel.template_name = template_name.strip()
    novel.template_data = template_data
    if cover_image_data is not None:
        novel.cover_image_data = cover_image_data
    novel.version += 1
    session.commit()
    return get_novel(session, novel_id)


def delete_volume(
    session: Session,
    novel_id: UUID,
    volume_id: UUID,
    *,
    expected_version: int,
    move_documents_to: UUID | None = None,
) -> None:
    volume = session.scalar(
        select(Volume)
        .where(Volume.id == volume_id, Volume.novel_id == novel_id)
        .with_for_update()
    )
    if volume is None:
        raise NotFoundError(f"volume {volume_id} not found")
    if volume.version != expected_version:
        raise EntityConflictError({"id": str(volume.id), "version": volume.version, "title": volume.title})
    documents = session.scalars(
        select(Document).where(Document.volume_id == volume_id).with_for_update()
    ).all()
    volume_count = session.scalar(
        select(func.count(Volume.id)).where(Volume.novel_id == novel_id)
    )
    if int(volume_count or 0) <= 1 and documents:
        raise ValidationError("最后一个分卷仍有章节，不能直接删除")
    if documents and move_documents_to is None:
        raise ValidationError("分卷内仍有章节，请先选择移动目标分卷")
    if move_documents_to:
        target = _require_volume(session, novel_id, move_documents_to)
        if target.id == volume.id:
            raise ValidationError("移动目标不能是当前分卷")
        for document in documents:
            document.volume_id = target.id
            document.version += 1
    session.delete(volume)
    session.commit()


def reorder_volumes(
    session: Session, novel_id: UUID, *, ordered_volume_ids: list[UUID]
) -> list[dict[str, Any]]:
    volumes = session.scalars(
        select(Volume).where(Volume.novel_id == novel_id).with_for_update()
    ).all()
    by_id = {item.id: item for item in volumes}
    if len(ordered_volume_ids) != len(set(ordered_volume_ids)) or set(ordered_volume_ids) != set(by_id):
        raise ValidationError("分卷排序必须包含当前小说的全部分卷且不能重复")
    for index, volume_id in enumerate(ordered_volume_ids, start=1):
        by_id[volume_id].position = -(index * 1000)
    session.flush()
    for index, volume_id in enumerate(ordered_volume_ids, start=1):
        volume = by_id[volume_id]
        volume.position = index * 1000
        volume.version += 1
    session.commit()
    return [
        {"id": str(by_id[item_id].id), "novel_id": str(novel_id), "title": by_id[item_id].title,
         "position": by_id[item_id].position, "version": by_id[item_id].version}
        for item_id in ordered_volume_ids
    ]


def update_document_metadata(
    session: Session,
    novel_id: UUID,
    document_id: UUID,
    *,
    expected_version: int,
    title: str,
) -> dict[str, Any]:
    document = session.scalar(
        select(Document)
        .where(Document.id == document_id, Document.novel_id == novel_id)
        .with_for_update()
    )
    if document is None:
        raise NotFoundError(f"document {document_id} not found")
    working = session.get(DocumentWorkingCopy, document.id)
    if working is None:
        raise NotFoundError(f"working copy for document {document_id} not found")
    if document.version != expected_version:
        raise EntityConflictError(_document_payload(document, working))
    document.title = _clean_title(title, "章节标题")
    document.version += 1
    session.commit()
    return get_document(session, document.id)


def delete_document(
    session: Session, novel_id: UUID, document_id: UUID, *, expected_version: int
) -> None:
    document = session.scalar(
        select(Document)
        .where(Document.id == document_id, Document.novel_id == novel_id)
        .with_for_update()
    )
    if document is None:
        raise NotFoundError(f"document {document_id} not found")
    working = session.get(DocumentWorkingCopy, document.id)
    if working is None:
        raise NotFoundError(f"working copy for document {document_id} not found")
    if document.version != expected_version:
        raise EntityConflictError(_document_payload(document, working))
    session.delete(document)
    session.commit()


def reorder_chapters(
    session: Session,
    novel_id: UUID,
    *,
    ordered_document_ids: list[UUID],
    volume_by_document: dict[str, UUID | None],
) -> list[dict[str, Any]]:
    chapters = session.scalars(
        select(Document)
        .where(Document.novel_id == novel_id, Document.kind == "chapter")
        .with_for_update()
    ).all()
    by_id = {item.id: item for item in chapters}
    if len(ordered_document_ids) != len(set(ordered_document_ids)) or set(ordered_document_ids) != set(by_id):
        raise ValidationError("章节排序必须包含当前小说的全部章节且不能重复")
    valid_volume_ids = set(
        session.scalars(select(Volume.id).where(Volume.novel_id == novel_id)).all()
    )
    for raw_id in volume_by_document.values():
        if raw_id is not None and raw_id not in valid_volume_ids:
            raise ValidationError("章节移动目标分卷不属于当前小说")
    for index, document_id in enumerate(ordered_document_ids, start=1):
        by_id[document_id].position = -(index * 1000)
    session.flush()
    for index, document_id in enumerate(ordered_document_ids, start=1):
        document = by_id[document_id]
        document.position = index * 1000
        raw_key = str(document_id)
        if raw_key in volume_by_document:
            document.volume_id = volume_by_document[raw_key]
        document.version += 1
    session.commit()
    return [get_document(session, item_id) for item_id in ordered_document_ids]


def build_novel_export(
    session: Session, novel_id: UUID, *, export_format: str = "markdown"
) -> dict[str, Any]:
    novel = _require_novel(session, novel_id)
    if export_format not in {"markdown", "text"}:
        raise ValidationError("当前只支持 Markdown 或纯文本导出")
    volumes = session.scalars(
        select(Volume).where(Volume.novel_id == novel_id).order_by(Volume.position)
    ).all()
    chunks: list[str] = [f"# {novel.title}" if export_format == "markdown" else novel.title]
    chapter_count = 0
    visible_count = 0
    chapter_stats: list[dict[str, Any]] = []

    def append_document(document: Document) -> None:
        nonlocal chapter_count, visible_count
        working = session.get(DocumentWorkingCopy, document.id)
        if working is None:
            return
        body = (
            working.content_markdown
            if export_format == "markdown"
            else markdown_to_text(working.content_markdown)
        )
        chunks.append(
            f"### {document.title}"
            if export_format == "markdown"
            else f"\n{document.title}"
        )
        chunks.append(body)
        count = visible_character_count(working.content_markdown)
        visible_count += count
        chapter_count += 1
        chapter_stats.append(
            {
                "document_id": str(document.id),
                "title": document.title,
                "visible_character_count": count,
            }
        )

    for volume in volumes:
        chunks.append(f"## {volume.title}" if export_format == "markdown" else f"\n{volume.title}")
        documents = session.scalars(
            select(Document)
            .where(
                Document.novel_id == novel_id,
                Document.volume_id == volume.id,
                Document.kind == "chapter",
            )
            .order_by(Document.position)
        ).all()
        for document in documents:
            append_document(document)
    ungrouped_documents = session.scalars(
        select(Document)
        .where(
            Document.novel_id == novel_id,
            Document.volume_id.is_(None),
            Document.kind == "chapter",
        )
        .order_by(Document.position)
    ).all()
    if ungrouped_documents:
        chunks.append("## 未分卷" if export_format == "markdown" else "\n未分卷")
        for document in ungrouped_documents:
            append_document(document)
    content = "\n\n".join(chunks).strip() + "\n"
    export = NovelExport(
        id=uuid4(),
        novel_id=novel_id,
        export_format=export_format,
        state="ready",
        content_hash=content_hash(content),
        storage_path="",
        metadata_json={
            "novel_title": novel.title,
            "volume_count": len(volumes),
            "ungrouped_chapter_count": len(ungrouped_documents),
            "chapter_count": chapter_count,
            "visible_character_count": visible_count,
            "chapters": chapter_stats,
        },
        completed_at=datetime.now(timezone.utc),
    )
    session.add(export)
    session.commit()
    return {
        "id": str(export.id),
        "novel_id": str(novel_id),
        "export_format": export_format,
        "state": export.state,
        "content_hash": export.content_hash,
        "content": content,
        "metadata": export.metadata_json,
        "created_at": _iso(export.created_at),
        "completed_at": _iso(export.completed_at),
    }
