"""Pydantic contracts for the complete long-form workflow API."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


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
    target_chapter_count: int | None = Field(default=None, ge=1, le=1000)
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
    relation_type: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=10_000)


class UpdateRelationshipRequest(BaseModel):
    expected_version: int = Field(ge=1)
    relation_type: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=10_000)


class CreateStorylineRequest(BaseModel):
    storyline_type: str = Field(pattern="^(main|support|romance|faction)$")
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=30_000)


class UpdateStorylineRequest(CreateStorylineRequest):
    expected_version: int = Field(ge=1)
    status: str = Field(pattern="^(active|paused|completed|archived)$")
    progress: int = Field(ge=0, le=100)


class CreateForeshadowRequest(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(default="", max_length=30_000)


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
    target_character_count: int | None = Field(default=None, ge=3000, le=5000)
    expectation_text: str | None = Field(default=None, max_length=12_000)
    outline_text: str | None = Field(default=None, max_length=30_000)
    data_patch: dict[str, Any] = Field(default_factory=dict)


class StartCreativeGenerationRequest(BaseModel):
    scope_type: str = Field(min_length=1, max_length=40)
    scope_id: UUID
    kind: str = Field(
        pattern="^(novel_naming|novel_cover|outline_background|outline_characters|outline_plot|outline_highlight|chapter_outline|review)$"
    )
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    novel_id: UUID | None = None
    document_id: UUID | None = None
    target_character_count: int | None = Field(default=None, ge=1, le=50_000)
    requested_model_id: str = Field(default="MiniMax-M3", min_length=1, max_length=120)
    force_new: bool = False


class UpdateVolumeRequest(BaseModel):
    expected_version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=240)


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
    volume_by_document: dict[str, UUID] = Field(default_factory=dict)


class CreateExportRequest(BaseModel):
    export_format: str = Field(default="markdown", pattern="^(markdown|text)$")
