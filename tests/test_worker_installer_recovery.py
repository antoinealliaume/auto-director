from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WorkerInstallerRecoveryTests(unittest.TestCase):
    def test_failed_agent_start_restores_previous_repository(self):
        installer = (ROOT / "app/static/Install-AutoDirector.ps1").read_text(encoding="utf-8")

        start_guard = installer.index("try{\n  $proc=[System.Diagnostics.Process]::Start($psi)")
        wait_for_agent = installer.index("$status=Wait-ForAgent", start_guard)
        failure_handler = installer.index("}catch{", wait_for_agent)
        rollback = installer.index("Move-Item $Backup $RepoRoot", failure_handler)

        self.assertLess(wait_for_agent, failure_handler)
        self.assertGreater(rollback, failure_handler)
        self.assertIn("try{Stop-PreviousAutoDirector}catch{}", installer[failure_handler:rollback])
        self.assertIn("version précédente restaurée", installer[rollback:])

    def test_update_stops_orphaned_worker_process_tree(self):
        installer = (ROOT / "app/static/Install-AutoDirector.ps1").read_text(encoding="utf-8")
        stop_start = installer.index("function Stop-PreviousAutoDirector")
        wait_start = installer.index("function Wait-ForAgent", stop_start)
        stop_body = installer[stop_start:wait_start]

        self.assertIn("[regex]::Escape($InstallRoot)", stop_body)
        self.assertIn("run_worker_logged\\.ps1", stop_body)
        self.assertIn("START_LOCAL_WORKER_WINDOWS\\.ps1", stop_body)
        self.assertIn("http_worker\\.py", stop_body)
        self.assertIn("taskkill.exe /PID $p.ProcessId /T /F", stop_body)


if __name__ == "__main__":
    unittest.main()
