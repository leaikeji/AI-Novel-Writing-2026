import pytest
from pydantic import ValidationError

from backend.creative_schemas import UpdateNovelSettingsRequest
from backend.creative_services import COVER_MODES


def test_text_cover_is_a_supported_persistent_mode_without_image_data() -> None:
    request = UpdateNovelSettingsRequest(
        expected_version=1,
        cover_mode="text",
        cover_image_data="",
    )

    assert request.cover_mode == "text"
    assert request.cover_image_data == ""
    assert "text" in COVER_MODES


def test_unknown_cover_mode_is_rejected_at_the_api_boundary() -> None:
    with pytest.raises(ValidationError):
        UpdateNovelSettingsRequest(
            expected_version=1,
            cover_mode="remote-image",
        )
