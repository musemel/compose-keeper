#!/usr/bin/env python3
"""Create and run a small, real Compose project plus a local Keeper UI."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys

def prepare(repo, runtime, engine='podman', port=18090):
    project = runtime / 'web'
    for name in ('site', 'config'):
        (project / 'data' / name).mkdir(parents=True, exist_ok=True)
    for source, target in [('compose.yaml', project / 'compose.yaml'),
                           ('index.html', project / 'data/site/index.html'),
                           ('default.conf', project / 'data/config/default.conf')]:
        if not target.exists():
            shutil.copyfile(Path(__file__).parent / source, target)
            target.chmod(0o644)
    config = {'listen': '127.0.0.1', 'port': port, 'schedule': '23:59', 'timezone': 'Asia/Tokyo',
              'state_dir': str(runtime / 'state'), 'engine_command': [engine],
              'compose_command': [engine, 'compose'], 'projects': [{
                  'id': 'quickstart-web', 'name': 'Quickstart Web (2 data paths)',
                  'project_name': 'keeper-quickstart', 'directory': str(project),
                  'data_paths': [str(project / 'data/site'), str(project / 'data/config')],
                  'backup_path': str(runtime / 'backups/web'), 'health_timeout': 90,
                  'health_interval': 2, 'healthy_samples': 2,
                  'web': {'enabled': True, 'url': 'http://127.0.0.1:18091/', 'status_codes': [200]}}]}
    config_path = runtime / 'keeper.json'
    config_path.write_text(json.dumps(config, indent=2), encoding='utf-8')
    return project, config_path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare-only', action='store_true', help='Start the sample stack without starting another management UI')
    parser.add_argument('--engine', choices=['podman', 'docker'], default='podman')
    parser.add_argument('--port', type=int, default=18090)
    parser.add_argument('--runtime', type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    runtime = (args.runtime or repo / 'runtime/quickstart').resolve()
    project, config = prepare(repo, runtime, args.engine, args.port)
    subprocess.run([args.engine, 'compose', '--project-name', 'keeper-quickstart', 'up', '-d'], cwd=project, check=True)
    print('Demo web: http://localhost:18091/ (also port 18092)', flush=True)
    print('Configuration: ' + str(config), flush=True)
    if args.prepare_only:
        return
    env = os.environ.copy()
    if not env.get('KEEPER_ACCESS_KEY'):
        keyfile = runtime / 'access-key'
        if not keyfile.exists():
            keyfile.write_text(secrets.token_urlsafe(24), encoding='utf-8')
            keyfile.chmod(0o600)
        env['KEEPER_ACCESS_KEY'] = keyfile.read_text(encoding='utf-8').strip()
        print('Login key file: ' + str(keyfile), flush=True)
    print(f'Keeper UI: http://localhost:{args.port}/', flush=True)
    subprocess.run([sys.executable, str(repo / 'keeper.py'), '--config', str(config)], cwd=repo, env=env, check=True)

if __name__ == '__main__':
    main()
