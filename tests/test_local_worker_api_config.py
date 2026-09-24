import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LocalWorkerApiConfigTests(unittest.TestCase):
    def _read_limit(self, raw):
        env = os.environ.copy()
        env.pop('DATABASE_URL', None)
        env.pop('REDIS_URL', None)
        env['REMOTE_WORKER_MODE'] = '1'
        env['MAX_REMOTE_OUTPUT_MB'] = raw
        result = subprocess.run(
            [sys.executable, '-c', 'from app import local_worker_api2 as api; print(api.MAX_OUTPUT_MB)'],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def _read_worker_ttl(self, raw):
        env = os.environ.copy()
        env.pop('DATABASE_URL', None)
        env.pop('REDIS_URL', None)
        env['REMOTE_WORKER_MODE'] = '1'
        env['WORKER_TOKEN_TTL'] = raw
        result = subprocess.run(
            [sys.executable, '-c', 'from app import local_worker_api2 as api; print(api.TOKEN_TTL)'],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_invalid_remote_output_limit_uses_default(self):
        self.assertEqual(self._read_limit('broken'), '120')

    def test_remote_output_limit_keeps_existing_bounds(self):
        self.assertEqual(self._read_limit('1'), '20')
        self.assertEqual(self._read_limit('999'), '250')

    def test_invalid_worker_token_ttl_uses_default(self):
        self.assertEqual(self._read_worker_ttl('broken'), '86400')

    def test_worker_token_ttl_keeps_existing_bounds(self):
        self.assertEqual(self._read_worker_ttl('1'), '3600')
        self.assertEqual(self._read_worker_ttl('99999999'), '604800')


if __name__ == '__main__':
    unittest.main()
