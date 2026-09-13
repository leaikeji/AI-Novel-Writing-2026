"""Plan74: frozen-source hot update, read-only gates, no restart or migration.

Backups and generated receipts live in a caller-created private directory. This
script never restores a database. Rollback is limited to before new writing;
after controlled drafts exist, retain them and decide compatibility first.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile


def run(*args: str, **kwargs) -> bytes:
    return subprocess.run(args, check=True, capture_output=True, timeout=60, **kwargs).stdout


def hashes(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob('*')) if path.is_file()
            and '__pycache__' not in path.parts and path.suffix != '.pyc'}


def save(root: Path, name: str, value: object) -> None:
    with (root / name).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write('\n')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'install', 'verify', 'rollback'))
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--backup', type=Path, required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--before-writing', action='store_true')
    args = parser.parse_args()
    source, backup = args.source.resolve(strict=True), args.backup.resolve(strict=True)
    assert source != backup and len(args.commit) == 40
    assert run('git', '-C', str(source), 'rev-parse', 'HEAD').decode().strip() == args.commit
    assert not run('git', '-C', str(source), 'status', '--porcelain')
    sys.path.insert(0, str(source))
    from scripts import qwenpaw_lab_plugin as lab
    from scripts import configure_qwenpaw_novel_agent as configuration

    assert lab.BASE_URL == 'http://127.0.0.1:18088'
    candidate = source / 'build/ai-novel-world-2026'
    assert candidate.is_dir()

    def installed_hashes() -> dict[str, str]:
        code = """import pathlib,hashlib,json
p=pathlib.Path('/app/working/plugins/ai-novel-world-2026')
print(json.dumps({str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest()
for f in p.rglob('*') if f.is_file() and '__pycache__' not in f.parts and f.suffix!='.pyc'}))"""
        return json.loads(run('docker', 'exec', lab.CONTAINER, '/app/venv/bin/python', '-c', code))

    def container_state() -> dict:
        return json.loads(run('docker', 'inspect', lab.CONTAINER, '--format',
            '{"id":"{{.Id}}","image":"{{.Image}}","started":"{{.State.StartedAt}}","health":"{{.State.Health.Status}}"}'))

    def activity() -> dict:
        # This is the PawApp's dedicated database, not a QwenPaw private table.
        code = """import os,json
