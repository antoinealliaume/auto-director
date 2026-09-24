import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SlimeAtlasDependencySecurityTests(unittest.TestCase):
    def test_fflate_is_pinned_to_zip64_dos_fix(self):
        package = json.loads((ROOT / "slime-atlas-3d" / "package.json").read_text(encoding="utf-8"))
        version = package.get("dependencies", {}).get("fflate", "")
        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
        self.assertIsNotNone(match, "fflate must stay exactly pinned for reproducible builds")
        self.assertGreaterEqual(
            tuple(int(part) for part in match.groups()),
            (0, 8, 3),
            "fflate < 0.8.3 is affected by CVE-2026-45820 (malformed ZIP64 DoS)",
        )


if __name__ == "__main__":
    unittest.main()
