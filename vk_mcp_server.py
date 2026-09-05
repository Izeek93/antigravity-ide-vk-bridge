"""
vk-bot/vk_mcp_server.py
=======================
Официальный Stdio FastMCP сервер для взаимодействия Antigravity IDE с ВКонтакте.
Предоставляет агенту набор нативных инструментов Model Context Protocol:
- vk_send_message: отправка текстовых ответов пользователю
- vk_send_voice: нейросинтез речи (OmniVoice) и отправка голосовой заметки
- vk_send_photo: загрузка и доставка изображений
- vk_post_to_wall: мгновенная публикация записей от имени группы на стену
- vk_schedule_post: создание отложенных записей с расчётом таймера и карточкой согласования
- vk_list_scheduled_posts: просмотр очереди отложенных записей сообщества и их статусов
- vk_recall_scheduled_post: отзыв поста из публикации и удаление из таймера стены
- vk_get_status: получение состояния моста, очереди и настроек

Архитектурный стандарт:
- stdout строго зарезервирован для протокола MCP (JSON-RPC).
- Все логи перенаправлены в stderr.
- Безопасное исполнение без вызова терминала операционной системы.
"""

import os
import sys
import json
import logging
from pathlib import Path

# Обеспечиваем UTF-8 в консоли Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Логирование строго в stderr
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s [%(levelname)s] [VK-MCP] %(message)s"
)
logger = logging.getLogger("VK_MCP")

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Импорт FastMCP из virtualenv
from mcp.server.fastmcp import FastMCP

import config
import vk_api_client as vk
from send_vk import send_reply_with_optional_voice, send_message_to_user, send_photo_to_user, send_voice_to_user
from voice_engine import synthesize_voice
import status_tracker

mcp = FastMCP("antigravity-vk-mcp")

@mcp.tool()
def vk_send_message(user_id: int, text: str) -> str:
    """
    Отправляет текстовое сообщение пользователю ВКонтакте с авто-форматированием.
    
    :param user_id: Числовой ID пользователя VK (например 14901004)
    :param text: Текст ответа (поддерживает Markdown, списки, эмодзи)
    """
    try:
        clean_text = text.strip()
        if not clean_text:
            return "Ошибка: текст сообщения не может быть пустым."
        
        msg_ids = send_message_to_user(user_id, clean_text)
        return f"Успешно доставлено! ID сообщений VK: {msg_ids}"
    except Exception as e:
        logger.error(f"Ошибка в vk_send_message: {e}", exc_info=True)
        return f"Ошибка доставки сообщения: {e}"

@mcp.tool()
def vk_send_voice(user_id: int, text: str, voice_text: str = "") -> str:
    """
    Синтезирует нейроголос (OmniVoice Eva) и отправляет голосовой ответ в паре с текстом.
    
    :param user_id: Числовой ID пользователя VK
    :param text: Полный подробный текст ответа для чата
    :param voice_text: Краткая лаконичная выжимка для озвучки (15-20 секунд, до 250 символов)
    """
    try:
        v_text = voice_text.strip() if voice_text else None
        res = send_reply_with_optional_voice(user_id, text, voice_text=v_text)
        return f"Голосовой и текстовый ответ успешно доставлен пользователю {user_id}."
    except Exception as e:
        logger.error(f"Ошибка в vk_send_voice: {e}", exc_info=True)
        return f"Ошибка отправки голосового ответа: {e}"

@mcp.tool()
def vk_send_photo(user_id: int, photo_path: str, caption: str = "") -> str:
    """
    Загружает локальное изображение на сервера VK и отправляет в диалог с пользователем.
    
    :param user_id: Числовой ID пользователя VK
    :param photo_path: Абсолютный локальный путь к файлу изображения (PNG, JPG, WEBP)
    :param caption: Опциональная текстовая подпись к фото
    """
    try:
        p = Path(photo_path)
        if not p.exists():
            return f"Ошибка: файл изображения не найден по пути {photo_path}"
        
        msg_id = send_photo_to_user(user_id, str(p), caption=caption)
        return f"Фото успешно отправлено пользователю {user_id}. ID сообщения: {msg_id}"
    except Exception as e:
        logger.error(f"Ошибка в vk_send_photo: {e}", exc_info=True)
        return f"Ошибка отправки фото: {e}"

@mcp.tool()
def vk_post_to_wall(text: str, attachments: str = "") -> str:
    """
    Публикует новый пост на стене сообщества от имени группы.
    
    :param text: Текст публикации (пост, анонс, опрос, статья)
    :param attachments: Опциональная строка вложений через запятую (например 'photo-149687922_123')
    """
    try:
        group_id = config.VK_GROUP_ID
        params = {
            "owner_id": f"-{group_id}",
            "from_group": 1,
            "message": text.strip()
        }
        if attachments:
            params["attachments"] = attachments.strip()
        
        post_res = vk.call_api("wall.post", params)
        post_id = post_res.get("post_id")
        return f"Пост успешно опубликован на стене сообщества! ID записи: wall-{group_id}_{post_id}"
    except Exception as e:
        logger.error(f"Ошибка публикации на стену: {e}", exc_info=True)
        return f"Ошибка публикации поста на стену: {e}"

