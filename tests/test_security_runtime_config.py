import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SecurityRuntimeConfigTests(unittest.TestCase):
    def _read_limits(self, login_limit, login_window, global_limit):
        env = os.environ.copy()
        env['LOGIN_LIMIT'] = login_limit
        env['LOGIN_WINDOW_SECONDS'] = login_window
        env['GLOBAL_LOGIN_LIMIT'] = global_limit
        result = subprocess.run(
            [
                sys.executable,
                '-c',
                'from app import security; print(security.LOGIN_LIMIT, security.LOGIN_WINDOW, security.GLOBAL_LOGIN_LIMIT)',
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_invalid_login_limits_use_existing_defaults(self):
        self.assertEqual(self._read_limits('broken', '', 'not-a-number'), '10 600 120')

    def test_login_limits_keep_existing_bounds(self):
        self.assertEqual(self._read_limits('1', '1', '1'), '5 60 50')
        self.assertEqual(self._read_limits('999', '99999', '9999'), '30 3600 500')


if __name__ == '__main__':
    unittest.main()
