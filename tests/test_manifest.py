import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_manifest() -> dict:
    return json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))


def test_manifest_is_a_version_bounded_pawapp() -> None:
    manifest = load_manifest()

    assert manifest["id"] == "ai-novel-world-2026"
    assert manifest["type"] == "app"
    assert manifest["qwenpaw_version"] == {"min": "2.1.0", "max": "2.2.0"}
    assert manifest["meta"]["pawapp"]["entry_page"] == (
        "/apps/ai-novel-world-2026"
    )


def test_manifest_entries_exist() -> None:
    manifest = load_manifest()

    assert (ROOT / manifest["entry"]["backend"]).is_file()
    assert manifest["entry"]["frontend"] == "frontend/dist/index.js"


def test_runtime_dependencies_are_declared_in_requirements_file() -> None:
    assert load_manifest()["dependencies"] == []
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "SQLAlchemy==2.0.52" in requirements
    assert "psycopg[binary]==3.3.4" in requirements
    assert "pgvector==0.5.0" in requirements


def test_project_tools_are_declared_for_clean_uninstall() -> None:
    manifest = load_manifest()
    assert {tool["name"] for tool in manifest["meta"]["tools"]} == {
        "novel_get_context",
        "novel_get_document",
        "novel_get_workspace_context",
        "novel_prepare_selection_edit",
        "novel_search",
    }
