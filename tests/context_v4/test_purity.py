from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "backend/context_v4"


def test_context_v4_has_no_database_or_network_imports() -> None:
    forbidden_roots = {
        "sqlalchemy",
        "alembic",
        "requests",
        "httpx",
        "urllib",
        "socket",
        "backend.models",
        "backend.services",
    }
    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert not {
            item for item in imported
            if any(item == root or item.startswith(f"{root}.") for root in forbidden_roots)
        }, path


def test_context_v4_source_has_no_persistence_or_network_entrypoints() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in PACKAGE.glob("*.py")
    )
    for forbidden in (
        "Session",
        "create_engine",
        "apiRequest",
        "fetch(",
        ".commit(",
        ".flush(",
        "with_for_update",
    ):
        assert forbidden not in source
