from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ProductUiTests(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        self.css = (ROOT / "app/static/studio-polish.css").read_text(encoding="utf-8")
        self.js = (ROOT / "app/static/studio-polish.js").read_text(encoding="utf-8")

    def test_creation_ribbon_explains_manual_flow(self):
        for step in ("Préparer", "Produire", "Vérifier", "Exporter"):
            self.assertIn(step, self.html)
        self.assertIn("Aucun envoi automatique", self.html)
        self.assertIn('data-quick-tab="publication"', self.html)

    def test_polish_covers_every_major_workspace(self):
        for selector in (
            ".studio-ribbon", ".section-title", ".job-card", ".gallery",
            ".render-card", ".dashboard-grid", ".feedback-grid", ".publish-layout",
        ):
            self.assertIn(selector, self.css)
        self.assertIn("prefers-reduced-motion", self.css)
        self.assertIn("minmax(0, 1fr)", self.css)

    def test_behavior_layer_is_visual_only(self):
        self.assertNotIn("fetch(", self.js)
        self.assertNotIn("/api/", self.js)
        self.assertNotIn("tiktok", self.js.lower())
        self.assertIn("aria-current", self.js)
        self.assertIn("IntersectionObserver", self.js)

    def test_no_remote_design_dependency(self):
        self.assertNotIn("http://", self.css)
        self.assertNotIn("https://", self.css)
        self.assertNotIn("@import", self.css)


if __name__ == "__main__":
    unittest.main()
