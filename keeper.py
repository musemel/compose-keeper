#!/usr/bin/env python3
"""Small, sequential Compose updater. Python 3.11+; PyYAML for YAML providers."""
import argparse
import hmac
import http.cookies
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import threading
import time
import traceback
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo


def stamp():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class Keeper:
    def __init__(self, config_path):
        self.config_path = Path(config_path).resolve()
        self.config = json.loads(self.config_path.read_text(encoding='utf-8'))
        self.root = Path(self.config.get('state_dir', './state')).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.state_lock = threading.RLock()
        self.stop_event = threading.Event()
        self.children_lock = threading.Lock()
        self.children = set()
        self.projects = self.config['projects']
        self.validate()
        saved_settings = self.read(self.root / 'settings.json', {})
        if saved_settings:
            self.validate_schedule(saved_settings['schedule'], saved_settings['timezone'])
            self.config.update(saved_settings)
        self.state = self.read(self.root / 'state.json', {})
        self.secret = os.environ.get('KEEPER_ACCESS_KEY', '')
        if len(self.secret) < 16:
            raise ValueError('KEEPER_ACCESS_KEY must contain at least 16 characters')
        self.sessions = {}
        self.inventory = {}
        self.login_attempts = {}
        self.auth_lock = threading.Lock()

    @staticmethod
    def read(path, default):
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default

    @staticmethod
    def validate_schedule(schedule, timezone):
        if not isinstance(schedule, str) or datetime.strptime(schedule, '%H:%M').strftime('%H:%M') != schedule:
            raise ValueError('Schedule must be HH:MM')
        if not isinstance(timezone, str):
            raise ValueError('Invalid timezone')
        try:
            ZoneInfo(timezone)
        except (KeyError, ValueError) as exc:
            raise ValueError('Invalid timezone') from exc

    def set_schedule(self, schedule, timezone):
        self.validate_schedule(schedule, timezone)
        with self.state_lock:
            now = datetime.now(ZoneInfo(timezone))
            settings = {'schedule': schedule, 'timezone': timezone}
            write_json(self.root / 'settings.json', settings)
            # Editing a past time schedules tomorrow, without an immediate update.
            write_json(self.root / 'schedule.json', {'date': now.strftime('%Y-%m-%d') if now.strftime('%H:%M') >= schedule else None})
            self.config.update(settings)

    def validate(self):
        def argv(value):
            return isinstance(value, list) and bool(value) and all(isinstance(x, str) and x for x in value)
        for key in ('engine_command', 'compose_command'):
            if key in self.config and not argv(self.config[key]):
                raise ValueError(key + ' must be a command argument array')
        ids, all_data, all_backups = set(), [], []
        for p in self.projects:
            pid = p['id']
            if not pid or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in pid) or pid in ids:
                raise ValueError('Project IDs must be unique letters, digits, - or _')
            ids.add(pid)
            directory = Path(p['directory']).resolve()
            if not directory.is_dir():
                raise ValueError(f'{pid}: compose directory does not exist')
            p['directory'] = str(directory)
            backup = Path(p['backup_path']).resolve()
            if backup == backup.parent:
                raise ValueError('Backup path cannot be filesystem root')
            p['backup_path'] = str(backup)
            all_backups.append(backup)
            paths = [Path(x).resolve() for x in p.get('data_paths', [])]
            for path in paths:
                if path == path.parent or path == directory or path in directory.parents:
                    raise ValueError(f'{pid}: unsafe data path {path}')
                if path == self.root or path in self.root.parents or self.root in path.parents:
                    raise ValueError('State and data paths must not overlap')
            for i, path in enumerate(paths):
                if any(path == other or path in other.parents or other in path.parents for other in paths[:i]):
                    raise ValueError('Data paths must not overlap')
            p['data_paths'] = [str(x) for x in paths]
            all_data.extend(paths)
            for key in ('engine_command', 'compose_command'):
                if key in p and not argv(p[key]):
                    raise ValueError(key + ' must be a command argument array')
            for key in ('health_timeout', 'health_interval', 'healthy_samples', 'command_timeout'):
                if key in p and (not isinstance(p[key], (int, float)) or p[key] <= 0):
                    raise ValueError(key + ' must be positive')
            for name, command in p.get('scripts', {}).items():
                if name not in ('stop', 'backup', 'start', 'restore') or not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
                    raise ValueError('Scripts must be argv arrays: stop/backup/start/restore')
            if ('backup' in p.get('scripts', {})) != ('restore' in p.get('scripts', {})):
                raise ValueError('Custom backup and restore must be configured together')
            if p.get('web', {}).get('enabled') and not p['web'].get('url', '').startswith(('http://', 'https://')):
                raise ValueError('Web check requires an http(s) URL')
        for i, backup in enumerate(all_backups):
            for other in all_data + all_backups[:i] + [self.root] + [Path(p['directory']) for p in self.projects]:
                if backup == other or backup in other.parents or other in backup.parents:
                    raise ValueError(f'Backup path overlaps another managed path: {backup}')
            for transient in [backup.with_name(backup.name + '.staging'), backup.with_name(backup.name + '.previous')]:
                for other in all_data + all_backups + [self.root]:
                    if transient == other or transient in other.parents or other in transient.parents:
                        raise ValueError('Backup staging paths overlap managed paths')
        for i, path in enumerate(all_data):
            if any(path == other or path in other.parents or other in path.parents for other in all_data[:i]):
                raise ValueError('Projects cannot share managed data paths')
        ZoneInfo(self.config.get('timezone', 'Asia/Tokyo'))
        schedule = self.config.get('schedule', '04:00')
        if datetime.strptime(schedule, '%H:%M').strftime('%H:%M') != schedule:
            raise ValueError('schedule must be zero-padded HH:MM')

    def update(self, p, **fields):
        with self.state_lock:
            self.state.setdefault(p['id'], {}).update(fields)
            write_json(self.root / 'state.json', self.state)

    def log(self, p, message):
        line = f'{stamp()} {message}\n'
        with self.state_lock:
            path = self.root / (p['id'] + '.log')
            # Bound logs; last_error is persisted independently.
            if path.exists() and path.stat().st_size > 2_000_000:
                data = path.read_bytes()[-1_000_000:]
                path.write_bytes(data[data.find(b'\n') + 1:])
            with path.open('a', encoding='utf-8') as f:
                f.write(line)
        print(f'[{p["id"]}] {message}', flush=True)

    def run(self, p, argv, env=None, timeout=None, log_output=True, return_stderr=False):
        if self.stop_event.is_set():
            raise RuntimeError('Management service is shutting down')
        timeout = timeout or p.get('command_timeout', 900)
        self.log(p, 'Run: ' + repr(argv))
        with self.children_lock:
            if self.stop_event.is_set():
                raise RuntimeError('Management service is shutting down')
            child = subprocess.Popen(argv, cwd=p['directory'], env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     start_new_session=(os.name != 'nt'))
            self.children.add(child)
        try:
            output, errors = child.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name != 'nt':
                os.killpg(child.pid, signal.SIGKILL)
            else:
                child.kill()
            output, errors = child.communicate()
            self.log(p, (output + errors).decode(errors='replace')[-20000:])
            raise RuntimeError(f'Command timed out after {timeout}s: {argv[0]}')
        finally:
            with self.children_lock:
                self.children.discard(child)
        result = output.decode(errors='replace')
        diagnostics = errors.decode(errors='replace')
        if result.strip() and log_output:
            self.log(p, result[-20000:])
        if diagnostics.strip():
            self.log(p, diagnostics[-20000:])
        if child.returncode:
            raise RuntimeError(f'Command failed ({child.returncode}): {argv[0]}\n{(result + diagnostics)[-12000:]}')
        return result + diagnostics if return_stderr else result

    def shutdown(self):
        self.stop_event.set()
        with self.children_lock:
            for child in self.children:
                if child.poll() is None:
                    try:
                        if os.name == 'posix':
                            os.killpg(child.pid, signal.SIGKILL)
                        else:
                            child.kill()
                    except ProcessLookupError:
                        pass

    def compose(self, p, args, override=None):
        argv = list(p.get('compose_command', self.config.get('compose_command', ['podman', 'compose'])))
        # Explicit project name remains stable when an override in another folder is added.
        argv += ['--project-name', p.get('project_name', p['id'])]
        for file in p.get('compose_files', ['compose.yaml']):
            argv += ['-f', str(Path(p['directory']) / file)]
        if override:
            argv += ['-f', str(override)]
        return self.run(p, argv + args, log_output=args[0] != 'config', return_stderr=args[0] == 'logs')

    def engine(self, p, args):
        return self.run(p, list(p.get('engine_command', self.config.get('engine_command', ['podman']))) + args, log_output=args[0] != 'inspect')

    def containers(self, p, service=None):
        args = ['ps', '-a', '-q', '--filter', 'label=com.docker.compose.project=' + p.get('project_name', p['id'])]
        if service:
            args += ['--filter', 'label=com.docker.compose.service=' + service]
        return self.engine(p, args).split()

    @staticmethod
    def parse_compose(raw):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            import yaml
            return yaml.safe_load(raw)

    def journal_path(self, p):
        return self.root / (p['id'] + '.transaction.json')

    def override(self, p, images):
        path = self.root / (p['id'] + '.images.json')
        write_json(path, {'services': {name: {'image': image, 'pull_policy': 'never'} for name, image in images.items()}})
        return path

    def script(self, p, action, tx, default):
        command = p.get('scripts', {}).get(action)
        self.update(p, status=action)
        if command:
            env = os.environ.copy()
            env.update(KEEPER_PROJECT=p['id'], KEEPER_COMPOSE_DIR=p['directory'],
                       KEEPER_BACKUP_DIR=p['backup_path'],
                       KEEPER_DATA_PATHS=json.dumps(p.get('data_paths', [])),
                       KEEPER_IMAGE_OVERRIDE=str(self.root / (p['id'] + '.images.json')),
                       KEEPER_TRANSACTION=str(tx.get('_journal', self.journal_path(p))),
                       KEEPER_CONFIG=str(self.config_path),
                       KEEPER_ROLLBACK='1' if tx.get('phase') == 'rollback' else '0')
            self.run(p, command, env=env)
        else:
            default()

    def backup(self, p):
        target = Path(p['backup_path'])
        staging = target.with_name(target.name + '.staging')
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        manifest = []
        for i, raw in enumerate(p.get('data_paths', [])):
            source = Path(raw)
            if not source.exists() or source.is_symlink():
                raise RuntimeError(f'Data path missing or top-level symlink: {source}')
            dest = staging / str(i)
            self.copy_data(source, dest, p)
            manifest.append({'source': raw, 'slot': str(i), 'directory': source.is_dir()})
        write_json(staging / 'manifest.json', manifest)
        # Never remove the last complete backup before the new copy finishes.
        retired = target.with_name(target.name + '.previous')
        if retired.exists():
            shutil.rmtree(retired)
        if target.exists():
            target.rename(retired)
        staging.rename(target)
        if retired.exists():
            shutil.rmtree(retired)

    def copy_data(self, source, dest, p, restore=False):
        if os.name == 'posix':
            # Fail the transaction on any rsync metadata-preservation error.
            # -a: mode/owner/group/times/symlinks/devices; -H: hardlinks;
            # -A/-X: ACLs and xattrs; numeric IDs avoid name-based remapping.
            if source.is_dir():
                dest.mkdir(exist_ok=restore)
                source_arg, dest_arg = str(source) + '/', str(dest) + '/'
            else:
                source_arg, dest_arg = str(source), str(dest)
            flags = ['rsync', '-aHAXS', '--numeric-ids']
            if restore:
                # Updates may rewrite same-size files within timestamp precision.
                # A restore must never rely on rsync's size/mtime quick check.
                flags.append('--ignore-times')
                if source.is_dir():
                    flags.append('--delete')
            self.run(p, flags + ['--', source_arg, dest_arg])
            return
        # Portable fallback for development tests; production runs on Linux.
        if source.is_dir():
            shutil.copytree(source, dest, symlinks=True, copy_function=shutil.copy2)
        else:
            shutil.copy2(source, dest)
        if hasattr(os, 'chown'):
            # copy2 preserves mode/timestamps/xattrs, but not numeric UID/GID.
            paths = [source]
            if source.is_dir():
                for root, dirs, files in os.walk(source, followlinks=False):
                    paths.extend(Path(root) / name for name in dirs + files)
            for path in paths:
                stat = path.lstat()
                destination = dest if path == source else dest / path.relative_to(source)
                os.chown(destination, stat.st_uid, stat.st_gid, follow_symlinks=False)
                shutil.copystat(path, destination, follow_symlinks=False)
    def restore(self, p):
        target = Path(p['backup_path'])
        manifest = self.read(target / 'manifest.json', None)
        if manifest is None or [x['source'] for x in manifest] != p.get('data_paths', []):
            raise RuntimeError('Backup manifest missing or data paths changed; refusing restore')
        for i, entry in enumerate(manifest):
            if entry['slot'] != str(i) or not (target / str(i)).exists():
                raise RuntimeError('Backup incomplete; refusing restore')
        for entry in manifest:
            dest, source = Path(entry['source']), target / entry['slot']
            if dest.is_symlink():
                raise RuntimeError('Refusing to restore through a top-level symlink')
            if dest.is_dir() and not (os.name == 'posix' and source.is_dir()):
                shutil.rmtree(dest)
            elif dest.exists() and not dest.is_dir():
                dest.unlink()
            dest.parent.mkdir(parents=True, exist_ok=True)
            self.copy_data(source, dest, p, restore=True)

    def ensure_stopped(self, p):
        ids = self.containers(p)
        if ids:
            info = json.loads(self.engine(p, ['inspect', *ids]))
            if any(x['State'].get('Running') for x in info):
                raise RuntimeError('Stop script left running containers; refusing data copy')

    def inspect_images(self, p, services):
        result = {}
        for name, spec in services.items():
            if 'image' not in spec or spec.get('build'):
                raise RuntimeError(f'{name}: only registry images without build are supported')
            result[name] = self.engine(p, ['image', 'inspect', '--format', '{{.Id}}', spec['image']]).strip()
        return result

    def running_images(self, p, services):
        images = {}
        for name in services:
            ids = self.containers(p, name)
            if not ids:
                raise RuntimeError(f'{name}: existing container required for safe first update')
            info = json.loads(self.engine(p, ['inspect', *ids]))
            values = {x['Image'] for x in info}
            if len(values) != 1 or not all(x['State'].get('Running') for x in info):
                raise RuntimeError(f'{name}: service must be running with one consistent image')
            images[name] = values.pop()
        return images

    def verify(self, p, override, images):
        deadline = time.monotonic() + p.get('health_timeout', 180)
        reason = 'No health observation'
        successes = 0
        while time.monotonic() < deadline:
            try:
                for name, image in images.items():
                    ids = self.containers(p, name)
                    if not ids:
                        raise RuntimeError(f'{name}: no container')
                    for info in json.loads(self.engine(p, ['inspect', *ids])):
                        state = info['State']
                        if not state.get('Running'):
                            raise RuntimeError(f'{name}: not running; exit={state.get("ExitCode")}')
                        if info['Image'].removeprefix('sha256:') != image.removeprefix('sha256:'):
                            raise RuntimeError(f'{name}: wrong image is running')
                        health = state.get('Health', state.get('Healthcheck', {})).get('Status')
                        if p.get('healthcheck', True) and health and health != 'healthy':
                            raise RuntimeError(f'{name}: health={health}')
                web = p.get('web', {})
                if web.get('enabled', False):
                    with urllib.request.urlopen(web['url'], timeout=min(web.get('timeout', 5), max(0.1, deadline - time.monotonic()))) as response:
                        if response.status not in web.get('status_codes', [200]):
                            raise RuntimeError(f'HTTP status {response.status}')
                successes += 1
                if successes >= p.get('healthy_samples', 3):
                    return
            except Exception as exc:
                successes = 0
                reason = str(exc)
                self.log(p, 'Health wait: ' + reason)
            time.sleep(min(p.get('health_interval', 5), max(0, deadline - time.monotonic())))
        raise RuntimeError('Health check timeout: ' + reason)

    def collect_error(self, p, exc):
        error = {'time': stamp(), 'message': str(exc), 'traceback': traceback.format_exc()}
        for label, args in [('containers', ['ps']), ('logs', ['logs', '--tail', '100'])]:
            try:
                error[label] = self.compose(p, args)[-30000:]
            except Exception as nested:
                error[label] = str(nested)
        self.update(p, last_error=error)
        self.log(p, 'ERROR: ' + str(exc))

    def rollback(self, p, tx):
        tx['phase'] = 'rollback'
        write_json(self.journal_path(p), tx)
        self.update(p, status='rolling_back')
        old_override = self.override(p, tx['old_images'])
        self.script(p, 'stop', tx, lambda: self.compose(p, ['stop'], old_override))
        self.ensure_stopped(p)
        if tx.get('backup_complete'):
            self.script(p, 'restore', tx, lambda: self.restore(p))
        self.script(p, 'start', tx, lambda: self.compose(p, ['up', '-d', '--no-build', '--force-recreate'], old_override))
        self.verify(p, old_override, tx['old_images'])
        self.update(p, status='rolled_back', current_images=tx['old_images'], last_rollback=stamp())
        self.journal_path(p).unlink()
        self.log(p, 'Rollback completed; original error retained')

    def process(self, p):
        tx = None
        if self.state.get(p['id'], {}).get('manual_stopped'):
            self.log(p, 'Manually stopped: skipping update')
            return
        if self.journal_path(p).exists():
            self.log(p, 'Unresolved transaction: skipping update until recovery succeeds')
            return
        try:
            self.update(p, status='checking', last_check_started=stamp(), last_checked=stamp())
            spec = self.parse_compose(self.compose(p, ['config']))
            services = spec['services']
            old = self.running_images(p, services)
            self.update(p, current_images=old, image_refs={k: v.get('image') for k, v in services.items()})
            # Pull in service order, never parallel across projects or services.
            for name, service in services.items():
                if service.get('build') or not service.get('image'):
                    raise RuntimeError(f'{name}: build services are unsupported')
                self.engine(p, ['pull', service['image']])
            new = self.inspect_images(p, services)
            self.update(p, last_checked=stamp())
            if {k: v.removeprefix('sha256:') for k, v in old.items()} == {k: v.removeprefix('sha256:') for k, v in new.items()}:
                self.update(p, status='up_to_date')
                return
            override = self.override(p, new)
            tx = {'phase': 'stopping', 'time': stamp(), 'old_images': old, 'new_images': new,
                  'backup_complete': False, 'config': p}
            write_json(self.journal_path(p), tx)
            self.script(p, 'stop', tx, lambda: self.compose(p, ['stop']))
            self.ensure_stopped(p)
            tx['phase'] = 'backup'
            write_json(self.journal_path(p), tx)
            self.script(p, 'backup', tx, lambda: self.backup(p))
            tx['backup_complete'] = True
            tx['phase'] = 'deploy'
            write_json(self.journal_path(p), tx)
            self.script(p, 'start', tx, lambda: self.compose(p, ['up', '-d', '--no-build', '--force-recreate'], override))
            self.update(p, status='verifying')
            self.verify(p, override, new)
            self.update(p, status='updated', last_updated=stamp(), current_images=new)
            self.journal_path(p).unlink()
            self.log(p, 'Update completed')
        except Exception as exc:
            self.collect_error(p, exc)
            if tx:
                try:
                    self.rollback(p, tx)
                except Exception as rollback_exc:
                    self.update(p, status='rollback_failed', rollback_error={'time': stamp(), 'message': str(rollback_exc)})
                    self.log(p, 'ROLLBACK FAILED: ' + str(rollback_exc))
            else:
                self.update(p, status='error')

    def batch(self, selected=None, recovery=False):
        if not self.lock.acquire(blocking=False):
            return False
        def work():
            try:
                for p in self.projects:
                    if selected and p['id'] != selected:
                        continue
                    if recovery:
                        path = self.journal_path(p)
                        if path.exists():
                            tx = self.read(path, {})
                            # Recover with the transaction's exact configuration, not edited paths.
                            original = tx['config']
                            fields = {'recovery_started': stamp()}
                            if not self.state.get(original['id'], {}).get('last_error'):
                                fields['last_error'] = {'time': stamp(), 'message': 'Interrupted transaction; recovery requested'}
                            self.update(original, **fields)
                            try:
                                self.rollback(original, tx)
                            except Exception as exc:
                                self.update(original, status='rollback_failed', rollback_error={'time': stamp(), 'message': str(exc)})
                    else:
                        self.process(p)
            finally:
                self.lock.release()
        threading.Thread(target=work, daemon=True).start()
        return True

    def scheduler(self):
        while not self.stop_event.wait(5):
            with self.state_lock:
                now = datetime.now(ZoneInfo(self.config.get('timezone', 'Asia/Tokyo')))
                today = now.strftime('%Y-%m-%d')
                marker = self.root / 'schedule.json'
                last = self.read(marker, {}).get('date')
                if now.strftime('%H:%M') >= self.config.get('schedule', '04:00') and last != today:
                    if self.batch():
                        write_json(marker, {'date': today})

    def refresh_inventory(self, p):
        command = list(p.get('engine_command', self.config.get('engine_command', ['podman'])))
        def read(args):
            result = subprocess.run(command + args, cwd=p['directory'], capture_output=True,
                                    text=True, timeout=15, check=True)
            return result.stdout
        try:
            ids = read(['ps', '-a', '-q', '--filter', 'label=com.docker.compose.project=' + p.get('project_name', p['id'])]).split()
            containers = []
            for c in json.loads(read(['inspect', *ids])) if ids else []:
                state = c['State']
                containers.append({'id': c['Id'], 'name': c.get('Name', '').lstrip('/'),
                    'service': c.get('Config', {}).get('Labels', {}).get('com.docker.compose.service', ''),
                    'image': c.get('Config', {}).get('Image', ''), 'image_id': c['Image'],
                    'status': state.get('Status', 'unknown'), 'running': bool(state.get('Running')),
                    'health': state.get('Health', state.get('Healthcheck', {})).get('Status'),
                    'ports': c.get('NetworkSettings', {}).get('Ports') or {}})
            value = {'containers': containers, 'observed_at': stamp(), 'error': None}
        except Exception as exc:
            value = {'containers': [], 'observed_at': stamp(), 'error': str(exc)}
        with self.state_lock:
            self.inventory[p['id']] = value

    def inventory_loop(self):
        while not self.stop_event.is_set():
            for p in self.projects:
                self.refresh_inventory(p)
            self.stop_event.wait(10)

    def control(self, pid, action):
        p = next(p for p in self.projects if p['id'] == pid)
        if not self.lock.acquire(blocking=False):
            return False
        if self.journal_path(p).exists():
            self.lock.release()
            raise ValueError('Recovery required')
        def work():
            path = self.root / (pid + '.control.json')
            try:
                self.refresh_inventory(p)
                with self.state_lock:
                    observed = self.inventory[pid]
                if observed['error']:
                    raise RuntimeError(observed['error'])
                images = dict(self.state.get(pid, {}).get('current_images', {}))
                for container in observed['containers']:
                    service = container['service']
                    if any(c['service'] == service and c['image_id'] != container['image_id'] for c in observed['containers']):
                        raise RuntimeError('Inconsistent service image IDs')
                    if service:
                        images[service] = container['image_id']
                if not images:
                    raise RuntimeError('Existing containers or recorded images required')
                if action == 'start':
                    spec = self.parse_compose(self.compose(p, ['config']))
                    services = spec.get('services', {})
                    if not services or any(name not in images for name in services):
                        raise RuntimeError('Image IDs required for every service; refusing to pull on start')
                    images = {name: images[name] for name in services}
                override = self.override(p, images)
                tx = {'phase': 'manual_' + action, 'config': p, '_journal': str(path), 'old_images': images}
                write_json(path, tx)
                if action == 'stop':
                    self.update(p, manual_stopped=True)
                    self.script(p, 'stop', tx, lambda: self.compose(p, ['stop'], override))
                    self.ensure_stopped(p)
                    self.update(p, status='stopped')
                else:
                    self.script(p, 'start', tx, lambda: self.compose(p, ['up', '-d', '--no-build', '--force-recreate'], override))
                    self.update(p, status='verifying')
                    self.verify(p, override, images)
                    self.update(p, status='running', manual_stopped=False, current_images=images)
                self.update(p, last_control={'action': action, 'time': stamp()})
                path.unlink(missing_ok=True)
            except Exception as exc:
                self.update(p, status='error', control_error={'time': stamp(), 'action': action, 'message': str(exc)})
                self.log(p, 'CONTROL FAILED: ' + str(exc))
            finally:
                self.refresh_inventory(p)
                self.lock.release()
        threading.Thread(target=work, daemon=True).start()
        return True


