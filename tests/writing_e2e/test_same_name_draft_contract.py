from __future__ import annotations

from uuid import uuid4

import pytest

from backend.creative_services import (
    ValidationError,
    _validate_outline_character_draft_identities,
)


def test_outline_draft_uniqueness_uses_stable_keys_not_names() -> None:
    _validate_outline_character_draft_identities(
        [
            {"draft_key": "same-name-a", "name": "阿澄"},
            {"draft_key": "same-name-b", "name": "阿澄"},
        ]
    )


def test_outline_draft_rejects_duplicate_stable_identity() -> None:
    with pytest.raises(ValidationError, match="draft_key"):
        _validate_outline_character_draft_identities(
            [
                {"draft_key": "same-key", "name": "甲"},
                {"draft_key": "same-key", "name": "乙"},
            ]
        )

    character_id = uuid4()
    with pytest.raises(ValidationError, match="character_id"):
        _validate_outline_character_draft_identities(
            [
                {
                    "draft_key": "linked-a",
                    "name": "甲",
                    "character_id": character_id,
                },
                {
                    "draft_key": "linked-b",
                    "name": "乙",
                    "character_id": character_id,
                },
            ]
        )
