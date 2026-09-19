from datetime import datetime, timezone
from pathlib import Path
import unittest

from app.job_lifecycle import can_transition, claimable, recoverable
from app.manual_export import export_filename, export_manifest
from tools.production_smoke import validate_health, validate_homepage


ROOT = Path(__file__).resolve().parents[1]


class V21ReleaseTests(unittest.TestCase):
    def test_export_has_clean_filename_and_manual_only_contract(self):
        created = datetime(2026, 9, 19, tzinfo=timezone.utc)
        self.assertEqual(export_filename("Démo / Été", 2, created), "demo-ete_20260919_v2.mp4")
        manifest = export_manifest(
            asset_id="asset-1", project="Démo", source_name="render.mp4", size=12,
            created_at=created, job_id="job-1", score=91.5, strategy="story", variant=2,
        )
        self.assertEqual(manifest["publicationMode"], "manual-only")
        self.assertEqual(manifest["status"], "ready_for_manual_publication")
        self.assertEqual(manifest["downloadEndpoint"], "/api/assets/asset-1/download")

    def test_restart_recovery_then_cancellation_is_safe(self):
        self.assertTrue(claimable("queued"))
        self.assertTrue(can_transition("queued", "claimed"))
        self.assertFalse(claimable("claimed"))
        self.assertTrue(can_transition("claimed", "running"))
        self.assertTrue(recoverable("running", has_live_lease=False, age_seconds=61, timeout_seconds=60))
        self.assertTrue(can_transition("running", "queued"))
        self.assertTrue(can_transition("queued", "cancelled"))
        self.assertFalse(can_transition("cancelled", "running"))

    def test_worker_update_is_explicitly_manual(self):
        status = (ROOT / "app/worker_status.py").read_text(encoding="utf-8")
        agent = (ROOT / "self_hosted_worker/local_agent.ps1").read_text(encoding="utf-8")
        browser = (ROOT / "app/static/worker-status.js").read_text(encoding="utf-8")
        self.assertIn("EXPECTED_AGENT_VERSION = '2.8'", status)
        self.assertIn("'automaticInstall':False", status)
        self.assertIn("$AgentVersion = '2.8'", agent)
        self.assertIn("installation manuelle", browser)

    def test_production_smoke_contract(self):
        healthy = {
            "ok": True, "version": "9.2.2", "releaseCommit": "abcdef123456",
            "publicationMode": "manual-only",
        }
        self.assertEqual(validate_health(healthy, "abcdef1234567890"), [])
        self.assertEqual(validate_homepage("Prêt pour publication manuelle"), [])
        self.assertTrue(validate_health({**healthy, "publicationMode": "automatic"}))
        self.assertTrue(validate_health(healthy, "111111111111"))

    def test_security_versions_are_pinned_to_patched_lines(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("fastapi==0.139.2", requirements)
        self.assertIn("starlette==1.3.1", requirements)
        self.assertIn("cryptography==50.0.1", requirements)

    def test_release_version_is_consistent_across_api_and_ui(self):
        api = (ROOT / "app/v9_api.py").read_text(encoding="utf-8")
        html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        self.assertNotIn("main_module.APP_VERSION='9.2'", api)
        self.assertIn("main_module.APP_VERSION='9.2.2'", api)
        self.assertIn("Studio V9.2.2", html)


if __name__ == "__main__":
    unittest.main()
