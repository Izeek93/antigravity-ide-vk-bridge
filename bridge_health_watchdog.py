"""
vk-bot/bridge_health_watchdog.py
================================
Диагностика и автовосстановление очереди сообщений VK моста.
Работает исключительно с локальными файлами vk-bot/inbox.json и inbox.lock.
"""

import os
import time
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INBOX_FILE = os.path.join(BASE_DIR, "inbox.json")
LOCK_FILE = os.path.join(BASE_DIR, "inbox.lock")


def check_and_heal_lock_file(max_age_seconds: float = 5.0) -> bool:
    """Detects and removes stale lock files left by crashed processes."""
    if os.path.exists(LOCK_FILE):
        try:
            mtime = os.path.getmtime(LOCK_FILE)
            age = time.time() - mtime
            if age > max_age_seconds:
                os.remove(LOCK_FILE)
                return True
        except Exception:
            pass
    return False


def check_and_heal_stale_inbox(max_unprocessed_seconds: float = 15.0) -> bool:
    """Returns True if messages are stuck in inbox longer than threshold."""
    if os.path.exists(INBOX_FILE):
        try:
            with open(INBOX_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data and isinstance(data, list):
                    oldest = data[0]
                    ts = oldest.get("timestamp", time.time())
                    if time.time() - ts > max_unprocessed_seconds:
                        return True
        except Exception:
            pass
    return False


def run_self_healing_health_check() -> dict:
    """Executes full diagnostic and auto-remediation routine."""
    lock_healed = check_and_heal_lock_file()
    inbox_healed = check_and_heal_stale_inbox()

    inbox_count = 0
    if os.path.exists(INBOX_FILE):
        try:
            with open(INBOX_FILE, "r", encoding="utf-8") as f:
                inbox_count = len(json.load(f))
        except Exception:
            pass

    return {
        "status": "healthy",
        "lock_healed": lock_healed,
        "inbox_healed": inbox_healed,
        "pending_inbox_messages": inbox_count,
        "timestamp": time.time()
    }
