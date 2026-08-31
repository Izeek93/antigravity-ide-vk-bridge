import os
import json
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "tg-bot"))
INBOX_FILE = os.path.join(SHARED_DIR, "inbox.json")
LOCK_FILE = os.path.join(SHARED_DIR, "inbox.lock")
RECEIVER_URL = "http://127.0.0.1:8080"

def _acquire_lock(timeout=2.0):
    start = time.time()
    while time.time() - start < timeout:
        try:
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.close(fd)
            return True
        except FileExistsError:
            time.sleep(0.02)
        except Exception:
            return True
    return False

def _release_lock():
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception:
        pass

def push_message(msg_data: dict):
    _acquire_lock()
    try:
        messages = []
        if os.path.exists(INBOX_FILE):
            try:
                with open(INBOX_FILE, "r", encoding="utf-8") as f:
                    content = json.load(f)
                    if isinstance(content, list):
                        messages = content
                    elif isinstance(content, dict):
                        messages = [content]
            except Exception:
                messages = []
                
        messages.append(msg_data)
        
        with open(INBOX_FILE, "w", encoding="utf-8") as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)
    finally:
        _release_lock()

def trigger_ide_receiver():
    try:
        req = urllib.request.Request(RECEIVER_URL, data=b'{"action":"new_message"}')
        with urllib.request.urlopen(req, timeout=1):
            pass
    except Exception:
        pass
