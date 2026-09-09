"""Stable speaker-coordinate digest used by narration continuation fences."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from .services import canonical_sha256


@dataclass(frozen=True, slots=True)
class FrozenSpeakerSegment:
    ordinal: int
    segment_kind: str
    source_start_utf16: int | None
    source_end_utf16: int | None
    speaker_kind: str
    character_id: UUID | None = None
    anonymous_speaker_id: UUID | None = None

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("speaker ordinal must be non-negative")
        if not self.segment_kind or self.speaker_kind not in {
            "narrator",
            "character",
            "anonymous",
            "group",
            "unknown",
        }:
            raise ValueError("speaker segment identity is unsupported")
        if (self.source_start_utf16 is None) != (self.source_end_utf16 is None):
            raise ValueError("speaker source range must be complete or absent")
        if self.source_start_utf16 is not None and (
            type(self.source_start_utf16) is not int
            or type(self.source_end_utf16) is not int
            or self.source_start_utf16 < 0
            or self.source_end_utf16 <= self.source_start_utf16
        ):
            raise ValueError("speaker source range is invalid")
        if self.speaker_kind == "character":
            if self.character_id is None or self.anonymous_speaker_id is not None:
                raise ValueError("character speaker requires only character_id")
        elif self.speaker_kind == "anonymous":
            if self.anonymous_speaker_id is None or self.character_id is not None:
                raise ValueError("anonymous speaker requires only anonymous_speaker_id")
        elif self.character_id is not None or self.anonymous_speaker_id is not None:
            raise ValueError("non-character speaker cannot carry a target identity")


def speaker_summary_digest(segments: tuple[FrozenSpeakerSegment, ...]) -> str:
    if type(segments) is not tuple:
        raise TypeError("speaker segments must be a tuple")
    if tuple(item.ordinal for item in segments) != tuple(range(len(segments))):
        raise ValueError("speaker segment ordinals must be contiguous from zero")
    return canonical_sha256(
        {
            "schema_version": "narration-voice-preparation-speakers/1",
            "segments": [
                {
                    "ordinal": item.ordinal,
                    "segment_kind": item.segment_kind,
                    "source_start_utf16": item.source_start_utf16,
                    "source_end_utf16": item.source_end_utf16,
                    "speaker_kind": item.speaker_kind,
                    "character_id": (
                        str(item.character_id) if item.character_id is not None else None
                    ),
                    "anonymous_speaker_id": (
                        str(item.anonymous_speaker_id)
                        if item.anonymous_speaker_id is not None
                        else None
                    ),
                }
                for item in segments
            ],
        }
    )
