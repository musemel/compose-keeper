"""Linux metadata preservation checks; requires rsync, acl, attr-capable FS."""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from keeper import Keeper, write_json


@unittest.skipUnless(os.name == 'posix' and shutil.which('rsync') and shutil.which('setfacl'), 'Linux + rsync + acl required')
class MetadataTests(unittest.TestCase):
    def test_backup_restore_preserves_metadata(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            base = Path(tmp)
            app = base / 'app'
            data = app / 'data'
            data.mkdir(parents=True)
            directory_inode = data.stat().st_ino
            settings = app / 'settings.conf'
            settings.write_text('original-setting')
            settings.chmod(0o600)
            file = data / 'database'
            file.write_text('before-update')
            file.chmod(0o640)
            os.chown(file, 1234, 2345)
            os.utime(file, (1700000000, 1700000000))
            os.setxattr(file, 'user.keeper-test', b'attribute-value')
            subprocess.run(['setfacl', '-m', 'u:3456:r--', str(file)], check=True)
            os.link(file, data / 'hardlink')
            (data / 'symlink').symlink_to('database')
            os.chown(data, 1234, 2345)
            data.chmod(0o2750)
            expected_acl = subprocess.check_output(['getfacl', '-cpn', str(file)])
            expected_mode = stat.S_IMODE(file.stat().st_mode)
            config = {'state_dir': str(base / 'state'), 'projects': [{'id': 'meta', 'directory': str(app),
                      'data_paths': [str(data), str(settings)], 'backup_path': str(base / 'backup')}]}
            path = base / 'config.json'
            write_json(path, config)
            with patch.dict(os.environ, {'KEEPER_ACCESS_KEY': 'metadata-test-access-key'}):
                keeper = Keeper(path)
            p = keeper.projects[0]
            keeper.backup(p)
            file.write_text('after-update')
            os.chown(file, 0, 0)
            file.chmod(0o777)
            os.removexattr(file, 'user.keeper-test')
            (data / 'extra').write_text('must disappear')
            settings.write_text('changed-setting')
            settings.chmod(0o777)
            keeper.restore(p)
            self.assertEqual(file.read_text(), 'before-update')
            self.assertEqual((file.stat().st_uid, file.stat().st_gid), (1234, 2345))
            self.assertEqual(stat.S_IMODE(file.stat().st_mode), expected_mode)
            self.assertEqual(file.stat().st_mtime, 1700000000)
            self.assertEqual(os.getxattr(file, 'user.keeper-test'), b'attribute-value')
            self.assertEqual(subprocess.check_output(['getfacl', '-cpn', str(file)]), expected_acl)
            self.assertEqual(file.stat().st_ino, (data / 'hardlink').stat().st_ino)
            self.assertTrue((data / 'symlink').is_symlink())
            self.assertEqual(os.readlink(data / 'symlink'), 'database')
            self.assertFalse((data / 'extra').exists())
            self.assertEqual((data.stat().st_uid, data.stat().st_gid), (1234, 2345))
            self.assertEqual(stat.S_IMODE(data.stat().st_mode), 0o2750)
            self.assertEqual(data.stat().st_ino, directory_inode)
            self.assertEqual(settings.read_text(), 'original-setting')
            self.assertEqual(stat.S_IMODE(settings.stat().st_mode), 0o600)


if __name__ == '__main__':
    unittest.main()
