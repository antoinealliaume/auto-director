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

    def test_invalid_quality_audio_limit_does_not_break_import(self):
        env = os.environ.copy()
        env['PYTHONPATH'] = str(WORKER)
        env['QUALITY_AUDIO_MAX_SECONDS'] = 'broken'
        result = subprocess.run(
            [sys.executable, '-c', 'import quality_enhancer; print(quality_enhancer.MAX_SECONDS)'],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '120')

    def test_quality_audio_limit_stays_bounded(self):
        for raw, expected in [('1', '20'), ('999', '180')]:
            with self.subTest(raw=raw):
                env = os.environ.copy()
                env['PYTHONPATH'] = str(WORKER)
                env['QUALITY_AUDIO_MAX_SECONDS'] = raw
                result = subprocess.run(
                    [sys.executable, '-c', 'import quality_enhancer; print(quality_enhancer.MAX_SECONDS)'],
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), expected)


if __name__ == '__main__':
    unittest.main()
