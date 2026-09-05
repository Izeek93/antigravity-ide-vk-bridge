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
import re
import json
from typing import Optional, Dict, Any

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
    "✅ подтвердить", "подтвердить", "✅ да", "подтверждаю действие",
    "✅ утвердить план", "утвердить план", "утвердить", "одобряю", "утверждаю", "✅ применить"
}

APPROVAL_NEGATIVE = {
    "нет", "отмена", "отклонить", "не надо", "reject", "/reject", "/no", "0",
    "❌ отклонить", "отклонить", "❌ нет", "отменить", "доработать"
}

VOICE_TOGGLE_COMMANDS = {
    "/voice", "/voice on", "/voice off",
    "голос", "голос вкл", "голос выкл", "голос on", "голос off",
    "🎙 голос: вкл", "🔇 голос: выкл", "вкл голос", "выкл голос",
    "голос: вкл", "голос: выкл", "голос: включено", "голос: выключено"
}


def handle_remote_approval(user_id: int, cmd: str) -> bool:
    """Обработка подтверждения/отклонения опасных команд в IDE или паузы автопилота."""
    # Экстренная пауза автопилота
    if cmd in ("pause", "приостановить", "⏸ приостановить", "/pause"):
        res_str = "⏸ Выполнение плана приостановлено! Агент в IDE остановлен. Напишите или наговорите голосом ваши замечания."
        kb = get_main_keyboard(config.is_voice_enabled())
        vk.send_message(user_id, res_str, keyboard=kb)
        push_message({
            "source": "VK_PAUSE",
            "chat_id": user_id,
            "user_id": user_id,
            "text": "[USER_ACTION]: ⏸ Выполнение плана ПРИОСТАНОВЛЕНО пользователем через ВКонтакте. Ожидай новых указаний.",
            "timestamp": time.time()
        })
        return True

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


