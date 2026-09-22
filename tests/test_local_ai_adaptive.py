import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import local_ai_adaptive as local_ai


class LocalAIAdaptiveTests(unittest.TestCase):
    def test_captions_follow_original_segments_after_reorder(self):
        plan = {
            'segments': [
                {'assetId': 'asset-a', 'start': 0, 'duration': 1},
                {'assetId': 'asset-b', 'start': 1, 'duration': 1},
            ]
        }
        response = {
            'preferredOrder': [1, 0],
            'captions': {'0': 'caption alpha', '1': 'caption beta'},
            'hook': 'Hook valide',
        }
        paths = {'asset-a': Path('a.mp4'), 'asset-b': Path('b.mp4')}

        with tempfile.TemporaryDirectory() as td:
            with patch.object(local_ai, 'URL', 'http://127.0.0.1:11434'), \
                 patch.object(local_ai, '_frame', side_effect=lambda src, at, out: out), \
                 patch.object(local_ai, '_chat', return_value=response):
                refined, diag = local_ai.refine_plan('Projet', plan, [], paths, Path(td))

        self.assertEqual(diag['mode'], 'local-vlm')
        self.assertEqual([s['assetId'] for s in refined['segments']], ['asset-b', 'asset-a'])
        self.assertEqual([s.get('caption') for s in refined['segments']], ['caption beta', 'caption alpha'])


if __name__ == '__main__':
    unittest.main()
