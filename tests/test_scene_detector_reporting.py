# -*- coding: utf-8 -*-
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from engine import analysis


class SceneDetectorReportingTests(unittest.TestCase):
    def test_analysis_reports_ffmpeg_when_advanced_detection_falls_back(self):
        ffmpeg_result=SimpleNamespace(stderr='frame=1 pts_time:1.25\n',stdout='')
        with patch.dict(os.environ,{'ADVANCED_SCENE_DETECT':'1'}), \
             patch.object(analysis,'probe',return_value=(5.0,False,[720,1280])), \
             patch.object(analysis,'_pyscenedetect_cuts',return_value=[]), \
             patch.object(analysis,'run',return_value=ffmpeg_result), \
             patch.object(analysis,'candidate_points',return_value=[]):
            result,changed=analysis.analyze_asset(Path('asset.mp4'),'asset-1','asset.mp4','source')

        self.assertTrue(changed)
        self.assertEqual(result['cuts'],[1.25])
        self.assertEqual(result['sceneDetector'],'ffmpeg')

    def test_analysis_reports_pyscenedetect_when_it_supplies_cuts(self):
        with patch.dict(os.environ,{'ADVANCED_SCENE_DETECT':'1'}), \
             patch.object(analysis,'probe',return_value=(5.0,False,[720,1280])), \
             patch.object(analysis,'_pyscenedetect_cuts',return_value=[1.4]), \
             patch.object(analysis,'run') as run_mock, \
             patch.object(analysis,'candidate_points',return_value=[]):
            result,changed=analysis.analyze_asset(Path('asset.mp4'),'asset-1','asset.mp4','source')

        self.assertTrue(changed)
        self.assertEqual(result['cuts'],[1.4])
        self.assertEqual(result['sceneDetector'],'pyscenedetect')
        run_mock.assert_not_called()


if __name__=='__main__':
    unittest.main()
