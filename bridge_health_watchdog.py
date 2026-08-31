import os
import sys
import time
import json
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "tg-bot"))
INBOX_FILE = os.path.join(SHARED_DIR, "inbox.json")
LOCK_FILE = os.path.join(SHARED_DIR, "inbox.lock")
RECEIVER_URL = "http://127.0.0.1:8080"

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
    """Wakes up IDE receiver if messages are waiting in queue without being picked up."""
    if os.path.exists(INBOX_FILE):
        try:
            with open(INBOX_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data and isinstance(data, list):
                    oldest = data[0]
                    ts = oldest.get("timestamp", time.time())
                    if time.time() - ts > max_unprocessed_seconds:
                        try:
                            req = urllib.request.Request(RECEIVER_URL, data=b'{"action":"heal"}')
                            with urllib.request.urlopen(req, timeout=1):
                                pass
                        except Exception:
                            pass
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
