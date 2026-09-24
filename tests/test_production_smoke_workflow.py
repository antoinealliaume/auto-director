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
        self.assertIn('CURRENT_MAIN="$(git rev-parse HEAD)"', text)
        self.assertIn('if [ -z "$EXPECTED_COMMIT" ]; then', text)
        self.assertIn('EXPECTED_COMMIT="$CURRENT_MAIN"', text)
        self.assertIn('--expected-commit "$EXPECTED_COMMIT"', text)

    def test_stale_workflow_run_is_skipped_before_waiting_for_render(self):
        text = WORKFLOW.read_text(encoding="utf-8")

        guard = 'elif [ "$EXPECTED_COMMIT" != "$CURRENT_MAIN" ]; then'
        smoke = "python tools/production_smoke.py"
        self.assertIn(guard, text)
        self.assertIn("Skipping stale smoke run", text)
        self.assertIn("exit 0", text)
        self.assertLess(text.index(guard), text.index(smoke))


if __name__ == "__main__":
    unittest.main()
