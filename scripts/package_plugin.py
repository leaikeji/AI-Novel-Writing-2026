"""Create the minimal QwenPaw plugin directory under build/."""

from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "build" / "ai-novel-world-2026"
PLUGIN_COPY_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")


def copy_file(relative_path: str) -> None:
    source = ROOT / relative_path
    target = OUTPUT / relative_path
    if not source.is_file():
        raise FileNotFoundError(f"Required plugin file is missing: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def copy_tree(relative_path: str) -> None:
    source = ROOT / relative_path
    target = OUTPUT / relative_path
    if not source.is_dir():
        raise FileNotFoundError(f"Required plugin directory is missing: {source}")
    shutil.copytree(source, target, ignore=PLUGIN_COPY_IGNORE)


def main() -> None:
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir(parents=True)

    copy_file("plugin.json")
    copy_file("plugin.py")
    copy_file("requirements.txt")
    copy_file("alembic.ini")
    copy_tree("backend")
    copy_tree("skills")
    copy_tree("frontend/dist")

    print(OUTPUT)


if __name__ == "__main__":
    main()
