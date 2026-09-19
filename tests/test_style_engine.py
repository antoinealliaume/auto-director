import unittest

from engine.style_engine import PRESETS, STYLE_NAMES, choose_style, decorate_plan, normalize_style


class StyleEngineTests(unittest.TestCase):
    def sample_plan(self,n=6):
        return {
            'strategy':'speedrun','hook':'Test hook','segments':[
                {'assetId':str(i%2),'start':float(i),'duration':1.2,'zoom':1.02,'caption':'caption' if i%2 else ''}
                for i in range(n)
            ],
        }

    def test_public_styles_have_presets(self):
        self.assertIn('auto',STYLE_NAMES)
        for name in STYLE_NAMES:
            if name!='auto':self.assertIn(name,PRESETS)

    def test_unknown_style_falls_back_to_auto(self):
        self.assertEqual(normalize_style('does-not-exist'),'auto')

    def test_auto_varies_styles_across_variants(self):
        picks={choose_style('auto','speedrun','fast',variant,'aggressive') for variant in range(4)}
        self.assertGreaterEqual(len(picks),3)
        self.assertTrue(picks.issubset({'viral','kinetic','glitch','meme'}))

    def test_explicit_style_is_respected(self):
        self.assertEqual(choose_style('cinematic','speedrun','fast',2,'aggressive'),'cinematic')

    def test_soft_intensity_bounds_speed_and_effects(self):
        styled=decorate_plan(self.sample_plan(),'glitch','story','soft',0)
        self.assertEqual(styled['visualStyle'],'glitch')
        self.assertEqual(styled['styleEngine'],'v9.2')
        self.assertTrue(all(.94<=float(s['speed'])<=1.06 for s in styled['segments']))
        self.assertTrue(all(not s['flash'] for s in styled['segments']))
        self.assertTrue(all(1.005<=float(s['zoom'])<=1.12 for s in styled['segments']))

    def test_aggressive_style_keeps_render_values_bounded(self):
        styled=decorate_plan(self.sample_plan(10),'viral','highlight','aggressive',1)
        self.assertTrue(all(.90<=float(s['speed'])<=1.20 for s in styled['segments']))
        self.assertTrue(all(1.005<=float(s['zoom'])<=1.12 for s in styled['segments']))
        self.assertGreater(styled['styleDiversity'],0)
        for seg in styled['segments']:
            self.assertRegex(seg['accentColor'],r'^[0-9A-F]{6}$')
            self.assertIn(seg['captionStyle'],{'punch','kinetic','subtitle','highlight','neon','meme','minimal'})


if __name__=='__main__':
    unittest.main()
