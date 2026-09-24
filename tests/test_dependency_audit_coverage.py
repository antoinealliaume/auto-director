from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = (
    "requirements.txt",
    "self_hosted_worker/requirements-local.txt",
    "self_hosted_worker/requirements-quality.txt",
)


class DependencyAuditCoverageTests(unittest.TestCase):
    def test_ci_audits_every_runtime_manifest(self):
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("Audit runtime dependencies", ci)
        self.assertIn("python -m pip_audit -r", ci)
        for manifest in MANIFESTS:
            self.assertIn(manifest, ci)

    def test_continuous_audit_checks_every_runtime_manifest(self):
        audit = (ROOT / "tools" / "continuous_audit.py").read_text(encoding="utf-8")
        self.assertIn("for manifest in manifests:", audit)
        self.assertIn('[pip_audit, "-r", manifest, "--progress-spinner", "off"]', audit)
        for manifest in MANIFESTS:
            self.assertIn(f'"{manifest}"', audit)


if __name__ == "__main__":
    unittest.main()
