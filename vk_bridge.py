import os
import sys
import time
import json
import random
import urllib.request
import urllib.parse
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr.encoding != "utf-8":
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import config
import vk_api_client as vk
from vk_keyboard import get_main_keyboard, get_inline_status_keyboard
from vk_formatter import format_for_vk
from screenshot import capture_desktop
from limits_checker import format_limits_report
from tasks_checker import get_background_tasks_report
from local_stt import transcribe_local_whisper
from voice_engine import synthesize_voice

GROUP_ID = 149687922

def handle_command(user_id: int, text: str) -> bool:
    cmd = text.strip().lower()
    
    if cmd in ("/start", "/help", "помощь", "ℹ️ помощь"):
        help_text = (
            "🤖 Antigravity IDE VK Bridge v1.0\n\n"
            "Доступные команды:\n"
            "• 📊 Лимиты (/limits) — Текущий статус квот и моделей\n"
            "• 📸 Скриншот (/screen) — Снимок экрана рабочего стола\n"
            "• 📋 Задачи (/tasks) — Список активных задач\n"
            "• 🎙 Голос (/voice) — Включение/отключение голосовых ответов\n"
            "• ℹ️ Помощь (/help) — Список команд"
        )
        kb = get_main_keyboard(config.is_voice_enabled())
        vk.send_message(user_id, help_text, keyboard=kb)
        return True

    if cmd in ("/limits", "лимиты", "📊 лимиты", "квоты"):
        vk.set_activity(user_id, "typing")
        report = format_limits_report()
        kb = get_main_keyboard(config.is_voice_enabled())
        vk.send_message(user_id, format_for_vk(report), keyboard=kb)
        return True

    if cmd in ("/screen", "/screenshot", "скриншот", "📸 скриншот", "экран"):
        vk.set_activity(user_id, "photo")
        shot_path = capture_desktop("desktop_vk.png")
        if shot_path and os.path.exists(shot_path):
            att = vk.upload_photo(user_id, shot_path)
            kb = get_main_keyboard(config.is_voice_enabled())
            vk.send_message(user_id, "📸 Снимок экрана рабочего стола ПК:", keyboard=kb, attachment=att)
            try:
                os.remove(shot_path)
            except Exception:
                pass
        else:
            vk.send_message(user_id, "❌ Не удалось сделать снимок экрана.")
        return True

    if cmd in ("/tasks", "задачи", "📋 задачи"):
        vk.set_activity(user_id, "typing")
        report = get_background_tasks_report()
        kb = get_main_keyboard(config.is_voice_enabled())
        vk.send_message(user_id, format_for_vk(report), keyboard=kb)
        return True

    if cmd.startswith("/voice") or "голос" in cmd:
        current = config.is_voice_enabled()
        if "on" in cmd or "вкл" in cmd:
            new_state = True
        elif "off" in cmd or "выкл" in cmd:
            new_state = False
        else:
            new_state = not current
        config.set_voice_enabled(new_state)
        status_str = "ВКЛЮЧЕНО 🎙" if new_state else "ВЫКЛЮЧЕНО 🔇"
        kb = get_main_keyboard(new_state)
        vk.send_message(user_id, f"🎙 Голосовое сопровождение ответов: {status_str}", keyboard=kb)
        return True

    return False

def process_message(msg: dict):
    user_id = msg.get("from_id", msg.get("user_id"))
    text = msg.get("text", "")
    attachments = msg.get("attachments", [])
    
    if not config.is_user_allowed(user_id):
        vk.send_message(user_id, "🔒 Доступ ограничен. Этот бот настроен в приватном режиме.")
        return

    # Handle voice/audio messages
    for att in attachments:
        if att.get("type") == "audio_message":
            audio_data = att["audio_message"]
            audio_url = audio_data.get("link_ogg") or audio_data.get("link_mp3")
            if audio_url:
                vk.set_activity(user_id, "audiomessage")
                local_audio = f"incoming_vk_voice_{int(time.time())}.ogg"
                urllib.request.urlretrieve(audio_url, local_audio)
                stt_text = transcribe_local_whisper(local_audio)
                try:
                    os.remove(local_audio)
                except Exception:
                    pass
                if stt_text:
                    text = f"[🎙 Голосовое сообщение]: {stt_text}"
                else:
                    text = "[🎙 Не удалось распознать голосовое сообщение]"

        elif att.get("type") == "photo":
            photo = att["photo"]
            sizes = photo.get("sizes", [])
            if sizes:
                best_size = sorted(sizes, key=lambda s: s.get("width", 0) * s.get("height", 0))[-1]
                p_url = best_size.get("url")
                if p_url:
                    local_img = f"incoming_vk_photo_{int(time.time())}.png"
                    urllib.request.urlretrieve(p_url, local_img)
                    text = f"[📸 Входящее фото]: сохранено в `{os.path.abspath(local_img)}` с текстом: «{text}»"

    if not text:
        return

    # Check if command
    if handle_command(user_id, text):
        return

    # Forward to IDE and mirror
    print(f"\n=======================================================\n📥 VK INCOMING From user {user_id}:\n    {text}\n=======================================================\n", flush=True)

    # Initial acknowledgement
    kb = get_main_keyboard(config.is_voice_enabled())
    vk.send_message(user_id, "🤖 Принято в работу! Передаю в Antigravity IDE...", keyboard=kb)

def run_longpoll():
    print("🚀 Antigravity IDE VK Bridge daemon starting...", flush=True)
    
    while True:
        try:
            lp_info = vk.call_api("groups.getLongPollServer", {"group_id": GROUP_ID})
            server = lp_info["server"]
            key = lp_info["key"]
            ts = lp_info["ts"]
            print(f"✅ Connected to VK LongPoll server ({server})", flush=True)

            while True:
                url = f"{server}?act=a_check&key={key}&ts={ts}&wait=25"
                try:
                    req = urllib.request.Request(url)
                    with urllib.request.urlopen(req, timeout=35) as response:
                        data = json.loads(response.read().decode("utf-8"))
                except Exception as e:
                    time.sleep(2)
                    break

                if "failed" in data:
                    code = data["failed"]
                    if code == 1:
                        ts = data["ts"]
                    else:
                        break
                    continue

                ts = data.get("ts", ts)
                updates = data.get("updates", [])
                
                for update in updates:
                    ev_type = update.get("type")
                    if ev_type == "message_new":
                        msg_obj = update.get("object", {}).get("message", {})
                        if msg_obj:
                            process_message(msg_obj)

        except Exception as e:
            print(f"⚠️ LongPoll error: {e}. Reconnecting in 5s...", flush=True)
            time.sleep(5)

if __name__ == "__main__":
    run_longpoll()
