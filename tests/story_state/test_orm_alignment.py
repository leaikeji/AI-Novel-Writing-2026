from backend.creative_data_models import (
    CharacterInstance,
    StoryEventLink,
    StoryTimeline,
    StoryTimelineLink,
)
from backend.models import StoryFact
from backend.story_state import (
    CharacterInstanceRecord,
    StoryEventLinkRecord,
    StoryFactV2,
    StoryTimelineLinkRecord,
    StoryTimelineRecord,
)


def test_pure_records_align_with_frozen_orm_columns() -> None:
    pairs = (
        (StoryTimelineRecord, StoryTimeline),
        (StoryTimelineLinkRecord, StoryTimelineLink),
        (CharacterInstanceRecord, CharacterInstance),
        (StoryFactV2, StoryFact),
        (StoryEventLinkRecord, StoryEventLink),
    )

    for record_type, orm_type in pairs:
        assert set(record_type.model_fields).issubset(orm_type.__table__.columns.keys())
