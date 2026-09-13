"""Scoped content-addressed release; no Git writes, migrations or database restore."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from scripts import qwenpaw_lab_plugin as lab
from scripts import configure_qwenpaw_novel_agent as config

SOURCE_FILES = (
    "backend/narration/contracts.py",
    "frontend/src/characters/character-workspace.ts",
    "frontend/src/characters/character-workspace.test.ts",
    "frontend/src/narration/character-voice-design-suggestion.ts",
    "frontend/src/narration/character-voice-design-suggestion.test.ts",
    "frontend/src/narration/character-voice-panel.ts",
    "frontend/src/narration/character-voice-panel.test.ts",
    "frontend/src/narration/index.ts",
    "frontend/src/narration/voice-source-panel.ts",
    "frontend/src/narration/voice-source-panel.test.ts",
    "frontend/src/narration/voice-source-workspace.ts",
    "frontend/src/narration/voice-source-workspace.test.ts",
    "tests/narration/test_qwen_tts_provider_contract.py",
    "tests/narration/test_voice_design_language.py",
    "tests/narration/test_character_voice_design_handoff.py",
    "tests/fixtures/character_voice_design_cases.json",
)
EXPECTED_JS = "70f258797e17b512831f2386a796dd2129f0bafacdcb4bcd02b75bfe4a67329b"
ALLOWED_PACKAGE_DIFF = {"backend/narration/contracts.py", "frontend/dist/index.js"}
PLIST = Path.home() / "Library/LaunchAgents/com.ai-novel-world-2026.qwen-tts.plist"


def run(*args: str, **kwargs) -> bytes:
    return subprocess.run(args, check=True, capture_output=True, timeout=60, **kwargs).stdout


def hashes(root: Path) -> dict[str, str]:
    return {str(f.relative_to(root)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(root.rglob("*")) if f.is_file()
            and not any(x in f.parts for x in ("__pycache__", "node_modules", ".git"))
            and f.suffix != ".pyc"}


def save(root: Path, name: str, value: object) -> None:
    with (root / name).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)


def installed_hashes() -> dict[str, str]:
    code = """import pathlib,hashlib,json
p=pathlib.Path('/app/working/plugins/ai-novel-world-2026')
print(json.dumps({str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest()
 for f in p.rglob('*') if f.is_file() and '__pycache__' not in f.parts and f.suffix!='.pyc'}))"""
    return json.loads(run("docker", "exec", lab.CONTAINER, "/app/venv/bin/python", "-c", code))


def container_state() -> dict:
    return json.loads(run("docker", "inspect", lab.CONTAINER, "--format",
        '{"id":"{{.Id}}","image":"{{.Image}}","started":"{{.State.StartedAt}}","health":"{{.State.Health.Status}}"}'))


def activity() -> dict:
    code = """import os,json
