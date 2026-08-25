"""Pydantic contracts for the complete long-form workflow API."""

from __future__ import annotations

import re
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


SELECTION_EDIT_OPERATIONS = (
    "polish",
    "rewrite",
    "expand",
    "shorten",
    "dialogue",
    "review",
    "custom",
)
SELECTION_EDIT_ENTITY_TYPES = (
    "document",
    "outline",
    "character",
    "relationship",
    "storyline",
    "foreshadow",
    "setting",
)
SELECTION_EDIT_FIELD_IDS = frozenset(
    {
        "chapter.body",
        "chapter.title",
        "chapter.outline",
        "chapter.outline.targetCharacters",
        "chapter.outline.expectation",
        "chapter.outline.forbidden",
        "chapter.outline.roles.required",
        "chapter.outline.roles.allowed",
        "chapter.outline.roles.contextOnly",
        "chapter.outline.roles.forbidden",
        "outline.targetChapterCount",
        "outline.background",
        "outline.plot",
        "outline.highlight",
        "outline.character.roleType",
        "outline.character.name",
        "outline.character.gender",
        "outline.character.age",
        "outline.character.personality",
        "outline.character.identity",
        "outline.character.description",
        "character.roleType",
        "character.name",
        "character.gender",
        "character.age",
        "character.identity",
        "character.personality",
        "character.description",
        "relationship.sourceCharacterId",
        "relationship.targetCharacterId",
        "relationship.kind",
        "relationship.directionality",
        "relationship.label",
        "relationship.description",
        "storyline.storylineType",
        "storyline.title",
        "storyline.description",
        "storyline.status",
        "storyline.progress",
        "foreshadow.title",
        "foreshadow.content",
        "foreshadow.latestProgress",
        "foreshadow.status",
        "settings.templateName",
        "settings.genre",
        "settings.subgenre",
        "settings.idea",
    }
)
_SELECTION_EDIT_TEMPLATE_FIELD_ID = re.compile(
    r"^settings\.templateData\.[A-Za-z0-9_.!~*'()%\-]{1,160}$"
)


def is_selection_edit_field_id(value: str) -> bool:
    """Return whether a field id belongs to the frozen workbench registry."""

    return value in SELECTION_EDIT_FIELD_IDS or bool(
        _SELECTION_EDIT_TEMPLATE_FIELD_ID.fullmatch(value)
    )


class _StrictSelectionEditModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SelectionEditTarget(_StrictSelectionEditModel):
    novel_id: UUID
    document_id: UUID | None = None
    entity_type: Literal[
        "document",
        "outline",
        "character",
        "relationship",
        "storyline",
        "foreshadow",
        "setting",
    ]
    entity_id: UUID | None = None
    field_id: str = Field(min_length=1, max_length=200)
    field_label: str = Field(min_length=1, max_length=200)
    persistence: Literal["autosave", "explicit-save"]
    context_revision: int = Field(
        ge=0,
        le=9_007_199_254_740_991,
        strict=True,
    )

    @model_validator(mode="after")
    def validate_field_identity(self) -> "SelectionEditTarget":
        self.field_label = self.field_label.strip()
        if not self.field_label:
            raise ValueError("field_label 不能为空")
        if not is_selection_edit_field_id(self.field_id):
            raise ValueError("field_id 不属于受控选区字段")
        expected_entity = (
            "document"
            if self.field_id.startswith("chapter.")
            else "character"
            if self.field_id.startswith(("character.", "outline.character."))
            else "relationship"
            if self.field_id.startswith("relationship.")
            else "storyline"
            if self.field_id.startswith("storyline.")
            else "foreshadow"
            if self.field_id.startswith("foreshadow.")
            else "setting"
            if self.field_id.startswith("settings.")
            else "outline"
        )
        if self.entity_type != expected_entity:
            raise ValueError("field_id 与 entity_type 不匹配")
        expected_persistence = (
            "autosave" if self.field_id == "chapter.body" else "explicit-save"
        )
        if self.persistence != expected_persistence:
            raise ValueError("field_id 与 persistence 不匹配")
        if self.entity_type == "document":
            if self.document_id is None or self.entity_id != self.document_id:
                raise ValueError("文档字段必须绑定同一 document_id/entity_id")
        elif self.document_id is not None:
            raise ValueError("非文档字段不得携带 document_id")
        return self


