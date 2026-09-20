from pathlib import Path
import unittest

from app.worker_diagnostics import diagnostic_state, heartbeat_age_seconds, with_heartbeat_age


ROOT = Path(__file__).resolve().parents[1]


class WorkerDiagnosticsTests(unittest.TestCase):
    def test_heartbeat_age_is_safe_and_non_negative(self):
        self.assertEqual(heartbeat_age_seconds({"updatedAt": 100}, now=112), 12)
        self.assertEqual(heartbeat_age_seconds({"updatedAt": 120}, now=112), 0)
        self.assertIsNone(heartbeat_age_seconds({"updatedAt": "invalid"}, now=112))
        self.assertEqual(with_heartbeat_age({"updatedAt": 100}, now=112)["heartbeatAgeSeconds"], 12)

    def test_diagnostic_states_cover_idle_offline_incompatible_busy_and_ready(self):
        compatible = {"compatible": True}
        worker = {"engine": "9.2"}
        self.assertEqual(diagnostic_state(active=None, compatibility=None, queue_depth=0, retry_depth=0, current_job=None)["level"], "idle")
        self.assertEqual(diagnostic_state(active=None, compatibility=None, queue_depth=1, retry_depth=0, current_job=None)["level"], "offline")
        self.assertEqual(diagnostic_state(active=worker, compatibility={"compatible": False}, queue_depth=0, retry_depth=0, current_job=None)["level"], "incompatible")
        self.assertEqual(diagnostic_state(active=worker, compatibility=compatible, queue_depth=0, retry_depth=0, current_job={"id": "job"})["level"], "busy")
        self.assertEqual(diagnostic_state(active=worker, compatibility=compatible, queue_depth=0, retry_depth=2, current_job=None)["level"], "ready")

    def test_agent_versions_are_consistent_in_all_heartbeat_paths(self):
        worker = (ROOT / "self_hosted_worker/http_worker.py").read_text(encoding="utf-8")
        agent = (ROOT / "self_hosted_worker/local_agent.ps1").read_text(encoding="utf-8")
        status = (ROOT / "app/worker_status.py").read_text(encoding="utf-8")
        self.assertIn("'agentVersion':'2.8'", worker)
        self.assertIn("agentVersion=$AgentVersion", agent)
        self.assertIn("'automaticInstall':False", status)
        self.assertIn("'publicationMode':'manual-only'", status)

    def test_local_agent_tracks_process_handle_and_exit_code(self):
        agent = (ROOT / "self_hosted_worker/local_agent.ps1").read_text(encoding="utf-8")
        self.assertIn("$script:WorkerProcess = $null", agent)
        self.assertIn("$script:WorkerProcess=$proc", agent)
        self.assertIn("$script:WorkerProcess.HasExited", agent)
        self.assertIn("$script:LastExitCode=[int]$script:WorkerProcess.ExitCode", agent)
        self.assertNotIn("Get-Process -Id $script:WorkerPid", agent)

    def test_retry_queue_and_heartbeat_age_are_exposed_to_ui(self):
        server = (ROOT / "app/worker_status.py").read_text(encoding="utf-8")
        browser = (ROOT / "app/static/worker-status.js").read_text(encoding="utf-8")
        self.assertIn("'retryDepth':retry_depth", server)
        self.assertIn("heartbeatAgeSeconds", browser)
        self.assertIn("h.retryDepth", browser)


if __name__ == "__main__":
    unittest.main()
