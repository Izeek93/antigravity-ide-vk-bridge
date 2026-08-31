import time
import threading
import subprocess
import urllib.request
import json
import os

COMFY_PORT = 8188
IDLE_TIMEOUT_SECONDS = 300  # 5 minutes auto-shutdown timeout

_last_activity_time = 0
_watchdog_thread = None
_stop_watchdog = threading.Event()

def is_comfyui_running() -> bool:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{COMFY_PORT}/system_stats")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode())
            return bool(data.get("system", {}).get("comfyui_version"))
    except Exception:
        return False

def touch_activity():
    global _last_activity_time
    _last_activity_time = time.time()
    ensure_watchdog_running()

def free_comfyui_vram():
    """Unload all cached models from VRAM without killing the server."""
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{COMFY_PORT}/free",
            data=json.dumps({"unload_models": True, "free_memory": True}).encode(),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            return True
    except Exception:
        return False

def stop_comfyui_process():
    """Gracefully terminate ComfyUI process on Windows to free all memory & CPU."""
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*ComfyUI_windows_portable*' } | Stop-Process -Force"],
            capture_output=True, text=True
        )
        return True
    except Exception:
        return False

def _watchdog_loop():
    global _last_activity_time
    while not _stop_watchdog.wait(15):
        if is_comfyui_running():
            idle_duration = time.time() - _last_activity_time
            if _last_activity_time > 0 and idle_duration >= IDLE_TIMEOUT_SECONDS:
                print(f"[ModelLifecycle] ComfyUI idle for {int(idle_duration)}s (>= {IDLE_TIMEOUT_SECONDS}s). Auto-stopping...")
                stop_comfyui_process()
                _last_activity_time = 0

def ensure_watchdog_running():
    global _watchdog_thread
    if _watchdog_thread is None or not _watchdog_thread.is_alive():
        _stop_watchdog.clear()
        _watchdog_thread = threading.Thread(target=_watchdog_loop, daemon=True)
        _watchdog_thread.start()

# Start watchdog on import
ensure_watchdog_running()

if __name__ == "__main__":
    print(f"ComfyUI running: {is_comfyui_running()}")
    touch_activity()