def dispatch_command(user_id: int, raw_text: str, payload: str = "", peer_id: Optional[int] = None) -> bool:
    """
    Маршрутизация входящего сообщения как системной команды моста.
    Возвращает True, если сообщение было служебной командой и обработано.
    """
    raw = (raw_text or "").strip()
    # Срезаем префикс упоминания бота в беседах: [club149687922|@club149687922] или [club149687922|ЛФХ]
    clean_text = re.sub(r"^\[(?:club|public)\d+\|[^\]]+\]\s*", "", raw, flags=re.IGNORECASE).strip()
    cmd = clean_text.lower()

    # 0. Интерактивные кнопки согласования отложенных постов (Одобрено / Доработка / Отклонено / Отозвать)
    if payload:
        try:
            pdata = json.loads(payload) if isinstance(payload, str) else payload
            pcmd = pdata.get("command", "")
            if pcmd in ("post_approve", "post_revise", "post_reject", "post_recall"):
                import post_scheduler
                draft_id = pdata.get("draft_id", "")
                post_scheduler.handle_approval_action(pcmd, draft_id, user_id)
                return True
        except Exception as e:
            print(f"[Payload Parse Error] {e}", file=sys.stderr)

    # Текстовые эквиваленты кнопки отзыва публикации
    if (
        cmd in ("отозвать", "🚫 отозвать", "🚫 отозвать публикацию", "отменить публикацию", "отозвать черновик")
        or cmd.startswith("🚫 отозвать")
        or cmd.startswith("отозвать")
        or cmd.startswith("отменить публикацию")
    ):
        try:
            import post_scheduler
            drafts = post_scheduler.load_drafts()
            approved = [d for d in drafts.values() if d.get("status") in ("approved", "pending")]
            if approved:
                approved.sort(key=lambda d: d.get("created_at", 0), reverse=True)
                target_draft = approved[0]
                post_scheduler.handle_approval_action("post_recall", target_draft["id"], user_id)
                return True
        except Exception as e:
            print(f"[Text Recall Error] {e}", file=sys.stderr)

    # Текстовые эквиваленты кнопок согласования постов (с кнопками и с упоминанием бота)
    if (
        cmd in ("одобрено", "✅ одобрено", "доработка", "✏️ доработка", "отклонено", "❌ отклонено")
        or cmd.startswith("✅ одобрено")
        or cmd.startswith("одобрено")
        or cmd.startswith("✏️ доработка")
        or cmd.startswith("доработка")
        or cmd.startswith("❌ отклонено")
        or cmd.startswith("отклонено")
    ):
        try:
            import post_scheduler
            drafts = post_scheduler.load_drafts()
            pending = [d for d in drafts.values() if d.get("status") in ("pending", "revising")]
            if pending:
                pending.sort(key=lambda d: d.get("created_at", 0), reverse=True)
                target_draft = pending[0]
                action = "post_approve" if "одобр" in cmd else ("post_revise" if "доработ" in cmd else "post_reject")
                post_scheduler.handle_approval_action(action, target_draft["id"], user_id)
                return True
        except Exception as e:
            print(f"[Text Post Action Error] {e}", file=sys.stderr)



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
            "• 👥 Команда (/team) — Статус ролей мультиагентной системы\n"
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

    # 8. Статус мультиагентной команды (AATC)
    if cmd in ("/team", "команда", "агенты", "/agents"):
        vk.set_activity(user_id, "typing")
        team_info = (
            "🤖 Мультиагентная система AATC (Antigravity Team Core)\n\n"
            "Активные роли конвейера:\n"
            "• 📐 Прораб (Architect): Спецификация и проектирование\n"
            "• 💻 Кодер (Builder): Разработка и юнит-тесты\n"
            "• 🔍 Зануда (Reviewer): Анти-самоприёмка и стресс-тесты\n"
            "• 🛡 Инспектор (Auditor): Zero-Trust аудит безопасности\n"
            "• 🚀 Выпускатель (Release): Контроль релизов и отчёты\n\n"
            "⚡ Режим: Always-On Auto-Triage (Tier 0-2)"
        )
        kb = get_main_keyboard(config.is_voice_enabled())
        vk.send_message(user_id, team_info, keyboard=kb)
        return True

    # 9. Еженедельная ретроспектива уроков AATC
    if cmd in ("/retro", "/learnings", "ретро", "уроки"):
        vk.set_activity(user_id, "typing")
        try:
            core_dir = Path(__file__).resolve().parent.parent / "agent-core"
            if str(core_dir) not in sys.path:
                sys.path.insert(0, str(core_dir))
            import retro_manager
            digest = retro_manager.generate_weekly_digest()
            summary_text = digest.get("summary_text", "Уроков не найдено.")
            
            # Inline-кнопки согласования
            inline_kb = {
                "inline": True,
                "buttons": [
                    [
                        {"action": {"type": "text", "label": "✅ Применить"}, "color": "positive"},
                        {"action": {"type": "text", "label": "❌ Отклонить"}, "color": "negative"}
                    ]
                ]
            }
            vk.send_message(user_id, summary_text, keyboard=inline_kb)
        except Exception as e:
            vk.send_message(user_id, f"⚠️ Ошибка формирования ретроспективы: {e}")
        return True

    # 10. Управление режимом автопилота (Auto-Proceed)
    if cmd in ("/auto", "/autopilot", "авто", "автопилот") or cmd.startswith("/auto ") or cmd.startswith("авто "):
        vk.set_activity(user_id, "typing")
        try:
            core_dir = Path(__file__).resolve().parent.parent / "agent-core"
            if str(core_dir) not in sys.path:
                sys.path.insert(0, str(core_dir))
            import config as core_config

            parts = cmd.split()
            arg = parts[1] if len(parts) > 1 else ""
            if arg in ("on", "вкл", "1", "true"):
                core_config.set_autopilot_enabled(True)
                msg = "⚡ Режим Автопилота ВКЛЮЧЕН (по умолчанию).\n\nПланы принимаются сразу, исполнение начинается немедленно. В мост шлётся уведомление с кнопкой экстренной паузы."
            elif arg in ("off", "выкл", "0", "false"):
                core_config.set_autopilot_enabled(False)
                msg = "🛡 Режим Строгого Контроля ВКЛЮЧЕН.\n\nАгент будет останавливаться на каждом плане и ждать вашего ручного утверждения кнопкой или голосом."
            else:
                current = core_config.is_autopilot_enabled()
                state_str = "⚡ ВКЛЮЧЕН (Auto-Proceed)" if current else "🛡 ВЫКЛЮЧЕН (Строгий ручной контроль)"
                msg = f"⚙️ Текущий режим планов: {state_str}\n\n• Включить автопилот: /auto on\n• Включить ручной контроль: /auto off"

            kb = get_main_keyboard(config.is_voice_enabled())
            vk.send_message(user_id, msg, keyboard=kb)
        except Exception as e:
            vk.send_message(user_id, f"⚠️ Ошибка настройки автопилота: {e}")
        return True

    return False
