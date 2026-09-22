import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import local_ai_adaptive as local_ai


class LocalAiFallbackTests(unittest.TestCase):
    def test_missing_frame_falls_back_before_network_call(self):
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / 'missing.jpg'
            with patch.object(local_ai, 'URL', 'http://127.0.0.1:11434'), \
                 patch.object(local_ai, 'MIN_FREE_GB', 0.0), \
                 patch.object(local_ai, 'available_memory_gb', return_value=8.0), \
                 patch.object(local_ai.httpx, 'Client') as client:
                result = local_ai._chat('test', [missing])
        self.assertIsNone(result)
        client.assert_not_called()

    def test_critic_without_frames_keeps_technical_score(self):
        plan = {'hook': 'test', 'segments': [{'duration': 4.0}]}
        with tempfile.TemporaryDirectory() as td, \
             patch.object(local_ai, 'URL', 'http://127.0.0.1:11434'), \
             patch.object(local_ai, '_frame', side_effect=RuntimeError('frame failed')), \
             patch.object(local_ai, '_chat') as chat:
            score, diag = local_ai.critic_video(Path(td) / 'render.mp4', 73.0, plan, Path(td))
        self.assertEqual(score, 73.0)
        self.assertEqual(diag, {'mode': 'technical'})
        chat.assert_not_called()


if __name__ == '__main__':
    unittest.main()
