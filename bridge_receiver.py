"""
vk-bot/bridge_receiver.py
=========================
Автономный локальный файловый приёмник сообщений VK моста для Antigravity IDE.
- Работает исключительно с локальной очередью vk-bot/inbox.json.
- Не занимает сетевых портов.
- При получении сообщения выводит его в консоль и завершает процесс, пробуждая агента IDE.
"""

import os
import sys
import time
import json

# Принудительный UTF-8 вывод на консоли Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from queue_manager import pop_messages

def print_messages(messages: list):
    if not messages:
        return
    print("\n" + "="*55)
    print(f"📥 [VK BRIDGE] INCOMING MESSAGES ({len(messages)} message(s)):")
    for idx, msg in enumerate(messages, start=1):
        user_id = msg.get("user_id") or msg.get("chat_id")
        user = msg.get("user", f"vk_id{user_id}")
        text = msg.get("text", "")
        print(f"[{idx}] [VK] From: {user} (ID: {user_id})")
        print(f"    Message: {text}\n")
    print("="*55 + "\n", flush=True)

def print_incident(incident: dict):
    print("\n" + "!"*60)
    print(f"🚨 AUTONOMOUS INCIDENT ALERT from [{incident.get('service', 'VK_BRIDGE')}]:")
    print(f"   Error: {incident.get('error')}")
    if incident.get('traceback'):
        print(f"   Traceback:\n{incident.get('traceback')}")
    print("!"*60 + "\n", flush=True)

def check_incidents():
    """Проверка очереди критических инцидентов из incidents.json."""
    inc_file = os.path.join(os.path.dirname(__file__), "incidents.json")
    if os.path.exists(inc_file):
        try:
            with open(inc_file, "r", encoding="utf-8") as f:
                incidents = json.load(f)
            if incidents:
                for inc in incidents:
                    print_incident(inc)
                with open(inc_file, "w", encoding="utf-8") as f:
                    json.dump([], f)
                return True
        except Exception:
            pass
    return False

def check_sos() -> bool:
    """Проверка экстренного сигнала SOS (минуя обычную очередь)."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import sos_manager
        sos_event = sos_manager.check_and_consume_sos()
        if sos_event:
            print("\n" + "="*60)
            print("🚨🚨🚨 [EMERGENCY SOS SIGNAL RECEIVED] 🚨🚨🚨")
            print(f"Источник: {sos_event.get('source')} | Время: {sos_event.get('datetime')}")
            print(f"Детали: {sos_event.get('details')}")
            print("ПРИЧИНА: Пользователь нажал скрытую кнопку SOS!")
            print("Это означает, что либо сообщения пользователя не доходят, либо ответы агента не видны.")
            print("ИНСТРУКЦИЯ ДЛЯ АГЕНТА: НЕМЕДЛЕННО проведи аудит последних логов и сетевых статусов,")
            print("и отправь краткий фактологический отчёт о состоянии связи.")
            print("="*60 + "\n", flush=True)
            return True
    except Exception:
        pass
    return False

def main():
    if check_sos():
        sys.exit(0)
    if check_incidents():
        sys.exit(0)

    while True:
        try:
            if check_sos():
                sys.exit(0)

            messages = pop_messages()
            if messages:
                print_messages(messages)
                sys.exit(0)

            if check_incidents():
                sys.exit(0)
        except Exception:
            time.sleep(0.3)

        time.sleep(0.2)

if __name__ == "__main__":
    main()
