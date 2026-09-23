from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WorkerInstallerStartupTests(unittest.TestCase):
    def test_startup_batch_does_not_embed_user_specific_paths(self):
        installer = (ROOT / "app/static/Install-AutoDirector.ps1").read_text(encoding="utf-8")
        agent = (ROOT / "self_hosted_worker/local_agent.ps1").read_text(encoding="utf-8")
        startup_line = next(line for line in installer.splitlines() if "AutoDirectorLocalAgent.cmd" in line)
        cmd_expression = startup_line.split("$cmd=", 1)[1].split(";Set-Content", 1)[0]

        self.assertIn("[Environment]::SetEnvironmentVariable('AUTO_DIRECTOR_PYTHON',$PythonExe,'User')", installer)
        self.assertIn("%LOCALAPPDATA%\\AutoDirector\\repo\\self_hosted_worker\\local_agent.ps1", startup_line)
        self.assertNotIn("AUTO_DIRECTOR_PYTHON=$PythonExe", startup_line)
        self.assertNotIn("$Agent", startup_line)
        self.assertIn("-Encoding ASCII", startup_line)
        self.assertTrue(cmd_expression.isascii())
        self.assertIn("GetEnvironmentVariable('AUTO_DIRECTOR_PYTHON','User')", agent)


if __name__ == "__main__":
    unittest.main()
