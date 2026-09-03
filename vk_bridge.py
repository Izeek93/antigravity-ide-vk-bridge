"""
vk-bot/vk_bridge.py
===================
Основной фоновый сервис-демон VK моста для Antigravity IDE (v1.1.0).
Транспортный уровень ввода-вывода (I/O Pipe):
- Подключается к VK Bots LongPoll API (группа 149687922).
- Принимает текст, войсы (STT через Faster-Whisper), фото и документы.
- Отправляет сервисные команды через command_router.py.
- Сохраняет рабочие сообщения в изолированную FIFO очередь inbox.json.
- Автоматически очищает старые временные файлы из папки media/.
"""

import os
import sys
import time
import json
import urllib.request
import threading

# Принудительный UTF-8 вывод на консоли Windows
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
from command_router import dispatch_command
from queue_manager import push_message
from local_stt import transcribe_local_whisper

GROUP_ID = config.VK_GROUP_ID
MEDIA_DIR = os.path.join(os.path.dirname(__file__), "media")
os.makedirs(MEDIA_DIR, exist_ok=True)

_message_counter = 0
_CLEANUP_INTERVAL = 50
active_heartbeats = {}


def cleanup_old_media(max_age_seconds: int = 86400):
    """Автоматическая очистка временных медиафайлов старше 24 часов."""
    try:
        now = time.time()
        for fname in os.listdir(MEDIA_DIR):
            fpath = os.path.join(MEDIA_DIR, fname)
            if os.path.isfile(fpath) and (now - os.path.getmtime(fpath)) > max_age_seconds:
                try:
                    os.remove(fpath)
                except Exception:
                    pass
    except Exception:
        pass


def start_typing_heartbeat(user_id: int, duration_sec: float = 45.0):
    """Фоновый пульс активности (typing / audiomessage) для обратной связи в VK."""
    stop_typing_heartbeat(user_id)
    stop_event = threading.Event()
    active_heartbeats[user_id] = stop_event

    def heartbeat_worker():
        start_time = time.time()
        while not stop_event.is_set() and (time.time() - start_time) < duration_sec:
            act = "audiomessage" if config.is_voice_enabled() else "typing"
            vk.set_activity(user_id, act)
            stop_event.wait(4.0)

    t = threading.Thread(target=heartbeat_worker, daemon=True)
    t.start()


def stop_typing_heartbeat(user_id: int):
    """Остановка пульса активности."""
    if user_id in active_heartbeats:
        active_heartbeats[user_id].set()
        active_heartbeats.pop(user_id, None)


