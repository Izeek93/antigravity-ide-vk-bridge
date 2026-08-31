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

def send_document_to_user(user_id: int, file_path: str, caption: str = ""):
    att = vk.upload_document(user_id, file_path)
    kb = get_main_keyboard(config.is_voice_enabled())
    formatted = format_for_vk(caption) if caption else ""
    return vk.send_message(user_id, formatted, keyboard=kb, attachment=att)

def send_reply_with_optional_voice(user_id: int, text: str, voice_text: str = None):
    # 1. If voice is enabled, synthesize and send voice FIRST or together
    if config.is_voice_enabled():
        vk.set_activity(user_id, "audiomessage")
        speech = voice_text if voice_text else text
        out_ogg = os.path.join(os.path.dirname(__file__), "media", f"vk_reply_{user_id}.ogg")
        os.makedirs(os.path.dirname(out_ogg), exist_ok=True)
        synthesize_voice(speech, out_ogg)
        if os.path.exists(out_ogg) and os.path.getsize(out_ogg) > 0:
            send_voice_to_user(user_id, out_ogg)
            try:
                os.remove(out_ogg)
            except Exception:
                pass

    # 2. Send text message
    send_message_to_user(user_id, text)

if __name__ == "__main__":
    if len(sys.argv) > 2:
        target_uid = int(sys.argv[1])
        if sys.argv[2] == "--doc" and len(sys.argv) > 3:
            doc_file = sys.argv[3]
            doc_caption = " ".join(sys.argv[4:]) if len(sys.argv) > 4 else ""
            send_document_to_user(target_uid, doc_file, doc_caption)
            print(f"Document {doc_file} delivered to VK user {target_uid}!")
        else:
            msg_text = " ".join(sys.argv[2:])
            send_reply_with_optional_voice(target_uid, msg_text)
            print(f"Delivered to VK user {target_uid}!")
    else:
        print("Usage: python send_vk.py <user_id> <message> | python send_vk.py <user_id> --doc <file_path> [caption]")
