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
import status_tracker

GROUP_ID = config.VK_GROUP_ID
MEDIA_DIR = os.path.join(os.path.dirname(__file__), "media")
os.makedirs(MEDIA_DIR, exist_ok=True)

def ensure_single_instance(script_name: str = "vk_bridge.py"):
    """Гарантирует запуск строго одного экземпляра, принудительно завершая любые старые дубликаты."""
    try:
        import psutil
        current_pid = os.getpid()
        parent_pid = os.getppid()
        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                pid = p.info["pid"]
                if pid in (current_pid, parent_pid):
                    continue
                cmdline = p.info.get("cmdline") or []
                is_target = any(arg.endswith(script_name) for arg in cmdline[1:])
                if is_target and "python" in (p.info.get("name") or "").lower():
                    print(f"⚠️ [SingleInstance] Found old running instance PID {pid}, terminating...", flush=True)
                    p.terminate()
                    try:
                        p.wait(timeout=2)
                    except psutil.TimeoutExpired:
                        p.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception as e:
        print(f"[SingleInstance Warning] {e}", file=sys.stderr)


ensure_single_instance("vk_bridge.py")

from heartbeat_manager import start_typing_heartbeat, stop_typing_heartbeat, stop_all_heartbeats

_message_counter = 0
_CLEANUP_INTERVAL = 50


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


def process_message(msg: dict):
    """Обработка одного входящего сообщения от LongPoll сервера."""
    import importlib
    import status_tracker
    try:
        importlib.reload(status_tracker)
    except Exception:
        pass

    user_id = msg.get("from_id", msg.get("user_id"))
    text = (msg.get("text") or "").strip()
    attachments = msg.get("attachments", [])
    msg_id = msg.get("id") or msg.get("conversation_message_id")

    if not config.is_user_allowed(user_id):
        vk.send_message(user_id, "🔒 Доступ ограничен. Этот бот настроен в приватном режиме.")
        return

    # Мгновенная отметка о прочтении
    vk.mark_as_read(user_id, msg_id)

    # 🚨 Ранний перехват SOS в обход очереди FIFO
    payload_raw = str(msg.get("payload") or "")
    clean_txt = text.lower().strip()
    is_sos_cmd = (
        '"command":"sos"' in payload_raw.replace(" ", "")
        or any(clean_txt == kw or clean_txt.startswith(kw) for kw in ["sos", "сос", "/sos", "/сос", "стоп", "сброс", "отмена", "🚨"])
        or "проверить логи" in clean_txt
    )
    if is_sos_cmd:
        try:
            # 1. Принудительно завершаем любые зависшие тяжелые генерации
            try:
                import psutil
                for p in psutil.process_iter(["name"]):
                    p_name = (p.info.get("name") or "").lower()
                    if any(target in p_name for target in ["omnivoice", "ffmpeg"]):
                        p.kill()
            except Exception:
                pass

            # 2. Немедленно гасим активность и сбрасываем залипшие статусы
            stop_typing_heartbeat(user_id)
            try:
                import status_tracker
                status_tracker.finish_tracking(user_id, final_log="Сброшено по экстренному сигналу SOS.")
            except Exception:
                pass

            # 3. Регистрируем сигнал SOS
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            import sos_manager
            sos_manager.trigger_sos("VK", user_id=user_id)

            # 4. Передаем в очередь inbox.json, чтобы разбудить приёмник в IDE
            push_message({
                "source": "VK_SOS",
                "chat_id": user_id,
                "user_id": user_id,
                "user": f"vk_id{user_id}",
                "text": "🚨 [EMERGENCY SOS] Пользователь нажал кнопку SOS в VK. Задачи и процессы сброшены.",
                "timestamp": time.time()
            })

            # 4. Отправляем пользователю мгновенный прозрачный отчёт
            sos_reply = (
                "🚨 Сигнал SOS успешно принят!\n\n"
                "🛠 Автономная диагностика выполнена:\n"
                "• Зависшие задачи и таймеры статуса принудительно сброшены.\n"
                "• Индикатор активности («набирает сообщение») отключён.\n"
                "• Соединение с VK LongPoll стабильно.\n"
                "• Экстренное прерывание передано агенту в IDE.\n\n"
                "💬 Вы можете отправить новое сообщение или голосовой запрос."
            )
            vk.send_message(user_id, sos_reply)
        except Exception as e:
            print(f"[SOS Error] {e}", file=sys.stderr)
        return

    global _message_counter
    _message_counter += 1
    if _message_counter % _CLEANUP_INTERVAL == 0:
        cleanup_old_media()

    # Обработка вложений
    stt_dur = None
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

    # Инициализация терминального статус-трекера и реакция на входящее сообщение
    try:
        cmid = msg.get("conversation_message_id")
        is_voice = any(att.get("type") == "audio_message" for att in attachments)
        clean_title = text.replace("[🎙 Голосовое сообщение", "").strip()
        if "]:" in clean_title:
            clean_title = clean_title.split("]:", 1)[-1].strip()
        clean_title = clean_title[:45] if clean_title else "Запрос"
        status_tracker.start_tracking(user_id, task_name=clean_title, cmid=cmid, is_voice=is_voice, stt_duration=stt_dur)
    except Exception as e:
        print(f"[StatusTracker Init Error] {e}", file=sys.stderr)

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
            sleep_sec = min(30, 3 + consecutive_errors * 2)
            print(f"⚠️ LongPoll error ({consecutive_errors}): {e}. Reconnecting in {sleep_sec}s...", flush=True)
            if consecutive_errors == 5:
                try:
                    from incident_manager import report_bridge_incident
                    report_bridge_incident("VK_BRIDGE", f"5 consecutive LongPoll failures: {e}")
                except Exception:
                    pass
            time.sleep(sleep_sec)


if __name__ == "__main__":
    run_longpoll()