class Handler(BaseHTTPRequestHandler):
    server_version = 'ComposeKeeper'

    @property
    def keeper(self):
        return self.server.keeper

    def log_message(self, fmt, *args):
        # Do not print auth bodies, URLs or headers.
        pass

    def send(self, code, data, mime='application/json', cookie=None):
        raw = json.dumps(data, ensure_ascii=False).encode() if mime == 'application/json' else data
        self.send_response(code)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'")
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(raw)

    def authorized(self):
        try:
            cookie = http.cookies.SimpleCookie(self.headers.get('Cookie', ''))
            token = cookie['keeper_session'].value
        except (KeyError, http.cookies.CookieError):
            return False
        with self.keeper.auth_lock:
            return self.keeper.sessions.get(token, 0) > time.time()

    def do_GET(self):
        if self.path in ('/', '/app.js', '/i18n.js', '/style.css'):
            name, mime = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript'), '/i18n.js': ('i18n.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}[self.path]
            return self.send(200, (Path(__file__).parent / 'web' / name).read_bytes(), mime)
        if not self.authorized():
            return self.send(401, {'error': 'ログインしてください'})
        if self.path == '/api/projects':
            with self.keeper.state_lock:
                data = [{**self.keeper.state.get(p['id'], {}), 'inventory': self.keeper.inventory.get(p['id'], {}), 'id': p['id'], 'name': p.get('name', p['id']), 'directory': p['directory'], 'web': p.get('web', {}), 'recovery_pending': self.keeper.journal_path(p).exists()} for p in self.keeper.projects]
                return self.send(200, {'projects': data, 'busy': self.keeper.lock.locked(), 'schedule': self.keeper.config.get('schedule', '04:00'), 'timezone': self.keeper.config.get('timezone', 'Asia/Tokyo')})
        if self.path.startswith('/api/logs/'):
            pid = self.path.removeprefix('/api/logs/')
            if pid in [p['id'] for p in self.keeper.projects]:
                file = self.keeper.root / (pid + '.log')
                return self.send(200, {'log': file.read_text(encoding='utf-8')[-60000:] if file.exists() else ''})
        self.send(404, {'error': 'Not found'})

    def do_POST(self):
        # JSON-only + custom header prevent cross-origin form/CSRF requests. No CORS.
        if self.headers.get('X-Keeper-Request') != '1' or self.headers.get('Content-Type') != 'application/json':
            return self.send(403, {'error': 'Invalid request'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= length <= 4096:
                return self.send(413, {'error': 'Request too large'})
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('Expected JSON object')
        except Exception:
            return self.send(400, {'error': 'Invalid JSON'})
        if self.path == '/api/login':
            now, ip = time.time(), self.client_address[0]
            with self.keeper.auth_lock:
                self.keeper.login_attempts = {k: v for k, v in self.keeper.login_attempts.items() if v[0] > now - 300}
                since, count = self.keeper.login_attempts.get(ip, (now, 0))
                if count >= 10:
                    return self.send(429, {'error': 'しばらく待って再試行してください'})
                key = body.get('key', '')
                if not isinstance(key, str) or not hmac.compare_digest(key.encode(), self.keeper.secret.encode()):
                    self.keeper.login_attempts[ip] = (since, count + 1)
                    return self.send(401, {'error': 'キーが違います'})
                self.keeper.sessions = {k: v for k, v in self.keeper.sessions.items() if v > now}
                token = secrets.token_urlsafe(32)
                self.keeper.sessions[token] = now + 43200
            secure = '; Secure' if self.keeper.config.get('secure_cookie', False) else ''
            return self.send(200, {'ok': True}, cookie=f'keeper_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200{secure}')
        if not self.authorized():
            return self.send(401, {'error': 'ログインしてください'})
        if self.path == '/api/logout':
            cookie = http.cookies.SimpleCookie(self.headers.get('Cookie', ''))
            with self.keeper.auth_lock:
                self.keeper.sessions.pop(cookie['keeper_session'].value, None)
            return self.send(200, {'ok': True}, cookie='keeper_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
        if self.path == '/api/settings':
            try:
                self.keeper.set_schedule(body.get('schedule'), body.get('timezone'))
            except (ValueError, TypeError) as exc:
                return self.send(400, {'error': str(exc)})
            return self.send(200, {'ok': True})
        if self.path in ('/api/start', '/api/stop'):
            pid = body.get('id')
            if pid not in [p['id'] for p in self.keeper.projects]:
                return self.send(404, {'error': 'Unknown project'})
            try:
                ok = self.keeper.control(pid, self.path.removeprefix('/api/'))
            except ValueError as exc:
                return self.send(409, {'error': str(exc)})
            return self.send(202 if ok else 409, {'ok': ok, 'error': '' if ok else '処理中です'})
        if self.path in ('/api/run', '/api/recover'):
            pid = body.get('id')
            if pid is not None and pid not in [p['id'] for p in self.keeper.projects]:
                return self.send(404, {'error': 'Unknown project'})
            ok = self.keeper.batch(pid, recovery=self.path == '/api/recover')
            return self.send(202 if ok else 409, {'ok': ok, 'error': '' if ok else '処理中です'})
        self.send(404, {'error': 'Not found'})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config.json')
    args = parser.parse_args()
    keeper = Keeper(args.config)
    def terminate(signum, frame):
        keeper.shutdown()
        if keeper.lock.acquire(timeout=5):
            keeper.lock.release()
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    # Prevent a second process from bypassing the thread-level lock (Linux deployment).
    lockfile = (keeper.root / 'keeper.lock').open('a')
    if os.name != 'nt':
        import fcntl
        fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
    keeper.batch(recovery=True)
    threading.Thread(target=keeper.scheduler, daemon=True).start()
    threading.Thread(target=keeper.inventory_loop, daemon=True).start()
    server = ThreadingHTTPServer((keeper.config.get('listen', '0.0.0.0'), keeper.config.get('port', 8080)), Handler)
    server.keeper = keeper
    print(f'Compose Keeper listening on {server.server_address}', flush=True)
    try:
        server.serve_forever()
    finally:
        keeper.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
