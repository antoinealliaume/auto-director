from datetime import datetime, timezone
from pathlib import Path
import unittest

from app.job_history import serialize_events


ROOT = Path(__file__).resolve().parents[1]


class OperatorExperienceTests(unittest.TestCase):
    def test_job_events_are_serialized_in_api_shape(self):
        when = datetime(2026, 9, 19, 18, 30, tzinfo=timezone.utc)
        self.assertEqual(
            serialize_events([("running", "Rendu démarré", when)]),
            [{"stage": "running", "message": "Rendu démarré", "createdAt": when.isoformat()}],
        )

    def test_timeline_endpoint_is_authenticated_and_bounded(self):
        source = (ROOT / "app/main.py").read_text(encoding="utf-8")
        self.assertIn('@app.get("/api/jobs/{job_id}/events")', source)
        section = source.split('@app.get("/api/jobs/{job_id}/events")', 1)[1].split("class FeedbackIn", 1)[0]
        self.assertIn("require_auth(authorization)", section)
        self.assertIn("limit 200", section.lower())

    def test_frontend_persists_preferences_and_exposes_timeline(self):
        javascript = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
        html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        css = (ROOT / "app/static/operator-experience.css").read_text(encoding="utf-8")
        self.assertIn("auto_director_preferences_v2", javascript)
        self.assertIn("Voir l’historique", javascript)
        self.assertIn("X-Request-ID", javascript)
        self.assertIn('aria-live="polite"', html)
        self.assertIn("prefers-reduced-motion", css)

    def test_ui_contains_no_stale_v9_1_copy(self):
        html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        self.assertNotIn("V9.1", html)
        self.assertIn("publication manuelle", html.lower())


if __name__ == "__main__":
    unittest.main()
