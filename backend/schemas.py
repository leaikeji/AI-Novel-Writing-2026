"""Pydantic request schemas for the PawApp API."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateNovelRequest(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=4000)


class CreateVolumeRequest(BaseModel):
    title: str = Field(default="", max_length=240)


class CreateDocumentRequest(BaseModel):
    title: str = Field(default="", max_length=240)
    kind: str = Field(default="chapter", pattern="^(chapter|outline|setting)$")
    volume_id: UUID | None = None


class SaveDraftRequest(BaseModel):
    expected_draft_version: int = Field(ge=1)
    content_markdown: str = Field(max_length=2_000_000)
    content_hash: str | None = Field(default=None, min_length=64, max_length=64)


class CheckpointRequest(BaseModel):
    expected_draft_version: int = Field(ge=1)


class RestoreRevisionRequest(BaseModel):
    expected_draft_version: int = Field(ge=1)
    expected_fact_plan_hash: str | None = Field(default=None, min_length=64, max_length=64)


class SaveChapterBriefRequest(BaseModel):
    expected_version: int = Field(ge=0)
    target_word_count: int = Field(ge=200, le=20_000)
    expectation_text: str = Field(default="", max_length=12_000)
    outline_text: str = Field(default="", max_length=30_000)
    forbidden_text: str = Field(default="", max_length=8_000)
    role_constraints: dict[str, list[str]] = Field(default_factory=dict)


class GenerateChapterRequest(BaseModel):
    expected_brief_version: int = Field(ge=1)
    force_new: bool = False
    asset_ids: list[UUID] = Field(default_factory=list, max_length=500)
    preset_id: UUID | None = None


class AdoptCandidateRequest(BaseModel):
    expected_draft_version: int = Field(ge=1)


class ExtractIntelligenceRequest(BaseModel):
    revision_id: UUID


class ReviewIntelligenceItemRequest(BaseModel):
    review_state: str = Field(pattern="^(pending|rejected)$")


class CommitIntelligenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted_item_ids: list[UUID] = Field(min_length=1, max_length=200)
    expected_story_ledger_version: int | None = Field(default=None, ge=1)
    operation_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
