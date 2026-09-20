import os
import unittest
from pathlib import Path

os.environ.setdefault('DATABASE_URL','postgresql://unused:unused@127.0.0.1:5432/unused')
os.environ.setdefault('REDIS_URL','redis://127.0.0.1:6379/0')
os.environ.setdefault('STUDIO_PASSWORD','test-only')
os.environ.setdefault('TOKEN_SECRET','test-secret-that-is-long-enough')

from engine.director import choose_plan


def sources():
    return [
        {'id':'a','role':'source','duration':20,'moments':[
            {'start':1,'score':78,'motion':.65,'audio':.4},
            {'start':6,'score':94,'motion':.9,'audio':.8},
            {'start':12,'score':72,'motion':.4,'audio':.7},
        ]},
        {'id':'b','role':'source','duration':16,'moments':[
            {'start':2,'score':86,'motion':.7,'audio':.6},
            {'start':9,'score':68,'motion':.3,'audio':.35},
        ]},
    ]


class V9DirectorTests(unittest.TestCase):
    def test_story_mode_restricts_strategy_family(self):
        plan,sims=choose_plan('demo',sources(),{'pace':2},{'tempo':'balanced'},{},18,0,0,'story','balanced','auto')
        self.assertIn(plan['strategy'],{'clean_story','escalation','tease_payoff'})
        self.assertEqual(len(sims),3)
        self.assertEqual(plan['directorMode'],'story')

    def test_aggressive_intensity_has_shorter_pace(self):
        soft,_=choose_plan('demo',sources(),{'pace':2},{'tempo':'balanced'},{},18,0,0,'fast','soft','auto')
        hard,_=choose_plan('demo',sources(),{'pace':2},{'tempo':'balanced'},{},18,0,0,'fast','aggressive','auto')
        self.assertLess(hard['pace'],soft['pace'])

    def test_direct_hook_is_not_silent_fallback(self):
        plan,_=choose_plan('demo',sources(),{'pace':2},{'tempo':'balanced'},{},18,0,0,'clean','balanced','direct')
        self.assertEqual(plan['hookStyle'],'direct')
        self.assertTrue(plan['hook'])

    def test_segments_never_overrun_source(self):
        plan,_=choose_plan('demo',sources(),{'pace':2},{'tempo':'balanced'},{},18,0,0,'auto','balanced','auto')
        durations={'a':20,'b':16}
        for seg in plan['segments']:
            self.assertLessEqual(seg['start']+seg['duration'],durations[seg['assetId']]+0.001)


class V9RouteTests(unittest.TestCase):
    def test_single_post_jobs_route(self):
        from app.main import app
        routes=[r for r in app.router.routes if getattr(r,'path',None)=='/api/jobs' and 'POST' in (getattr(r,'methods',set()) or set())]
        self.assertEqual(len(routes),1)

    def test_v9_meta_route_exists(self):
        from app.main import app
        paths={getattr(r,'path',None) for r in app.router.routes}
        self.assertIn('/api/v9/meta',paths)

    def test_retry_does_not_write_null_critic_score(self):
        source=Path('app/main.py').read_text(encoding='utf-8')
        self.assertIn('critic_score=0',source)
        self.assertNotIn('critic_score=null',source)

    def test_api_version_metadata_is_v9_2_1(self):
        source=Path('app/main.py').read_text(encoding='utf-8')
        self.assertIn('APP_VERSION = "11.0.0"',source)
        self.assertIn('ENGINE_VERSION = "9.2"',source)
        self.assertIn('"ai": "director-v9.2-style"',source)
        self.assertNotIn('V8.7 keeps PostgreSQL',source)


if __name__=='__main__':
    unittest.main()
