import tempfile
import unittest
from pathlib import Path

from engine.config import FFMPEG, run
from engine.rendering import XFADE, _assemble_xfade, make_segment
from engine.analysis import probe


class StyleRenderingSmokeTests(unittest.TestCase):
    def _source(self,root:Path):
        src=root/'source.mp4'
        run([
            FFMPEG,'-y',
            '-f','lavfi','-i','testsrc2=size=360x640:rate=24:duration=1.6',
            '-f','lavfi','-i','sine=frequency=440:sample_rate=44100:duration=1.6',
            '-shortest','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p',
            '-c:a','aac','-b:a','96k',str(src),
        ],120)
        return src

    def test_styled_segment_executes_in_ffmpeg(self):
        with tempfile.TemporaryDirectory(prefix='ad_style_test_') as td:
            root=Path(td);src=self._source(root);out=root/'styled.mp4'
            style={
                'speed':1.08,'motionEffect':'drift','colorGrade':'punch',
                'hookVisualStyle':'impact','captionStyle':'punch','accentColor':'FFE45E','flash':True,
            }
            make_segment(src,out,0,.72,1.05,'Hook test','Caption test',.5,.5,style)
            duration,has_audio,res=probe(out)
            self.assertTrue(out.exists() and out.stat().st_size>1000)
            self.assertGreater(duration,.45)
            self.assertTrue(has_audio)
            self.assertEqual(res,[720,1280])

    def test_transition_chain_executes_when_supported(self):
        if not XFADE:self.skipTest('FFmpeg bundle has no xfade/acrossfade')
        with tempfile.TemporaryDirectory(prefix='ad_xfade_test_') as td:
            root=Path(td);src=self._source(root);a=root/'a.mp4';b=root/'b.mp4';out=root/'mix.mp4'
            make_segment(src,a,0,.62,1.03,style={'speed':1.0,'motionEffect':'static','colorGrade':'clean'})
            make_segment(src,b,.55,.62,1.04,style={'speed':1.04,'motionEffect':'push','colorGrade':'cinematic'})
            plan={'segments':[{'transition':'dissolve','transitionDuration':.06},{'transition':'fade','transitionDuration':.06}]}
            _assemble_xfade([a,b],plan,out)
            duration,has_audio,res=probe(out)
            self.assertTrue(out.exists() and out.stat().st_size>1000)
            self.assertGreater(duration,.8)
            self.assertTrue(has_audio)
            self.assertEqual(res,[720,1280])


if __name__=='__main__':
    unittest.main()
