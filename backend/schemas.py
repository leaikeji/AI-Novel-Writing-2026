"""Pydantic request schemas for the PawApp API."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class CreateNovelRequest(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=4000)


class CreateVolumeRequest(BaseModel):
    title: str = Field(min_length=1, max_length=240)


class CreateDocumentRequest(BaseModel):
    title: str = Field(min_length=1, max_length=240)
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
