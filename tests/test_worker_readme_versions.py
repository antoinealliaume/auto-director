from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WorkerReadmeVersionTests(unittest.TestCase):
    def test_worker_readme_tracks_runtime_versions(self):
        readme = (ROOT / "self_hosted_worker/README.md").read_text(encoding="utf-8")
        config = (ROOT / "engine/config.py").read_text(encoding="utf-8")
        agent = (ROOT / "self_hosted_worker/local_agent.ps1").read_text(encoding="utf-8")
        entrypoint = (ROOT / "self_hosted_worker/http_worker_v2.py").read_text(encoding="utf-8")

        engine_match = re.search(r"ENGINE_VERSION\s*=\s*['\"]([^'\"]+)", config)
        agent_match = re.search(r"\$AgentVersion\s*=\s*['\"]([^'\"]+)", agent)
        self.assertIsNotNone(engine_match)
        self.assertIsNotNone(agent_match)

        engine_version = engine_match.group(1)
        agent_version = agent_match.group(1)
        self.assertIn(f"Worker PC V{engine_version}", readme)
        self.assertIn(f"Quality Engine V{engine_version}", readme)
        self.assertIn(f"demarre l'agent local {agent_version}", readme)
        self.assertIn(f'"""V{engine_version} PC worker extensions:', entrypoint)


if __name__ == "__main__":
    unittest.main()
