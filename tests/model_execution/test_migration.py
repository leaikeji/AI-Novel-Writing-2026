from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


ROOT = Path(__file__).resolve().parents[2]


def test_model_execution_evidence_revision_is_the_linear_head() -> None:
    scripts = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert scripts.get_heads() == ["20260829_0033"]
    revision = scripts.get_revision("20260829_0033")
    assert revision is not None
    assert revision.down_revision == "20260829_0032"
