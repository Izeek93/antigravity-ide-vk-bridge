"""
vk-bot/post_scheduler.py
========================
Интеллектуальный менеджер отложенного постинга для сообществ ВКонтакте.

Возможности расписания и модерации:
1. Шаг публикации: настраиваемый интервал (по умолчанию 5 часов).
2. Плавающий люфт (джиттер): ±15 минут (защита от алгоритмической роботизации платформы).
3. Тихие часы (ночная пауза): с 23:00 до 09:00 (перенос на утренний слот).
4. Согласование через беседу модерации (Inline-кнопки):
   - [✅ Одобрено] ➔ официальный таймер VK (wall.post с publish_date).
   - [✏️ Доработка] ➔ статус 'revising', редактирование на месте через messages.edit (CMID).
   - [❌ Отклонено] ➔ статус 'rejected', отмена публикации.
   - [🚫 Отозвать] ➔ снятие с публикации и удаление из таймера стены.
"""

import os
import sys
import json
import time
import random
import logging
import datetime
from typing import Optional, Dict, Any, Tuple, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PostScheduler")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DRAFTS_FILE = os.path.join(BASE_DIR, "drafts.json")

STEP_HOURS = 5
JITTER_MINUTES = 15
QUIET_START_HOUR = 23  # 23:00
QUIET_END_HOUR = 9     # 09:00

import config
import vk_api_client as vk
from vk_formatter import format_for_vk

def _load_user_token() -> Optional[str]:
    for env_path in [
        os.path.join(BASE_DIR, "..", "ideas", ".env.secrets"),
        os.path.join(BASE_DIR, ".env")
    ]:
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("VK_USER_TOKEN="):
                            return line.split("=", 1)[1].strip().strip("\"'")
            except Exception:
                pass
    return None

def get_last_postponed_time() -> Optional[int]:
    """Получение времени публикации самого позднего отложенного поста в группе."""
    user_token = _load_user_token()
    if not user_token:
        return None
    try:
        import urllib.request, urllib.parse
        url = "https://api.vk.com/method/wall.get"
        params = {
            "access_token": user_token,
            "v": "5.199",
            "owner_id": f"-{config.VK_GROUP_ID}",
            "filter": "postponed",
            "count": 10
        }
        data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            items = res.get("response", {}).get("items", [])
            if items:
                dates = [it.get("date", 0) for it in items if isinstance(it.get("date"), int)]
                if dates:
                    return max(dates)
    except Exception as e:
        logger.warning(f"Не удалось получить отложенные посты: {e}")
    return None

def calculate_next_publish_date(base_time: Optional[int] = None) -> Tuple[int, str]:
    """
    Расчёт времени публикации с шагом 5 часов (±15 мин) и учётом тихих часов (23:00 - 09:00).
    Возвращает (timestamp, читаемая_строка).
    """
    now = int(time.time())
    if not base_time:
        last_postponed = get_last_postponed_time()
        base_time = last_postponed if last_postponed and last_postponed > now else now

    if base_time < now:
        base_time = now

    # Шаг 5 часов + джиттер ±15 мин
    jitter_sec = random.randint(-JITTER_MINUTES * 60, JITTER_MINUTES * 60)
    candidate_ts = base_time + (STEP_HOURS * 3600) + jitter_sec

    # Проверка на тихие часы (23:00 - 09:00 локального времени)
    dt = datetime.datetime.fromtimestamp(candidate_ts)
    if dt.hour >= QUIET_START_HOUR:
        # Переносим на следующее утро в 09:00 + 0..25 мин
        morning_jitter = random.randint(0, 25) * 60
        next_morning = dt.replace(hour=QUIET_END_HOUR, minute=0, second=0) + datetime.timedelta(days=1)
        candidate_ts = int(next_morning.timestamp()) + morning_jitter
    elif dt.hour < QUIET_END_HOUR:
        # Переносим на сегодняшнее утро в 09:00 + 0..25 мин
        morning_jitter = random.randint(0, 25) * 60
        today_morning = dt.replace(hour=QUIET_END_HOUR, minute=0, second=0)
        candidate_ts = int(today_morning.timestamp()) + morning_jitter

    # Гарантируем, что время хотя бы на 3 минуты в будущем
    if candidate_ts <= now + 180:
        candidate_ts = now + 600

    target_dt = datetime.datetime.fromtimestamp(candidate_ts)
    formatted = target_dt.strftime("%d.%m.%Y в %H:%M")
    return candidate_ts, formatted

