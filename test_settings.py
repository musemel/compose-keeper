import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
import test_keeper as fixtures
from keeper import Keeper

class SettingsTests(unittest.TestCase):
    setUp = fixtures.KeeperTests.setUp
    tearDown = fixtures.KeeperTests.tearDown

    def test_schedule_survives_restart(self):
        self.keeper.set_schedule('03:25', 'UTC')
        reloaded = Keeper(self.file)
        self.assertEqual(reloaded.config['schedule'], '03:25')
        self.assertEqual(reloaded.config['timezone'], 'UTC')

    def test_invalid_time_and_timezone_are_rejected(self):
        for value in ('3:25', '24:00', '12:99', None):
            with self.assertRaises((ValueError, TypeError)):
                self.keeper.set_schedule(value, 'UTC')
        with patch('keeper.ZoneInfo', side_effect=KeyError('invalid')):
            with self.assertRaisesRegex(ValueError, 'Invalid timezone'):
                self.keeper.set_schedule('03:25', 'Not/AZone')
        self.assertFalse((self.keeper.root / 'settings.json').exists())

    def test_past_time_does_not_trigger_immediately(self):
        with patch('keeper.datetime') as clock:
            clock.strptime.side_effect = datetime.strptime
            clock.now.return_value = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
            self.keeper.set_schedule('04:00', 'UTC')
        self.assertEqual(json.loads((self.keeper.root / 'schedule.json').read_text())['date'], '2026-11-03')

    def test_future_time_can_run_later_today(self):
        with patch('keeper.datetime') as clock:
            clock.strptime.side_effect = datetime.strptime
            clock.now.return_value = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
            self.keeper.set_schedule('18:00', 'UTC')
        self.assertIsNone(json.loads((self.keeper.root / 'schedule.json').read_text())['date'])

if __name__ == '__main__':
    unittest.main()
