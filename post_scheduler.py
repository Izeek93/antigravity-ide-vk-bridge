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
import threading
from typing import Optional, Dict, Any, Tuple, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PostScheduler")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DRAFTS_FILE = os.path.join(BASE_DIR, "drafts.json")
REVISION_STATE_FILE = os.path.join(BASE_DIR, "revision_state.json")

# Глобальный реестр таймеров удаления для отклоненных карточек (Rule 3)
_REJECT_TIMERS: Dict[str, threading.Timer] = {}

import config
STEP_HOURS = getattr(config, "VK_STEP_HOURS", 3.0)
JITTER_MINUTES = getattr(config, "VK_JITTER_MINUTES", 20)
QUIET_START_HOUR = getattr(config, "VK_QUIET_START_HOUR", 23)  # 23:00
QUIET_END_HOUR = getattr(config, "VK_QUIET_END_HOUR", 9)     # 09:00

import vk_api_client as vk
from vk_formatter import format_for_vk

def purge_approvals_chat(peer_id: Optional[int] = None, max_scan_cmids: int = 200) -> int:
    """Удаляет все сообщения бота в беседе согласования (принудительная чистка)."""
    target_peer = peer_id or getattr(config, "VK_APPROVALS_PEER_ID", 2000000001)
    total_deleted = 0
    for start in range(1, max_scan_cmids, 50):
        cmid_list = list(range(start, start + 50))
        cmid_str = ",".join(map(str, cmid_list))
        try:
            res = vk.call_api("messages.delete", {
                "peer_id": target_peer,
                "cmids": cmid_str,
                "delete_for_all": 1
            })
            if isinstance(res, list):
                successes = [r for r in res if r.get("response") == 1]
                total_deleted += len(successes)
        except Exception as e:
            logger.debug(f"Ошибка пачки удаления {start}..{start+49}: {e}")
    logger.info(f"Очистка беседы {target_peer}: удалено {total_deleted} сообщений.")
    return total_deleted


def schedule_ephemeral_delete(peer_id: int, cmid: int, delay_seconds: int = 35) -> threading.Timer:
    """Планирует автоудаление служебного сообщения по истечении TTL (Rule 2)."""
    def _deleter():
        try:
            vk.delete_conversation_message(peer_id, cmid)
            logger.info(f"Эфемерное сообщение {cmid} в peer {peer_id} удалено по TTL ({delay_seconds}с)")
        except Exception as e:
            logger.debug(f"Не удалось удалить эфемерное сообщение {cmid}: {e}")

    t = threading.Timer(delay_seconds, _deleter)
    t.daemon = True
    t.start()
    return t

def send_ephemeral_message(peer_id: int, text: str, ttl_seconds: int = 35) -> Optional[int]:
    """Отправляет служебное сообщение в беседу и ставит его на автоудаление (Rule 2)."""
    try:
        res = vk.call_api("messages.send", {
            "peer_ids": peer_id,
            "message": text,
            "random_id": random.randint(1, 10000000)
        })
        cmid = None
        if isinstance(res, list) and res:
            cmid = res[0].get("conversation_message_id")
        elif isinstance(res, dict):
            cmid = res.get("conversation_message_id")
        if cmid:
            schedule_ephemeral_delete(peer_id, cmid, delay_seconds=ttl_seconds)
            return cmid
    except Exception as e:
        logger.warning(f"Ошибка отправки эфемерного сообщения: {e}")
    return None


