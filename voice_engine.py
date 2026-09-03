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
        
    # 3. Clean multiple spaces but preserve explicit paragraphs
    text = text.replace("…", "...")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,.;:!?])([^\s\n,.;:!?])", r"\1 \2", text)
    text = text.strip()
    
    # 4. Split sentences to avoid overflowing the TTS model (max 170 chars per line)
    def split_existing_sentences(t: str) -> list[str]:
        rough = re.split(r"(?<=[.!?…])\s+|\n+", t)
        return [part.strip() for part in rough if part.strip()]

    def split_long_at_existing_commas(sentence: str, max_len: int) -> list[str]:
        if len(sentence) <= max_len:
            return [sentence]
        parts = [p.strip() for p in sentence.split(",")]
        if len(parts) <= 1:
            return [sentence]
        chunks = []
        current = parts[0]
        for part in parts[1:]:
            candidate = f"{current}, {part}"
            if len(candidate) > max_len and len(current) >= 40:
                chunks.append(current.rstrip())
                current = part
            else:
                current = candidate
        if current:
            chunks.append(current.rstrip())
        return chunks

    sentences = []
    for sentence in split_existing_sentences(text):
        sentences.extend(split_long_at_existing_commas(sentence, max_len=170))
        
    return "\n".join(sentences).strip()

def synthesize_voice(text: str, output_path: str = "voice_reply.ogg") -> str:
    """
    Modular voice synthesis wrapper.
    Attempts local OmniVoice with phonetic normalization natively on Windows via omnivoice-tts.exe
    """
    clean_text = clean_and_normalize_for_speech(text)
    
    abs_out = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(abs_out), exist_ok=True)
    
    # Paths for Windows native OmniVoice
    base_dir = os.path.dirname(os.path.abspath(__file__))
    app_exe = os.path.join(base_dir, r"omnivoice-win64\omnivoice-tts.exe")
    model_path = os.path.join(base_dir, r"omnivoice-gguf\models\omnivoice-base-Q8_0.gguf")
    codec_path = os.path.join(base_dir, r"omnivoice-gguf\models\omnivoice-tokenizer-Q8_0.gguf")
    ref_wav = os.path.join(base_dir, r"voice-refs\eva-default-ref.wav")
    ref_txt = os.path.join(base_dir, r"voice-refs\eva-default-ref.txt")
    
    tmp_wav = abs_out + ".tmp.wav"
    tmp_post = abs_out + ".post.wav"
    
    # Run omnivoice-tts natively
    cmd = [
        app_exe,
        "--model", model_path,
        "--codec", codec_path,
        "--lang", "Russian",
        "--instruct", "female, russian accent",
        "--format", "wav16",
        "--ref-wav", ref_wav,
        "--ref-text", ref_txt,
        "-o", tmp_wav
    ]
    
    # Set backend to Vulkan0 to utilize the GPU without needing CUDA toolkit!
    env = os.environ.copy()
    env["GGML_BACKEND"] = "Vulkan0"
    
    try:
        # Run inference
        result = subprocess.run(cmd, input=clean_text, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=600)
        
        if result.returncode == 0 and os.path.exists(tmp_wav):
            # Apply post processing (speed & pitch) via FFmpeg just like in the bash script
            # speed 1.1, pitch 1.04 => atempo = 1.1 / 1.04 = 1.0576923
            atempo = 1.1 / 1.04
            ffmpeg_post = [
                "ffmpeg", "-nostdin", "-y", "-i", tmp_wav,
                "-filter:a", f"asetrate=24000*1.04,aresample=24000,atempo={atempo:.8g}",
                "-ar", "24000", "-ac", "1", tmp_post
            ]
            subprocess.run(ffmpeg_post, capture_output=True, check=True)
            
            # Convert to final Opus OGG format
            ffmpeg_final = [
                "ffmpeg", "-nostdin", "-y", "-i", tmp_post,
                "-ar", "48000", "-ac", "1", "-c:a", "libopus", "-b:a", "64k", abs_out
            ]
            subprocess.run(ffmpeg_final, capture_output=True, check=True)
            
            # Cleanup temp wavs
            try:
                os.remove(tmp_wav)
                os.remove(tmp_post)
            except Exception:
                pass
                
            return abs_out
        else:
            print(f"[voice_engine error] returncode {result.returncode}: {result.stderr}", file=sys.stderr)
    except Exception as e:
        print(f"[voice_engine exception] {e}", file=sys.stderr)
        
    return abs_out

if __name__ == "__main__":
    test_text = "Проверка каскадного синтеза речи: универсальный нейро-голос и нормализация."
    out = synthesize_voice(test_text, "media/test_voice.ogg")
    print(f"Voice test generated at: {out}")