@mcp.tool()
def vk_schedule_post(title: str, text: str, attachments: str = "", wall_attachments: str = "", custom_publish_date: int = None, peer_id: int = None) -> str:
    """
    Создаёт отложенный черновик записи, рассчитывает оптимальный таймер (шаг 5ч, джиттер ±15м, тихие часы)
    и отправляет интерактивную карточку согласования в беседу модерации.
    
    :param title: Краткий заголовок темы поста для карточки
    :param text: Текст публикации (поддерживает разметку и ссылки)
    :param attachments: Вложения для сообщения в беседе (например 'photo123_456')
    :param wall_attachments: Вложения для стены сообщества (например 'photo-123_456')
    :param custom_publish_date: Опциональный unix timestamp времени публикации (если нужно переопределить авто-расчёт)
    :param peer_id: Опциональный ID беседы согласования (по умолчанию из VK_APPROVALS_PEER_ID)
    """
    try:
        import post_scheduler
        draft = post_scheduler.create_and_send_draft(
            title=title,
            text=text,
            attachments=attachments,
            wall_attachments=wall_attachments,
            peer_id=peer_id,
            custom_publish_date=custom_publish_date
        )
        return (
            f"Черновик «{draft['title']}» успешно создан и отправлен на согласование!\n"
            f"• ID черновика: {draft['id']}\n"
            f"• Запланированное время выхода: {draft.get('publish_date_str')}\n"
            f"• Статус: {draft['status']}"
        )
    except Exception as e:
        logger.error(f"Ошибка в vk_schedule_post: {e}", exc_info=True)
        return f"Ошибка создания отложенного поста: {e}"

@mcp.tool()
def vk_list_scheduled_posts(filter_status: str = "") -> str:
    """
    Возвращает список запланированных постов из локальной базы очередей со статусами и временем публикации.
    
    :param filter_status: Опциональный фильтр статуса: 'pending', 'approved', 'revising', 'rejected', 'recalled'
    """
    try:
        import post_scheduler
        drafts = post_scheduler.load_drafts()
        if not drafts:
            return "Очередь отложенных публикаций пуста."

        lines = ["📋 **Очередь отложенных публикаций сообщества:**"]
        filtered = [
            d for d in drafts.values()
            if not filter_status or d.get("status") == filter_status.strip().lower()
        ]
        if not filtered:
            return f"Публикаций со статусом '{filter_status}' не найдено."

        filtered.sort(key=lambda d: d.get("publish_date", 0))
        for idx, d in enumerate(filtered, 1):
            st = d.get("status", "unknown")
            st_icon = {"pending": "⏳", "approved": "✅", "revising": "✏️", "rejected": "❌", "recalled": "🚫"}.get(st, "ℹ️")
            pid_info = f" (wall post: {d.get('vk_post_id')})" if d.get("vk_post_id") else ""
            lines.append(f"{idx}. {st_icon} [{st.upper()}] «{d.get('title', 'Без названия')}» — {d.get('publish_date_str')}{pid_info} (ID: {d.get('id')})")

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Ошибка в vk_list_scheduled_posts: {e}", exc_info=True)
        return f"Ошибка получения списка постов: {e}"

@mcp.tool()
def vk_recall_scheduled_post(draft_id: str) -> str:
    """
    Отзывает черновик из публикации и удаляет запись из официального таймера стены VK (если была одобрена).
    
    :param draft_id: Идентификатор черновика (например 'post_1788572119_541')
    """
    try:
        import post_scheduler
        ok, msg = post_scheduler.handle_approval_action("post_recall", draft_id, user_id=0)
        return msg
    except Exception as e:
        logger.error(f"Ошибка в vk_recall_scheduled_post: {e}", exc_info=True)
        return f"Ошибка отзыва публикации: {e}"

@mcp.tool()
def vk_get_status() -> str:
    """
    Возвращает актуальную диагностику: статус моста, очереди inbox, голосового движка и настроек.
    """
    try:
        voice_on = config.is_voice_enabled()
        allowed_users = list(config.VK_ALLOWED_USER_IDS)
        group_id = config.VK_GROUP_ID

        # Проверка очереди inbox.json
        inbox_file = BASE_DIR / "inbox.json"
        queue_len = 0
        if inbox_file.exists():
            try:
                with open(inbox_file, "r", encoding="utf-8") as f:
                    q = json.load(f)
                    queue_len = len(q) if isinstance(q, list) else 0
            except Exception:
                pass

        # Проверка супервизора
        sup_file = BASE_DIR / "supervisor_status.json"
        sup_info = "не активен"
        if sup_file.exists():
            try:
                with open(sup_file, "r", encoding="utf-8") as f:
                    s = json.load(f)
                    sup_info = f"PID {s.get('supervisor_pid')}, Uptime {s.get('uptime_seconds')}с, рестартов: {s.get('restarts_total')}"
            except Exception:
                pass

        report = [
            "📊 **Диагностический статус VK Bridge & MCP:**",
            f"• Сообщество: ID {group_id}",
            f"• Разрешённые пользователи: {allowed_users}",
            f"• Голосовые ответы (OmniVoice): {'Включены' if voice_on else 'Выключены'}",
            f"• Супервизор процессов: {sup_info}",
            f"• Сообщений в очереди inbox: {queue_len}",
            f"• Режим транспорта: Stdio JSON-RPC FastMCP"
        ]
        return "\n".join(report)
    except Exception as e:
        logger.error(f"Ошибка в vk_get_status: {e}", exc_info=True)
        return f"Ошибка получения статуса: {e}"

if __name__ == "__main__":
    logger.info("Запуск Stdio FastMCP сервера ВКонтакте (antigravity-vk-mcp)...")
    mcp.run(transport="stdio")
