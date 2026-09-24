import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MainRuntimeConfigTests(unittest.TestCase):
    def _read_limits(self, token_ttl, max_upload):
        env = os.environ.copy()
        env.update({
            'DATABASE_URL': 'postgresql://user:pass@localhost/test',
            'REDIS_URL': 'redis://localhost:6379/0',
            'TOKEN_SECRET': 'test-token-secret',
            'TOKEN_TTL_SECONDS': token_ttl,
            'MAX_UPLOAD_MB': max_upload,
        })
        result = subprocess.run(
            [
                sys.executable,
                '-c',
                'from app import main, storage_api; print(main.TOKEN_TTL_SECONDS, main.MAX_UPLOAD_MB, storage_api.MAX_UPLOAD_MB)',
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_invalid_studio_limits_use_existing_defaults(self):
        self.assertEqual(self._read_limits('broken', ''), '604800 80 80')

    def test_studio_limits_keep_existing_bounds(self):
        self.assertEqual(self._read_limits('1', '1'), '3600 10 10')
        self.assertEqual(self._read_limits(str(31 * 24 * 3600), '9999'), '2592000 500 500')


if __name__ == '__main__':
    unittest.main()
