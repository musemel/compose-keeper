import json
import time
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_keeper as fixtures
from keeper import Keeper, write_json


class ControlTests(unittest.TestCase):
    setUp = fixtures.KeeperTests.setUp
    tearDown = fixtures.KeeperTests.tearDown

    def wait(self):
        deadline = time.monotonic() + 3
        while self.keeper.lock.locked():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)

    def prepare(self):
        self.calls = []
        def inventory(p):
            self.keeper.inventory[p['id']] = {'error': None, 'containers': [
                {'service': 'web', 'image_id': 'sha256:existing'}]}
        self.keeper.refresh_inventory = inventory
        def compose(p, args, override=None):
            if args[0] == 'config':
                return json.dumps({'services': getattr(self, 'services', {'web': {'image': 'example:latest'}})})
            self.calls.append((args, json.loads(override.read_text()) if override else None))
            return ''
        self.keeper.compose = compose
        self.keeper.verify = lambda *args: None

    def test_stop_persists_intent_and_blocks_update(self):
        self.prepare()
        self.assertTrue(self.keeper.control('app', 'stop'))
        self.wait()
        self.assertEqual(self.keeper.state['app']['status'], 'stopped')
        reloaded = Keeper(self.file)
        self.assertTrue(reloaded.state['app']['manual_stopped'])
        self.keeper.process(self.p)
        self.assertEqual([call[0][0] for call in self.calls], ['stop'])

    def test_start_uses_existing_image_instead_of_latest_record(self):
        self.prepare()
        self.keeper.update(self.p, manual_stopped=True, current_images={'web': 'sha256:wrong'})
        self.assertTrue(self.keeper.control('app', 'start'))
        self.wait()
        self.assertEqual(self.keeper.state['app']['status'], 'running')
        self.assertFalse(self.keeper.state['app']['manual_stopped'])
        self.assertEqual(self.calls[0][1]['services']['web']['image'], 'sha256:existing')
        self.assertEqual(self.calls[0][1]['services']['web']['pull_policy'], 'never')
        self.assertEqual(self.keeper.state['app']['current_images'], {'web': 'sha256:existing'})

    def test_control_is_exclusive_with_update(self):
        self.keeper.lock.acquire()
        try:
            self.assertFalse(self.keeper.control('app', 'stop'))
        finally:
            self.keeper.lock.release()

    def test_pending_recovery_blocks_control(self):
        write_json(self.keeper.journal_path(self.p), {'phase': 'rollback'})
        with self.assertRaisesRegex(ValueError, 'Recovery required'):
            self.keeper.control('app', 'start')
        self.assertFalse(self.keeper.lock.locked())

    def test_start_failure_retains_error_and_stop_intent(self):
        self.prepare()
        self.keeper.update(self.p, manual_stopped=True)
        def fail(*args):
            raise RuntimeError('probe failed')
        self.keeper.verify = fail
        self.keeper.control('app', 'start')
        self.wait()
        self.assertEqual(self.keeper.state['app']['control_error']['message'], 'probe failed')
        self.assertTrue(self.keeper.state['app']['manual_stopped'])

    def test_start_refuses_unknown_image_for_missing_service(self):
        self.prepare()
        self.services = {'web': {'image': 'example:latest'}, 'db': {'image': 'db:latest'}}
        self.keeper.control('app', 'start')
        self.wait()
        self.assertIn('every service', self.keeper.state['app']['control_error']['message'])
        self.assertEqual(self.calls, [])

    def test_start_uses_recorded_image_for_deleted_container(self):
        self.prepare()
        self.services = {'web': {'image': 'example:latest'}, 'db': {'image': 'db:latest'}}
        self.keeper.update(self.p, current_images={'db': 'sha256:recorded-db'})
        self.keeper.control('app', 'start')
        self.wait()
        self.assertEqual(self.calls[0][1]['services']['db']['image'], 'sha256:recorded-db')

    def test_inventory_only_exposes_selected_container_fields(self):
        info = {'Id': 'abc', 'Name': '/project_web_1', 'Image': 'sha256:old',
                'Config': {'Image': 'example:latest', 'Env': ['SECRET=not-for-api'],
                           'Labels': {'com.docker.compose.service': 'web'}},
                'State': {'Status': 'running', 'Running': True, 'Health': {'Status': 'healthy'}},
                'NetworkSettings': {'Ports': {'80/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '8081'}]}}}
        with patch('keeper.subprocess.run', side_effect=[SimpleNamespace(stdout='abc\n'), SimpleNamespace(stdout=json.dumps([info]))]):
            self.keeper.refresh_inventory(self.p)
        value = self.keeper.inventory['app']
        self.assertEqual(value['containers'][0]['health'], 'healthy')
        self.assertEqual(value['containers'][0]['service'], 'web')
        self.assertNotIn('SECRET', json.dumps(value))

    def test_shutdown_cancels_commands_and_prevents_new_commands(self):
        errors = []
        def run():
            try:
                self.keeper.run(self.p, [sys.executable, '-c', 'import time; time.sleep(30)'])
            except RuntimeError as exc:
                errors.append(str(exc))
        thread = threading.Thread(target=run)
        thread.start()
        deadline = time.monotonic() + 3
        while not self.keeper.children:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)
        self.keeper.shutdown()
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertTrue(errors)
        with self.assertRaisesRegex(RuntimeError, 'shutting down'):
            self.keeper.run(self.p, [sys.executable, '-c', 'print(1)'])


if __name__ == '__main__':
    unittest.main()
