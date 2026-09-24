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

    def test_model_presence_uses_exact_api_tag_names(self):
        text = LAUNCHER.read_text(encoding='utf-8')
        tags = text.index("$tags=Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags'")
        listed = text.index('$listed=@($tags.models', tags)
        exact = text.index('$listed -contains $model', listed)
        latest = text.index("$listed -contains ($model+':latest')", exact)
        pull = text.index('ollama pull $model', latest)

        self.assertLess(tags, listed)
        self.assertLess(listed, exact)
        self.assertLess(exact, latest)
        self.assertLess(latest, pull)
        self.assertNotIn("-match [regex]::Escape($model)", text)


if __name__ == '__main__':
    unittest.main()
