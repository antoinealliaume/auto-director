from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class StudioV10Tests(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        self.css = (ROOT / "app/static/studio-v10.css").read_text(encoding="utf-8")
        self.js = (ROOT / "app/static/studio-v10.js").read_text(encoding="utf-8")

    def test_adaptive_controls_are_present_and_loaded_last(self):
        for control in ("themeToggle", "densityToggle", "sidebarToggle"):
            self.assertIn(f'id="{control}"', self.html)
        styles = re.findall(r'<link rel="stylesheet" href="([^"]+)"', self.html)
        scripts = re.findall(r'<script src="([^"]+)"', self.html)
        self.assertEqual(styles[-2], "/static/studio-v10.css?v=11.0.0")
        self.assertEqual(styles[-1], "/static/studio-master.css?v=11.0.0")
        self.assertEqual(scripts[-2], "/static/studio-v10.js?v=11.0.0")
        self.assertEqual(scripts[-1], "/static/studio-master.js?v=11.0.0")

    def test_three_themes_density_sidebar_and_accessibility(self):
        for selector in (
            '[data-theme="aurora"]', '[data-theme="ember"]',
            '[data-theme="daylight"]', '[data-density="compact"]',
            '[data-sidebar="collapsed"]',
        ):
            self.assertIn(selector, self.css)
        self.assertIn("@media (max-width: 760px)", self.css)
        self.assertIn("prefers-reduced-motion", self.css)

    def test_preferences_are_local_and_visual_only(self):
        for key in ("ad_ui_theme_v10", "ad_ui_density_v10", "ad_ui_sidebar_v10"):
            self.assertIn(key, self.js)
        self.assertNotIn("fetch(", self.js)
        self.assertNotIn("/api/", self.js)
        self.assertNotIn("tiktok", self.js.lower())
        self.assertNotRegex(self.css, r"https?://")
        self.assertNotIn("@import", self.css)

    def test_manual_publication_contract_remains_visible(self):
        self.assertIn("Publication manuelle", self.html)
        self.assertIn("Aucun envoi automatique", self.html)
        self.assertNotIn("Publier automatiquement", self.html)


if __name__ == "__main__":
    unittest.main()
