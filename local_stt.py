"""
vk-bot/local_stt.py
===================
Локальный движок распознавания речи (STT) для VK моста на базе Faster-Whisper.
Работает 100% нативно на Windows (CUDA / CPU) без использования внешних подсистем и WSL.
"""

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
    """Локальная транскрибация аудиофайла через Faster-Whisper."""
    abs_audio = os.path.abspath(audio_path)
    if not os.path.exists(abs_audio):
        raise FileNotFoundError(f"Audio file not found: {abs_audio}")

    try:
        model = _get_direct_whisper_model(model_size)
        segments, info = model.transcribe(abs_audio, language="ru", beam_size=5)
        full_text = " ".join([s.text.strip() for s in segments]).strip()
        return full_text
    except Exception as e:
        print(f"[STT Error] Faster-Whisper failed: {e}", file=sys.stderr)
        raise RuntimeError(f"STT transcription failed: {e}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        sample = sys.argv[1]
        print(f"Testing local STT on {sample}...")
        res = transcribe_local_whisper(sample)
        print(f"Result: {res}")
    else:
        print("Usage: python local_stt.py <path_to_audio_file>")
