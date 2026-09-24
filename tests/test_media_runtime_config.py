import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MediaRuntimeConfigTests(unittest.TestCase):
    def _read_media_ttl(self, value):
        env = os.environ.copy()
        env['MEDIA_TICKET_TTL'] = value
        result = subprocess.run(
            [sys.executable, '-c', 'from app import media_api; print(media_api.MEDIA_TTL)'],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_invalid_media_ticket_ttl_uses_existing_default(self):
        self.assertEqual(self._read_media_ttl('not-a-number'), '1800')
        self.assertEqual(self._read_media_ttl(''), '1800')

    def test_media_ticket_ttl_keeps_existing_bounds(self):
        self.assertEqual(self._read_media_ttl('1'), '300')
        self.assertEqual(self._read_media_ttl('99999'), '3600')


if __name__ == '__main__':
    unittest.main()