from sqlalchemy import create_engine,text
with create_engine(os.environ['AI_NOVEL_DATABASE_URL']).connect() as c:
 c.execute(text('SET TRANSACTION READ ONLY'))
 out={'schema':c.execute(text('SELECT version_num FROM alembic_version')).scalar()}
 for t in ('chapter_generation_jobs','creative_generation_jobs','background_jobs'):
  out[t]=dict(c.execute(text('SELECT state,count(*) FROM '+t+' GROUP BY state')).all())
 out['old_creative']=[dict(r) for r in c.execute(text("SELECT kind,created_at,state FROM creative_generation_jobs WHERE state='running'")).mappings()]
 print(json.dumps(out,default=str))"""
        result = json.loads(run('docker', 'exec', lab.CONTAINER, '/app/venv/bin/python', '-c', code))
        assert result['schema'] == '20260913_0056'
        started = datetime.fromisoformat(container_state()['started'].replace('Z', '+00:00'))
        old = result['old_creative']
        assert all(row['kind'] == 'selection_edit' and datetime.fromisoformat(row['created_at']) < started for row in old)
        active = {'queued', 'running', 'retry_wait', 'cancel_requested', 'requested', 'pending'}
        assert not any(count for table in ('chapter_generation_jobs','creative_generation_jobs','background_jobs')
            for state,count in result[table].items() if state in active
            and not (table == 'creative_generation_jobs' and state == 'running' and count == len(old)))
        return result

    def choices() -> dict:
        agents = configuration.request_json('/api/agents')['agents']
        result = {}
        for agent in agents:
            agent_id = agent['id']
            skills = configuration.request_json('/api/skills', agent_id=agent_id)
            tools = configuration.request_json('/api/tools', agent_id=agent_id)
            model = configuration.request_json('/api/models/active?scope=effective&agent_id=' + agent_id)
            result[agent_id] = {
                'skills': {item['name']: item['enabled'] for item in skills
                           if item.get('source') == 'plugin:ai-novel-world-2026'},
                'tools': {item['name']: item['enabled'] for item in tools
                          if item.get('name', '').startswith('novel_')},
                'model': model.get('active_llm'),
                'system_prompt_files': configuration.request_json('/api/workspace/system-prompt-files', agent_id=agent_id),
            }
        return result

    with lab.installation_lock():
        if args.mode == 'prepare':
            before, wanted = installed_hashes(), hashes(candidate)
            state = container_state()
            assert state['health'] == 'healthy'
            save(backup, 'activity-before.json', activity())
            save(backup, 'container-before.json', state)
            save(backup, 'choices-before.json', choices())
            lab.save_preinstall_skill_state(backup / 'skills-before.json')
            run('docker', 'cp', f'{lab.CONTAINER}:{lab.INSTALLED_PLUGIN_DIR}', str(backup / 'plugin-before'))
            assert hashes(backup / 'plugin-before') == before == installed_hashes()
            dump = run('docker', 'exec', 'ai-novel-2026-postgres', 'sh', '-c',
                       'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"')
            assert dump.startswith(b'PGDMP') and len(dump) > 1000
            with (backup / 'database-before.dump').open('xb') as stream:
                stream.write(dump)
            (backup / 'database-before.dump').chmod(0o600)
            assert b'TABLE DATA' in run('docker', 'exec', '-i', 'ai-novel-2026-postgres',
                                       'pg_restore', '--list', input=dump)
            for name, root in (('candidate.tar.gz', candidate), ('plugin-before.tar.gz', backup / 'plugin-before')):
                with tarfile.open(backup / name, 'x:gz') as archive:
                    for relative in hashes(root):
                        archive.add(root / relative, arcname='ai-novel-world-2026/' + relative)
            manifest = {'commit': args.commit, 'tree': run('git','-C',str(source),'rev-parse','HEAD^{tree}').decode().strip(),
                'source': str(source), 'before': before, 'candidate': wanted,
                'changed': sorted(path for path in set(before) | set(wanted) if before.get(path) != wanted.get(path)),
                'archives': {name: hashlib.sha256((backup / name).read_bytes()).hexdigest()
                             for name in ('database-before.dump','candidate.tar.gz','plugin-before.tar.gz')},
                'database_archive_list_verified': True, 'database_restored': False}
            save(backup, 'manifest.json', manifest)
            print(json.dumps({key: manifest[key] for key in ('commit','tree','changed','archives')}, ensure_ascii=False, indent=2))
        else:
            manifest = json.loads((backup / 'manifest.json').read_text())
            assert manifest['commit'] == args.commit and hashes(candidate) == manifest['candidate']
            if args.mode == 'install':
                assert installed_hashes() == manifest['before'], 'Concurrent source change; stop'
                assert choices() == json.loads((backup / 'choices-before.json').read_text()), 'Configuration drift; stop'
                assert container_state() == json.loads((backup / 'container-before.json').read_text())
                save(backup, 'activity-install.json', activity())
                lab.PLUGIN_DIR = candidate
                save(backup, 'install-result.json', lab.hot_install_packaged_plugin(backup / 'skills-before.json'))
                print('PUBLIC HOT UPDATE DONE; verification required')
            elif args.mode == 'verify':
                assert installed_hashes() == manifest['candidate'], 'Installed source mismatch'
                current = choices()
                save(backup, 'choices-after.json', current)
                assert current == json.loads((backup / 'choices-before.json').read_text()), 'Configuration drift'
                assert container_state() == json.loads((backup / 'container-before.json').read_text()), 'Container changed'
                health = configuration.request_json('/api/ai-novel-world-2026/health')
                assert health['status'] == 'ready' and health['database']['connected']
                assert health['narration_production']['lifecycle_status'] == 'ready'
                save(backup, 'health-after.json', health)
                save(backup, 'model-after.json', configuration.request_json('/api/ai-novel-world-2026/generation-model'))
                save(backup, 'activity-after.json', activity())
                print('VERIFY PASS: exact package, unchanged per-Agent choices/model, healthy, no restart, schema0056')
            else:
                assert args.before_writing, 'After new writing: stop and decide recovery compatibility first'
                assert activity() == json.loads((backup / 'activity-before.json').read_text()), 'Writing activity changed'
                lab.PLUGIN_DIR = backup / 'plugin-before'
                assert hashes(lab.PLUGIN_DIR) == manifest['before']
                save(backup, 'rollback-result.json', lab.hot_install_packaged_plugin(backup / 'skills-before.json'))
                assert installed_hashes() == manifest['before']
                print('PLUGIN ROLLBACK DONE; no database restored; retain browser drafts')


if __name__ == '__main__':
    main()
