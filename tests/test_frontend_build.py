from pathlib import Path
import unittest


ROOT=Path(__file__).resolve().parents[1]


class StaticFrontendBuildTests(unittest.TestCase):
    def test_every_local_static_reference_exists(self):
        html=(ROOT/'app/static/index.html').read_text(encoding='utf-8')
        for name in ('app.js','secure-media.js','worker-status.js','publication.js','style.css','worker-status.css','publication.css','v2-status.css','operator-experience.css'):
            self.assertIn('/static/'+name,html)
            self.assertTrue((ROOT/'app/static'/name).is_file(),name)

    def test_pipeline_stops_for_manual_publication(self):
        html=(ROOT/'app/static/index.html').read_text(encoding='utf-8')
        javascript=(ROOT/'app/static/app.js').read_text(encoding='utf-8')
        self.assertIn('prêt pour publication manuelle',html.lower())
        self.assertIn('Publication exclusivement manuelle',javascript)

    def test_render_workers_do_not_call_platform_publication(self):
        for relative in ('engine/job.py','engine/runtime.py','self_hosted_worker/http_worker.py'):
            source=(ROOT/relative).read_text(encoding='utf-8').lower()
            self.assertNotIn('/api/publications',source,relative)
            self.assertNotIn('/api/tiktok',source,relative)


if __name__ == '__main__':
    unittest.main()
