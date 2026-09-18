# -*- coding: utf-8 -*-
import ctypes
import json
import os
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / '.auto_profile.env'


def total_ram_gb():
    try:
        if os.name == 'nt':
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ('dwLength', ctypes.c_ulong),
                    ('dwMemoryLoad', ctypes.c_ulong),
                    ('ullTotalPhys', ctypes.c_ulonglong),
                    ('ullAvailPhys', ctypes.c_ulonglong),
                    ('ullTotalPageFile', ctypes.c_ulonglong),
                    ('ullAvailPageFile', ctypes.c_ulonglong),
                    ('ullTotalVirtual', ctypes.c_ulonglong),
                    ('ullAvailVirtual', ctypes.c_ulonglong),
                    ('sullAvailExtendedVirtual', ctypes.c_ulonglong),
                ]
            s = MEMORYSTATUSEX()
            s.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)):
                return round(s.ullTotalPhys / (1024 ** 3), 1)
        if hasattr(os, 'sysconf'):
            pages = os.sysconf('SC_PHYS_PAGES')
            page_size = os.sysconf('SC_PAGE_SIZE')
            return round((pages * page_size) / (1024 ** 3), 1)
    except Exception:
        pass
    return 0.0


def nvidia_info():
    exe = shutil.which('nvidia-smi')
    if not exe:
        return {'name': '', 'vram_gb': 0.0}
    try:
        p = subprocess.run(
            [exe, '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=8,
        )
        best = {'name': '', 'vram_gb': 0.0}
        for line in (p.stdout or '').splitlines():
            if ',' not in line:
                continue
            name, mem = line.rsplit(',', 1)
            try:
                gb = float(mem.strip()) / 1024.0
            except Exception:
                continue
            if gb > best['vram_gb']:
                best = {'name': name.strip(), 'vram_gb': round(gb, 1)}
        return best
    except Exception:
        return {'name': '', 'vram_gb': 0.0}


def choose_profile(ram, cpu, gpu):
    """Choose a conservative profile. Never auto-select above a 3B VLM or 720p."""
    cpu = max(1, int(cpu or 1))
    vram = float(gpu.get('vram_gb') or 0.0)

    if ram <= 0 or ram < 8 or cpu <= 4:
        name = 'safe-minimal'
        local_ai = False
        ff_threads = 1 if cpu <= 2 else 2
        samples = 4
        revisions = 0
        fps = 24
    elif ram < 12:
        name = 'safe-light'
        local_ai = False
        ff_threads = min(2, max(1, cpu // 2))
        samples = 5
        revisions = 0
        fps = 24
    elif vram >= 6 and ram >= 12 and cpu >= 6:
        name = 'safe-local-ai'
        local_ai = True
        ff_threads = min(3, max(2, cpu // 3))
        samples = 5
        revisions = 1
        fps = 30
    else:
        name = 'safe-balanced'
        local_ai = False
        ff_threads = min(3, max(2, cpu // 3))
        samples = 6
        revisions = 1
        fps = 30

    ai_threads = min(3, max(1, cpu // 4))
    return {
        'PROFILE_NAME': name,
        'LOCAL_AI_AUTO_ENABLED': '1' if local_ai else '0',
        'LOCAL_VLM_MODEL': 'qwen2.5vl:3b',
        'LOCAL_VLM_URL': 'http://127.0.0.1:11434' if local_ai else '',
        'LOCAL_VLM_TIMEOUT': '150',
        'LOCAL_VLM_IMAGE_WIDTH': '448',
        'LOCAL_VLM_MAX_IMAGES': '3',
        'LOCAL_VLM_NUM_CTX': '1280',
        'LOCAL_VLM_NUM_PREDICT': '200',
        'LOCAL_VLM_MIN_FREE_GB': '3.0',
        'LOCAL_VLM_THREADS': str(ai_threads),
        'RENDER_WIDTH': '720',
        'RENDER_HEIGHT': '1280',
        'RENDER_FPS': str(fps),
        'FFMPEG_THREADS': str(ff_threads),
        'MOMENT_SAMPLES': str(samples),
        'MAX_REVISIONS': str(revisions),
        'WORKER_CONCURRENCY': '1',
        'SELF_TEST_ON_START': '0',
        'OLLAMA_NUM_PARALLEL': '1',
        'OLLAMA_MAX_LOADED_MODELS': '1',
        'OLLAMA_MAX_QUEUE': '1',
        'OLLAMA_KEEP_ALIVE': '90s',
    }


def main():
    ram = total_ram_gb()
    cpu = os.cpu_count() or 1
    gpu = nvidia_info()
    profile = choose_profile(ram, cpu, gpu)
    OUT.write_text('\n'.join(f'{k}={v}' for k, v in profile.items()) + '\n', encoding='utf-8')
    report = {
        'profile': profile['PROFILE_NAME'],
        'ramGb': ram if ram > 0 else 'inconnue',
        'cpuThreads': cpu,
        'gpu': gpu['name'] or 'non detecte',
        'vramGb': gpu['vram_gb'],
        'localAI': profile['LOCAL_AI_AUTO_ENABLED'] == '1',
        'model': profile['LOCAL_VLM_MODEL'] if profile['LOCAL_AI_AUTO_ENABLED'] == '1' else 'V8 heuristique',
        'render': f"{profile['RENDER_WIDTH']}x{profile['RENDER_HEIGHT']}@{profile['RENDER_FPS']}",
        'ffmpegThreads': int(profile['FFMPEG_THREADS']),
        'revisions': int(profile['MAX_REVISIONS']),
    }
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
