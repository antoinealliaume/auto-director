import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / 'self_hosted_worker' / 'START_LOCAL_WORKER_WINDOWS.ps1'


class WorkerOllamaBootstrapTests(unittest.TestCase):
    def test_failed_model_pull_disables_local_vlm(self):
        text = LAUNCHER.read_text(encoding='utf-8')
        pull = text.index('ollama pull $model')
        capture = text.index('$pullCode=$LASTEXITCODE', pull)
        guard = text.index('if($pullCode -ne 0)', capture)
        fallback = text.index("$env:LOCAL_VLM_URL=''", guard)

        self.assertLess(pull, capture)
        self.assertLess(capture, guard)
        self.assertLess(guard, fallback)


if __name__ == '__main__':
    unittest.main()
