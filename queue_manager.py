"""
vk-bot/queue_manager.py
========================
Потокобезопасная автономная FIFO-очередь сообщений через inbox.json.
Использует portalocker для надёжной OS-level блокировки файлов
(без внешних зависимостей от других проектов).
"""

import os
import json
import portalocker

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INBOX_FILE = os.path.join(BASE_DIR, "inbox.json")
LOCK_FILE = os.path.join(BASE_DIR, "inbox.lock")


def _read_inbox() -> list:
    """Читает текущее содержимое inbox.json (вызывать под локом)."""
    if not os.path.exists(INBOX_FILE):
        return []
    try:
        with open(INBOX_FILE, "r", encoding="utf-8") as f:
            content = json.load(f)
            if isinstance(content, list):
                return content
            if isinstance(content, dict):
                return [content]
    except (json.JSONDecodeError, ValueError, OSError):
        pass
    return []


def _write_inbox(messages: list):
    """Атомарно записывает список сообщений в inbox.json (вызывать под локом)."""
    with open(INBOX_FILE, "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)


def push_message(msg_data: dict):
    """Добавляет сообщение в конец очереди с OS-level блокировкой."""
    with portalocker.Lock(LOCK_FILE, timeout=5, fail_when_locked=False):
        messages = _read_inbox()
        messages.append(msg_data)
        _write_inbox(messages)


def pop_messages() -> list:
    """Извлекает и очищает все сообщения из очереди с OS-level блокировкой."""
    with portalocker.Lock(LOCK_FILE, timeout=5, fail_when_locked=False):
        messages = _read_inbox()
        _write_inbox([])
        return messages
