from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "continuous-audit.yml"


class ContinuousAuditWorkflowTests(unittest.TestCase):
    def test_main_push_refreshes_audit_and_fallback_triggers_remain(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        lines = text.splitlines()

        push_index = lines.index("  push:")
        self.assertEqual(lines[push_index + 1].strip(), "branches:")
        self.assertEqual(lines[push_index + 2].strip(), "- main")
        self.assertIn("  schedule:", lines)
        self.assertIn("  workflow_dispatch:", lines)
        self.assertIn("          ref: main", lines)
        self.assertIn("          git switch -C automation/audit-report origin/main", lines)
        self.assertIn('select(.title == "Auto Director Continuous Audit")', text)
        self.assertNotIn(r'select(.title == \"Auto Director Continuous Audit\")', text)

    def test_stale_audit_is_not_published_or_written_to_issue(self):
        text = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("        id: publish_report", text)
        self.assertIn('          audited_sha="$(git rev-parse HEAD)"', text)
        self.assertGreaterEqual(text.count("          git fetch origin main"), 2)
        self.assertGreaterEqual(
            text.count('          if [ "$audited_sha" != "$current_main_sha" ]; then'),
            2,
        )
        self.assertIn('            echo "published=false" >> "$GITHUB_OUTPUT"', text)
        self.assertIn('          echo "published=true" >> "$GITHUB_OUTPUT"', text)
        self.assertIn("        if: steps.publish_report.outputs.published == 'true'", text)

        first_fetch = text.index("          git fetch origin main")
        switch = text.index("          git switch -C automation/audit-report origin/main")
        second_fetch = text.index("          git fetch origin main", first_fetch + 1)
        push = text.index("          git push --force origin automation/audit-report")
        self.assertLess(first_fetch, switch)
        self.assertLess(switch, second_fetch)
        self.assertLess(second_fetch, push)

    def test_publish_does_not_hide_git_commit_failures(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        commit = "          git commit -m 'chore(audit): refresh continuous report [skip ci]'"

        self.assertNotIn(commit + " || true", text)
        self.assertIn("          if ! git diff --cached --quiet; then", text)
        self.assertIn(commit, text)

        add = text.index("          git add audit/AUTO_DIRECTOR_AUDIT.md audit/AUTO_DIRECTOR_AUDIT.json")
        guard = text.index("          if ! git diff --cached --quiet; then")
        commit_index = text.index(commit)
        second_fetch = text.index("          git fetch origin main", text.index("          git fetch origin main") + 1)
        self.assertLess(add, guard)
        self.assertLess(guard, commit_index)
        self.assertLess(commit_index, second_fetch)


if __name__ == "__main__":
    unittest.main()
