from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.models import DocumentWorkingCopy
from backend.services import visible_character_count


ROOT = Path(__file__).resolve().parents[2]
REVISION = "20260902_0039"
DOWN_REVISION = "20260902_0038"
MIGRATION = (
    ROOT
    / "backend/migrations/versions/20260902_0039_working_copy_visible_count.py"
)


def _scripts() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))


def test_visible_character_count_revision_is_the_only_linear_head() -> None:
    scripts = _scripts()
    assert scripts.get_heads() == [REVISION]
    assert scripts.get_revision(REVISION).down_revision == DOWN_REVISION


def test_working_copy_model_exposes_non_nullable_count() -> None:
    column = DocumentWorkingCopy.__table__.c.visible_character_count
    assert column.nullable is False
    assert column.server_default is not None


def test_migration_backfill_matches_runtime_visible_count() -> None:
    module = _scripts().get_revision(REVISION).module
    samples = (
        "",
        "# 标题\n\n正文 123",
        "链接：[名称](https://example.invalid) ![替代文字](x.png)",
        "```python\nignored = True\n```\n保留内容",
        "**粗体**、`代码`、~~删除线~~",
    )
    for markdown in samples:
        assert module._visible_character_count(markdown) == visible_character_count(markdown)


def test_migration_is_bounded_and_reversible() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    for marker in (
        'revision = "20260902_0039"',
        'down_revision = "20260902_0038"',
        "BACKFILL_BATCH_SIZE = 500",
        "document_id > CAST(:last_document_id AS uuid)",
        "LIMIT :batch_size",
        'op.drop_column("document_working_copies", "visible_character_count")',
        "visible_character_count >= 0",
    ):
        assert marker in source
    for forbidden in ("from backend.services", "create_engine", "requests.", "subprocess"):
        assert forbidden not in source
