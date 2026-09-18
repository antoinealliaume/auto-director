import unittest

from engine.director import choose_plan
from self_hosted_worker.detect_profile import choose_profile


class ProfileTests(unittest.TestCase):
    def test_unknown_machine_is_minimal(self):
        p = choose_profile(0, 2, {'vram_gb': 0})
        self.assertEqual(p['PROFILE_NAME'], 'safe-minimal')
        self.assertEqual(p['LOCAL_AI_AUTO_ENABLED'], '0')
        self.assertEqual(p['LOCAL_TRANSCRIBE'], '0')
        self.assertLessEqual(int(p['FFMPEG_THREADS']), 2)

    def test_midrange_machine_stays_conservative(self):
        p = choose_profile(10, 8, {'vram_gb': 0})
        self.assertEqual(p['PROFILE_NAME'], 'safe-light')
        self.assertEqual(p['LOCAL_AI_AUTO_ENABLED'], '0')
        self.assertEqual(p['LOCAL_WHISPER_MODEL'], 'tiny')
        self.assertEqual(p['RENDER_WIDTH'], '720')

    def test_gpu_machine_never_exceeds_safe_limits(self):
        p = choose_profile(32, 16, {'vram_gb': 12})
        self.assertEqual(p['PROFILE_NAME'], 'safe-local-ai')
        self.assertEqual(p['LOCAL_VLM_MODEL'], 'qwen2.5vl:3b')
        self.assertLessEqual(int(p['FFMPEG_THREADS']), 3)
        self.assertLessEqual(int(p['RENDER_FPS']), 30)


class DirectorTests(unittest.TestCase):
    def test_director_returns_bounded_plan(self):
        sources = [
            {'id': 'a', 'role': 'source', 'moments': [
                {'start': 0, 'score': 80, 'motion': .8, 'audio': .5},
                {'start': 3, 'score': 70, 'motion': .5, 'audio': .7},
            ]},
            {'id': 'b', 'role': 'source', 'moments': [
                {'start': 1, 'score': 90, 'motion': .9, 'audio': .8},
                {'start': 4, 'score': 65, 'motion': .4, 'audio': .4},
            ]},
        ]
        plan, sims = choose_plan('test', sources, {'pace': 2.0}, {'tempo': 'balanced'}, {}, 18, 0, 0)
        self.assertTrue(plan['segments'])
        self.assertGreaterEqual(plan['predictedRetention'], 0)
        self.assertLessEqual(plan['predictedRetention'], 100)
        self.assertEqual(len(sims), 5)
        self.assertIn(plan['strategy'], {'tease_payoff','escalation','speedrun','contrast','clean_story'})


if __name__ == '__main__':
    unittest.main()
