import os
import json
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
SETTINGS_PATH = BASE_DIR / "voice_settings.json"

load_dotenv(dotenv_path=ENV_PATH)

VK_GROUP_TOKEN = os.getenv("VK_GROUP_TOKEN", "").strip()
VK_API_VERSION = "5.199"

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
        # Auto-whitelist first user
        VK_ALLOWED_USER_IDS.add(user_id)
        save_allowed_users()
        return True
    return user_id in VK_ALLOWED_USER_IDS

def add_allowed_user(user_id: int):
    VK_ALLOWED_USER_IDS.add(user_id)
    save_allowed_users()

def save_allowed_users():
    pass

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
