"""
vk-bot/status_tracker.py
========================
Менеджер интерактивных терминальных статус-сообщений для Antigravity IDE в VK.
- Ставит реакцию на входящее сообщение пользователя (messages.sendReaction).
- Отправляет и в реальном времени редактирует статусное сообщение (messages.edit).
- Отображает тайминг, пошаговые индикаторы (STT -> IDE -> TTS -> VK) и логи терминала.
- При завершении фиксирует итоговое время и статус готовности.
"""

import os
import sys
import time
import json
import threading

# Принудительный UTF-8 вывод на консоли Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import vk_api_client as vk

STATUS_FILE = os.path.join(os.path.dirname(__file__), "active_status.json")
_lock = threading.Lock()
_active_tickers = {}

DEFAULT_STEPS = [
    {"key": "STT", "title": "STT", "status": "pending", "desc": "Ожидание аудио"},
    {"key": "IDE", "title": "IDE", "status": "pending", "desc": "Ожидание агента"},
    {"key": "TTS", "title": "TTS", "status": "pending", "desc": "Ожидание синтеза"},
    {"key": "VK", "title": "VK", "status": "pending", "desc": "Ожидание отправки"}
]

try:
    from heartbeat_manager import stop_typing_heartbeat, stop_all_heartbeats
except Exception:
    def stop_typing_heartbeat(user_id: int): pass
    def stop_all_heartbeats(): pass

def stop_all_tickers():
    """Останавливает все фоновые тикеры и пульсы активности."""
    stop_all_heartbeats()

