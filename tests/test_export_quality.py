from datetime import datetime, timezone
from pathlib import Path
import unittest

from app.manual_export import export_manifest


ROOT = Path(__file__).resolve().parents[1]


class ExportQualityTests(unittest.TestCase):
    def test_manifest_exposes_recorded_media_quality_and_integrity(self):
        manifest = export_manifest(
            asset_id="asset", project="Projet", source_name="render.mp4", size=1024,
            created_at=datetime(2026, 9, 19, tzinfo=timezone.utc), job_id="job", score=92,
            strategy="story", variant=1, checksum_sha256="a" * 64,
            metadata={"duration": 18.4, "resolution": [720, 1280], "fps": 24},
        )
        self.assertEqual(manifest["durationSeconds"], 18.4)
        self.assertEqual(manifest["resolution"], [720, 1280])
        self.assertEqual(manifest["fps"], 24)
        self.assertEqual(manifest["checksumSha256"], "a" * 64)
        self.assertEqual(manifest["integrity"], "checksum-available")
        self.assertEqual(manifest["publicationMode"], "manual-only")

    def test_invalid_resolution_is_not_advertised(self):
        manifest = export_manifest(
            asset_id="asset", project="Projet", source_name="render.mp4", size=0,
            created_at=datetime(2026, 9, 19, tzinfo=timezone.utc), job_id=None, score=None,
            strategy=None, variant=1, metadata={"resolution": "720x1280"},
        )
        self.assertIsNone(manifest["resolution"])
        self.assertEqual(manifest["integrity"], "not-recorded")

    def test_gallery_requires_explicit_download_and_offers_filename_copy(self):
        source = (ROOT / "app/static/secure-media.js").read_text(encoding="utf-8")
        self.assertIn("Télécharger la vidéo", source)
        self.assertIn("Copier le nom", source)
        self.assertIn("checksumSha256", source)
        self.assertNotIn("direct-post", source)
        self.assertNotIn("/api/tiktok", source)


if __name__ == "__main__":
    unittest.main()
