"""Plan 76 V0.8 scoped frontend release with an exact public rollback point."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from scripts import configure_qwenpaw_novel_agent as config  # noqa: E402
from scripts import qwenpaw_lab_plugin as lab  # noqa: E402


EXPECTED_JS = "2fe4278a442e36974a8d1330ac4732b3b6a8d0bb7a77896549eac4f32655298c"
SOURCE_FILES = (
    "frontend/src/characters/character-workspace.ts",
    "frontend/src/characters/character-workspace.test.ts",
    "frontend/src/narration/character-voice-configurator.ts",
    "frontend/src/narration/character-voice-configurator.test.ts",
    "frontend/src/narration/character-voice-panel.ts",
    "frontend/src/narration/character-voice-panel.test.ts",
    "frontend/src/narration/styles/t2-c.ts",
    "frontend/src/narration/styles/t2-d.ts",
    "frontend/src/narration/voice-source-workspace.ts",
    "frontend/src/narration/voice-source-workspace.test.ts",
)
ALLOWED_PACKAGE_DIFF = {"frontend/dist/index.js"}


def run(*args: str, **kwargs) -> bytes:
    return subprocess.run(args, check=True, capture_output=True, timeout=60, **kwargs).stdout


def hashes(root: Path) -> dict[str, str]:
    return {
        str(file.relative_to(root)): hashlib.sha256(file.read_bytes()).hexdigest()
        for file in sorted(root.rglob("*"))
        if file.is_file()
        and "__pycache__" not in file.parts
        and file.suffix != ".pyc"
    }


def save(root: Path, name: str, value: object) -> None:
    with (root / name).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)


def save_observation(root: Path, name: str, value: object) -> None:
    """Preserve every read-only verification instead of overwriting earlier evidence."""
    target = root / name
    sequence = 2
    while target.exists():
        target = root / f"{Path(name).stem}-{sequence}{Path(name).suffix}"
        sequence += 1
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)


def installed_hashes() -> dict[str, str]:
    code = """import hashlib,json,pathlib
p=pathlib.Path('/app/working/plugins/ai-novel-world-2026')
print(json.dumps({str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest()
 for f in p.rglob('*') if f.is_file() and '__pycache__' not in f.parts and f.suffix!='.pyc'}))"""
    return json.loads(run("docker", "exec", lab.CONTAINER, "/app/venv/bin/python", "-c", code))


def container_state() -> dict[str, str]:
    return json.loads(run(
        "docker", "inspect", lab.CONTAINER, "--format",
        '{"id":"{{.Id}}","image":"{{.Image}}","started":"{{.State.StartedAt}}","health":"{{.State.Health.Status}}"}',
    ))


def activity() -> dict[str, object]:
    code = """import json,os
