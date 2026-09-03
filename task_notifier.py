import os
import sys
import time

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import config
import send_vk

def notify_task_finished(task_name: str, status: str = "SUCCESS", details: str = "", duration_sec: float = None, target_uid: int = None):
    """
    Sends an instant push notification to VK (and optionally Telegram) when a long-running IDE job completes.
    """
    if target_uid is None:
        target_uid = send_vk.get_default_user_id()

    icon = "✅" if status.upper() == "SUCCESS" else "⚠️" if status.upper() == "WARNING" else "❌"
    
    dur_str = f" за {int(duration_sec)} сек." if duration_sec else ""
    spoken = f"Задача {task_name} завершена со статусом {status}{dur_str}!"

    msg = f"{icon} **Уведомление о фоновой задаче:**\n"
    msg += f"• **Задача:** «{task_name}»\n"
    msg += f"• **Статус:** `{status.upper()}`\n"
    if duration_sec:
        msg += f"• **Время выполнения:** `{duration_sec:.1f}s`\n"
    if details:
        msg += f"• **Детали:** {details}\n"

    try:
        send_vk.send_reply_with_optional_voice(target_uid, msg, spoken)
        return True
    except Exception as e:
        print(f"[Task Notifier Error] {e}", file=sys.stderr)
        return False

if __name__ == "__main__":
    if len(sys.argv) > 1:
        t_name = sys.argv[1]
        t_status = sys.argv[2] if len(sys.argv) > 2 else "SUCCESS"
        t_details = sys.argv[3] if len(sys.argv) > 3 else ""
        notify_task_finished(t_name, t_status, t_details)
    else:
        print("Usage: python task_notifier.py <task_name> [status] [details]")
