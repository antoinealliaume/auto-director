import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'self_hosted_worker'))

from detect_profile import choose_profile


class AdaptiveProfileTests(unittest.TestCase):
    def profile(self, ram, cpu, vram=0):
        return choose_profile(ram, cpu, {'name': 'GPU' if vram else '', 'vram_gb': vram})

    def test_unknown_machine_fails_safe(self):
        p = self.profile(0, 2, 0)
        self.assertEqual(p['PROFILE_NAME'], 'safe-minimal')
        self.assertEqual(p['LOCAL_AI_AUTO_ENABLED'], '0')
        self.assertEqual(p['RENDER_FPS'], '24')
        self.assertLessEqual(int(p['FFMPEG_THREADS']), 1)

    def test_8gb_stays_light(self):
        p = self.profile(8, 8, 0)
        self.assertEqual(p['PROFILE_NAME'], 'safe-light')
        self.assertEqual(p['LOCAL_AI_AUTO_ENABLED'], '0')
        self.assertEqual(p['RENDER_FPS'], '24')

    def test_ram_without_gpu_does_not_force_vlm(self):
        p = self.profile(32, 16, 0)
        self.assertEqual(p['PROFILE_NAME'], 'safe-balanced')
        self.assertEqual(p['LOCAL_AI_AUTO_ENABLED'], '0')
        self.assertEqual(p['RENDER_WIDTH'], '720')

    def test_local_ai_requires_real_margin(self):
        p = self.profile(16, 8, 8)
        self.assertEqual(p['PROFILE_NAME'], 'safe-local-ai')
        self.assertEqual(p['LOCAL_AI_AUTO_ENABLED'], '1')
        self.assertEqual(p['LOCAL_VLM_MODEL'], 'qwen2.5vl:3b')
        self.assertLessEqual(int(p['LOCAL_VLM_MAX_IMAGES']), 3)
        self.assertLessEqual(int(p['FFMPEG_THREADS']), 3)

    def test_never_auto_enables_1080p(self):
        for ram, cpu, vram in [(4,2,0),(8,8,0),(16,8,8),(64,32,24)]:
            p = self.profile(ram,cpu,vram)
            self.assertEqual((p['RENDER_WIDTH'], p['RENDER_HEIGHT']), ('720','1280'))
            self.assertEqual(p['WORKER_CONCURRENCY'], '1')

    def test_hardware_diagnostic_propagates_profile_detection_failure(self):
        script = (ROOT / 'self_hosted_worker' / 'CHECK_MY_PC.bat').read_text(encoding='utf-8')
        self.assertIn('set ERR=%ERRORLEVEL%', script)
        self.assertIn('if not "%ERR%"=="0"', script)
        self.assertIn('exit /b %ERR%', script)
        self.assertLess(script.index('set ERR=%ERRORLEVEL%'), script.index('echo Le profil ci-dessus'))
        self.assertLess(script.index('if not "%ERR%"=="0"'), script.index('echo Le profil ci-dessus'))

    def test_worker_launcher_ignores_stale_auto_profile_after_detection_failure(self):
        script = (ROOT / 'self_hosted_worker' / 'START_LOCAL_WORKER_WINDOWS.ps1').read_text(encoding='utf-8')
        guarded_import = "if($profileCode -eq 0){Import-EnvFile (Join-Path $PSScriptRoot '.auto_profile.env') $true}else{Write-Host 'Profil matériel auto indisponible: profil sûr.'"
        self.assertIn(guarded_import, script)
        self.assertNotIn("if($profileCode -ne 0){Write-Host 'Profil matériel auto indisponible: profil sûr.' -ForegroundColor Yellow};Import-EnvFile", script)


if __name__ == '__main__':
    unittest.main()
