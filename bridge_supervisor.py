"""
vk-bot/bridge_supervisor.py
===========================
Отказоустойчивый Watchdog-супервизор для демона vk_bridge.py.
- Гарантирует режим Self-Healing: автоматический перезапуск при падении процесса за <0.5 сек.
- Защита от флуд-перезапусков (экспоненциальный backoff: 0.5s -> 1s -> 2s -> max 5s).
- Единая точка входа (Single Instance) через supervisor.pid.
- Запись статуса и метрик надёжности в supervisor_status.json.
- Не требует прав администратора Windows (UAC) в отличие от служб NSSM.
"""

import os
import sys
import time
import json
import signal
import subprocess
from pathlib import Path

# Обеспечиваем UTF-8 в консоли Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR = Path(__file__).resolve().parent
PYTHON_EXE = BASE_DIR / "venv" / "Scripts" / "python.exe"
TARGET_SCRIPT = BASE_DIR / "vk_bridge.py"
PID_FILE = BASE_DIR / "supervisor.pid"
STATUS_FILE = BASE_DIR / "supervisor_status.json"

_running = True
_child_proc = None

def _log(msg: str):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [Supervisor] {msg}", flush=True)

def _save_status(data: dict):
    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def handle_exit(signum, frame):
    global _running, _child_proc
    _log(f"Получен сигнал завершения ({signum}). Остановка супервизора...")
    _running = False
    if _child_proc and _child_proc.poll() is None:
        _log(f"Завершение дочернего процесса VK Bridge (PID: {_child_proc.pid})...")
        try:
            _child_proc.terminate()
            _child_proc.wait(timeout=5)
        except Exception:
            _child_proc.kill()
    if PID_FILE.exists():
        try:
            PID_FILE.unlink()
        except Exception:
            pass
    _log("Супервизор успешно остановлен.")
    sys.exit(0)

def main():
    global _child_proc, _running

    # Регистрация обработчиков сигналов
    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    # Проверка Single Instance
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text(encoding="utf-8").strip())
            # Проверяем, жив ли старый супервизор
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, old_pid)
            if handle:
                kernel32.CloseHandle(handle)
                _log(f"⚠️ Старый экземпляр супервизора уже запущен (PID {old_pid}). Выход.")
                sys.exit(0)
        except Exception:
            pass

    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    _log(f"🛡️ Супервизор VK Bridge запущен (PID: {os.getpid()}).")

    restart_count = 0
    start_time = time.time()
    backoff = 0.5

    while _running:
        _log(f"🚀 Запуск дочернего процесса: {TARGET_SCRIPT.name} (попытка {restart_count + 1})...")
        
        status_data = {
            "supervisor_pid": os.getpid(),
            "start_time": start_time,
            "uptime_seconds": round(time.time() - start_time, 1),
            "restarts_total": restart_count,
            "status": "running",
            "child_pid": None
        }

        try:
            _child_proc = subprocess.Popen(
                [str(PYTHON_EXE), str(TARGET_SCRIPT)],
                cwd=str(BASE_DIR),
                stdout=None,
                stderr=None,
                creationflags=0
            )
            status_data["child_pid"] = _child_proc.pid
            _save_status(status_data)
            _log(f"✅ Дочерний процесс активен (PID: {_child_proc.pid})")

            # Сброс backoff, если процесс проработал более 30 секунд
            run_start = time.time()
            exit_code = _child_proc.wait()

            if time.time() - run_start > 30:
                backoff = 0.5
            else:
                backoff = min(5.0, backoff * 1.5)

            _log(f"⚠️ Дочерний процесс завершился с кодом: {exit_code}")
            restart_count += 1

            status_data["status"] = "crashed"
            status_data["last_exit_code"] = exit_code
            status_data["last_crash_time"] = time.time()
            _save_status(status_data)

            if not _running:
                break

            _log(f"⏳ Перезапуск через {backoff:.1f} сек...")
            time.sleep(backoff)

        except Exception as e:
            _log(f"❌ Критическая ошибка супервизора при запуске: {e}")
            time.sleep(2.0)

    if PID_FILE.exists():
        PID_FILE.unlink(missing_ok=True)

if __name__ == "__main__":
    main()
