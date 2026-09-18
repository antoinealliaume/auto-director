import unittest

from engine.director import choose_plan
from engine.quality import fit_segment, rhythm_duration, sequence_quality, shots_from_cuts


class QualityHelpersTests(unittest.TestCase):
    def test_shots_from_cuts_builds_natural_intervals(self):
        shots=shots_from_cuts(10,[2.0,5.0,7.5])
        self.assertEqual(len(shots),4)
        self.assertEqual(shots[1]['start'],2.0)
        self.assertEqual(shots[-1]['end'],10.0)

    def test_story_segment_prefers_speech_end(self):
        moment={'start':2.2,'speechStart':2.0,'speechEnd':4.1,'shotStart':2.0,'shotEnd':5.0}
        source={'duration':8,'beats':[3.0,4.0,5.0],'onsets':[]}
        fit=fit_segment(moment,source,1.8,5.0,'clean_story')
        self.assertIsNotNone(fit)
        self.assertAlmostEqual(fit['start'],2.0,places=2)
        self.assertAlmostEqual(fit['end'],4.1,places=2)
        self.assertIn('speech_end',fit['alignment'])

    def test_hook_is_faster_than_body(self):
        hook=rhythm_duration(2.0,0.2,18,'tease_payoff','balanced')
        body=rhythm_duration(2.0,8.0,18,'tease_payoff','balanced')
        payoff=rhythm_duration(2.0,15.0,18,'tease_payoff','balanced')
        self.assertLess(hook,body)
        self.assertGreater(payoff,body)

    def test_repeated_source_scores_lower(self):
        repeated=[{'assetId':'a','duration':1.2},{'assetId':'a','duration':1.3},{'assetId':'a','duration':1.4}]
        varied=[{'assetId':'a','duration':1.0,'alignment':['beat_end'],'beatSync':.9},{'assetId':'b','duration':1.35,'alignment':['shot_end'],'beatSync':.8},{'assetId':'a','duration':1.65,'alignment':['speech_end'],'beatSync':.85}]
        self.assertGreater(sequence_quality(varied),sequence_quality(repeated))


class DirectorQualityTests(unittest.TestCase):
    def test_plan_carries_smart_crop_and_never_overruns_source(self):
        sources=[
            {'id':'a','role':'source','duration':8.0,'beats':[1,2,3,4,5,6,7],'onsets':[.9,2.1,4.0,6.0],'moments':[
                {'start':.9,'score':84,'motion':.8,'audio':.7,'focusX':.72,'focusY':.44,'focusConfidence':.8,'shotStart':.5,'shotEnd':2.2},
                {'start':4.0,'score':91,'motion':.9,'audio':.8,'focusX':.68,'focusY':.48,'focusConfidence':.9,'shotStart':3.5,'shotEnd':5.2},
                {'start':6.0,'score':78,'motion':.6,'audio':.5,'focusX':.64,'focusY':.50,'focusConfidence':.6,'shotStart':5.5,'shotEnd':7.4},
            ]},
            {'id':'b','role':'source','duration':9.0,'beats':[1.1,2.1,3.1,4.1,5.1,6.1,7.1,8.1],'onsets':[1.1,3.1,5.1,7.1],'moments':[
                {'start':1.1,'score':87,'motion':.7,'audio':.8,'focusX':.31,'focusY':.46,'focusConfidence':.8,'shotStart':.8,'shotEnd':2.5},
                {'start':3.1,'score':80,'motion':.5,'audio':.7,'focusX':.36,'focusY':.48,'focusConfidence':.7,'shotStart':2.8,'shotEnd':4.7},
                {'start':7.1,'score':89,'motion':.85,'audio':.9,'focusX':.40,'focusY':.52,'focusConfidence':.9,'shotStart':6.7,'shotEnd':8.5},
            ]},
        ]
        plan,_=choose_plan('quality',sources,{'pace':1.6},{'tempo':'dynamic'}, {},12,0,0,'highlight','balanced','auto')
        self.assertTrue(plan['segments'])
        self.assertEqual(plan['qualityEngine'],'shot-speech-beat-aware')
        self.assertTrue(any(abs(float(s.get('focusX',.5))-.5)>.05 for s in plan['segments']))
        durations={s['id']:s['duration'] for s in sources}
        for seg in plan['segments']:
            self.assertLessEqual(float(seg['start'])+float(seg['duration']),durations[seg['assetId']]+.02)


if __name__=='__main__':unittest.main()
