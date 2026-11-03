import json
from pathlib import Path
import time
import unittest
import test_keeper as fixtures
from keeper import write_json


class BackupTests(unittest.TestCase):
    setUp = fixtures.KeeperTests.setUp
    tearDown = fixtures.KeeperTests.tearDown

    def wait(self):
        deadline = time.monotonic() + 4
        while self.keeper.lock.locked():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)

    def prepare(self, running=True):
        self.calls = []
        def inventory(p):
            self.keeper.inventory[p['id']] = {'error': None, 'containers': [
                {'service': 'web', 'image_id': 'sha256:current', 'running': running}],
                'backup': self.keeper.backup_info(p)}
        self.keeper.refresh_inventory = inventory
        def compose(p, args, override=None):
            self.calls.append((args, json.loads(override.read_text()) if override else None))
            return json.dumps({'services': {'web': {'image': 'example:latest'}}}) if args[0] == 'config' else ''
        self.keeper.compose = compose
        self.keeper.engine = lambda *args: 'sha256:old'
        self.keeper.verify = lambda *args: None

    def snapshot(self):
        self.keeper.update(self.p, current_images={'web': 'sha256:old'})
        self.keeper.backup(self.p)
        return self.keeper.backup_info(self.p)

    def test_state_reports_missing_ready_and_metadata(self):
        self.assertEqual(self.keeper.backup_info(self.p)['status'], 'missing')
        info = self.snapshot()
        self.assertEqual(info['status'], 'ready')
        self.assertTrue(info['restorable'])
        self.assertEqual(info['size_bytes'], len('original'))
        self.assertEqual(info['file_count'], 1)
        self.assertEqual(info['images'], {'web': 'sha256:old'})

    def test_restore_returns_multiple_paths_and_saved_image(self):
        second = self.base / 'other-data'
        second.mkdir()
        (second / 'settings').write_text('saved settings')
        self.p['data_paths'].append(str(second))
        snapshot = self.snapshot()
        (self.data / 'db').write_text('modified')
        (self.data / 'added').write_text('must disappear')
        (second / 'settings').write_text('changed settings')
        self.prepare()
        self.assertTrue(self.keeper.storage_action('app', 'restore', snapshot['id']))
        self.wait()
        self.assertEqual((self.data / 'db').read_text(), 'original')
        self.assertEqual((second / 'settings').read_text(), 'saved settings')
        self.assertFalse((self.data / 'added').exists())
        self.assertEqual(self.keeper.state['app']['status'], 'restored')
        start = next(c for c in self.calls if c[0][0] == 'up')
        self.assertEqual(start[1]['services']['web']['image'], 'sha256:old')
        self.assertEqual(self.keeper.backup_info(self.p)['id'], snapshot['id'])
        self.assertFalse(self.keeper.journal_path(self.p).exists())

    def test_changed_snapshot_and_missing_files_block_restore(self):
        self.snapshot()
        with self.assertRaises(ValueError):
            self.keeper.storage_action('app', 'restore', 'stale-snapshot-id')
        self.assertFalse(self.keeper.lock.locked())
        (Path(self.p['backup_path']) / '0' / 'db').unlink()
        self.assertEqual(self.keeper.backup_info(self.p)['status'], 'invalid')
        self.assertEqual((self.data / 'db').read_text(), 'original')

    def test_changed_paths_and_legacy_backup_are_not_restorable(self):
        self.snapshot()
        self.p['data_paths'] = []
        self.assertFalse(self.keeper.backup_info(self.p)['restorable'])
        (Path(self.p['backup_path']) / 'snapshot.json').unlink()
        self.assertEqual(self.keeper.backup_info(self.p)['status'], 'legacy')

    def test_backup_of_stopped_project_does_not_start_it(self):
        self.prepare(running=False)
        self.keeper.update(self.p, manual_stopped=True)
        self.keeper.storage_action('app', 'backup')
        self.wait()
        self.assertTrue(self.keeper.state['app']['manual_stopped'])
        self.assertTrue(self.keeper.backup_info(self.p)['restorable'])
        self.assertFalse(any(c[0][0] == 'up' for c in self.calls))

    def test_failed_backup_keeps_live_data_and_restarts_current_image(self):
        self.snapshot()
        (self.data / 'db').write_text('newer live data')
        self.prepare()
        def fail(p):
            raise RuntimeError('disk full')
        self.keeper.backup = fail
        self.keeper.storage_action('app', 'backup')
        self.wait()
        self.assertEqual((self.data / 'db').read_text(), 'newer live data')
        start = next(c for c in self.calls if c[0][0] == 'up')
        self.assertEqual(start[1]['services']['web']['image'], 'sha256:current')
        self.assertIn('disk full', self.keeper.state['app']['last_error']['message'])

    def test_failed_restore_keeps_journal_and_can_resume(self):
        snapshot = self.snapshot()
        self.prepare()
        restore = self.keeper.restore
        def fail(p):
            raise RuntimeError('temporary restore failure')
        self.keeper.restore = fail
        self.keeper.storage_action('app', 'restore', snapshot['id'])
        self.wait()
        self.assertTrue(self.keeper.journal_path(self.p).exists())
        self.assertEqual(self.keeper.state['app']['status'], 'restore_failed')
        self.keeper.restore = restore
        self.keeper.batch('app', recovery=True)
        self.wait()
        self.assertEqual(self.keeper.state['app']['status'], 'restored')
        self.assertIn('temporary restore failure', self.keeper.state['app']['last_error']['message'])

    def test_backup_uses_global_operation_lock(self):
        self.keeper.lock.acquire()
        try:
            self.assertFalse(self.keeper.storage_action('app', 'backup'))
        finally:
            self.keeper.lock.release()

    def test_custom_restore_uses_command_saved_with_snapshot(self):
        self.snapshot()
        self.p['scripts'] = {'restore': ['old-restore'], 'backup': ['old-backup']}
        saved = self.keeper.write_backup_metadata(self.p)
        self.p['scripts']['restore'] = ['new-restore']
        self.prepare()
        observed = []
        def script(p, action, tx, default):
            if action == 'restore':
                observed.append(p['scripts']['restore'])
            default()
        self.keeper.script = script
        self.keeper.storage_action('app', 'restore', saved['id'])
        self.wait()
        self.assertEqual(observed, [['old-restore']])

    def test_completed_backup_is_not_overwritten_during_recovery(self):
        snapshot = self.snapshot()
        self.prepare()
        tx = {'operation': 'manual_backup', 'phase': 'starting', 'data_complete': True,
              'old_images': snapshot['images'], 'resume_running': True, 'config': self.p}
        write_json(self.keeper.journal_path(self.p), tx)
        def must_not_run(p):
            self.fail('Completed backup must not be replaced during recovery')
        self.keeper.backup = must_not_run
        self.keeper.resume_storage(self.p, tx)
        self.assertEqual(self.keeper.backup_info(self.p)['id'], snapshot['id'])


if __name__ == '__main__':
    unittest.main()