from sqlalchemy import create_engine,text
with create_engine(os.environ['AI_NOVEL_DATABASE_URL']).connect() as c:
 c.execute(text('SET TRANSACTION READ ONLY'))
 out={'schema':c.execute(text('SELECT version_num FROM alembic_version')).scalar()}
 for t in ('chapter_generation_jobs','creative_generation_jobs','background_jobs'):
  out[t]=dict(c.execute(text('SELECT state,count(*) FROM '+t+' GROUP BY state')).all())
 out['running_creative']=[dict(r) for r in c.execute(text("SELECT id,kind,created_at,state FROM creative_generation_jobs WHERE state='running'")).mappings()]
 print(json.dumps(out,default=str))"""
    result = json.loads(run("docker", "exec", lab.CONTAINER, "/app/venv/bin/python", "-c", code))
    active = {"queued", "running", "retry_wait", "cancel_requested", "requested", "pending"}
    started = datetime.fromisoformat(container_state()["started"].replace("Z", "+00:00"))
    old_creative = result["running_creative"]
    if not all(
        row["kind"] == "selection_edit"
        and datetime.fromisoformat(row["created_at"]) < started
        for row in old_creative
    ):
        raise RuntimeError("active creative generation found; stop update")
    for table in ("chapter_generation_jobs", "background_jobs"):
        if any(count for state, count in result[table].items() if state in active):
            raise RuntimeError(f"active jobs in {table}; stop update")
    if any(
        count
        for state, count in result["creative_generation_jobs"].items()
        if state in active and not (state == "running" and count == len(old_creative))
    ):
        raise RuntimeError("active creative generation found; stop update")
    return result


def choices() -> dict[str, object]:
    result: dict[str, object] = {}
    for agent in config.request_json("/api/agents")["agents"]:
        agent_id = agent["id"]
        result[agent_id] = {
            "skills": {
                item["name"]: item["enabled"]
                for item in config.request_json("/api/skills", agent_id=agent_id)
                if item.get("source") == "plugin:ai-novel-world-2026"
            },
            "tools": {
                item["name"]: item["enabled"]
                for item in config.request_json("/api/tools", agent_id=agent_id)
                if item.get("name", "").startswith("novel_")
            },
            "model": config.request_json(
                "/api/models/active?scope=effective&agent_id=" + agent_id
            ).get("active_llm"),
            "prompt_files": config.request_json(
                "/api/workspace/system-prompt-files", agent_id=agent_id
            ),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "install", "verify", "rollback"))
    parser.add_argument("--backup", type=Path, required=True)
    args = parser.parse_args()
    backup = args.backup.resolve(strict=True)
    if backup == ROOT or not backup.name.startswith("plan76-voice-v08-"):
        raise RuntimeError("unexpected backup path")
    candidate = ROOT / "build/ai-novel-world-2026"

    with lab.installation_lock():
        if args.mode == "prepare":
            before = installed_hashes()
            wanted = hashes(candidate)
            changed = {path for path in before.keys() | wanted.keys() if before.get(path) != wanted.get(path)}
            if changed != ALLOWED_PACKAGE_DIFF:
                raise RuntimeError(f"unexpected package diff: {sorted(changed)}")
            if wanted.get("frontend/dist/index.js") != EXPECTED_JS:
                raise RuntimeError("candidate bundle hash changed")
            state = container_state()
            if state["health"] != "healthy":
                raise RuntimeError("QwenPaw container is not healthy")
            save(backup, "activity-before.json", activity())
            save(backup, "container-before.json", state)
            save(backup, "choices-before.json", choices())
            lab.save_preinstall_skill_state(backup / "skills-before.json")
            run("docker", "cp", f"{lab.CONTAINER}:{lab.INSTALLED_PLUGIN_DIR}", str(backup / "plugin-before"))
            if hashes(backup / "plugin-before") != before or installed_hashes() != before:
                raise RuntimeError("plugin backup mismatch")
            save(backup, "manifest.json", {
                "head": run("git", "-C", str(ROOT), "rev-parse", "HEAD").decode().strip(),
                "source": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in SOURCE_FILES},
                "before": before,
                "candidate": wanted,
                "changed": sorted(changed),
            })
            print("BACKUP VERIFIED: exact plugin, configuration and activity; frontend-only candidate")
            return

        manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
        if choices() != json.loads((backup / "choices-before.json").read_text(encoding="utf-8")):
            raise RuntimeError("Agent configuration changed; stop")
        if args.mode == "install":
            if installed_hashes() != manifest["before"]:
                raise RuntimeError("installed plugin changed concurrently")
            activity()
            lab.PLUGIN_DIR = candidate
            save(backup, "install-result.json", lab.hot_install_packaged_plugin(backup / "skills-before.json"))
            print("PUBLIC UPDATE DONE; verify next")
            return
        if args.mode == "verify":
            if installed_hashes() != manifest["candidate"]:
                raise RuntimeError("installed plugin differs from candidate")
            if container_state() != json.loads((backup / "container-before.json").read_text(encoding="utf-8")):
                raise RuntimeError("container restarted or changed")
            health = config.request_json("/api/ai-novel-world-2026/health")
            if health["status"] != "ready" or health["narration_production"]["lifecycle_status"] != "ready":
                raise RuntimeError("product health is not ready")
            save_observation(backup, "health-after.json", health)
            save_observation(backup, "activity-after.json", activity())
            print("VERIFY PASS: exact package, configuration retained, healthy; no restart")
            return

        activity()
        if installed_hashes() != manifest["candidate"]:
            raise RuntimeError("installed plugin is not the recorded candidate")
        lab.PLUGIN_DIR = backup / "plugin-before"
        save(backup, "rollback-result.json", lab.hot_install_packaged_plugin(backup / "skills-before.json"))
        if installed_hashes() != manifest["before"]:
            raise RuntimeError("rollback package mismatch")
        print("OLD PLUGIN RESTORED; database and TTS runtime unchanged")


if __name__ == "__main__":
    main()
