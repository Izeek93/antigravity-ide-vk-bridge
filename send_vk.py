"""
vk-bot/send_vk.py
=================
Универсальный клиент и CLI-утилита для отправки сообщений, фото, документов
и голосовых ответов (TTS) пользователям ВКонтакте.
Поддерживает автоматический сплиттер длинных сообщений (>4000 символов),
доставку вложений и гибкий интерфейс командной строки.
"""

import os
import sys
import time
import argparse

# Принудительный UTF-8 вывод на консоли Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import config
import vk_api_client as vk
from vk_keyboard import get_main_keyboard
from vk_formatter import format_for_vk
from voice_engine import synthesize_voice


def get_default_user_id() -> int:
    """Возвращает первый разрешённый ID пользователя из настроек."""
    allowed = config.VK_ALLOWED_USER_IDS
    if allowed:
        return next(iter(allowed))
    raise ValueError("Не указан получатель: укажите --user_id или настройте VK_ALLOWED_USER_IDS в .env")


def split_message_text(text: str, chunk_size: int = 4000) -> list[str]:
    """Разбивает длинный текст на блоки до 4000 символов без разрыва слов по возможности."""
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    lines = text.split("\n")
    current_chunk = []
    current_len = 0

    for line in lines:
        if current_len + len(line) + 1 > chunk_size:
            if current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = [line]
                current_len = len(line)
            else:
                # Если одна строка больше chunk_size
                for i in range(0, len(line), chunk_size):
                    chunks.append(line[i:i + chunk_size])
                current_len = 0
        else:
            current_chunk.append(line)
            current_len += len(line) + 1

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    return chunks


def send_message_to_user(user_id: int, text: str, attachment: str = None) -> list[int]:
    """Отправляет текстовое сообщение (с авто-нарезкой при превышении лимита 4000 символов)."""
    kb = get_main_keyboard(config.is_voice_enabled())
    formatted = format_for_vk(text)
    chunks = split_message_text(formatted)
    msg_ids = []

    for i, chunk in enumerate(chunks):
        # Прикрепляем вложение и клавиатуру к последнему фрагменту
        is_last = (i == len(chunks) - 1)
        att = attachment if is_last else None
        keyboard = kb if is_last else None

        msg_id = vk.send_message(user_id, chunk, keyboard=keyboard, attachment=att)
        if msg_id and isinstance(msg_id, int):
            msg_ids.append(msg_id)
            if is_last and not att:
                vk.verify_message_delivered(msg_id)
        time.sleep(0.1)

    return msg_ids


def send_photo_to_user(user_id: int, photo_path: str, caption: str = "") -> int:
    """Загружает и отправляет фотографию с опциональной подписью."""
    if not os.path.exists(photo_path):
        raise FileNotFoundError(f"Photo file not found: {photo_path}")

    att = vk.upload_photo(user_id, photo_path)
    kb = get_main_keyboard(config.is_voice_enabled())
    formatted_cap = format_for_vk(caption) if caption else ""
    return vk.send_message(user_id, formatted_cap, keyboard=kb, attachment=att)


def send_voice_to_user(user_id: int, voice_path: str) -> int:
    """Загружает и отправляет аудиосообщение (voice note)."""
    if not os.path.exists(voice_path):
        raise FileNotFoundError(f"Audio file not found: {voice_path}")

    att = vk.upload_audiomessage(user_id, voice_path)
    kb = get_main_keyboard(config.is_voice_enabled())
    msg_id = vk.send_message(user_id, "", keyboard=kb, attachment=att)
    if msg_id and isinstance(msg_id, int):
        vk.verify_message_delivered(msg_id, expect_attachment="audio_message")
    return msg_id


def send_document_to_user(user_id: int, file_path: str, caption: str = "") -> int:
    """Загружает и отправляет документ пользователю."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Document file not found: {file_path}")

    att = vk.upload_document(user_id, file_path)
    kb = get_main_keyboard(config.is_voice_enabled())
    formatted = format_for_vk(caption) if caption else ""
    msg_id = vk.send_message(user_id, formatted, keyboard=kb, attachment=att)
    if msg_id and isinstance(msg_id, int):
        vk.verify_message_delivered(msg_id, expect_attachment="doc")
    return msg_id


def send_reply_with_optional_voice(user_id: int, text: str, voice_text: str = None):
    """Синтезирует голос (если включен) и отправляет ответ в диалог."""
    if config.is_voice_enabled():
        vk.set_activity(user_id, "audiomessage")
        speech = voice_text if voice_text else text
        out_ogg = os.path.join(os.path.dirname(__file__), "media", f"vk_reply_{user_id}_{int(time.time())}.ogg")
        os.makedirs(os.path.dirname(out_ogg), exist_ok=True)
        try:
            tts_start = time.time()
            synthesize_voice(speech, out_ogg)
            tts_duration = round(time.time() - tts_start, 1)
            text += f"\n\n⏱ Генерация голоса (TTS): {tts_duration} сек."
            if os.path.exists(out_ogg) and os.path.getsize(out_ogg) > 0:
                send_voice_to_user(user_id, out_ogg)
        except Exception as e:
            print(f"[Warning] Failed to generate/send voice: {e}", file=sys.stderr)
        finally:
            if os.path.exists(out_ogg):
                try:
                    os.remove(out_ogg)
                except Exception:
                    pass

    return send_message_to_user(user_id, text)


def main():
    parser = argparse.ArgumentParser(description="Отправка сообщений, медиа и документов пользователям ВКонтакте.")
    parser.add_argument("text", nargs="?", default="", help="Текст сообщения")
    parser.add_argument("--user_id", type=int, default=None, help="ID пользователя VK")
    parser.add_argument("--photo", help="Путь к фото для отправки")
    parser.add_argument("--voice", help="Путь к аудиофайлу (voice note)")
    parser.add_argument("--doc", help="Путь к документу")
    parser.add_argument("--caption", default="", help="Подпись к фото или документу")
    parser.add_argument("--action", help="Статус активности (typing, audiomessage, photo)")

    try:
        user_id = args.user_id or get_default_user_id()
    except ValueError as e:
        print(f"❌ {e}", file=sys.stderr)
        return

    if args.action:
        vk.set_activity(user_id, args.action)
        print(f"Activity '{args.action}' sent to VK user {user_id}")
    elif args.photo:
        caption = args.caption or args.text
        send_photo_to_user(user_id, args.photo, caption=caption)
        print(f"Photo sent to VK user {user_id}")
    elif args.voice:
        send_voice_to_user(user_id, args.voice)
        print(f"Voice sent to VK user {user_id}")
    elif args.doc:
        caption = args.caption or args.text
        send_document_to_user(user_id, args.doc, caption=caption)
        print(f"Document sent to VK user {user_id}")
    elif args.text:
        send_reply_with_optional_voice(user_id, args.text)
        print(f"Message delivered to VK user {user_id}!")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
