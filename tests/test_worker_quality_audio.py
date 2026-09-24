import importlib.util
import sys
import types
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / 'self_hosted_worker' / 'quality_enhancer.py'


def load_quality_enhancer():
    spec = importlib.util.spec_from_file_location('worker_quality_enhancer_test_module', MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class WorkerQualityAudioTests(unittest.TestCase):
    def test_asset_failure_does_not_disable_quality_engine(self):
        module = load_quality_enhancer()
        module.ENABLED = True
        module.AUDIO_ENABLED = True
        module._failed = False

        fake_librosa = types.ModuleType('librosa')
        fake_numpy = types.ModuleType('numpy')
        old_librosa = sys.modules.get('librosa')
        old_numpy = sys.modules.get('numpy')
        sys.modules['librosa'] = fake_librosa
        sys.modules['numpy'] = fake_numpy

        def fail_extract(*_args, **_kwargs):
            raise RuntimeError('no audio stream')

        module.run = fail_extract
        try:
            result = module.analyze_audio(Path('silent.mp4'))
        finally:
            if old_librosa is None:
                sys.modules.pop('librosa', None)
            else:
                sys.modules['librosa'] = old_librosa
            if old_numpy is None:
                sys.modules.pop('numpy', None)
            else:
                sys.modules['numpy'] = old_numpy

        self.assertFalse(result['enabled'])
        self.assertEqual(result['error'], 'RuntimeError')
        self.assertTrue(module.enabled())
        self.assertFalse(module._failed)


if __name__ == '__main__':
    unittest.main()
