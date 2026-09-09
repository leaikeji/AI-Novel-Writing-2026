from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "backend/migrations/versions/20260909_0048_failed_retry_review_guard.py"


def test_failed_retry_review_guard_migration_is_narrow_and_fail_closed() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    for expected in (
        'revision = "20260909_0048"',
        'down_revision = "20260909_0047"',
        "narration_require_review_action()",
        "IF OLD.state IS DISTINCT FROM ''queued'' AND NEW.state=''queued'' THEN",
        "IF OLD.state IN (''analyzed'',''review_required'') AND NEW.state=''queued'' THEN",
        "pg_get_functiondef",
        "position(old_fragment IN function_definition)=0",
        "EXECUTE replace(function_definition, old_fragment, new_fragment)",
    ):
        assert expected in source
    for forbidden in ("DELETE FROM", "UPDATE narration_", "DROP FUNCTION", "ALTER TABLE"):
        assert forbidden not in source
