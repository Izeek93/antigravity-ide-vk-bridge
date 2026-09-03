"""
vk-bot/remote_approval_manager.py
==================================
Менеджер удалённых интерактивных согласований действий в IDE.
Позволяет подтверждать/отклонять опасные операции из диалога ВКонтакте.
Полностью изолирован от других проектов (tg-bot).
"""

import os
import json
import time

import vk_api_client as vk
import config
from vk_keyboard import get_main_keyboard

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APPROVAL_FILE = os.path.join(BASE_DIR, "pending_approval.json")


def request_remote_approval(action_description: str, timeout_sec: float = 120.0) -> dict:
    """
    Creates a pending remote approval request and sends a prompt to VK.
    """
    request_id = f"req_{int(time.time())}"
    data = {
        "request_id": request_id,
        "action": action_description,
        "status": "PENDING",
        "created_at": time.time(),
        "timeout_sec": timeout_sec
    }
    with open(APPROVAL_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Send approval prompt to VK with inline keyboard
    try:
        target_uid = next(iter(config.VK_ALLOWED_USER_IDS)) if config.VK_ALLOWED_USER_IDS else None
        if target_uid:
            vk_text = f"🔔 Запрос подтверждения действия в IDE:\n\n«{action_description}»\n\nНажмите кнопку ниже или отправьте ответ:"
            vk_inline_kb = {
                "inline": True,
                "buttons": [
                    [
                        {"action": {"type": "text", "label": "✅ Подтвердить"}, "color": "positive"},
                        {"action": {"type": "text", "label": "❌ Отклонить"}, "color": "negative"}
                    ]
                ]
            }
            vk.send_message(target_uid, vk_text, keyboard=vk_inline_kb)
    except Exception as e:
        import sys
        print(f"[Remote Approval VK Error] {e}", file=sys.stderr)

    return data


def resolve_approval(decision: bool) -> bool:
    """Resolves the current pending approval request."""
    if os.path.exists(APPROVAL_FILE):
        try:
            with open(APPROVAL_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["status"] = "APPROVED" if decision else "REJECTED"
            data["resolved_at"] = time.time()
            with open(APPROVAL_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            pass
    return False


def get_pending_approval() -> dict:
    if os.path.exists(APPROVAL_FILE):
        try:
            with open(APPROVAL_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("status") == "PENDING":
                    return data
        except Exception:
            pass
    return None