def load_drafts() -> Dict[str, Any]:
    if os.path.exists(DRAFTS_FILE):
        try:
            with open(DRAFTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_drafts(drafts: Dict[str, Any]):
    with open(DRAFTS_FILE, "w", encoding="utf-8") as f:
        json.dump(drafts, f, indent=2, ensure_ascii=False)

def get_approval_keyboard(draft_id: str, publish_date_str: str = "") -> dict:
    """Формирует Inline-кнопки согласования (Одобрено / Доработка / Отклонено)."""
    time_badge = ""
    if " в " in publish_date_str:
        time_badge = f" ({publish_date_str.split(' в ', 1)[-1]})"
    elif publish_date_str:
        time_badge = f" ({publish_date_str})"

    approve_label = f"✅ Одобрить{time_badge}"
    if len(approve_label) > 40:
        approve_label = "✅ Одобрено"

    return {
        "inline": True,
        "buttons": [
            [
                {
                    "action": {
                        "type": "text",
                        "label": approve_label,
                        "payload": json.dumps({"command": "post_approve", "draft_id": draft_id})
                    },
                    "color": "positive"
                },
                {
                    "action": {
                        "type": "text",
                        "label": "✏️ Доработка",
                        "payload": json.dumps({"command": "post_revise", "draft_id": draft_id})
                    },
                    "color": "primary"
                },
                {
                    "action": {
                        "type": "text",
                        "label": "❌ Отклонить",
                        "payload": json.dumps({"command": "post_reject", "draft_id": draft_id})
                    },
                    "color": "negative"
                }
            ]
        ]
    }


def get_recall_keyboard(draft_id: str) -> dict:
    """Формирует кнопку отзыва/отмены одобренного поста."""
    return {
        "inline": True,
        "buttons": [
            [
                {
                    "action": {
                        "type": "text",
                        "label": "🚫 Отозвать публикацию",
                        "payload": json.dumps({"command": "post_recall", "draft_id": draft_id})
                    },
                    "color": "negative"
                }
            ]
        ]
    }

def delete_post_from_wall(post_id: int) -> Tuple[bool, str]:
    """Пытается удалить пост из таймера стены сообщества через API."""
    user_token = _load_user_token()
    if not user_token:
        return False, "User token отсутствует"
    try:
        import urllib.request, urllib.parse
        url = "https://api.vk.com/method/wall.delete"
        params = {
            "access_token": user_token,
            "v": config.VK_API_VERSION,
            "owner_id": f"-{config.VK_GROUP_ID}",
            "post_id": post_id
        }
        data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            if res.get("response") == 1:
                return True, "Успешно удалено из таймера VK API"
            err = res.get("error", {})
            return False, f"{err.get('error_msg', 'Ошибка VK API')}"
    except Exception as e:
        return False, str(e)


def ensure_community_link(text: str) -> str:
    """
    Гарантирует наличие кликабельной гиперссылки на сообщество для репостов.
    Шаблон считывается из config.VK_POST_FOOTER_TEMPLATE.
    """
    gid = getattr(config, "VK_GROUP_ID", 0)
    if not gid:
        return text.strip()

    template = getattr(config, "VK_POST_FOOTER_TEMPLATE", "")
    if not template:
        return text.strip()

    try:
        link_line = template.format(group_id=gid)
    except Exception:
        link_line = f"Больше интересного — [club{gid}|ТУТ] 💡"

    # Удаляем любые старые варианты строки со ссылкой на группу
    cleaned_lines = []
    for line in text.strip().split("\n"):
        if f"club{gid}" in line:
            continue
        cleaned_lines.append(line)
    text = "\n".join(cleaned_lines).strip()

    lines = text.split("\n")
    non_empty = [i for i, l in enumerate(lines) if l.strip()]
    if non_empty and lines[non_empty[-1]].strip().startswith("#"):
        last_idx = non_empty[-1]
        before = "\n".join(lines[:last_idx]).rstrip()
        hashtags = lines[last_idx].strip()
        return f"{before}\n\n{link_line}\n\n{hashtags}"
    return f"{text.strip()}\n\n{link_line}"


def create_and_send_draft(
    title: str,
    text: str,
    attachments: str = "",
    wall_attachments: str = "",
    peer_id: Optional[int] = None,
    custom_publish_date: Optional[int] = None
) -> Dict[str, Any]:
    """
    Создает черновик поста, рассчитывает таймер и отправляет карточку на согласование в беседу.
    """
    target_peer = peer_id or getattr(config, "VK_APPROVALS_PEER_ID", 0)
    if not target_peer:
        raise ValueError("Peer ID для согласования не задан и не настроен в VK_APPROVALS_PEER_ID")

    drafts = load_drafts()
    draft_id = f"post_{int(time.time())}_{random.randint(100, 999)}"

    # Добавляем гиперссылку на группу для репостов
    text = ensure_community_link(text)

    if custom_publish_date:
        pub_ts = custom_publish_date
        dt_str = datetime.datetime.fromtimestamp(pub_ts).strftime("%d.%m.%Y в %H:%M")
    else:
        pub_ts, dt_str = calculate_next_publish_date()

    draft = {
        "id": draft_id,
        "title": title,
        "text": text.strip(),
        "attachments": attachments.strip(),
        "wall_attachments": (wall_attachments or attachments).strip(),
        "publish_date": pub_ts,
        "publish_date_str": dt_str,
        "status": "pending",
        "created_at": int(time.time()),
        "peer_id": target_peer
    }
    drafts[draft_id] = draft
    save_drafts(drafts)

    card_msg = format_for_vk(text)

    kb = get_approval_keyboard(draft_id, publish_date_str=dt_str)
    send_params = {
        "peer_ids": target_peer,
        "message": card_msg,
        "keyboard": json.dumps(kb, ensure_ascii=False),
        "random_id": random.randint(1, 10000000)
    }

    if attachments:
        send_params["attachment"] = attachments

    res = vk.call_api("messages.send", send_params)
    logger.info(f"Черновик {draft_id} отправлен на согласование в peer {target_peer}: {res}")

    # Извлекаем conversation_message_id для бесед (peer_ids возвращает список объектов)
    cmid = None
    if isinstance(res, list) and res:
        cmid = res[0].get("conversation_message_id")
    elif isinstance(res, dict):
        cmid = res.get("conversation_message_id") or res.get("message_id")

    if cmid:
        draft["conversation_message_id"] = cmid
        drafts[draft_id] = draft
        save_drafts(drafts)

    return draft

def update_draft_card(
    draft_id: str,
    new_text: Optional[str] = None,
    new_attachments: Optional[str] = None,
    new_wall_attachments: Optional[str] = None
) -> bool:
    """
    Обновляет черновик и редактирует карточку согласования НА МЕСТЕ через messages.edit.
    Использует conversation_message_id, исключая дублирование сообщений в ленте беседы.
    """
    drafts = load_drafts()
    draft = drafts.get(draft_id)
    if not draft:
        return False

    if new_text is not None:
        draft["text"] = ensure_community_link(new_text.strip())
    if new_attachments is not None:
        draft["attachments"] = new_attachments.strip()
    if new_wall_attachments is not None:
        draft["wall_attachments"] = new_wall_attachments.strip()

    draft["status"] = "pending"
    drafts[draft_id] = draft
    save_drafts(drafts)

    peer_id = draft.get("peer_id", 2000000005)
    pub_str = draft.get("publish_date_str", "")
    kb = get_approval_keyboard(draft_id, publish_date_str=pub_str)

    cmid = draft.get("conversation_message_id")
    edited = False
    if cmid:
        try:
            edit_params = {
                "peer_id": peer_id,
                "conversation_message_id": cmid,
                "message": format_for_vk(draft["text"]),
                "keyboard": json.dumps(kb, ensure_ascii=False)
            }
            if draft.get("attachments"):
                edit_params["attachment"] = draft["attachments"]
            res = vk.call_api("messages.edit", edit_params)
            edited = bool(res == 1 or res is True)
            logger.info(f"Карточка {draft_id} отредактирована на месте (cmid={cmid}): {res}")
        except Exception as e:
            logger.warning(f"Не удалось отредактировать сообщение {cmid}: {e}")

    if not edited:
        # Фолбэк на отправку сообщения с фиксацией нового cmid, если редактирование недоступно
        send_params = {
            "peer_ids": peer_id,
            "message": format_for_vk(draft["text"]),
            "keyboard": json.dumps(kb, ensure_ascii=False),
            "random_id": random.randint(1, 10000000)
        }
        if draft.get("attachments"):
            send_params["attachment"] = draft["attachments"]
        res = vk.call_api("messages.send", send_params)
        new_cmid = res[0].get("conversation_message_id") if isinstance(res, list) and res else None
        if new_cmid:
            draft["conversation_message_id"] = new_cmid
            drafts[draft_id] = draft
            save_drafts(drafts)

    return True

def handle_approval_action(action: str, draft_id: str, user_id: int) -> Tuple[bool, str]:
    """
    Обработка нажатия кнопок согласования (approve, revise, reject, recall).
    """
    drafts = load_drafts()
    draft = drafts.get(draft_id)
    if not draft:
        return False, f"⚠️ Черновик с ID '{draft_id}' не найден."

    peer_id = draft.get("peer_id", 2000000005)
    pub_str = draft.get("publish_date_str", "")

    if action == "post_approve":
        if draft.get("status") == "approved":
            return True, f"ℹ️ Этот пост уже был одобрен ранее и находится в таймере."

        # Отправляем в таймер группы через wall.post
        post_params = {
            "owner_id": f"-{config.VK_GROUP_ID}",
            "from_group": 1,
            "message": draft["text"],
            "publish_date": draft["publish_date"]
        }
        wall_att = draft.get("wall_attachments") or draft.get("attachments")
        if wall_att:
            post_params["attachments"] = wall_att

        res = vk.call_api("wall.post", post_params)
        if "post_id" in res:
            pid = res["post_id"]
            draft["status"] = "approved"
            draft["vk_post_id"] = pid
            save_drafts(drafts)

            recall_kb = get_recall_keyboard(draft_id)
            recall_kb_json = json.dumps(recall_kb, ensure_ascii=False)

            # 1. Подтверждение в беседу согласования («Апрувы постов»)
            reply = (
                f"✅ Черновик одобрен!\n\n"
                f"Запись поставлена в официальный таймер сообщества.\n"
                f"📅 Выход: {pub_str}\n"
                f"🔗 В таймере: wall-{config.VK_GROUP_ID}_{pid}\n\n"
                f"Если одобрение произошло случайно, нажмите кнопку отзыва ниже."
            )
            vk.call_api("messages.send", {
                "peer_id": peer_id,
                "message": reply,
                "keyboard": recall_kb_json,
                "random_id": random.randint(1, 10000000)
            })

            # 2. Опциональное дублирование в резервное хранилище постов
            storage_peer = getattr(config, "VK_STORAGE_PEER_ID", 0)
            if storage_peer and storage_peer != peer_id:
                storage_card = (
                    f"📦 ОДОБРЕННЫЙ ПОСТ В ТАЙМЕРЕ\n"
                    f"«{draft.get('title', 'Без названия')}»\n\n"
                    f"{format_for_vk(draft['text'])}\n\n"
                    f"⏰ Запланирован на: {pub_str}\n"
                    f"🔗 Запись в таймере: wall-{config.VK_GROUP_ID}_{pid}\n"
                    f"🆔 Черновик: {draft_id}"
                )
                storage_params = {
                    "peer_id": storage_peer,
                    "message": storage_card,
                    "keyboard": recall_kb_json,
                    "random_id": random.randint(1, 10000000)
                }
                if draft.get("attachments"):
                    storage_params["attachment"] = draft["attachments"]
                try:
                    vk.call_api("messages.send", storage_params)
                except Exception as e:
                    logger.warning(f"Не удалось отправить пост в хранилище {storage_peer}: {e}")

            return True, reply

        else:
            err = res.get("error", {}).get("error_msg", "Неизвестная ошибка")
            return False, f"⚠️ Ошибка постановки в таймер: {err}"

    elif action == "post_recall":
        if draft.get("status") not in ("approved", "pending"):
            return False, f"⚠️ Черновик имеет статус '{draft.get('status')}', отзыв недоступен."

        pid = draft.get("vk_post_id")
        deleted_api = False
        del_detail = ""
        if pid:
            deleted_api, del_detail = delete_post_from_wall(pid)
            logger.info(f"Удаление поста {pid} из таймера VK: {deleted_api} ({del_detail})")

        draft["status"] = "recalled"
        save_drafts(drafts)

        api_info = (
            "✅ Запись удалена из таймера стены VK через API."
            if deleted_api else
            f"ℹ️ Ссылка на таймер группы (отложенные записи):\n"
            f"https://vk.com/wall-{config.VK_GROUP_ID}?filter=postponed"
        )

        reply = (
            f"🚫 Публикация «{draft.get('title')}» отозвана!\n\n"
            f"Пост снят с активной очереди публикации и помечен как отозванный.\n\n"
            f"{api_info}"
        )

        # Отправляем в беседу согласования
        vk.call_api("messages.send", {
            "peer_id": peer_id,
            "message": reply,
            "random_id": random.randint(1, 10000000)
        })

        # Также уведомляем хранилище постов, если настроено
        storage_peer = getattr(config, "VK_STORAGE_PEER_ID", 0)
        if storage_peer and storage_peer != peer_id:
            try:
                vk.call_api("messages.send", {
                    "peer_id": storage_peer,
                    "message": f"🚫 Черновик «{draft.get('title')}» (ID: {draft_id}) отозван из публикации.",
                    "random_id": random.randint(1, 10000000)
                })
            except Exception:
                pass

        return True, reply

    elif action == "post_revise":
        draft["status"] = "revising"
        save_drafts(drafts)
        reply = (
            f"✏️ Черновик «{draft.get('title')}» отправлен на доработку.\n\n"
            f"Напиши прямо сюда свои замечания (стиль, факты, заголовок, картинку) — я внесу правки и пришлю обновленный черновик."
        )
        vk.call_api("messages.send", {
            "peer_id": peer_id,
            "message": reply,
            "random_id": random.randint(1, 10000000)
        })

        try:
            from queue_manager import push_message
            push_message({
                "source": "VK_POST_REVISE",
                "chat_id": peer_id,
                "user_id": user_id,
                "user": f"vk_id{user_id}",
                "text": f"[✏️ ДОРАБОТКА ПОСТА]: Пользователь отправил на доработку черновик «{draft.get('title')}» (ID: {draft_id}).",
                "draft_id": draft_id,
                "timestamp": time.time()
            })
        except Exception:
            pass

        return True, reply

    elif action == "post_reject":
        draft["status"] = "rejected"
        save_drafts(drafts)
        reply = f"❌ Черновик «{draft.get('title')}» отклонен и снят с публикации."
        vk.call_api("messages.send", {
            "peer_id": peer_id,
            "message": reply,
            "random_id": random.randint(1, 10000000)
        })
        return True, reply


    return False, "Неизвестное действие."


