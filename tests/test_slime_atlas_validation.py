import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SLIME = ROOT / "slime-atlas-3d"


class SlimeAtlasValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        cls.npm = shutil.which("npm")
        if not cls.node or not cls.npm:
            raise unittest.SkipTest("Node.js/npm are required for Slime Atlas validation")

    def test_slime_atlas_node_sources_parse(self):
        sources = [
            *SLIME.glob("*.js"),
            *SLIME.glob("*.mjs"),
            *(SLIME / "v4").glob("*.js"),
            *(SLIME / "tests").glob("*.mjs"),
        ]
        self.assertTrue(sources, "Slime Atlas JavaScript sources should be present")
        for source in sorted(sources):
            with self.subTest(source=source.relative_to(ROOT)):
                proc = subprocess.run(
                    [self.node, "--check", str(source)],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_slime_atlas_node_suite_passes(self):
        proc = subprocess.run(
            [self.npm, "test", "--prefix", str(SLIME)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=90,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
