import json
import os
from pathlib import Path
import tempfile
import unittest
from datetime import timezone
from unittest.mock import patch

from keeper import Keeper, write_json


class KeeperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.base = Path(self.tmp.name)
        self.app = self.base / 'app'
        self.app.mkdir()
        self.data = self.app / 'data'
        self.data.mkdir()
        (self.data / 'db').write_text('original')
        self.project = {'id': 'app', 'directory': str(self.app), 'data_paths': [str(self.data)],
                        'backup_path': str(self.base / 'backups' / 'app'), 'health_timeout': 0.01,
                        'health_interval': 0.001, 'healthy_samples': 1}
        config = {'state_dir': str(self.base / 'state'), 'projects': [self.project]}
        self.file = self.base / 'config.json'
        write_json(self.file, config)
        self.env = patch.dict(os.environ, {'KEEPER_ACCESS_KEY': 'unit-test-access-key-123'})
        self.env.start()
        self.tz = patch('keeper.ZoneInfo', return_value=timezone.utc)
        self.tz.start()
        self.keeper = Keeper(self.file)
        self.p = self.keeper.projects[0]
        self.keeper.ensure_stopped = lambda p: None

    def tearDown(self):
        self.env.stop()
        self.tz.stop()
        self.tmp.cleanup()

    def test_restore_replaces_new_files_and_old_data(self):
        self.keeper.backup(self.p)
        (self.data / 'db').write_text('migrated')
        (self.data / 'newfile').write_text('new')
        self.keeper.restore(self.p)
        self.assertEqual((self.data / 'db').read_text(), 'original')
        self.assertFalse((self.data / 'newfile').exists())

    def test_failed_backup_preserves_previous_complete_backup(self):
        self.keeper.backup(self.p)
        self.p['data_paths'].append(str(self.app / 'missing'))
        with self.assertRaises(RuntimeError):
            self.keeper.backup(self.p)
        self.assertEqual((Path(self.p['backup_path']) / '0' / 'db').read_text(), 'original')

    def test_changed_manifest_cannot_delete_data(self):
        self.keeper.backup(self.p)
        write_json(Path(self.p['backup_path']) / 'manifest.json', [{'source': '/unexpected', 'slot': '0', 'directory': True}])
        with self.assertRaises(RuntimeError):
            self.keeper.restore(self.p)
        self.assertEqual((self.data / 'db').read_text(), 'original')

    def fake_compose(self, p, args, override=None):
        if args[0] == 'config':
            return json.dumps({'services': {'web': {'image': 'example:latest'}}})
        return ''

    def setup_update(self):
        self.keeper.compose = self.fake_compose
        self.keeper.running_images = lambda p, services: {'web': 'sha256:old'}
        self.keeper.inspect_images = lambda p, services: {'web': 'sha256:new'}
        self.keeper.engine = lambda p, args: ''

    def test_failed_deploy_restores_data_old_image_and_retains_error(self):
        self.setup_update()
        calls = []
        def compose(p, args, override=None):
            calls.append(args)
            if args[0] == 'up':
                image = json.loads(Path(override).read_text())['services']['web']['image']
                if image.endswith('new'):
                    (self.data / 'db').write_text('incompatible schema')
                    raise RuntimeError('new image failed to start')
            return self.fake_compose(p, args, override)
        self.keeper.compose = compose
        self.keeper.verify = lambda *a: None
        self.keeper.process(self.p)
        state = self.keeper.state['app']
        self.assertEqual(state['status'], 'rolled_back')
        self.assertEqual(state['current_images'], {'web': 'sha256:old'})
        self.assertIn('new image failed', state['last_error']['message'])
        self.assertEqual((self.data / 'db').read_text(), 'original')
        self.assertFalse(self.keeper.journal_path(self.p).exists())

    def test_backup_failure_does_not_deploy_or_restore_stale_backup(self):
        self.setup_update()
        self.keeper.backup(self.p)
        (self.data / 'db').write_text('newer live data')
        starts = []
        def fail(p):
            raise RuntimeError('disk full')
        self.keeper.backup = fail
        def compose(p, args, override=None):
            if args[0] == 'up':
                starts.append(json.loads(Path(override).read_text())['services']['web']['image'])
            return self.fake_compose(p, args, override)
        self.keeper.compose = compose
        self.keeper.verify = lambda *a: None
        self.keeper.process(self.p)
        self.assertEqual(starts, ['sha256:old'])
        self.assertEqual((self.data / 'db').read_text(), 'newer live data')

    def test_success_commits_version_and_timestamp(self):
        self.setup_update()
        self.keeper.verify = lambda *a: None
        self.keeper.process(self.p)
        state = self.keeper.state['app']
        self.assertEqual(state['status'], 'updated')
        self.assertEqual(state['current_images'], {'web': 'sha256:new'})
        self.assertTrue(state['last_updated'])
        self.assertFalse(self.keeper.journal_path(self.p).exists())

    def test_http_check_failure_times_out(self):
        self.p['web'] = {'enabled': True, 'url': 'http://127.0.0.1:1'}
        self.keeper.compose = lambda *a: 'container-id'
        self.keeper.containers = lambda *a: ['container-id']
        self.keeper.engine = lambda *a: json.dumps([{'Image': 'sha256:old', 'State': {'Running': True}}])
        with patch('keeper.urllib.request.urlopen', side_effect=RuntimeError('probe failed')):
            with self.assertRaisesRegex(RuntimeError, 'Health check timeout: probe failed'):
                self.keeper.verify(self.p, None, {'web': 'sha256:old'})

    def test_unhealthy_container_cannot_pass_without_web_check(self):
        self.keeper.compose = lambda *a: 'container-id'
        self.keeper.containers = lambda *a: ['container-id']
        self.keeper.engine = lambda *a: json.dumps([{'Image': 'sha256:old', 'State': {'Running': True, 'Health': {'Status': 'unhealthy'}}}])
        with self.assertRaisesRegex(RuntimeError, 'health=unhealthy'):
            self.keeper.verify(self.p, None, {'web': 'sha256:old'})

    def test_wrong_image_cannot_pass(self):
        self.keeper.compose = lambda *a: 'container-id'
        self.keeper.containers = lambda *a: ['container-id']
        self.keeper.engine = lambda *a: json.dumps([{'Image': 'sha256:wrong', 'State': {'Running': True}}])
        with self.assertRaisesRegex(RuntimeError, 'wrong image'):
            self.keeper.verify(self.p, None, {'web': 'sha256:old'})

    def test_overlapping_backup_path_is_rejected(self):
        config = json.loads(self.file.read_text())
        config['projects'][0]['backup_path'] = str(self.data / 'backup')
        write_json(self.file, config)
        with self.assertRaises(ValueError):
            Keeper(self.file)

    def test_second_batch_is_rejected(self):
        self.keeper.lock.acquire()
        try:
            self.assertFalse(self.keeper.batch())
        finally:
            self.keeper.lock.release()

    def test_pending_transaction_preserves_original_failure(self):
        original = {'message': 'original update error', 'logs': 'failed application output'}
        self.keeper.update(self.p, last_error=original, status='rollback_failed')
        write_json(self.keeper.journal_path(self.p), {'phase': 'rollback'})
        self.keeper.process(self.p)
        self.assertEqual(self.keeper.state['app']['last_error'], original)
        self.assertEqual(self.keeper.state['app']['status'], 'rollback_failed')


if __name__ == '__main__':
    unittest.main()
