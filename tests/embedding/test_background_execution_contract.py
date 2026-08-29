from pathlib import Path

from backend.narration.scheduler import SchedulerConfig


def test_embedding_scheduler_contract_is_explicit() -> None:
    config = SchedulerConfig(
        lease_owner="embedding-worker:test",
        executor_key="embedding-worker",
        resource_classes=("dashscope-embedding",),
        job_kinds=("embedding.index_batch",),
    )
    config.validate()


def test_semantic_migration_registers_executor_and_all_kinds_fail_closed() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (
        root
        / "backend/migrations/versions/20260829_0028_semantic_index_schema.py"
    ).read_text(encoding="utf-8")
    assert "'embedding.index_batch','dashscope-embedding','embedding-worker'" in source
    upgraded = source.split("def downgrade() -> None:", 1)[0]
    assert "IF NOT EXISTS (" in upgraded
    assert "NEW.job_kind LIKE 'narration.%'" not in upgraded