from sqlalchemy import create_engine,text
with create_engine(os.environ['AI_NOVEL_DATABASE_URL']).connect() as c:
 c.execute(text('SET TRANSACTION READ ONLY'))
 out={'schema':c.execute(text('SELECT version_num FROM alembic_version')).scalar()}
 for t in ('chapter_generation_jobs','creative_generation_jobs','background_jobs'):
  out[t]=dict(c.execute(text('SELECT state,count(*) FROM '+t+' GROUP BY state')).all())
 out['old_creative']=[dict(r) for r in c.execute(text("SELECT id,kind,created_at,state FROM creative_generation_jobs WHERE state='running'")).mappings()]
 print(json.dumps(out,default=str))"""
    result = json.loads(run("docker", "exec", lab.CONTAINER, "/app/venv/bin/python", "-c", code))
    assert result["schema"] == "20260913_0056"
    active = {"queued", "running", "retry_wait", "cancel_requested", "requested", "pending"}
    old = result["old_creative"]
    started = datetime.fromisoformat(container_state()["started"].replace("Z", "+00:00"))
    assert {row["id"] for row in old} <= {
        "823d775b-282a-4736-9afb-5a0bff05685b", "096def65-095e-44a1-b6f0-da88db41b70a"}
    assert all(row["kind"] == "selection_edit" and datetime.fromisoformat(row["created_at"]) < started for row in old)
    assert not any(count for table in ("chapter_generation_jobs", "creative_generation_jobs", "background_jobs")
                   for state, count in result[table].items() if state in active
                   and not (table == "creative_generation_jobs" and state == "running" and count == len(old))), "Active jobs: stop update"
    return result


def choices() -> dict:
    result = {}
    for agent in config.request_json("/api/agents")["agents"]:
        key = agent["id"]
        result[key] = {
            "skills": {i["name"]: i["enabled"] for i in config.request_json("/api/skills", agent_id=key)
                       if i.get("source") == "plugin:ai-novel-world-2026"},
            "tools": {i["name"]: i["enabled"] for i in config.request_json("/api/tools", agent_id=key)
                      if i.get("name", "").startswith("novel_")},
            "model": config.request_json("/api/models/active?scope=effective&agent_id=" + key).get("active_llm"),
            "prompt_files": config.request_json("/api/workspace/system-prompt-files", agent_id=key),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "prepare", "install", "verify", "rollback"))
    parser.add_argument("--backup", type=Path, required=True)
    args = parser.parse_args()
    backup = args.backup.resolve(strict=True)
    assert backup != ROOT and backup.name.startswith("plan76-voice-v07-")
    source = backup / "source"
    candidate = source / "build/ai-novel-world-2026"
    if args.mode == "freeze":
        archive = run("git", "-C", str(ROOT), "archive", "HEAD")
        (backup / "source-head.tar").write_bytes(archive)
        source.mkdir()
        run("tar", "-x", "-C", str(source), input=archive)
        before = {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in SOURCE_FILES}
        for relative in SOURCE_FILES:
            target = source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)
        assert before == {f: hashlib.sha256((source / f).read_bytes()).hexdigest() for f in SOURCE_FILES}
        (source / "node_modules").symlink_to(ROOT / "node_modules", target_is_directory=True)
        run("/Users/liujia/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node",
            str(ROOT / "node_modules/vite/bin/vite.js"), "build", cwd=source)
        run(sys.executable, str(source / "scripts/package_plugin.py"), cwd=source)
        assert hashes(candidate)["frontend/dist/index.js"] == EXPECTED_JS
        assert hashes(candidate)["backend/narration/contracts.py"] == before["backend/narration/contracts.py"]
        save(backup, "source.json", {"head": run("git", "rev-parse", "HEAD", cwd=ROOT).decode().strip(),
            "archive_sha256": hashlib.sha256(archive).hexdigest(), "overlay": before,
            "source": hashes(source), "candidate": hashes(candidate)})
        print("FROZEN: tracked HEAD archive + explicit 16-file overlay; no Git writes")
        return

    frozen = json.loads((backup / "source.json").read_text())
    assert hashes(source) == frozen["source"], "Frozen source changed; stop"
    assert hashes(candidate) == frozen["candidate"]
    with lab.installation_lock():
        if args.mode == "prepare":
            before, wanted = installed_hashes(), hashes(candidate)
            changed = {p for p in before.keys() | wanted.keys() if before.get(p) != wanted.get(p)}
            assert changed == ALLOWED_PACKAGE_DIFF, changed
            assert container_state()["health"] == "healthy"
            save(backup, "activity-before.json", activity())
            save(backup, "container-before.json", container_state())
            save(backup, "choices-before.json", choices())
            lab.save_preinstall_skill_state(backup / "skills-before.json")
            run("docker", "cp", f"{lab.CONTAINER}:{lab.INSTALLED_PLUGIN_DIR}", str(backup / "plugin-before"))
            assert hashes(backup / "plugin-before") == before == installed_hashes()
            dump = run("docker", "exec", "ai-novel-2026-postgres", "sh", "-c",
                       'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"')
            assert dump.startswith(b"PGDMP") and len(dump) > 1000
            assert b"TABLE DATA" in run("docker", "exec", "-i", "ai-novel-2026-postgres", "pg_restore", "--list", input=dump)
            (backup / "database-before.dump").write_bytes(dump)
            (backup / "database-before.dump").chmod(0o600)
            shutil.copy2(PLIST, backup / "runtime-before.plist")
            runtime = plistlib.loads(PLIST.read_bytes())
            assert runtime["WorkingDirectory"] == str(ROOT)
            assert runtime["EnvironmentVariables"]["PYTHONPATH"] == str(ROOT)
            old_source = backup / "runtime-before-source"
            old_source.mkdir()
            run("tar", "-x", "-C", str(old_source), input=(backup / "source-head.tar").read_bytes())
            assert hashes(old_source / "tts_runtime") == hashes(ROOT / "tts_runtime")
            assert hashes(backup / "plugin-before")["backend/narration/contracts.py"] == hashes(old_source)["backend/narration/contracts.py"]
            save(backup, "manifest.json", {"before": before, "candidate": wanted, "changed": sorted(changed),
                "dump_sha256": hashlib.sha256(dump).hexdigest(), "database_restored": False,
                "runtime_before": {k: runtime[k] for k in ("ProgramArguments", "WorkingDirectory")}})
            print("BACKUP VERIFIED: database, plugin, choices, native config and old source")
            return
        manifest = json.loads((backup / "manifest.json").read_text())
        assert choices() == json.loads((backup / "choices-before.json").read_text()), "Agent choice drift"
        assert container_state() == json.loads((backup / "container-before.json").read_text()), "Container drift"
        if args.mode == "install":
            assert installed_hashes() == manifest["before"], "Concurrent update"
            save(backup, "activity-install.json", activity())
            lab.PLUGIN_DIR = candidate
            save(backup, "install-result.json", lab.hot_install_packaged_plugin(backup / "skills-before.json"))
            print("PUBLIC UPDATE DONE; verify next")
        elif args.mode == "verify":
            assert installed_hashes() == manifest["candidate"]
            health = config.request_json("/api/ai-novel-world-2026/health")
            assert health["status"] == "ready" and health["narration_production"]["lifecycle_status"] == "ready"
            save(backup, "health-after.json", health)
            save(backup, "activity-after.json", activity())
            print("VERIFY PASS: exact package, configuration retained, healthy; no Docker restart")
        else:
            assert activity() == json.loads((backup / "activity-before.json").read_text()), "Activity changed; review rollback first"
            assert installed_hashes() == manifest["candidate"]
            lab.PLUGIN_DIR = backup / "plugin-before"
            save(backup, "rollback-result.json", lab.hot_install_packaged_plugin(backup / "skills-before.json"))
            assert installed_hashes() == manifest["before"]
            print("OLD PLUGIN RESTORED; no database restoration")


if __name__ == "__main__":
    main()
