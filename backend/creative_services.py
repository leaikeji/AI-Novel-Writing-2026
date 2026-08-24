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
    CreativeGenerationJob,
    Document,
    DocumentRevision,
    DocumentWorkingCopy,
    Foreshadow,
    Novel,
    NovelCharacter,
    NovelCreationDraft,
    NovelExport,
    OutlineDraft,
    PrivateAsset,
    Storyline,
    Volume,
)
from .services import (
    DomainError,
    NotFoundError,
    ValidationError,
    _document_payload,
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


MINIMAX_M3_MODEL_ID = "MiniMax-M3"
PRIVATE_ASSET_TYPES = {"plot", "writing_style", "vocabulary", "idea"}
ROLE_TYPES = {"main", "supporting"}
STORYLINE_TYPES = {"main", "support", "romance", "faction"}
STORYLINE_STATUSES = {"active", "paused", "completed", "archived"}
FORESHADOW_STATUSES = {"planned", "active", "resolved", "dropped"}
CREATIVE_GENERATION_KINDS = {
    "novel_naming",
    "novel_cover",
    "outline_background",
    "outline_characters",
    "outline_plot",
    "outline_highlight",
    "chapter_storyline_recommendation",
    "chapter_outline",
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


def _model_matches_minimax_m3(value: str | None) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", (value or "").lower())
    return normalized == "minimaxm3"


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
    volume = Volume(id=uuid4(), novel_id=novel.id, title="第一卷", position=1000)
    session.add_all((novel, volume))
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


def _character_payload(character: NovelCharacter) -> dict[str, Any]:
    return {
        "id": str(character.id),
        "novel_id": str(character.novel_id),
        "role_type": character.role_type,
        "name": character.name,
        "description": character.description,
        "details": character.details,
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
        .where(NovelCharacter.novel_id == novel_id)
        .order_by(NovelCharacter.position)
    ).all()
    return [_character_payload(character) for character in characters]


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
    session.delete(character)
    session.commit()


def _relationship_payload(relation: CharacterRelationship) -> dict[str, Any]:
    return {
        "id": str(relation.id),
        "novel_id": str(relation.novel_id),
        "source_character_id": str(relation.source_character_id),
        "target_character_id": str(relation.target_character_id),
        "relation_type": relation.relation_type,
        "description": relation.description,
        "version": relation.version,
        "created_at": _iso(relation.created_at),
        "updated_at": _iso(relation.updated_at),
    }


def list_character_relationships(session: Session, novel_id: UUID) -> list[dict[str, Any]]:
    _require_novel(session, novel_id)
    relations = session.scalars(
        select(CharacterRelationship)
        .where(CharacterRelationship.novel_id == novel_id)
        .order_by(CharacterRelationship.created_at, CharacterRelationship.id)
    ).all()
    return [_relationship_payload(relation) for relation in relations]


def create_character_relationship(
    session: Session,
    novel_id: UUID,
    *,
    source_character_id: UUID,
    target_character_id: UUID,
    relation_type: str,
    description: str,
) -> dict[str, Any]:
    if source_character_id == target_character_id:
        raise ValidationError("角色不能与自己建立关系")
    source = session.get(NovelCharacter, source_character_id)
    target = session.get(NovelCharacter, target_character_id)
    if source is None or target is None or source.novel_id != novel_id or target.novel_id != novel_id:
        raise ValidationError("关系两端角色必须属于当前小说")
    relation = CharacterRelationship(
        id=uuid4(),
        novel_id=novel_id,
        source_character_id=source_character_id,
        target_character_id=target_character_id,
        relation_type=_clean_title(relation_type, "关系类型"),
        description=description.strip(),
    )
    session.add(relation)
    session.commit()
    return _relationship_payload(relation)


def update_character_relationship(
    session: Session,
    novel_id: UUID,
    relationship_id: UUID,
    *,
    expected_version: int,
    relation_type: str,
    description: str,
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
    if relation.version != expected_version:
        raise EntityConflictError(_relationship_payload(relation))
    relation.relation_type = _clean_title(relation_type, "关系类型")
    relation.description = description.strip()
    relation.version += 1
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
    if relation.version != expected_version:
        raise EntityConflictError(_relationship_payload(relation))
    session.delete(relation)
    session.commit()


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


def list_storylines(session: Session, novel_id: UUID) -> list[dict[str, Any]]:
    _require_novel(session, novel_id)
    rows = session.scalars(
        select(Storyline).where(Storyline.novel_id == novel_id).order_by(Storyline.position)
    ).all()
    return [_storyline_payload(item) for item in rows]


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


def list_foreshadows(session: Session, novel_id: UUID) -> list[dict[str, Any]]:
    _require_novel(session, novel_id)
    rows = session.scalars(
        select(Foreshadow).where(Foreshadow.novel_id == novel_id).order_by(Foreshadow.position)
    ).all()
    return [_foreshadow_payload(item) for item in rows]


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
        id=uuid4(), draft_key=key, novel_id=novel_id, volume_id=volume_id, data_json={}
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
        if not 3000 <= target_character_count <= 5000:
            raise ValidationError("目标字数必须在3000到5000之间")
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
        "requested_model_id": job.requested_model_id,
        "actual_model_id": job.actual_model_id,
        "provider_profile": job.provider_profile,
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
    novel_id: UUID | None = None,
    document_id: UUID | None = None,
    target_character_count: int | None = None,
    requested_model_id: str = MINIMAX_M3_MODEL_ID,
    force_new: bool = False,
) -> dict[str, Any]:
    if kind not in CREATIVE_GENERATION_KINDS:
        raise ValidationError("创作生成类型无效")
    if not _model_matches_minimax_m3(requested_model_id):
        raise ValidationError("本项目的创作生成模型固定为 MiniMax M3")
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
    serialized = json.dumps(input_snapshot, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if len(serialized) > 500_000:
        raise ValidationError("生成输入快照不能超过500000个字符")
    input_digest = content_hash(serialized)
    attempt = 1
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
    if existing and not force_new:
        return _creative_job_payload(existing)
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
        requested_model_id=MINIMAX_M3_MODEL_ID,
        target_character_count=target_character_count,
        attempt=attempt,
    )
    session.add(job)
    session.commit()
    return _creative_job_payload(job)


def _validate_creative_generation_scope(
    session: Session,
    *,
    scope_type: str,
    scope_id: UUID,
    kind: str,
    novel_id: UUID | None,
    document_id: UUID | None,
) -> None:
    if kind in {"novel_naming", "novel_cover"}:
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
        "novel_naming": (
            "根据受众、题材、核心创意和模板生成10个不重复的中文小说名。"
            "返回 {\"titles\":[\"书名1\",\"书名2\"]}。"
        ),
        "novel_cover": (
            "生成可供封面图模型使用的中文封面提示词、短副标题和视觉关键词。"
            "返回 {\"cover_prompt\":\"...\",\"subtitle\":\"...\",\"keywords\":[\"...\"]}。"
        ),
        "outline_background": (
            "生成具体、可连续写作的故事背景。"
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
            "生成覆盖目标章节数的主要情节，包含开局、升级、转折、高潮和收束。"
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
            "结合故事线、角色、伏笔、期望情节和前文，为本章生成可直接写作的详细章纲和简洁章节标题。"
            "标题不带章节序号，章纲必须包含场景顺序、核心冲突、人物行动、信息揭示、伏笔推进和结尾钩子。"
            "返回 {\"title\":\"...\",\"outline_text\":\"...\"}。"
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
        "你是长篇小说创作流程中的结构化助手。本次固定使用 MiniMax M3。\n"
        "只返回一个严格 JSON 对象，不要 Markdown 代码围栏、解释、状态胶囊或保存声明。\n"
        f"任务：{instruction}\n"
        "输入快照：\n"
        f"{json.dumps(snapshot, ensure_ascii=False, sort_keys=True)}"
    )


def complete_creative_generation(
    session: Session,
    job_id: UUID,
    *,
    actual_model_id: str,
    provider_profile: str,
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
    if job.state == "ready":
        return _creative_job_payload(job)
    if not _model_matches_minimax_m3(actual_model_id):
        job.state = "failed"
        job.actual_model_id = actual_model_id
        job.provider_profile = provider_profile
        job.failure_message = "实际模型不是 MiniMax M3，结果已作废"
        job.completed_at = datetime.now(timezone.utc)
        session.commit()
        raise ValidationError(job.failure_message)
    job.state = "ready"
    job.actual_model_id = actual_model_id
    job.provider_profile = provider_profile
    job.output_text = output_text.strip()
    job.output_json = output_json or {}
    job.output_visible_character_count = visible_character_count(job.output_text)
    job.failure_message = None
    job.completed_at = datetime.now(timezone.utc)
    session.commit()
    return _creative_job_payload(job)


def fail_creative_generation(
    session: Session, job_id: UUID, *, failure_message: str
) -> dict[str, Any]:
    job = session.get(CreativeGenerationJob, job_id)
    if job is None:
        raise NotFoundError(f"creative generation job {job_id} not found")
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
    volume_count = session.scalar(
        select(func.count(Volume.id)).where(Volume.novel_id == novel_id)
    )
    if int(volume_count or 0) <= 1:
        raise ValidationError("小说至少需要保留一个分卷")
    documents = session.scalars(
        select(Document).where(Document.volume_id == volume_id).with_for_update()
    ).all()
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
