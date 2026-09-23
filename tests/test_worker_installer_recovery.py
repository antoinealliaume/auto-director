from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WorkerInstallerRecoveryTests(unittest.TestCase):
    def test_post_swap_setup_failure_restores_previous_repository_and_agent(self):
        installer = (ROOT / "app/static/Install-AutoDirector.ps1").read_text(encoding="utf-8")

        post_swap = installer.index("$Agent=Join-Path $RepoRoot 'self_hosted_worker\\local_agent.ps1'")
        psi_setup = installer.index("$psi=New-Object System.Diagnostics.ProcessStartInfo", post_swap)
        start_guard = installer.index("try{\n  [Environment]::SetEnvironmentVariable", psi_setup)
        persist_python = installer.index("[Environment]::SetEnvironmentVariable('AUTO_DIRECTOR_PYTHON'", start_guard)
        startup_file = installer.index("Set-Content -Path $StartupCmd", persist_python)
        start_agent = installer.index("$proc=[System.Diagnostics.Process]::Start($psi)", startup_file)
        wait_for_agent = installer.index("$status=Wait-ForAgent", start_agent)
        failure_handler = installer.index("}catch{", wait_for_agent)
        rollback = installer.index("Move-Item $Backup $RepoRoot", failure_handler)
        restart = installer.index("$restoredProc=[System.Diagnostics.Process]::Start($psi)", rollback)
        settle = installer.index("Start-Sleep -Milliseconds 1200", restart)
        exit_check = installer.index("if($restoredProc.HasExited)", settle)
        rollback_error = installer.index("Mise à jour annulée ; version précédente restaurée", exit_check)

        self.assertLess(psi_setup, start_guard)
        self.assertLess(start_guard, persist_python)
        self.assertLess(persist_python, startup_file)
        self.assertLess(startup_file, start_agent)
        self.assertLess(start_agent, wait_for_agent)
        self.assertLess(wait_for_agent, failure_handler)
        self.assertGreater(rollback, failure_handler)
        self.assertGreater(restart, rollback)
        self.assertGreater(settle, restart)
        self.assertGreater(exit_check, settle)
        self.assertGreater(rollback_error, exit_check)
        self.assertIn("try{Stop-PreviousAutoDirector}catch{}", installer[failure_handler:rollback])
        self.assertIn("L agent précédent s est arrêté immédiatement après restauration.", installer[restart:rollback_error])
        self.assertIn("Agent précédent redémarré après restauration.", installer[restart:rollback_error])
        self.assertIn("Version précédente restaurée, mais son agent n a pas redémarré", installer[restart:rollback_error])

    def test_repository_swap_failure_restores_previous_repository_and_agent(self):
        installer = (ROOT / "app/static/Install-AutoDirector.ps1").read_text(encoding="utf-8")

        swap_start = installer.index("try{\n  if(Test-Path $RepoRoot){Move-Item $RepoRoot $Backup}")
        move_new_repo = installer.index("Move-Item $Source $RepoRoot", swap_start)
        failure_handler = installer.index("}catch{", move_new_repo)
        backup_guard = installer.index("if(Test-Path $Backup)", failure_handler)
        remove_partial = installer.index("if(Test-Path $RepoRoot){Remove-Item $RepoRoot -Recurse -Force}", backup_guard)
        rollback = installer.index("Move-Item $Backup $RepoRoot", remove_partial)
        restart = installer.index("$restoredProc=[System.Diagnostics.Process]::Start($restoredPsi)", rollback)
        settle = installer.index("Start-Sleep -Milliseconds 1200", restart)
        exit_check = installer.index("if($restoredProc.HasExited)", settle)
        rollback_error = installer.index("Mise à jour annulée ; version précédente restaurée après échec du remplacement", exit_check)

        self.assertLess(move_new_repo, failure_handler)
        self.assertLess(backup_guard, remove_partial)
        self.assertLess(remove_partial, rollback)
        self.assertLess(rollback, restart)
        self.assertLess(restart, settle)
        self.assertLess(settle, exit_check)
        self.assertLess(exit_check, rollback_error)
        self.assertIn("$restoredAgent=Join-Path $RepoRoot 'self_hosted_worker\\local_agent.ps1'", installer[rollback:restart])
        self.assertIn("L agent précédent s est arrêté immédiatement après restauration.", installer[restart:rollback_error])
        self.assertIn("Agent précédent redémarré après échec du remplacement.", installer[restart:rollback_error])
        self.assertIn("Installation interrompue pendant le remplacement du dépôt", installer[failure_handler:])

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
        status_probe = stop_body.index("$status=Invoke-RestMethod -Method Get -Uri $AgentStatusUrl")
        root_check = stop_body.index("([string]$status.installRoot) -eq $InstallRoot", status_probe)
        graceful_stop = stop_body.index("Invoke-RestMethod -Method Post -Uri $AgentStopUrl", root_check)
        self.assertLess(status_probe, root_check)
        self.assertLess(root_check, graceful_stop)
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

        wait_after_kill = stop_body.index("Start-Sleep -Milliseconds 900")
        verify_remaining = stop_body.index("$remaining=Get-CimInstance Win32_Process -ErrorAction Stop", wait_after_kill)
        fail_closed = stop_body.index("Impossible d arrêter complètement l ancienne installation Auto Director", verify_remaining)
        self.assertLess(wait_after_kill, verify_remaining)
        self.assertLess(verify_remaining, fail_closed)
        self.assertIn("local_agent\\.ps1", stop_body[verify_remaining:fail_closed])
        self.assertIn("run_worker_logged\\.ps1", stop_body[verify_remaining:fail_closed])
        self.assertIn("START_LOCAL_WORKER_WINDOWS\\.ps1", stop_body[verify_remaining:fail_closed])
        self.assertIn("http_worker\\.py", stop_body[verify_remaining:fail_closed])
        self.assertIn("http_worker_v2\\.py", stop_body[verify_remaining:fail_closed])

    def test_wait_for_agent_requires_expected_install_root(self):
        installer = (ROOT / "app/static/Install-AutoDirector.ps1").read_text(encoding="utf-8")
        wait_start = installer.index("function Wait-ForAgent")
        main_start = installer.index("Write-Host '=== Auto Director", wait_start)
        wait_body = installer[wait_start:main_start]

        version_check = wait_body.index("[version]$lastVersion -ge $ExpectedAgentVersion")
        root_check = wait_body.index("[string]$status.installRoot -eq $InstallRoot")
        return_status = wait_body.index("return $status")
        self.assertLess(version_check, return_status)
        self.assertLess(root_check, return_status)

    def test_installer_finds_all_supported_system_python_installs(self):
        installer = (ROOT / "app/static/Install-AutoDirector.ps1").read_text(encoding="utf-8")
        resolver = installer.split("function Resolve-RealPython", 1)[1].split("function Stop-PreviousAutoDirector", 1)[0]

        self.assertIn("Get-ChildItem $env:ProgramFiles -Directory -Filter 'Python3*'", resolver)
        self.assertIn("'-3.14'", resolver)
        self.assertIn("'-3.10'", resolver)
        self.assertIn("sys.version_info >= (3,10)", installer)

    def test_bootstrap_keeps_temp_path_out_of_powershell_source(self):
        bootstrap = (ROOT / "app/static/INSTALL_AUTO_DIRECTOR_WORKER.bat").read_text(encoding="utf-8")
        download_line = next(line for line in bootstrap.splitlines() if "Invoke-WebRequest" in line)

        self.assertIn("-OutFile (Join-Path $env:TEMP 'Install-AutoDirector.ps1')", download_line)
        self.assertNotIn("-OutFile '%PS1%'", download_line)
        self.assertIn('set "PS1=%TEMP%\\Install-AutoDirector.ps1"', bootstrap)
        self.assertIn('-File "%PS1%"', bootstrap)


if __name__ == "__main__":
    unittest.main()
