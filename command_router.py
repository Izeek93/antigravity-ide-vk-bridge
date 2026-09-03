"""
vk-bot/command_router.py
========================
Модульный маршрутизатор сервисных команд VK моста для Antigravity IDE.
Изолирует обработку системных команд от транспортного демона:
- Удалённые согласования действий в IDE (/approve, /reject, да, нет).
- Управление телеметрией (/limits, /tasks, /status).
- Захват рабочего стола (/screen).
- Переключение голосового режима (/voice on/off).
- Справочная система (/help, /start).
"""

import os
import sys
import time

import config
import vk_api_client as vk
from vk_keyboard import get_main_keyboard
from vk_formatter import format_for_vk
from screenshot import capture_desktop
from limits_checker import format_limits_report
from tasks_checker import get_background_tasks_report
from queue_manager import push_message

APPROVAL_AFFIRMATIVE = {
    "да", "подтверждаю", "разрешаю", "ок", "выполняй", "approve", "/approve", "/yes", "1",
    "✅ подтвердить", "подтвердить", "✅ да", "подтверждаю действие"
}

APPROVAL_NEGATIVE = {
    "нет", "отмена", "отклонить", "не надо", "reject", "/reject", "/no", "0",
    "❌ отклонить", "отклонить", "❌ нет", "отменить"
}

VOICE_TOGGLE_COMMANDS = {
    "/voice", "/voice on", "/voice off",
    "голос", "голос вкл", "голос выкл", "голос on", "голос off",
    "🎙 голос: вкл", "🔇 голос: выкл", "вкл голос", "выкл голос",
    "голос: вкл", "голос: выкл", "голос: включено", "голос: выключено"
}


def handle_remote_approval(user_id: int, cmd: str) -> bool:
    """Обработка подтверждения/отклонения опасных команд в IDE."""
    if cmd not in APPROVAL_AFFIRMATIVE and cmd not in APPROVAL_NEGATIVE:
        return False

    try:
        from remote_approval_manager import get_pending_approval, resolve_approval

        pending = get_pending_approval()
        if not pending:
            return False

        decision = cmd in APPROVAL_AFFIRMATIVE
        resolve_approval(decision)
        res_str = (
            "✅ Действие подтверждено! Передано в IDE на исполнение."
            if decision else
            "❌ Действие отклонено. Отменено в IDE."
        )
        kb = get_main_keyboard(config.is_voice_enabled())
        vk.send_message(user_id, res_str, keyboard=kb)

        push_message({
            "source": "REMOTE_APPROVAL",
            "chat_id": user_id,
            "user_id": user_id,
            "user": f"vk_id{user_id}",
            "action": pending.get("action"),
            "approved": decision,
            "text": f"[{'✅ ПОДТВЕРЖДЕНО' if decision else '❌ ОТКЛОНЕНО'} через VK]: «{pending.get('action')}»",
            "timestamp": time.time()
        })
        return True
    except Exception as e:
        print(f"[Remote Approval Error VK] {e}", file=sys.stderr)
        return False


