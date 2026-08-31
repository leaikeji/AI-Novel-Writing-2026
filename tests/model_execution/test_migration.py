from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


ROOT = Path(__file__).resolve().parents[2]


def test_model_execution_evidence_revision_is_on_the_linear_head_chain() -> None:
    scripts = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    heads = scripts.get_heads()
    assert len(heads) == 1
    assert "20260829_0033" in {
        item.revision for item in scripts.iterate_revisions(heads[0], "base")
    }
    revision = scripts.get_revision("20260829_0033")
    assert revision is not None
    assert revision.down_revision == "20260829_0032"
