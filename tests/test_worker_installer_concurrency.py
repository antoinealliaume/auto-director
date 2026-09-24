from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WorkerInstallerConcurrencyTests(unittest.TestCase):
    def test_installer_serializes_concurrent_updates_before_mutating_shared_paths(self):
        installer = (ROOT / "app/static/Install-AutoDirector.ps1").read_text(encoding="utf-8")

        install_root = installer.index("New-Item -ItemType Directory -Force -Path $InstallRoot")
        lock_path = installer.index("$InstallLockPath=Join-Path $InstallRoot 'install.lock'", install_root)
        lock_open = installer.index("[System.IO.File]::Open($InstallLockPath", lock_path)
        temp_cleanup = installer.index("Remove-Item $TempZip", lock_open)
        download = installer.index("Invoke-WebRequest -Uri $ZipUrl", temp_cleanup)
        backup_cleanup = installer.index("if(Test-Path $Backup){Remove-Item $Backup", download)
        stop = installer.index("Stop-PreviousAutoDirector", backup_cleanup)

        self.assertLess(lock_path, lock_open)
        self.assertLess(lock_open, temp_cleanup)
        self.assertLess(temp_cleanup, download)
        self.assertLess(download, backup_cleanup)
        self.assertLess(backup_cleanup, stop)
        self.assertIn("[System.IO.FileShare]::None", installer[lock_open:temp_cleanup])
        self.assertIn("catch [System.IO.IOException]", installer[lock_path:temp_cleanup])
        self.assertIn("déjà en cours", installer[lock_path:temp_cleanup])


if __name__ == "__main__":
    unittest.main()
