from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class StudioMasterTests(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        self.css = (ROOT / "app/static/studio-master.css").read_text(encoding="utf-8")
        self.js = (ROOT / "app/static/studio-master.js").read_text(encoding="utf-8")

    def test_master_layer_is_loaded_last(self):
        styles = re.findall(r'<link rel="stylesheet" href="([^"]+)"', self.html)
        scripts = re.findall(r'<script src="([^"]+)"', self.html)
        self.assertEqual(styles[-1], "/static/studio-master.css?v=11.0.0")
        self.assertEqual(scripts[-1], "/static/studio-master.js?v=11.0.0")

    def test_ten_distinct_master_modules_exist(self):
        for marker in (
            "commandPalette", "masterSettings", "focusModeBtn", "motionModeBtn",
            "accent-grid", "masterHud", "mobileMasterNav", "scrollProgress",
            "shortcutHelp", "master-dock",
        ):
            self.assertIn(marker, self.html + self.css)
        self.assertIn("Alt 1–6", self.html)
        self.assertIn("MutationObserver", self.js)

    def test_master_layer_is_local_only_and_accessible(self):
        for key in ("ad_master_accent", "ad_master_focus", "ad_master_motion"):
            self.assertIn(key, self.js)
        self.assertNotIn("fetch(", self.js)
        self.assertNotIn("/api/", self.js)
        self.assertNotIn("tiktok", self.js.lower())
        self.assertIn('aria-modal="true"', self.html)
        self.assertIn("prefers-reduced-motion", self.css)
        self.assertIn("@media (max-width:760px)", self.css)
        self.assertNotRegex(self.css, r"https?://")

    def test_manual_only_contract_is_unchanged(self):
        self.assertIn("Aucun envoi automatique", self.html)
        self.assertIn("Publication toujours manuelle", self.html)
        self.assertNotIn("Publier automatiquement", self.html)


if __name__ == "__main__":
    unittest.main()
