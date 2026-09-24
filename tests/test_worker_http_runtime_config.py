import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / 'self_hosted_worker'


class WorkerHttpRuntimeConfigTests(unittest.TestCase):
    def _run(self, poll, renew):
        env = os.environ.copy()
        env['PYTHONPATH'] = str(WORKER)
        env['WORKER_TOKEN'] = 'test-token'
        env['WORKER_POLL_SECONDS'] = poll
        env['WORKER_RENEW_SECONDS'] = renew
        result = subprocess.run(
            [
                sys.executable,
                '-c',
                'import http_worker; print(http_worker.POLL_SECONDS, http_worker.RENEW_SECONDS)',
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_invalid_loop_timing_settings_use_existing_defaults(self):
        self.assertEqual(self._run('broken', ''), '4 10800')

    def test_loop_timing_settings_keep_existing_bounds(self):
        self.assertEqual(self._run('1', '1'), '2 1800')
        self.assertEqual(self._run('99', '999999'), '15 21600')


if __name__ == '__main__':
    unittest.main()