def _load_trackers() -> dict:
    with _lock:
        if os.path.exists(STATUS_FILE):
            try:
                with open(STATUS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

def _save_trackers(data: dict):
    with _lock:
        try:
            with open(STATUS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[StatusTracker Error] Failed to save {STATUS_FILE}: {e}", file=sys.stderr)

def make_progress_bar(percent: int, total_blocks: int = 10) -> str:
    filled = max(0, min(total_blocks, int(round((percent / 100.0) * total_blocks))))
    empty = total_blocks - filled
    return "▰" * filled + "▱" * empty

def format_status_text(tracker: dict) -> str:
    elapsed = round(time.time() - tracker.get("start_time", time.time()), 1)
    is_done = tracker.get("is_done", False)
    task_name = tracker.get("task_name", "Обработка запроса")
    steps = tracker.get("steps", DEFAULT_STEPS)

    # Динамический расчет процента шкалы прогресса
    total_steps = len(steps)
    if is_done:
        percent = 100
    else:
        score = 0.0
        for s in steps:
            st = s.get("status")
            if st == "done":
                score += 1.0
            elif st == "running":
                score += 0.5
        percent = min(95, max(15, int((score / max(1, total_steps)) * 100)))

    bar = make_progress_bar(percent, total_blocks=10)

    header = f"🚀 Antigravity Runner [{elapsed}с]" if is_done else "🚀 Antigravity Runner"
    lines = [
        header,
        f"{bar} {percent}%",
        f"Задача: {task_name}"
    ]

    for step in steps:
        st = step.get("status", "pending")
        if st == "done":
            icon = "✔"
        elif st == "running":
            icon = "⏳"
        elif st == "failed":
            icon = "✖"
        else:
            icon = "○"

        key = step.get("key")
        desc = step.get("desc", "")
        duration = step.get("duration")
        if duration is not None:
            desc_str = f" {desc} ({duration}с)" if desc else f" {duration}с"
        else:
            desc_str = f" {desc}" if desc else ""
        lines.append(f"{icon} {key} ──{desc_str}")

    # Компактный блок подсчета токенов (честный контекст + дельта)
    tokens = tracker.get("tokens")
    if tokens:
        ctx_t = tokens.get("context")
        in_t = tokens.get("in", 0)
        out_t = tokens.get("out", 0)
        tot_t = tokens.get("total", (ctx_t or 0) + in_t + out_t)

        def _fmt(v):
            if v >= 10_000:
                return f"{v/1000:.1f}k"
            return f"{v:,}".replace(",", " ")

        if ctx_t:
            lines.append(f"Токены: 🧠 Контекст {_fmt(ctx_t)} | ⬇️ Вход {_fmt(in_t)} | ⬆️ Ответ {_fmt(out_t)} | Σ {_fmt(tot_t)}")
        else:
            lines.append(f"Токены: ⬇️ {_fmt(in_t)} | ⬆️ {_fmt(out_t)} | Σ {_fmt(tot_t)}")

    if is_done:
        lines.append(f"✨ Завершено за {elapsed}с")
    else:
        last_log = tracker.get("last_log")
        if last_log:
            lines.append(f">_ {last_log}")

    return "\n".join(lines)


def set_tokens(user_id: int, in_tokens: int, out_tokens: int, context_tokens: int = None):
    """Фиксирует количество контекстных, входящих и исходящих токенов в статус-карточке."""
    trackers = _load_trackers()
    tracker = trackers.get(str(user_id))
    if not tracker:
        return

    tracker["tokens"] = {
        "context": int(context_tokens) if context_tokens is not None else None,
        "in": int(in_tokens),
        "out": int(out_tokens),
        "total": int((context_tokens or 0) + in_tokens + out_tokens)
    }
    trackers[str(user_id)] = tracker
    _save_trackers(trackers)

    msg_id = tracker.get("message_id")
    if msg_id:
        new_text = format_status_text(tracker)
        vk.edit_message(user_id, msg_id, new_text)


def start_tracking(user_id: int, task_name: str = "Запрос пользователя", cmid: int = None, is_voice: bool = False, stt_duration: float = None) -> int:
    """Инициализация новой задачи: ставит реакцию и отправляет первое статус-сообщение."""
    # 1. Ставим реакцию на входящее сообщение (👍 = 1)
    if cmid:
        try:
            vk.send_reaction(user_id, cmid, reaction_id=1)
        except Exception:
            pass

    # 2. Инициализируем шаги
    stt_desc = "Голос распознан" if is_voice else "Текстовый ввод"
    steps = [
        {"key": "STT", "title": "STT", "status": "done" if is_voice else "skipped", "desc": stt_desc, "duration": stt_duration},
        {"key": "IDE", "title": "IDE", "status": "running", "desc": "Агент приступил к анализу", "duration": None, "step_start": time.time()},
        {"key": "TTS", "title": "TTS", "status": "pending", "desc": "Ожидание генерации речи", "duration": None},
        {"key": "VK", "title": "VK", "status": "pending", "desc": "Ожидание доставки", "duration": None}
    ]

    tracker = {
        "user_id": user_id,
        "task_name": task_name[:50],
        "start_time": time.time(),
        "is_done": False,
        "steps": steps,
        "last_log": "Initializing agent workspace environment...",
        "message_id": None
    }

    initial_text = format_status_text(tracker)
    msg_id = vk.send_message(user_id, initial_text)
    tracker["message_id"] = msg_id

    trackers = _load_trackers()
    trackers[str(user_id)] = tracker
    _save_trackers(trackers)

    return msg_id


def update_step(user_id: int, step_key: str, status: str, desc: str = None, duration: float = None, log_line: str = None):
    """Обновляет состояние конкретного этапа и редактирует статусное сообщение в VK."""
    trackers = _load_trackers()
    tracker = trackers.get(str(user_id))
    if not tracker:
        return

    for step in tracker.get("steps", []):
        if step.get("key") == step_key:
            step["status"] = status
            if desc:
                step["desc"] = desc
            if duration is not None:
                step["duration"] = round(float(duration), 1)
            break

    if log_line:
        tracker["last_log"] = log_line

    trackers[str(user_id)] = tracker
    _save_trackers(trackers)

    msg_id = tracker.get("message_id")
    if msg_id:
        new_text = format_status_text(tracker)
        vk.edit_message(user_id, msg_id, new_text)


def finish_tracking(user_id: int, final_log: str = "Финальный ответ доставлен в диалог."):
    """Фиксирует успешное завершение всех этапов задачи и гасит индикатор активности."""
    stop_typing_heartbeat(user_id)
    trackers = _load_trackers()
    tracker = trackers.get(str(user_id))
    if not tracker:
        return

    tracker["is_done"] = True
    for step in tracker.get("steps", []):
        if step.get("status") != "skipped":
            step["status"] = "done"

    tracker["last_log"] = final_log
    trackers[str(user_id)] = tracker
    _save_trackers(trackers)

    msg_id = tracker.get("message_id")
    if msg_id:
        new_text = format_status_text(tracker)
        vk.edit_message(user_id, msg_id, new_text)


def start_tts_step(user_id: int, desc: str = "Синтез голосового ответа..."):
    """Переключает статус трекера на фазу TTS: IDE завершено, TTS выполняется."""
    update_step(user_id, "IDE", "done", desc="Анализ и код завершены")
    update_step(user_id, "TTS", "running", desc=desc, log_line="Генерация нейро-голоса (OmniVoice)...")


def start_delivery_step(user_id: int, desc: str = "Отправка в диалог..."):
    """Переключает статус трекера на фазу VK: TTS завершено, VK выполняется."""
    update_step(user_id, "TTS", "done", desc="Голос сгенерирован")
    update_step(user_id, "VK", "running", desc=desc, log_line="Доставка ответа в VK...")

