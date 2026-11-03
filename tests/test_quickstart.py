import importlib.util
import json
from pathlib import Path
import unittest
import test_keeper as fixtures
from keeper import Keeper

class QuickstartTests(unittest.TestCase):
    setUp = fixtures.KeeperTests.setUp
    tearDown = fixtures.KeeperTests.tearDown

    def test_prepare_creates_valid_multiple_path_config_without_overwriting_data(self):
        repo = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('quickstart', repo / 'examples/quickstart/run.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        project, config = module.prepare(repo, self.base / 'runtime')
        keeper = Keeper(config)
        p = keeper.projects[0]
        self.assertEqual(len(p['data_paths']), 2)
        self.assertTrue(all(Path(path).is_dir() for path in p['data_paths']))
        self.assertNotIn(p['backup_path'], p['data_paths'])
        page = project / 'data/site/index.html'
        page.write_text('user-edited sample')
        module.prepare(repo, self.base / 'runtime')
        self.assertEqual(page.read_text(), 'user-edited sample')
        self.assertEqual(json.loads(config.read_text())['listen'], '127.0.0.1')

if __name__ == '__main__':
    unittest.main()
