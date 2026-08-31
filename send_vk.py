import os
import sys
import config
import vk_api_client as vk
from vk_keyboard import get_main_keyboard
from vk_formatter import format_for_vk
from voice_engine import synthesize_voice

def send_message_to_user(user_id: int, text: str):
    kb = get_main_keyboard(config.is_voice_enabled())
    return vk.send_message(user_id, format_for_vk(text), keyboard=kb)

def send_voice_to_user(user_id: int, voice_path: str):
    att = vk.upload_audiomessage(user_id, voice_path)
    kb = get_main_keyboard(config.is_voice_enabled())
    return vk.send_message(user_id, "", keyboard=kb, attachment=att)

def send_reply_with_optional_voice(user_id: int, text: str, voice_text: str = None):
    # 1. Send text
    send_message_to_user(user_id, text)
    
    # 2. Send voice if enabled
    if config.is_voice_enabled():
        vk.set_activity(user_id, "audiomessage")
        speech = voice_text if voice_text else text
        out_ogg = os.path.join(os.path.dirname(__file__), "media", f"vk_reply_{user_id}.ogg")
        os.makedirs(os.path.dirname(out_ogg), exist_ok=True)
        synthesize_voice(speech, out_ogg)
        if os.path.exists(out_ogg):
            send_voice_to_user(user_id, out_ogg)
            try:
                os.remove(out_ogg)
            except Exception:
                pass

if __name__ == "__main__":
    if len(sys.argv) > 2:
        target_uid = int(sys.argv[1])
        msg_text = " ".join(sys.argv[2:])
        send_reply_with_optional_voice(target_uid, msg_text)
        print(f"Delivered to VK user {target_uid}!")
    else:
        print("Usage: python send_vk.py <user_id> <message>")