class SelectionEditBase(_StrictSelectionEditModel):
    field_value_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    persistence_version_kind: Literal["draft", "entity", "none"]
    persistence_version: int | None = Field(default=None, ge=1, strict=True)
    start_utf16: int = Field(ge=0, le=50_000_000, strict=True)
    end_utf16: int = Field(ge=1, le=50_000_000, strict=True)
    selection_text: str = Field(min_length=1, max_length=12_000)
    selection_text_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    before: str = Field(default="", max_length=1_500)
    after: str = Field(default="", max_length=1_500)

    @model_validator(mode="after")
    def validate_selection_bounds(self) -> "SelectionEditBase":
        self.field_value_sha256 = self.field_value_sha256.lower()
        self.selection_text_sha256 = self.selection_text_sha256.lower()
        if not self.selection_text.strip():
            raise ValueError("selection_text 不能只包含空白")
        if self.end_utf16 <= self.start_utf16:
            raise ValueError("选区 UTF-16 范围无效")
        utf16_length = len(self.selection_text.encode("utf-16-le")) // 2
        if self.end_utf16 - self.start_utf16 != utf16_length:
            raise ValueError("选区 UTF-16 范围与 selection_text 不一致")
        if self.persistence_version_kind == "none":
            if self.persistence_version is not None:
                raise ValueError("none 版本不得携带 persistence_version")
        elif self.persistence_version is None:
            raise ValueError("draft/entity 版本必须携带 persistence_version")
        return self


class SelectionEditInputSnapshot(_StrictSelectionEditModel):
    schema_version: Literal[1]
    selection_id: UUID
    operation: Literal[
        "polish",
        "rewrite",
        "expand",
        "shorten",
        "dialogue",
        "review",
        "custom",
    ]
    custom_instruction: str | None = Field(default=None, max_length=2_000)
    target: SelectionEditTarget
    base: SelectionEditBase

    @model_validator(mode="before")
    @classmethod
    def validate_schema_version_type(cls, value: Any) -> Any:
        if not isinstance(value, dict) or type(value.get("schema_version")) is not int:
            raise ValueError("schema_version 必须是整数 1")
        return value

    @model_validator(mode="after")
    def validate_operation_payload(self) -> "SelectionEditInputSnapshot":
        instruction = (self.custom_instruction or "").strip()
        if self.operation == "custom":
            if not instruction:
                raise ValueError("custom 操作必须提供 custom_instruction")
            self.custom_instruction = instruction
        elif self.custom_instruction is not None:
            raise ValueError("仅 custom 操作可携带 custom_instruction")
        if (
            self.target.persistence == "autosave"
            and self.base.persistence_version_kind != "draft"
        ):
            raise ValueError("autosave 字段必须使用 draft 版本")
        if (
            self.target.persistence == "explicit-save"
            and self.base.persistence_version_kind == "draft"
        ):
            raise ValueError("explicit-save 字段不得使用 draft 版本")
        if self.target.persistence == "explicit-save":
            expected_version_kind = (
                "entity" if self.target.entity_id is not None else "none"
            )
            if self.base.persistence_version_kind != expected_version_kind:
                raise ValueError(
                    "显式保存字段的 entity_id 与 persistence_version_kind 不一致"
                )
        try:
            "".join(
                (
                    self.custom_instruction or "",
                    self.target.field_label,
                    self.base.selection_text,
                    self.base.before,
                    self.base.after,
                )
            ).encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError("选区编辑输入包含非法 Unicode 字符") from error
        return self


class CreateNovelDraftRequest(BaseModel):
    draft_key: str = Field(min_length=1, max_length=120)


class UpdateNovelDraftRequest(BaseModel):
    expected_version: int = Field(ge=1)
    step: int = Field(ge=0, le=6)
    data_patch: dict[str, Any] = Field(default_factory=dict)


class CompleteVersionedRequest(BaseModel):
    expected_version: int = Field(ge=1)


class CreatePrivateAssetRequest(BaseModel):
    asset_type: str = Field(pattern="^(plot|writing_style|vocabulary|idea)$")
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(default="", max_length=30_000)


