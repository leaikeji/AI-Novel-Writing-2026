"""UTF-16 source mapping primitives for narration segmentation.

The browser/editor contract uses UTF-16 code units while Python indexes Unicode
code points.  This module is intentionally small and dependency-free so every
segmentation path performs the same boundary checks before materializing the
frozen T3-A ranges.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from typing import Sequence

from .script_contracts import (
    ScriptContractError,
    Utf16Range,
    utf16_length,
    utf16_slice,
)


class SourceMappingError(ScriptContractError):
    """Raised when a Python or UTF-16 boundary cannot map to source text."""


def _require_index(value: object, *, field_name: str, maximum: int) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise SourceMappingError(
            f"{field_name} must be an integer between 0 and {maximum}"
        )
    return value


@dataclass(frozen=True, slots=True)
class SourceIndexMap:
    """Immutable bidirectional index for one authoritative source string."""

    source_text: str
    _python_to_utf16: tuple[int, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if type(self.source_text) is not str:
            raise SourceMappingError("source_text must be a string")
        # The frozen helper also rejects unpaired surrogates.
        utf16_length(self.source_text)
        offsets = [0]
        units = 0
        for character in self.source_text:
            units += 2 if ord(character) > 0xFFFF else 1
            offsets.append(units)
        object.__setattr__(self, "_python_to_utf16", tuple(offsets))

    @property
    def python_length(self) -> int:
        return len(self.source_text)

    @property
    def utf16_length(self) -> int:
        return self._python_to_utf16[-1]

    def to_utf16_offset(self, python_index: int) -> int:
        index = _require_index(
            python_index,
            field_name="python_index",
            maximum=self.python_length,
        )
        return self._python_to_utf16[index]

    def to_python_index(self, utf16_offset: int) -> int:
        offset = _require_index(
            utf16_offset,
            field_name="utf16_offset",
            maximum=self.utf16_length,
        )
        index = bisect_left(self._python_to_utf16, offset)
        if (
            index >= len(self._python_to_utf16)
            or self._python_to_utf16[index] != offset
        ):
            raise SourceMappingError("utf16_offset splits a surrogate pair")
        return index

    def to_utf16_range(self, python_start: int, python_end_exclusive: int) -> Utf16Range:
        start = _require_index(
            python_start,
            field_name="python_start",
            maximum=self.python_length,
        )
        end = _require_index(
            python_end_exclusive,
            field_name="python_end_exclusive",
            maximum=self.python_length,
        )
        if end <= start:
            raise SourceMappingError("python source range must be non-empty")
        return Utf16Range(
            self._python_to_utf16[start],
            self._python_to_utf16[end],
        )

    def to_python_range(self, source_range: Utf16Range) -> tuple[int, int]:
        if type(source_range) is not Utf16Range:
            raise SourceMappingError("source_range must be Utf16Range")
        return (
            self.to_python_index(source_range.start),
            self.to_python_index(source_range.end_exclusive),
        )

    def slice(self, source_range: Utf16Range) -> str:
        # Call the frozen helper as the final authority as well as the local map.
        self.to_python_range(source_range)
        return utf16_slice(self.source_text, source_range)


def validate_complete_utf16_partition(
    source_text: str,
    ranges: Sequence[Utf16Range],
) -> None:
    """Require ordered half-open ranges to cover the exact source once."""

    index = SourceIndexMap(source_text)
    cursor = 0
    for source_range in ranges:
        if type(source_range) is not Utf16Range:
            raise SourceMappingError("partition members must be Utf16Range values")
        # This also rejects a surrogate-splitting boundary.
        index.to_python_range(source_range)
        if source_range.start != cursor:
            raise SourceMappingError(
                "UTF-16 ranges must completely partition source text"
            )
        cursor = source_range.end_exclusive
    if cursor != index.utf16_length:
        raise SourceMappingError("UTF-16 ranges must completely partition source text")


__all__ = [
    "SourceIndexMap",
    "SourceMappingError",
    "validate_complete_utf16_partition",
]