def process_message(msg: dict):
    """Обработка одного входящего сообщения от LongPoll сервера."""
    user_id = msg.get("from_id", msg.get("user_id"))
    text = (msg.get("text") or "").strip()
    attachments = msg.get("attachments", [])
    msg_id = msg.get("id") or msg.get("conversation_message_id")

    if not config.is_user_allowed(user_id):
        vk.send_message(user_id, "🔒 Доступ ограничен. Этот бот настроен в приватном режиме.")
        return

    # Мгновенная отметка о прочтении
    vk.mark_as_read(user_id, msg_id)

    global _message_counter
    _message_counter += 1
    if _message_counter % _CLEANUP_INTERVAL == 0:
        cleanup_old_media()

    # Обработка вложений
    for att in attachments:
        att_type = att.get("type")

        if att_type == "audio_message":
            audio_data = att["audio_message"]
            audio_url = audio_data.get("link_ogg") or audio_data.get("link_mp3")
            if audio_url:
                vk.set_activity(user_id, "audiomessage")
                local_audio = os.path.join(MEDIA_DIR, f"incoming_vk_voice_{time.time_ns()}.ogg")
                try:
                    urllib.request.urlretrieve(audio_url, local_audio)
                    stt_start = time.time()
                    stt_text = transcribe_local_whisper(local_audio)
                    stt_dur = round(time.time() - stt_start, 1)
                    if stt_text:
                        text = f"[🎙 Голосовое сообщение | STT {stt_dur}с]: {stt_text}"
                    else:
                        text = "[🎙 Не удалось распознать голосовое сообщение]"
                except Exception as e:
                    print(f"[STT Error] {e}", file=sys.stderr)
                    text = "[🎙 Ошибка загрузки голосового сообщения]"
                finally:
                    if os.path.exists(local_audio):
                        try:
                            os.remove(local_audio)
                        except Exception:
                            pass

        elif att_type == "photo":
            photo = att.get("photo", {})
            sizes = photo.get("sizes", [])
            if sizes:
                best_size = sorted(sizes, key=lambda s: s.get("width", 0) * s.get("height", 0))[-1]
                p_url = best_size.get("url")
                if p_url:
                    local_img = os.path.join(MEDIA_DIR, f"incoming_vk_photo_{time.time_ns()}.png")
                    try:
                        urllib.request.urlretrieve(p_url, local_img)
                        cap_str = f" с комментарием: «{text}»" if text else ""
                        text = f"[📸 Входящее фото]: сохранено в `{local_img}`{cap_str}"
                    except Exception as e:
                        print(f"[Photo Download Error] {e}", file=sys.stderr)

        elif att_type == "doc":
            doc = att.get("doc", {})
            d_url = doc.get("url")
            d_title = doc.get("title", f"doc_{time.time_ns()}.dat")
            if d_url:
                local_doc = os.path.join(MEDIA_DIR, f"incoming_{d_title}")
                try:
                    urllib.request.urlretrieve(d_url, local_doc)
                    cap_str = f" с комментарием: «{text}»" if text else ""
                    text = f"[📁 Входящий документ «{d_title}»]: сохранён в `{local_doc}`{cap_str}"
                except Exception as e:
                    print(f"[Doc Download Error] {e}", file=sys.stderr)

    if not text:
        return

    # Проверка служебных команд моста через command_router
    if dispatch_command(user_id, text):
        return

    # Перекладывание в изолированную FIFO-очередь inbox.json для IDE
    print(f"\n📥 [VK INCOMING] User {user_id}: {text}\n", flush=True)
    start_typing_heartbeat(user_id)

    payload = {
        "source": "VK",
        "chat_id": user_id,
        "user_id": user_id,
        "user": f"vk_id{user_id}",
        "text": text,
        "timestamp": time.time()
    }
    push_message(payload)


def run_longpoll():
    """Основной отказоустойчивый цикл LongPoll прослушивания событий VK."""
    print("🚀 Antigravity IDE VK Bridge daemon starting (v1.1.0 Decoupled)...", flush=True)
    consecutive_errors = 0

    while True:
        try:
            lp_info = vk.call_api("groups.getLongPollServer", {"group_id": GROUP_ID})
            server = lp_info["server"]
            key = lp_info["key"]
            ts = lp_info["ts"]
            print(f"✅ Connected to VK LongPoll server ({server})", flush=True)
            consecutive_errors = 0

            while True:
                url = f"{server}?act=a_check&key={key}&ts={ts}&wait=25"
                try:
                    req = urllib.request.Request(url)
                    with urllib.request.urlopen(req, timeout=35) as response:
                        data = json.loads(response.read().decode("utf-8"))
                except Exception:
                    time.sleep(2)
                    break

                consecutive_errors = 0
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
            consecutive_errors += 1
            print(f"⚠️ LongPoll error ({consecutive_errors}/5): {e}. Reconnecting in 5s...", flush=True)
            if consecutive_errors >= 5:
                try:
                    from incident_manager import report_bridge_incident
                    report_bridge_incident("VK_BRIDGE", f"5 consecutive LongPoll failures: {e}")
                except Exception:
                    pass
            time.sleep(5)


if __name__ == "__main__":
    run_longpoll()