class UpdatePrivateAssetRequest(BaseModel):
    expected_version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(default="", max_length=30_000)


class CreateAssetPresetRequest(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=4000)
    asset_ids: list[UUID] = Field(default_factory=list, max_length=500)


class UpdateAssetPresetRequest(CreateAssetPresetRequest):
    expected_version: int = Field(ge=1)


class UpdateOutlineDraftRequest(BaseModel):
    expected_version: int = Field(ge=1)
    step: int = Field(ge=1, le=5)
    target_chapter_count: int | None = Field(default=None, ge=10, le=10_000)
    background_text: str | None = Field(default=None, max_length=30_000)
    characters: list[dict[str, Any]] | None = Field(default=None, max_length=200)
    plot_text: str | None = Field(default=None, max_length=50_000)
    highlight_text: str | None = Field(default=None, max_length=200)


class CreateCharacterRequest(BaseModel):
    role_type: str = Field(pattern="^(main|supporting)$")
    name: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=20_000)
    details: dict[str, Any] = Field(default_factory=dict)


class UpdateCharacterRequest(CreateCharacterRequest):
    expected_version: int = Field(ge=1)


class CreateRelationshipRequest(BaseModel):
    source_character_id: UUID
    target_character_id: UUID
    label: str | None = Field(default=None, min_length=1, max_length=80)
    relation_type: str | None = Field(default=None, min_length=1, max_length=80)
    directionality: str = Field(default="undirected", pattern="^(directed|undirected)$")
    relation_kind: str = Field(
        default="other",
        pattern="^(family|colleague|mentor|ally|enemy|romance|other)$",
    )
    description: str = Field(default="", max_length=10_000)


class UpdateRelationshipRequest(BaseModel):
    expected_version: int = Field(ge=1)
    source_character_id: UUID | None = None
    target_character_id: UUID | None = None
    label: str | None = Field(default=None, min_length=1, max_length=80)
    relation_type: str | None = Field(default=None, min_length=1, max_length=80)
    directionality: str | None = Field(default=None, pattern="^(directed|undirected)$")
    relation_kind: str | None = Field(
        default=None,
        pattern="^(family|colleague|mentor|ally|enemy|romance|other)$",
    )
    description: str | None = Field(default=None, max_length=10_000)
    status: str | None = Field(default=None, pattern="^(active|resolved)$")


class RelationshipBatchOperation(BaseModel):
    action: str = Field(pattern="^(create|update|archive|restore)$")
    client_id: str | None = Field(default=None, max_length=120)
    relationship_id: UUID | None = None
    expected_version: int | None = Field(default=None, ge=1)
    source_character_id: UUID | None = None
    target_character_id: UUID | None = None
    label: str | None = Field(default=None, min_length=1, max_length=80)
    relation_type: str | None = Field(default=None, min_length=1, max_length=80)
    directionality: str | None = Field(
        default=None, pattern="^(directed|undirected)$"
    )
    relation_kind: str | None = Field(
        default=None,
        pattern="^(family|colleague|mentor|ally|enemy|romance|other)$",
    )
    description: str | None = Field(default=None, max_length=10_000)
    status: str | None = Field(default=None, pattern="^(active|resolved)$")


class BatchRelationshipsRequest(BaseModel):
    operations: list[RelationshipBatchOperation] = Field(min_length=1, max_length=200)


class SyncRelationshipsRequest(BaseModel):
    force_new: bool = False


class RelationshipGraphPositionRequest(BaseModel):
    character_id: UUID
    x: float = Field(ge=-1_000_000, le=1_000_000)
    y: float = Field(ge=-1_000_000, le=1_000_000)
    pinned: bool = False


class SaveRelationshipGraphViewRequest(BaseModel):
    expected_version: int = Field(ge=0)
    name: str = Field(default="默认视图", min_length=1, max_length=120)
    layout_algorithm: str = Field(default="force_atlas_2", max_length=40)
    random_seed: str = Field(default="relationship-v1", min_length=1, max_length=64)
    zoom: float = Field(gt=0, le=10)
    pan_x: float = Field(ge=-1_000_000, le=1_000_000)
    pan_y: float = Field(ge=-1_000_000, le=1_000_000)
    positions: list[RelationshipGraphPositionRequest] = Field(
        default_factory=list,
        max_length=2000,
    )


