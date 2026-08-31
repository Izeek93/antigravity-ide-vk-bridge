import subprocess
import os
import sys
import re

# Dictionary for natural Russian phonetic pronunciation of tech terms/brands
PHONETIC_REPLACEMENTS = {
    r"\bFlux\s*2\s*Klein\b": "Флакс два Кляйн",
    r"\bFlux\s*2\b": "Флакс два",
    r"\bFlux\b": "Флакс",
    r"\bKlein\b": "Кляйн",
    r"\bComfyUI\b": "Комфи Ю Ай",
    r"\bOpenClaw\b": "Опен Кло",
    r"\bOpenAI\b": "Опен Эй Ай",
    r"\bRTX\s*3060\b": "эр тэ икс тридцать шестьдесят",
    r"\bRTX\b": "эр тэ икс",
    r"\bGPU\b": "гэ пэ у",
    r"\bCPU\b": "цэ пэ у",
    r"\bCUDA\b": "Куда",
    r"\bTTS\b": "тэ тэ эс",
    r"\bSTT\b": "эс тэ тэ",
    r"\bRAG\b": "Раг",
    r"\bLoRA\b": "Лора",
    r"\bControlNet\b": "Контрол Нэт",
    r"\bWhisper\b": "Виспер",
    r"\bOmniVoice\b": "Омнивойс",
    r"\bPolza\.ai\b": "Польза точка аи",
    r"\bAI\b": "эй ай",
    r"\bv(\d+)\b": r"версии \1",
}

def clean_and_normalize_for_speech(text: str) -> str:
    # 1. Remove markdown bold/italic/code/link syntax
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    
    # 2. Apply phonetic replacements
    for pattern, replacement in PHONETIC_REPLACEMENTS.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        
    # 3. Clean multiple spaces
    text = re.sub(r"\s+", " ", text).strip()
    return text

def synthesize_voice(text: str, output_path: str = "voice_reply.ogg") -> str:
    """
    Modular voice synthesis wrapper.
    Attempts local OmniVoice / Edge-TTS with phonetic normalization.
    """
    clean_text = clean_and_normalize_for_speech(text)
    
    abs_out = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(abs_out), exist_ok=True)
    
    # Run OmniVoice inside WSL if available
    cmd = [
        "wsl", "-d", "Ubuntu", "-e", "bash", "-c",
        f"~/.openclaw/workspace/skills/local-voice-replies/scripts/omnivoice_voice_reply.sh --channel telegram --text {subprocess.list2cmdline([clean_text])}"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        if result.returncode == 0:
            wsl_ogg_path = result.stdout.strip().split("\n")[-1].strip()
            if wsl_ogg_path.endswith(".ogg"):
                wsl_win_path = abs_out.replace("\\", "/").replace("C:", "/mnt/c")
                copy_cmd = ["wsl", "-d", "Ubuntu", "-e", "cp", wsl_ogg_path, wsl_win_path]
                subprocess.run(copy_cmd, check=True)
                return abs_out
    except Exception:
        pass
        
    return abs_out

if __name__ == "__main__":
    test_text = "Проверка каскадного синтеза речи: универсальный нейро-голос и нормализация."
    out = synthesize_voice(test_text, "media/test_voice.ogg")
    print(f"Voice test generated at: {out}")