def dispatch_command(user_id: int, raw_text: str) -> bool:
    """
    Маршрутизация входящего сообщения как системной команды моста.
    Возвращает True, если сообщение было служебной командой и обработано.
    """
    cmd = (raw_text or "").strip().lower()
    if not cmd:
        return False

    # 1. Интерактивные согласования IDE
    if handle_remote_approval(user_id, cmd):
        return True

    # 2. Справка и старт
    if cmd in ("/start", "/help", "помощь", "ℹ️ помощь", "меню"):
        help_text = (
            "🤖 Antigravity IDE VK Bridge v1.1.0\n\n"
            "Доступные команды:\n"
            "• 📊 Лимиты (/limits) — Статус квот, моделей и контекста\n"
            "• 📸 Скриншот (/screen) — Снимок экрана рабочего стола\n"
            "• 📋 Задачи (/tasks) — Список фоновых задач и процессов\n"
            "• 🎙 Голос (/voice) — Включение/отключение голосовых ответов\n"
            "• 📊 Статус (/status) — Состояние подключения моста\n"
            "• ℹ️ Помощь (/help) — Список команд"
        )
        kb = get_main_keyboard(config.is_voice_enabled())
        vk.send_message(user_id, help_text, keyboard=kb)
        return True

    # 3. Диагностика и статус
    if cmd in ("/status", "статус", "/heal", "диагностика"):
        vk.set_activity(user_id, "typing")
        from bridge_health_watchdog import run_self_healing_health_check
        diag = run_self_healing_health_check()
        v_status = "🔊 Включено" if config.is_voice_enabled() else "🔇 Выключено"
        heal_info = "🟢 Без сбоев" if not diag.get("lock_healed") and not diag.get("inbox_healed") else "🛠 Выполнено автовосстановление"
        msg = (
            "🟢 Antigravity IDE VK Bridge Status\n"
            f"• Версия: v1.1.0 (Modular & Decoupled)\n"
            f"• Статус моста: Active / Healthy\n"
            f"• Очередь: {heal_info}\n"
            f"• Сообщений в inbox: {diag.get('pending_inbox_messages', 0)}\n"
            f"• Голосовые ответы: {v_status}\n"
            "• STT: Faster-Whisper CUDA / Local\n"
            "• Документы и медиа: Активны"
        )
        kb = get_main_keyboard(config.is_voice_enabled())
        vk.send_message(user_id, msg, keyboard=kb)
        return True

    # 4. Лимиты и квоты
    if cmd in ("/limits", "лимиты", "📊 лимиты", "квоты"):
        vk.set_activity(user_id, "typing")
        report = format_limits_report()
        kb = get_main_keyboard(config.is_voice_enabled())
        vk.send_message(user_id, format_for_vk(report), keyboard=kb)
        return True

    # 5. Скриншот рабочего стола
    if cmd in ("/screen", "/screenshot", "скриншот", "📸 скриншот", "экран"):
        vk.set_activity(user_id, "photo")
        shot_path = capture_desktop("desktop_vk.png")
        if shot_path and os.path.exists(shot_path):
            try:
                att = vk.upload_photo(user_id, shot_path)
                kb = get_main_keyboard(config.is_voice_enabled())
                vk.send_message(user_id, "📸 Снимок экрана рабочего стола ПК:", keyboard=kb, attachment=att)
            except Exception as e:
                kb = get_main_keyboard(config.is_voice_enabled())
                vk.send_message(user_id, f"⚠️ Не удалось загрузить снимок экрана: {e}", keyboard=kb)
            finally:
                try:
                    os.remove(shot_path)
                except Exception:
                    pass
        else:
            vk.send_message(user_id, "❌ Не удалось сделать снимок экрана.")
        return True

    # 6. Список фоновых задач
    if cmd in ("/tasks", "задачи", "📋 задачи"):
        vk.set_activity(user_id, "typing")
        report = get_background_tasks_report()
        kb = get_main_keyboard(config.is_voice_enabled())
        vk.send_message(user_id, format_for_vk(report), keyboard=kb)
        return True

    # 7. Переключение голосового режима
    if cmd in VOICE_TOGGLE_COMMANDS or cmd.startswith("/voice "):
        current = config.is_voice_enabled()
        if cmd in ("🎙 голос: вкл", "голос: вкл", "голос вкл", "голос: включено", "вкл голос"):
            new_state = False if current else True
            if "вкл" in cmd and current:
                new_state = False
            elif "выкл" in cmd and not current:
                new_state = True
        elif cmd in ("🔇 голос: выкл", "голос: выкл", "голос выкл", "голос: выключено", "выкл голос"):
            new_state = True
        elif cmd in ("/voice on", "голос on"):
            new_state = True
        elif cmd in ("/voice off", "голос off"):
            new_state = False
        else:
            new_state = not current

        config.set_voice_enabled(new_state)
        state_str = "🔊 Голосовые ответы ВКЛЮЧЕНЫ." if new_state else "🔇 Голосовые ответы ВЫКЛЮЧЕНЫ."
        kb = get_main_keyboard(new_state)
        vk.send_message(user_id, state_str, keyboard=kb)
        return True

    return False
