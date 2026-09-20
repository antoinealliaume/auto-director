from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WorkerInstallerRecoveryTests(unittest.TestCase):
    def test_failed_agent_start_restores_previous_repository_and_agent(self):
        installer = (ROOT / "app/static/Install-AutoDirector.ps1").read_text(encoding="utf-8")

        start_guard = installer.index("try{\n  $proc=[System.Diagnostics.Process]::Start($psi)")
        wait_for_agent = installer.index("$status=Wait-ForAgent", start_guard)
        failure_handler = installer.index("}catch{", wait_for_agent)
        rollback = installer.index("Move-Item $Backup $RepoRoot", failure_handler)
        restart = installer.index("$restoredProc=[System.Diagnostics.Process]::Start($psi)", rollback)
        rollback_error = installer.index("Mise à jour annulée ; version précédente restaurée", restart)

        self.assertLess(wait_for_agent, failure_handler)
        self.assertGreater(rollback, failure_handler)
        self.assertGreater(restart, rollback)
        self.assertGreater(rollback_error, restart)
        self.assertIn("try{Stop-PreviousAutoDirector}catch{}", installer[failure_handler:rollback])
        self.assertIn("Agent précédent redémarré après restauration.", installer[restart:rollback_error])
        self.assertIn("Version précédente restaurée, mais son agent n a pas redémarré", installer[restart:rollback_error])

    def test_update_prepares_package_before_stopping_existing_agent(self):
        installer = (ROOT / "app/static/Install-AutoDirector.ps1").read_text(encoding="utf-8")

        python_ready = installer.index('Write-Host "Python valide: $PythonExe"')
        download = installer.index("Invoke-WebRequest -Uri $ZipUrl", python_ready)
        source_validation = installer.index("if(-not(Test-Path $SourceRunner))", download)
        backup_cleanup = installer.index("if(Test-Path $Backup){Remove-Item $Backup", source_validation)
        stop = installer.index("Stop-PreviousAutoDirector", backup_cleanup)
        swap = installer.index("Move-Item $RepoRoot $Backup", stop)

        self.assertLess(download, source_validation)
        self.assertLess(source_validation, backup_cleanup)
        self.assertLess(backup_cleanup, stop)
        self.assertLess(stop, swap)
        self.assertNotIn("Stop-PreviousAutoDirector", installer[python_ready:download])

    def test_update_stops_only_installed_agent_and_orphaned_workers(self):
        installer = (ROOT / "app/static/Install-AutoDirector.ps1").read_text(encoding="utf-8")
        launcher = (ROOT / "self_hosted_worker/START_LOCAL_WORKER_WINDOWS.ps1").read_text(encoding="utf-8")
        stop_start = installer.index("function Stop-PreviousAutoDirector")
        wait_start = installer.index("function Wait-ForAgent", stop_start)
        stop_body = installer[stop_start:wait_start]

        self.assertIn("$rootPattern=[regex]::Escape($InstallRoot)+'[\\\\/]'", stop_body)
        self.assertNotIn("$rootPattern=[regex]::Escape($InstallRoot)\n", stop_body)
        self.assertIn(
            "$_.CommandLine -match $rootPattern -and $_.CommandLine -match 'local_agent\\.ps1'",
            stop_body,
        )
        self.assertIn("run_worker_logged\\.ps1", stop_body)
        self.assertIn("START_LOCAL_WORKER_WINDOWS\\.ps1", stop_body)
        self.assertIn("http_worker\\.py", stop_body)
        self.assertIn("http_worker_v2.py", launcher)
        self.assertIn("http_worker_v2\\.py", stop_body)
        self.assertIn("taskkill.exe /PID $p.ProcessId /T /F", stop_body)


if __name__ == "__main__":
    unittest.main()
