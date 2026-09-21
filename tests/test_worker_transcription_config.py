import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / 'self_hosted_worker'


class WorkerTranscriptionConfigTests(unittest.TestCase):
    def test_invalid_optional_limits_do_not_break_import(self):
        env = os.environ.copy()
        env['PYTHONPATH'] = str(WORKER)
        env.update({
            'LOCAL_WHISPER_THREADS': 'broken',
            'LOCAL_WHISPER_MAX_SECONDS': 'not-a-number',
            'LOCAL_WHISPER_MAX_SEGMENTS': '',
            'LOCAL_WHISPER_MAX_WORDS': '???',
        })
        code = (
            'import transcription; '
            'print(transcription.CPU_THREADS, transcription.MAX_SECONDS, '
            'transcription.MAX_SEGMENTS, transcription.MAX_WORDS)'
        )
        result = subprocess.run(
            [sys.executable, '-c', code],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '1 90 22 240')

    def test_optional_limits_stay_bounded(self):
        env = os.environ.copy()
        env['PYTHONPATH'] = str(WORKER)
        env.update({
            'LOCAL_WHISPER_THREADS': '99',
            'LOCAL_WHISPER_MAX_SECONDS': '1',
            'LOCAL_WHISPER_MAX_SEGMENTS': '999',
            'LOCAL_WHISPER_MAX_WORDS': '-5',
        })
        code = (
            'import transcription; '
            'print(transcription.CPU_THREADS, transcription.MAX_SECONDS, '
            'transcription.MAX_SEGMENTS, transcription.MAX_WORDS)'
        )
        result = subprocess.run(
            [sys.executable, '-c', code],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '3 15 40 40')


if __name__ == '__main__':
    unittest.main()
