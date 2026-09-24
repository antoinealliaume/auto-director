import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SLIME_ATLAS = ROOT / "slime-atlas-3d"


class SlimeAtlasVersionTests(unittest.TestCase):
    def test_package_version_matches_generated_build_version(self):
        package = json.loads((SLIME_ATLAS / "package.json").read_text(encoding="utf-8"))
        prepare_assets = (SLIME_ATLAS / "prepare-assets.mjs").read_text(encoding="utf-8")
        build = re.search(r"build:'[^']*-v(\d+\.\d+\.\d+)'", prepare_assets)

        self.assertIsNotNone(build, "prepare-assets.mjs must expose a semver build identifier")
        self.assertEqual(package["version"], build.group(1))


if __name__ == "__main__":
    unittest.main()