class CreateStorylineRequest(BaseModel):
    storyline_type: str = Field(pattern="^(main|support|romance|faction)$")
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=30_000)


class UpdateStorylineRequest(CreateStorylineRequest):
    expected_version: int = Field(ge=1)
    status: str = Field(pattern="^(active|paused|completed|archived)$")
    progress: int = Field(ge=0, le=100)


class CreateForeshadowRequest(BaseModel):
    title: str = Field(min_length=1, max_length=50)
    content: str = Field(default="", max_length=200)
    latest_progress: str = Field(default="", max_length=200)


class UpdateForeshadowRequest(CreateForeshadowRequest):
    expected_version: int = Field(ge=1)
    status: str = Field(pattern="^(planned|active|resolved|dropped)$")
    progress: int = Field(ge=0, le=100)


class CreateChapterDraftRequest(BaseModel):
    draft_key: str = Field(min_length=1, max_length=120)
    volume_id: UUID | None = None


class UpdateChapterDraftRequest(BaseModel):
    expected_version: int = Field(ge=1)
    step: int = Field(ge=1, le=6)
    title: str | None = Field(default=None, max_length=240)
    target_character_count: int | None = Field(default=None, ge=2000, le=5000)
    expectation_text: str | None = Field(default=None, max_length=12_000)
    outline_text: str | None = Field(default=None, max_length=30_000)
    data_patch: dict[str, Any] = Field(default_factory=dict)


class StartCreativeGenerationRequest(BaseModel):
    scope_type: str = Field(min_length=1, max_length=40)
    scope_id: UUID
    kind: str = Field(
        pattern="^(novel_template|novel_naming|novel_cover|outline_background|outline_characters|outline_plot|outline_highlight|chapter_storyline_recommendation|chapter_outline|review|selection_edit)$"
    )
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    novel_id: UUID | None = None
    document_id: UUID | None = None
    target_character_count: int | None = Field(default=None, ge=1, le=50_000)
    force_new: bool = False

    @model_validator(mode="after")
    def validate_selection_edit_request(self) -> "StartCreativeGenerationRequest":
        if self.kind != "selection_edit":
            return self
        snapshot = SelectionEditInputSnapshot.model_validate(self.input_snapshot)
        target = snapshot.target
        if self.novel_id != target.novel_id:
            raise ValueError("selection_edit novel_id 与 target 不匹配")
        if self.document_id != target.document_id:
            raise ValueError("selection_edit document_id 与 target 不匹配")
        if target.entity_type == "document":
            if self.scope_type != "document" or self.scope_id != target.document_id:
                raise ValueError("文档选区任务必须使用 document scope")
        elif self.scope_type != "novel" or self.scope_id != target.novel_id:
            raise ValueError("非文档选区任务必须使用 novel scope")
        if self.target_character_count is not None:
            raise ValueError("selection_edit 不接受 target_character_count")
        self.input_snapshot = snapshot.model_dump(mode="json")
        return self


class UpdateVolumeRequest(BaseModel):
    expected_version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=240)


class UpdateNovelSettingsRequest(BaseModel):
    expected_version: int = Field(ge=1)
    genre: str = Field(default="", max_length=80)
    subgenre: str = Field(default="", max_length=80)
    idea: str = Field(default="", max_length=30_000)
    template_name: str = Field(default="", max_length=160)
    template_data: dict[str, Any] = Field(default_factory=dict)
    cover_image_data: str | None = Field(default=None, max_length=250_000)


class DeleteVolumeRequest(BaseModel):
    expected_version: int = Field(ge=1)
    move_documents_to: UUID | None = None


class ReorderVolumesRequest(BaseModel):
    ordered_volume_ids: list[UUID] = Field(min_length=1, max_length=1000)


class UpdateDocumentMetadataRequest(BaseModel):
    expected_version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=240)


class ReorderChaptersRequest(BaseModel):
    ordered_document_ids: list[UUID] = Field(default_factory=list, max_length=5000)
    volume_by_document: dict[str, UUID | None] = Field(default_factory=dict)


class CreateExportRequest(BaseModel):
    export_format: str = Field(default="markdown", pattern="^(markdown|text)$")
