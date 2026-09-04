"""
vk-bot/local_stt.py
===================
Двухуровневый движок локального распознавания речи (STT) для VK моста:
- Уровень 1: Высокоскоростной GPU Faster-Whisper (CUDA / float16) через WSL (~0.5 сек).
- Уровень 2: Прямой локальный Faster-Whisper (Windows fallback).
"""

import subprocess
import os
import sys

# Ensure UTF-8 output on Windows consoles
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

_cached_model = None

def _get_direct_whisper_model(model_size: str = "large-v3-turbo"):
    global _cached_model
    if _cached_model is not None:
        return _cached_model
        
    try:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        compute_type = "float16" if torch.cuda.is_available() else "int8"
    except Exception:
        device = "cpu"
        compute_type = "int8"
    
    from faster_whisper import WhisperModel
    print(f"[STT] Initializing Faster-Whisper ({model_size}) on {device} ({compute_type})...")
    _cached_model = WhisperModel(model_size, device=device, compute_type=compute_type)
    return _cached_model

def transcribe_local_whisper(audio_path: str, model_size: str = "large-v3-turbo") -> str:
    abs_audio = os.path.abspath(audio_path)
    
    # TIER 1: Try Primary Custom WSL Whisper GPU script (User's primary setup)
    try:
        wsl_audio_path = abs_audio.replace("\\", "/").replace("C:", "/mnt/c")
        script = f"""
import sys
from faster_whisper import WhisperModel

path = "{wsl_audio_path}"
model = WhisperModel("{model_size}", device="cuda", compute_type="float16")
segments, info = model.transcribe(path, language="ru", beam_size=5)
full_text = " ".join([s.text.strip() for s in segments])
print("RESULT:" + full_text)
"""
        cmd = [
            "wsl", "-d", "Ubuntu", "-e", "bash", "-c",
            f"~/.openclaw/workspace/scripts/run-whisper-gpu.sh - <<'PY'\n{script}\nPY"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        if result.returncode == 0:
            for line in result.stdout.split("\n"):
                if line.startswith("RESULT:"):
                    return line.replace("RESULT:", "").strip()
            if result.stdout.strip():
                return result.stdout.strip()
    except Exception as e:
        print(f"[STT Warning] Primary WSL Whisper unavailable, falling back to Direct Faster-Whisper: {e}", file=sys.stderr)
        
    # TIER 2: Direct In-Process Faster-Whisper (Universal Fallback for any PC)
    try:
        model = _get_direct_whisper_model(model_size)
        segments, info = model.transcribe(abs_audio, language="ru", beam_size=5)
        full_text = " ".join([s.text.strip() for s in segments]).strip()
        return full_text
    except Exception as e:
        print(f"[STT Error] Direct Faster-Whisper failed: {e}", file=sys.stderr)
        raise RuntimeError(f"All STT methods failed: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        sample = sys.argv[1]
        print(f"Testing cascade STT on {sample}...")
        res = transcribe_local_whisper(sample)
        print(f"Result: {res}")
    else:
        print("Usage: python local_stt.py <path_to_audio_file>")
