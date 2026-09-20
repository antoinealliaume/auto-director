from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "production-smoke.yml"


class ProductionSmokeWorkflowTests(unittest.TestCase):
    def test_manual_dispatch_validates_checked_out_main_commit(self):
        text = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:", text)
        self.assertIn("ref: main", text)
        self.assertIn('EXPECTED_COMMIT: ${{ github.event.workflow_run.head_sha }}', text)
        self.assertIn('if [ -z "$EXPECTED_COMMIT" ]; then', text)
        self.assertIn('EXPECTED_COMMIT="$(git rev-parse HEAD)"', text)
        self.assertIn('--expected-commit "$EXPECTED_COMMIT"', text)


if __name__ == "__main__":
    unittest.main()
