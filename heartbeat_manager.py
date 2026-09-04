"""
vk-bot/heartbeat_manager.py
===========================
Управление фоновым пульсом активности («набирает сообщение...» / «записывает голосовое...») в VK.
Обеспечивает непрерывный визуальный статус во время работы агента
и гарантированное мгновенное отключение при отправке ответа или сигнале SOS.
"""

import time
import threading
import config
import vk_api_client as vk

active_heartbeats: dict[int, threading.Event] = {}
_lock = threading.Lock()


def start_typing_heartbeat(user_id: int, duration_sec: float = 600.0):
    """Запускает непрерывный пульс активности «набирает сообщение...» с шагом 4.5 секунды."""
    stop_typing_heartbeat(user_id)
    with _lock:
        stop_event = threading.Event()
        active_heartbeats[user_id] = stop_event

    def heartbeat_worker():
        start_time = time.time()
        print(f"💓 [Heartbeat] Worker started for user {user_id} (duration={duration_sec}s)", flush=True)
        while not stop_event.is_set() and (time.time() - start_time) < duration_sec:
            try:
                ok = vk.set_activity(user_id, "typing")
                # Логируем пульс для наглядного контроля
                status_str = "OK" if ok else "FAIL"
                print(f"💓 [Heartbeat] vk.setActivity(peer_id={user_id}, type='typing') -> {status_str}", flush=True)
            except Exception as e:
                print(f"⚠️ [Heartbeat Error] {e}", flush=True)
            if stop_event.wait(4.5):
                break
        print(f"💓 [Heartbeat] Worker finished for user {user_id}", flush=True)

    t = threading.Thread(target=heartbeat_worker, daemon=True, name=f"heartbeat-{user_id}")
    t.start()


def stop_typing_heartbeat(user_id: int):
    """Мгновенно останавливает пульс активности для пользователя."""
    with _lock:
        event = active_heartbeats.pop(user_id, None)
        if event:
            event.set()
            print(f"💓 [Heartbeat] Stop signal sent for user {user_id}", flush=True)


def stop_all_heartbeats():
    """Останавливает все активные пульсы."""
    with _lock:
        for ev in active_heartbeats.values():
            ev.set()
        active_heartbeats.clear()
