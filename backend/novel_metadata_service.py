"""Author-confirmed book identity edits using the existing scope and revision chain."""
from copy import deepcopy
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from .creative_authority.service import get_settings, save_settings
from .novel_lifecycle import lock_active_novel
from .services import get_novel


def update_novel_metadata(
    session: Session, novel_id: UUID, *, expected_version: int,
    title: str, author_name: str,
) -> dict[str, Any]:
    title, author_name = title.strip(), author_name.strip()
    if type(expected_version) is not int or expected_version < 1:
        raise ValueError("作品版本无效")
    if not 1 <= len(title) <= 240 or not 1 <= len(author_name) <= 120:
        raise ValueError("书名需为1—240字符，作者笔名需为1—120字符")
    novel = lock_active_novel(session, novel_id, expected_version)
    if (novel.title, novel.author_name) == (title, author_name):
        result = get_novel(session, novel_id)
        session.commit()
        return result
    before = {"title": novel.title, "author_name": novel.author_name}
    current = get_settings(session, novel_id)
    if current:
        head, revision = current
        settings = deepcopy(revision.settings_json)
        schema_id, schema_version = revision.schema_id, revision.schema_version
        head_version = head.version
    else:
        settings = {key: deepcopy(getattr(novel, key)) for key in (
            "author_name", "writing_type", "audience", "genre", "subgenre",
            "idea", "template_key", "template_name", "template_data",
        )}
        schema_id, schema_version, head_version = "novel-settings/1", 1, 0
    settings["author_name"] = author_name
    novel.title = title
    save_settings(
        session, novel_id, expected_head_version=head_version,
        idempotency_key=f"novel-metadata:{novel_id}:{expected_version}",
        source_kind="manual", schema_id=schema_id, schema_version=schema_version,
        settings=settings,
        change_set={"saved_from": "novel_metadata", "before": before,
                    "after": {"title": title, "author_name": author_name}},
    )
    result = get_novel(session, novel_id)
    session.commit()
    return result