def _load_user_token() -> Optional[str]:
    tok = os.getenv("VK_USER_TOKEN", "").strip()
    if tok:
        return tok
    for env_path in [
        os.path.join(BASE_DIR, ".env"),
        os.path.join(BASE_DIR, "..", "ideas", ".env.secrets"),
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
    Расчёт времени публикации с шагом ~3 часа (±20 мин) и учётом тихих часов (23:00 - 09:00).
    Возвращает (timestamp, читаемая_строка).
    """
    now = int(time.time())
    if not base_time:
        last_postponed = get_last_postponed_time()
        base_time = last_postponed if last_postponed and last_postponed > now else now

    if base_time < now:
        base_time = now

    # Шаг ~3 часа + плавающие минуты (джиттер ±20 мин)
    jitter_sec = random.randint(-JITTER_MINUTES * 60, JITTER_MINUTES * 60)
    candidate_ts = int(base_time + (STEP_HOURS * 3600) + jitter_sec)

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
    tmp_file = f"{DRAFTS_FILE}.tmp_{os.getpid()}_{random.randint(1000, 9999)}"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(drafts, f, indent=2, ensure_ascii=False)
        os.replace(tmp_file, DRAFTS_FILE)
    except Exception as e:
        logger.warning(f"Ошибка атомарного сохранения drafts.json: {e}")
        if os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except Exception:
                pass

def set_active_revision(draft_id: str, user_id: int):
    """Сохраняет текущий черновик в состоянии активной доработки."""
    data = {
        "draft_id": draft_id,
        "user_id": user_id,
        "timestamp": int(time.time())
    }
    try:
        with open(REVISION_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Не удалось сохранить revision_state: {e}")

def get_active_revision(max_age_seconds: int = 3600) -> Optional[Dict[str, Any]]:
    """Возвращает контекст активного черновика в ревизии (окно ожидания 1 час)."""
    if not os.path.exists(REVISION_STATE_FILE):
        return None
    try:
        with open(REVISION_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            ts = data.get("timestamp", 0)
            if time.time() - ts <= max_age_seconds:
                return data
    except Exception:
        pass
    return None

def clear_active_revision():
    """Сбрасывает состояние активной доработки после получения правок."""
    try:
        if os.path.exists(REVISION_STATE_FILE):
            os.remove(REVISION_STATE_FILE)
    except Exception:
        pass

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


def get_revising_keyboard(draft_id: str) -> dict:
    """Формирует кнопку отмены режима доработки (возврат в согласование)."""
    return {
        "inline": True,
        "buttons": [
            [
                {
                    "action": {
                        "type": "text",
                        "label": "↩️ Отменить доработку",
                        "payload": json.dumps({"command": "post_cancel_revise", "draft_id": draft_id})
                    },
                    "color": "secondary"
                }
            ]
        ]
    }


def get_recalled_keyboard(draft_id: str) -> dict:
    """Формирует кнопку возврата отозванной публикации обратно на согласование."""
    return {
        "inline": True,
        "buttons": [
            [
                {
                    "action": {
                        "type": "text",
                        "label": "♻️ Вернуть на согласование",
                        "payload": json.dumps({"command": "post_restore", "draft_id": draft_id})
                    },
                    "color": "positive"
                }
            ]
        ]
    }


def get_rejected_keyboard(draft_id: str) -> dict:
    """Формирует кнопку отмены удаления отклоненного черновика (Rule 3)."""
    return {
        "inline": True,
        "buttons": [
            [
                {
                    "action": {
                        "type": "text",
                        "label": "↩️ Отменить удаление",
                        "payload": json.dumps({"command": "post_restore", "draft_id": draft_id})
                    },
                    "color": "positive"
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

def render_card_content(draft: Dict[str, Any]) -> Tuple[str, dict]:
    """Генерирует актуальный текст и Inline-клавиатуру карточки в зависимости от её статуса."""
    draft_id = draft["id"]
    status = draft.get("status", "pending")
    pub_str = draft.get("publish_date_str", "")
    base_text = format_for_vk(draft.get("text", ""))

    if status == "approved":
        pid = draft.get("vk_post_id", "")
        header = (
            f"✅ [В ТАЙМЕРЕ СТЕНЫ — {pub_str}]\n"
            f"🔗 wall-{config.VK_GROUP_ID}_{pid}\n"
            f"────────────────────\n"
        )
        return header + base_text, get_recall_keyboard(draft_id)

    elif status == "revising":
        header = (
            f"✏️ [НА ДОРАБОТКЕ]\n"
            f"Ожидаются замечания или голосовой комментарий в чат...\n"
            f"────────────────────\n"
        )
        return header + base_text, get_revising_keyboard(draft_id)

    elif status == "recalled":
        header = (
            f"🚫 [ПУБЛИКАЦИЯ ОТОЗВАНА]\n"
            f"────────────────────\n"
        )
        return header + base_text, get_recalled_keyboard(draft_id)

    elif status == "rejected":
        header = (
            f"❌ [ОТКЛОНЕНО]\n"
            f"Карточка будет автоматически удалена через 10 секунд...\n"
            f"────────────────────\n"
        )
        return header + base_text, get_rejected_keyboard(draft_id)

    else:
        # Default 'pending'
        return base_text, get_approval_keyboard(draft_id, publish_date_str=pub_str)


def mutate_draft_card_in_place(draft_id: str, new_status: Optional[str] = None) -> bool:
    """
    Редактирует сообщение карточки прямо в чате через messages.edit (Rule 1).
    Полностью устраняет дублирующие сообщения в ленте беседы.
    """
    drafts = load_drafts()
    draft = drafts.get(draft_id)
    if not draft:
        return False

    if new_status is not None:
        draft["status"] = new_status
        drafts[draft_id] = draft
        save_drafts(drafts)

    peer_id = draft.get("peer_id", 2000000001)
    cmid = draft.get("conversation_message_id")
    if not cmid:
        return False

    card_text, card_kb = render_card_content(draft)

    try:
        edit_params = {
            "peer_id": peer_id,
            "conversation_message_id": cmid,
            "message": card_text,
            "keyboard": json.dumps(card_kb, ensure_ascii=False)
        }
        if draft.get("attachments"):
            edit_params["attachment"] = draft["attachments"]
        res = vk.call_api("messages.edit", edit_params)
        logger.info(f"Карточка {draft_id} обновлена на месте (status={draft.get('status')}, cmid={cmid}): {res}")
        return bool(res == 1 or res is True)
    except Exception as e:
        logger.warning(f"Ошибка in-place мутации карточки {cmid}: {e}")
        return False


def update_draft_card(
    draft_id: str,
    new_text: Optional[str] = None,
    new_attachments: Optional[str] = None,
    new_wall_attachments: Optional[str] = None,
    new_publish_date: Optional[int] = None
) -> bool:
    """
    Обновляет контент черновика и редактирует карточку НА МЕСТЕ через messages.edit.
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
    if new_publish_date is not None:
        draft["publish_date"] = new_publish_date
        draft["publish_date_str"] = datetime.datetime.fromtimestamp(new_publish_date).strftime("%d.%m.%Y в %H:%M")

    draft["status"] = "pending"
    drafts[draft_id] = draft
    save_drafts(drafts)

    edited = mutate_draft_card_in_place(draft_id, new_status="pending")
    if not edited:
        # Фолбэк на отправку новой карточки, если редактирование невозможно
        peer_id = draft.get("peer_id", 2000000001)
        card_text, card_kb = render_card_content(draft)
        send_params = {
            "peer_ids": peer_id,
            "message": card_text,
            "keyboard": json.dumps(card_kb, ensure_ascii=False),
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


def handle_approval_action(action: str, draft_id: str, user_id: int, peer_id: Optional[int] = None) -> Tuple[bool, str]:
    """
    Конечный автомат жизненного цикла кнопок согласования:
    - post_approve: публикация в таймер стены + in-place плашка [В ТАЙМЕРЕ] + кнопка [🚫 Отозвать].
    - post_revise: in-place плашка [НА ДОРАБОТКЕ] + кнопка [↩️ Отменить] + эфемерная подсказка (TTL 45с).
    - post_cancel_revise: сброс режима доработки + возврат карточки в pending на месте.
    - post_reject: in-place плашка [ОТКЛОНЕНО] + кнопка [↩️ Отменить] + автоудаление через 10с (Rule 3).
    - post_recall: снятие из таймера стены + in-place [ОТОЗВАНО] + кнопка [♻️ Вернуть] + эфемерка (TTL 35с).
    - post_restore: отмена таймера удаления / возврат черновика в pending на месте.
    """
    drafts = load_drafts()
    draft = drafts.get(draft_id)
    if not draft:
        return False, f"⚠️ Черновик с ID '{draft_id}' не найден."

    if peer_id is None:
        peer_id = draft.get("peer_id", 2000000001)
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

            # Правило 1: In-Place мутация исходной карточки без спама отдельными сообщениями
            mutate_draft_card_in_place(draft_id, "approved")

            # Перемещение в "Одобренные посты" (VK_STORAGE_PEER_ID) "как есть", без изменения содержимого
            storage_peer = getattr(config, "VK_STORAGE_PEER_ID", 0)
            if storage_peer and storage_peer != peer_id:
                storage_params = {
                    "peer_id": storage_peer,
                    "message": format_for_vk(draft["text"]),
                    "random_id": random.randint(1, 10000000)
                }
                storage_att = draft.get("attachments") or draft.get("wall_attachments")
                if storage_att:
                    storage_params["attachment"] = storage_att
                try:
                    vk.call_api("messages.send", storage_params)
                    logger.info(f"Пост {draft_id} отправлен в «Одобренные посты» ({storage_peer}) «как есть».")
                except Exception as e:
                    logger.warning(f"Не удалось отправить пост в хранилище {storage_peer}: {e}")

            return True, f"✅ Черновик «{draft.get('title')}» одобрен и помещён в таймер стены."

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
        mutate_draft_card_in_place(draft_id, "recalled")

        api_info = (
            "✅ Запись удалена из таймера стены VK через API."
            if deleted_api else
            f"ℹ️ Для удаления из отложки стены перейдите по ссылке:\n"
            f"https://vk.com/wall-{config.VK_GROUP_ID}?filter=postponed"
        )
        recall_note = (
            f"🚫 Публикация «{draft.get('title')}» отозвана.\n\n"
            f"{api_info}\n\n"
            f"Чтобы вернуть пост в согласование, нажмите «♻️ Вернуть на согласование» на карточке."
        )
        send_ephemeral_message(peer_id, recall_note, ttl_seconds=35)
        return True, recall_note

    elif action == "post_revise":
        draft["status"] = "revising"
        save_drafts(drafts)
        set_active_revision(draft_id, user_id)
        mutate_draft_card_in_place(draft_id, "revising")

        hint = (
            f"✏️ Черновик «{draft.get('title')}» переведён в режим доработки.\n\n"
            f"Напишите в чат или отправьте голосовое с правками — агент внесёт исправления.\n"
            f"Для отмены нажмите кнопку «↩️ Отменить доработку» на карточке."
        )
        send_ephemeral_message(peer_id, hint, ttl_seconds=45)

        try:
            from queue_manager import push_message
            push_message({
                "source": "VK_POST_REVISE",
                "chat_id": peer_id,
                "user_id": user_id,
                "user": f"vk_id{user_id}",
                "text": f"[✏️ ДОРАБОТКА ПОСТА]: Черновик «{draft.get('title')}» (ID: {draft_id}) ожидает замечаний пользователя.",
                "draft_id": draft_id,
                "timestamp": time.time()
            })
        except Exception:
            pass

        return True, hint

    elif action == "post_cancel_revise":
        clear_active_revision()
        draft["status"] = "pending"
        save_drafts(drafts)
        mutate_draft_card_in_place(draft_id, "pending")
        send_ephemeral_message(peer_id, f"ℹ️ Режим доработки отменён. Черновик «{draft.get('title')}» возвращён на согласование.", ttl_seconds=20)
        return True, "Доработка отменена."

    elif action == "post_reject":
        draft["status"] = "rejected"
        save_drafts(drafts)
        mutate_draft_card_in_place(draft_id, "rejected")

        # Отменяем предыдущий таймер, если уже был запущен
        old_timer = _REJECT_TIMERS.pop(draft_id, None)
        if old_timer:
            old_timer.cancel()

        cmid = draft.get("conversation_message_id")
        if cmid:
            def _delete_card_task():
                try:
                    vk.delete_conversation_message(peer_id, cmid)
                    logger.info(f"Карточка {draft_id} (cmid {cmid}) удалена из беседы (Rule 3 Clean-on-Reject)")
                except Exception as e:
                    logger.warning(f"Не удалось удалить отклоненную карточку {cmid}: {e}")
                finally:
                    _REJECT_TIMERS.pop(draft_id, None)

            reject_timer = threading.Timer(10.0, _delete_card_task)
            reject_timer.daemon = True
            reject_timer.start()
            _REJECT_TIMERS[draft_id] = reject_timer

        return True, "Карточка отклонена и будет удалена через 10 секунд."

    elif action == "post_restore":
        # Отменяем таймер удаления карточки (Rule 3)
        timer = _REJECT_TIMERS.pop(draft_id, None)
        if timer:
            timer.cancel()
            logger.info(f"Таймер удаления карточки {draft_id} успешно отменен пользователем.")

        clear_active_revision()
        draft["status"] = "pending"
        save_drafts(drafts)
        mutate_draft_card_in_place(draft_id, "pending")
        send_ephemeral_message(peer_id, f"♻️ Черновик «{draft.get('title')}» восстановлен и возвращён на согласование.", ttl_seconds=20)
        return True, "Черновик восстановлен на согласование."

    return False, "Неизвестное действие."



