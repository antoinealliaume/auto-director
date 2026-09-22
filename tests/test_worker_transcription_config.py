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

    def test_invalid_local_ai_limits_do_not_break_import(self):
        env = os.environ.copy()
        env.pop('DATABASE_URL', None)
        env.pop('REDIS_URL', None)
        env.update({
            'REMOTE_WORKER_MODE': '1',
            'LOCAL_VLM_TIMEOUT': 'broken',
            'LOCAL_VLM_IMAGE_WIDTH': '',
            'LOCAL_VLM_MAX_IMAGES': 'nope',
            'LOCAL_VLM_NUM_CTX': '???',
            'LOCAL_VLM_NUM_PREDICT': 'bad',
            'LOCAL_VLM_THREADS': 'invalid',
            'LOCAL_VLM_MIN_FREE_GB': 'NaN-ish',
        })
        code = (
            'from engine import local_ai_adaptive as ai; '
            'print(ai.TIMEOUT, ai.IMAGE_WIDTH, ai.MAX_IMAGES, ai.NUM_CTX, '
            'ai.NUM_PREDICT, ai.NUM_THREADS, ai.MIN_FREE_GB)'
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
        self.assertEqual(result.stdout.strip(), '150.0 448 3 1280 200 2 3.0')

    def test_local_ai_limits_keep_existing_bounds(self):
        env = os.environ.copy()
        env.pop('DATABASE_URL', None)
        env.pop('REDIS_URL', None)
        env.update({
            'REMOTE_WORKER_MODE': '1',
            'LOCAL_VLM_IMAGE_WIDTH': '1',
            'LOCAL_VLM_MAX_IMAGES': '99',
            'LOCAL_VLM_NUM_CTX': '1',
            'LOCAL_VLM_NUM_PREDICT': '999',
            'LOCAL_VLM_THREADS': '99',
            'LOCAL_VLM_MIN_FREE_GB': '0',
        })
        code = (
            'from engine import local_ai_adaptive as ai; '
            'print(ai.IMAGE_WIDTH, ai.MAX_IMAGES, ai.NUM_CTX, ai.NUM_PREDICT, '
            'ai.NUM_THREADS, ai.MIN_FREE_GB)'
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
        self.assertEqual(result.stdout.strip(), '384 4 1024 320 4 2.0')

    def test_invalid_runtime_limits_do_not_break_worker_import(self):
        env = os.environ.copy()
        env.pop('DATABASE_URL', None)
        env.pop('REDIS_URL', None)
        env.update({
            'REMOTE_WORKER_MODE': '1',
            'RENDER_WIDTH': 'broken',
            'RENDER_HEIGHT': '',
            'RENDER_FPS': 'nope',
            'FFMPEG_THREADS': '???',
            'RENDER_CRF': 'bad',
            'MAX_REVISIONS': 'invalid',
            'MOMENT_SAMPLES': 'not-a-number',
            'JOB_TIMEOUT_SECONDS': 'oops',
        })
        code = (
            'from engine import config; '
            'print(config.RENDER_WIDTH, config.RENDER_HEIGHT, config.RENDER_FPS, '
            'config.FFMPEG_THREADS, config.RENDER_CRF, config.MAX_REVISIONS, '
            'config.MOMENT_SAMPLES, config.JOB_TIMEOUT_SECONDS)'
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
        self.assertEqual(result.stdout.strip(), '720 1280 30 2 20 1 7 2700')

    def test_runtime_limits_keep_existing_bounds(self):
        env = os.environ.copy()
        env.pop('DATABASE_URL', None)
        env.pop('REDIS_URL', None)
        env.update({
            'REMOTE_WORKER_MODE': '1',
            'RENDER_WIDTH': '1',
            'RENDER_HEIGHT': '99999',
            'RENDER_FPS': '1',
            'FFMPEG_THREADS': '99',
            'RENDER_CRF': '1',
            'MAX_REVISIONS': '99',
            'MOMENT_SAMPLES': '1',
            'JOB_TIMEOUT_SECONDS': '999999',
        })
        code = (
            'from engine import config; '
            'print(config.RENDER_WIDTH, config.RENDER_HEIGHT, config.RENDER_FPS, '
            'config.FFMPEG_THREADS, config.RENDER_CRF, config.MAX_REVISIONS, '
            'config.MOMENT_SAMPLES, config.JOB_TIMEOUT_SECONDS)'
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
        self.assertEqual(result.stdout.strip(), '480 1920 24 6 18 2 4 14400')

    def test_invalid_cloud_runtime_limits_do_not_break_import(self):
        env = os.environ.copy()
        env.pop('DATABASE_URL', None)
        env.pop('REDIS_URL', None)
        env.update({
            'REMOTE_WORKER_MODE': '1',
            'RENDER_FPS': 'broken',
            'QUEUE_RECOVERY_SECONDS': '',
            'PORT': 'not-a-number',
        })
        code = (
            'from engine import runtime; '
            'print(runtime.RENDER_FPS, runtime.RECOVERY_SECONDS, runtime.PORT)'
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
        self.assertEqual(result.stdout.strip(), '30 60 10000')

    def test_cloud_runtime_limits_stay_bounded(self):
        env = os.environ.copy()
        env.pop('DATABASE_URL', None)
        env.pop('REDIS_URL', None)
        env.update({
            'REMOTE_WORKER_MODE': '1',
            'RENDER_FPS': '99',
            'QUEUE_RECOVERY_SECONDS': '999',
            'PORT': '70000',
        })
        code = (
            'from engine import runtime; '
            'print(runtime.RENDER_FPS, runtime.RECOVERY_SECONDS, runtime.PORT)'
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
        self.assertEqual(result.stdout.strip(), '30 300 65535')


if __name__ == '__main__':
    unittest.main()
