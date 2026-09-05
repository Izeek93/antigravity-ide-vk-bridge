import os
import json
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
SETTINGS_PATH = BASE_DIR / "voice_settings.json"

load_dotenv(dotenv_path=ENV_PATH)

VK_GROUP_TOKEN = os.getenv("VK_GROUP_TOKEN", "").strip()
_raw_gid = os.getenv("VK_GROUP_ID", "").strip()
VK_GROUP_ID = int(_raw_gid) if _raw_gid.isdigit() else 0
VK_API_VERSION = "5.199"

VK_APPROVALS_PEER_ID = int(os.getenv("VK_APPROVALS_PEER_ID", "0"))
VK_STORAGE_PEER_ID = int(os.getenv("VK_STORAGE_PEER_ID", "0"))
VK_POST_FOOTER_TEMPLATE = os.getenv("VK_POST_FOOTER_TEMPLATE", "Больше интересного — [club{group_id}|ТУТ] 💡")

# User whitelist
_raw_allowed = os.getenv("VK_ALLOWED_USER_IDS", "").strip()
VK_ALLOWED_USER_IDS = set()
if _raw_allowed:
    for uid in _raw_allowed.split(","):
        uid = uid.strip()
        if uid.isdigit():
            VK_ALLOWED_USER_IDS.add(int(uid))

def is_user_allowed(user_id: int) -> bool:
    if not VK_ALLOWED_USER_IDS:
        return True  # If no whitelist configured, allow all
    return user_id in VK_ALLOWED_USER_IDS

def add_allowed_user(user_id: int):
    VK_ALLOWED_USER_IDS.add(user_id)

def is_voice_enabled() -> bool:
    if SETTINGS_PATH.exists():
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("voice_enabled", True)
        except Exception:
            pass
    env_val = os.getenv("ENABLE_VOICE_REPLIES", "True").strip().lower()
    return env_val in ("true", "1", "yes")

def set_voice_enabled(enabled: bool) -> bool:
    try:
        data = {}
        if SETTINGS_PATH.exists():
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        data["voice_enabled"] = bool(enabled)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False
