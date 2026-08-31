import os
import sys
import json
import time
import urllib.request
import urllib.parse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APPROVAL_FILE = os.path.join(BASE_DIR, "pending_approval.json")

def request_remote_approval(action_description: str, timeout_sec: float = 120.0) -> dict:
    """
    Creates a pending remote approval request that can be confirmed from Telegram or VK.
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

    # Broadcast approval prompt to Telegram with Inline Keyboard
    try:
        tg_dir = os.path.abspath(os.path.join(BASE_DIR, "..", "tg-bot"))
        if tg_dir not in sys.path:
            sys.path.insert(0, tg_dir)
        from send_tg import send_message
        tg_text = f"🔔 **Запрос подтверждения действия в IDE:**\n\n«{action_description}»\n\nНажмите кнопку ниже или отправьте ответ текстом:"
        tg_inline_kb = {
            "inline_keyboard": [
                [
                    {"text": "✅ Подтвердить", "callback_data": "approve"},
                    {"text": "❌ Отклонить", "callback_data": "reject"}
                ]
            ]
        }
        send_message(tg_text, reply_markup=tg_inline_kb)
    except Exception as e:
        print(f"[Remote Approval TG Error] {e}", file=sys.stderr)

    # Broadcast approval prompt to VK with Inline Keyboard
    try:
        import importlib.util
        vk_dir = os.path.abspath(os.path.join(BASE_DIR, "..", "vk-bot"))
        vk_api_path = os.path.join(vk_dir, "vk_api_client.py")
        vk_cfg_path = os.path.join(vk_dir, "config.py")
        
        spec_cfg = importlib.util.spec_from_file_location("vk_config", vk_cfg_path)
        vk_cfg = importlib.util.module_from_spec(spec_cfg)
        spec_cfg.loader.exec_module(vk_cfg)
        
        target_uid = list(vk_cfg.VK_ALLOWED_USER_IDS)[0] if vk_cfg.VK_ALLOWED_USER_IDS else 14901004
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
        
        # Direct VK API call
        params = {
            "user_id": target_uid,
            "message": vk_text,
            "random_id": int(time.time() * 1000) % (2**31 - 1),
            "keyboard": json.dumps(vk_inline_kb, ensure_ascii=False),
            "v": vk_cfg.VK_API_VERSION,
            "access_token": vk_cfg.VK_GROUP_TOKEN
        }
        encoded = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request("https://api.vk.com/method/messages.send", data=encoded)
        with urllib.request.urlopen(req, timeout=10) as resp:
            pass
    except Exception as e:
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
