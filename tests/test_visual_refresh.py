from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class VisualRefreshTests(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        self.css = (ROOT / "app/static/visual-refresh.css").read_text(encoding="utf-8")

    def test_refresh_stylesheet_is_loaded_last(self):
        styles = re.findall(r'<link rel="stylesheet" href="([^"]+)"', self.html)
        self.assertTrue(styles)
        self.assertEqual(styles[-2], "/static/visual-refresh.css?v=9.4.0")
        self.assertEqual(styles[-1], "/static/studio-polish.css?v=9.4.0")

    def test_refresh_covers_core_workspace_and_mobile_layout(self):
        for selector in (
            ".sidebar", ".topbar", ".hero-v9", ".overview-grid", ".worker-banner",
            ".card", ".source", ".director-card", ".gallery", ".render-card",
        ):
            self.assertIn(selector, self.css)
        self.assertIn("@media (max-width: 760px)", self.css)
        self.assertIn("prefers-reduced-motion", self.css)

    def test_visual_layer_is_self_contained_and_keeps_manual_publication(self):
        self.assertNotRegex(self.css, r"url\(['\"]?https?://")
        self.assertIn("publication manuelle", self.html)
        self.assertNotIn("Publier automatiquement", self.html)


if __name__ == "__main__":
    unittest.main()
