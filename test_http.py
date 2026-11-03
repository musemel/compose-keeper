import http.cookiejar
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
from datetime import timezone
from http.server import ThreadingHTTPServer
from keeper import Keeper, Handler, write_json


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        path = Path(self.tmp.name) / 'config.json'
        write_json(path, {'state_dir': str(Path(self.tmp.name) / 'state'), 'projects': []})
        with patch.dict(os.environ, {'KEEPER_ACCESS_KEY': 'http-test-key-123456789'}), patch('keeper.ZoneInfo', return_value=timezone.utc):
            self.keeper = Keeper(path)
        try:
            self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        except OSError as exc:
            self.tmp.cleanup()
            self.skipTest('Local socket unavailable: ' + str(exc))
        self.server.keeper = self.keeper
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def tearDown(self):
        if hasattr(self, 'server'):
            self.server.shutdown()
            self.server.server_close()
            self.thread.join()
        self.tmp.cleanup()

    def request(self, route, body=None, custom_header=True):
        headers = {}
        if body is not None:
            headers['Content-Type'] = 'application/json'
            if custom_header:
                headers['X-Keeper-Request'] = '1'
        req = urllib.request.Request(self.url + route, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            response = self.client.open(req)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.code, response.read(), response.headers

    def login(self):
        return self.request('/api/login', {'key': 'http-test-key-123456789'})

    def test_auth_cookie_and_logout(self):
        self.assertEqual(self.request('/api/projects')[0], 401)
        code, _, headers = self.login()
        self.assertEqual(code, 200)
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', headers['Set-Cookie'])
        self.assertEqual(self.request('/api/projects')[0], 200)
        self.assertEqual(self.request('/api/logout', {})[0], 200)
        self.assertEqual(self.request('/api/projects')[0], 401)

    def test_csrf_and_unknown_project_rejected(self):
        self.login()
        self.assertEqual(self.request('/api/run', {}, custom_header=False)[0], 403)
        self.assertEqual(self.request('/api/run', {'id': 'unknown'})[0], 404)
        self.assertEqual(self.request('/api/start', {'id': 'unknown'})[0], 404)
        self.assertEqual(self.request('/api/stop', {}, custom_header=False)[0], 403)

    def test_wrong_key_and_rate_limit(self):
        for _ in range(10):
            self.assertEqual(self.request('/api/login', {'key': 'wrong'})[0], 401)
        self.assertEqual(self.login()[0], 429)

    def test_settings_require_auth_and_validate_values(self):
        self.assertEqual(self.request('/api/settings', {'schedule': '03:00', 'timezone': 'UTC'})[0], 401)
        self.login()
        self.assertEqual(self.request('/api/settings', {'schedule': '99:00', 'timezone': 'UTC'})[0], 400)
        self.assertEqual(self.request('/api/settings', {'schedule': '03:00', 'timezone': 'UTC'}, custom_header=False)[0], 403)
        self.assertEqual(self.request('/api/settings', {'schedule': '03:00', 'timezone': 'UTC'})[0], 200)
        data = json.loads(self.request('/api/projects')[1])
        self.assertEqual(data['schedule'], '03:00')

    def test_assets_and_no_file_traversal(self):
        for asset in ('/', '/app.js', '/i18n.js', '/style.css'):
            code, data, headers = self.request(asset)
            self.assertEqual(code, 200)
            self.assertTrue(data)
            self.assertEqual(headers['X-Frame-Options'], 'DENY')
        self.login()
        self.assertEqual(self.request('/api/logs/../../config.json')[0], 404)


if __name__ == '__main__':
    unittest.main()
