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

    # Remote approval handler for interactive IDE requests
    APPROVAL_AFFIRMATIVE = {"да", "подтверждаю", "разрешаю", "ок", "выполняй", "approve", "/approve", "/yes", "1"}
    APPROVAL_NEGATIVE = {"нет", "отмена", "отклонить", "не надо", "reject", "/reject", "/no", "0"}
    if cmd in APPROVAL_AFFIRMATIVE or cmd in APPROVAL_NEGATIVE:
        try:
            shared_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "shared_ai"))
            if shared_dir not in sys.path:
                sys.path.insert(0, shared_dir)
            from remote_approval_manager import get_pending_approval, resolve_approval
            pending = get_pending_approval()
            if pending:
                decision = cmd in APPROVAL_AFFIRMATIVE
                resolve_approval(decision)
                res_str = "✅ Действие подтверждено! Передано в IDE на исполнение." if decision else "❌ Действие отклонено. Отменено в IDE."
                kb = get_main_keyboard(config.is_voice_enabled())
                vk.send_message(user_id, res_str, keyboard=kb)
                from queue_manager import push_message, trigger_ide_receiver
                push_message({
                    "source": "REMOTE_APPROVAL",
                    "chat_id": user_id,
                    "user_id": user_id,
                    "user": f"vk_id{user_id}",
                    "action": pending.get("action"),
                    "approved": decision,
                    "text": f"[{'✅ ПОДТВЕРЖДЕНО' if decision else '❌ ОТКЛОНЕНО'} через VK]: «{pending.get('action')}»",
                    "timestamp": time.time()
                })
                trigger_ide_receiver()
                return True
        except Exception as e:
            print(f"[Remote Approval Error VK] {e}", file=sys.stderr)
    
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

    if cmd in ("/status", "статус", "/heal", "диагностика", "error", "ошибка"):
        vk.set_activity(user_id, "typing")
        from bridge_health_watchdog import run_self_healing_health_check
        diag = run_self_healing_health_check()
        v_status = "🔊 Включено" if config.is_voice_enabled() else "🔇 Выключено"
        heal_info = "🟢 Без сбоев" if not diag["lock_healed"] and not diag["inbox_healed"] else "🛠 Выполнено автовосстановление"
        msg = (
            "🟢 Antigravity IDE VK Bridge Health\n"
            f"• Статус моста: Active / Healthy\n"
            f"• Самовосстановление: {heal_info}\n"
            f"• Сообщений в очереди: {diag['pending_inbox_messages']}\n"
            f"• Голосовые ответы: {v_status}\n"
            "• STT: Faster-Whisper CUDA\n"
            "• Docs / Files API: Активен\n"
            "• Связь с IDE: 127.0.0.1:8080 (Active)"
        )
        kb = get_main_keyboard(config.is_voice_enabled())
        vk.send_message(user_id, msg, keyboard=kb)
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
            try:
                att = vk.upload_photo(user_id, shot_path)
                kb = get_main_keyboard(config.is_voice_enabled())
                vk.send_message(user_id, "📸 Снимок экрана рабочего стола ПК:", keyboard=kb, attachment=att)
            except Exception as e:
                kb = get_main_keyboard(config.is_voice_enabled())
                vk.send_message(user_id, f"⚠️ Не удалось загрузить снимок экрана: {e}", keyboard=kb)
            finally:
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

    voice_toggle_commands = {
        "/voice", "/voice on", "/voice off",
        "голос", "голос вкл", "голос выкл", "голос on", "голос off",
        "🎙 голос: вкл", "🔇 голос: выкл", "вкл голос", "выкл голос",
        "голос: вкл", "голос: выкл", "голос: включено", "голос: выключено"
    }
    if cmd in voice_toggle_commands or cmd.startswith("/voice "):
        current = config.is_voice_enabled()
        if cmd in ("🎙 голос: вкл", "голос: вкл", "голос вкл", "голос: включено", "вкл голос"):
            new_state = False if current else True
            if "вкл" in cmd and current:
                new_state = False
            elif "выкл" in cmd and not current:
                new_state = True
        elif cmd in ("🔇 голос: выкл", "голос: выкл", "голос выкл", "голос: выключено", "выкл голос"):
            new_state = True
        elif cmd in ("/voice on", "голос on"):
            new_state = True
        elif cmd in ("/voice off", "голос off"):
            new_state = False
        else:
            new_state = not current

        config.set_voice_enabled(new_state)
        status_str = "ВКЛЮЧЕНО 🎙" if new_state else "ВЫКЛЮЧЕНО 🔇"
        kb = get_main_keyboard(new_state)
        vk.send_message(user_id, f"🎙 Голосовое сопровождение ответов: {status_str}", keyboard=kb)
        return True

    return False

import threading

active_heartbeats = {}

def start_typing_heartbeat(user_id: int, duration_sec: float = 45.0):
    stop_typing_heartbeat(user_id)
    stop_event = threading.Event()
    active_heartbeats[user_id] = stop_event

    def heartbeat_worker():
        start_time = time.time()
        while not stop_event.is_set() and time.time() - start_time < duration_sec:
            act = "audiomessage" if config.is_voice_enabled() else "typing"
            vk.set_activity(user_id, act)
            stop_event.wait(4.0)

    t = threading.Thread(target=heartbeat_worker, daemon=True)
    t.start()

def stop_typing_heartbeat(user_id: int):
    if user_id in active_heartbeats:
        active_heartbeats[user_id].set()
        active_heartbeats.pop(user_id, None)

def process_message(msg: dict):
    user_id = msg.get("from_id", msg.get("user_id"))
    text = msg.get("text", "")
    attachments = msg.get("attachments", [])
    msg_id = msg.get("id") or msg.get("conversation_message_id")
    
    if not config.is_user_allowed(user_id):
        vk.send_message(user_id, "🔒 Доступ ограничен. Этот бот настроен в приватном режиме.")
        return

    # Instant mark as read in first 50ms
    vk.mark_as_read(user_id, msg_id)

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

        elif att.get("type") == "doc":
            doc = att["doc"]
            d_url = doc.get("url")
            d_title = doc.get("title", f"incoming_doc_{int(time.time())}")
            if d_url:
                local_doc = os.path.join(os.path.dirname(__file__), "downloads", d_title)
                os.makedirs(os.path.dirname(local_doc), exist_ok=True)
                urllib.request.urlretrieve(d_url, local_doc)
                text = f"[📁 Входящий документ «{d_title}»]: сохранён в `{os.path.abspath(local_doc)}` с комментарием: «{text}»"

    if not text:
        return

    # Check if command
    if handle_command(user_id, text):
        return

    # Forward to IDE and mirror
    print(f"\n=======================================================\n📥 VK INCOMING From user {user_id}:\n    {text}\n=======================================================\n", flush=True)
    
    # Start live typing / audiomessage heartbeat for continuous feedback
    start_typing_heartbeat(user_id)
    
    # Push to unified IDE Queue and trigger receiver
    try:
        from queue_manager import push_message, trigger_ide_receiver
        payload = {
            "source": "VK",
            "chat_id": user_id,
            "user_id": user_id,
            "user": f"vk_id{user_id}",
            "text": text,
            "timestamp": time.time()
        }
        push_message(payload)
        trigger_ide_receiver()
    except Exception as e:
        print(f"[VK Queue Error] {e}", file=sys.stderr)

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
            try:
                from incident_manager import report_bridge_incident
                report_bridge_incident("VK_BRIDGE", str(e))
            except Exception:
                pass
            time.sleep(5)

if __name__ == "__main__":
    run_longpoll()
