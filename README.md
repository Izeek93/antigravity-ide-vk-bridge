<div align="center">

# 🤖 Antigravity IDE VK Bridge
### *Двусторонний автономный агентный мост между ВКонтакте и Antigravity IDE*

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![CUDA Acceleration](https://img.shields.io/badge/CUDA-Enabled-76B900.svg?style=flat&logo=nvidia&logoColor=white)](https://developer.nvidia.com/cuda-zone)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-blue.svg?style=flat)](https://github.com/)
[![Version](https://img.shields.io/badge/release-v1.2.0--Supervisor--MCP-green.svg?style=flat)](CHANGELOG.md)
[![Roadmap](https://img.shields.io/badge/roadmap-2026-orange.svg?style=flat)](ROADMAP.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

**Antigravity IDE VK Bridge & MCP** — это полностью автономная система двусторонней синхронизации активной сессии разработчика в **Antigravity IDE** с социальной сетью **ВКонтакте** (VK Community Bots LongPoll API). 

Включает:
- 🛡️ **Self-Healing Watchdog Supervisor** (`bridge_supervisor.py`) для мгновенного авто-рестарта при сетевых сбоях.
- ⚡ **Stdio FastMCP Server** (`vk_mcp_server.py`) для нативного вызова функций VK агентом прямо из среды IDE.
- 🎙️ Голосовой ввод/вывод (локальный Faster-Whisper STT + нейро-TTS OmniVoice Eva).
- 📊 Терминальные статус-карточки, мониторинг токенов и квот IDE, захват экрана ПК и потокобезопасную очередь `portalocker`.

Подробный план развития проекта см. в [ROADMAP.md](ROADMAP.md).

</div>

---

## 🌟 Архитектура системы

```
                                  ┌──────────────────────────────┐
                                  │    VK App / Сообщения группы │
                                  └──────────────┬───────────────┘
                                                 │ 🎙 Голос / 💬 Текст / 📸 Фото
                                                 ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                          🤖 ANTIGRAVITY IDE VK BRIDGE (v1.1.0)                         │
│                                                                                        │
│  ┌────────────────────────┐   ┌────────────────────────┐   ┌────────────────────────┐  │
│  │ 🎙 Pluggable STT Engine│   │ 🗣 Pluggable TTS Engine│   │ ⏳ Live RPC Quota Probe│  │
│  │ (Faster-Whisper CUDA)  │   │ (Local OmniVoice / OGG)│   │ (LanguageServer gRPC)  │  │
│  └────────────────────────┘   └────────────────────────┘   └────────────────────────┘  │
│                                                                                        │
│  ┌────────────────────────┐   ┌────────────────────────┐   ┌────────────────────────┐  │
│  │ 📸 Desktop Screenshot  │   │ ⌨️ Dynamic VK Keyboard │   │ 🛡 LongPoll Circuit    │  │
│  │ (Multi-monitor capture)│   │ (Interactive Buttons)  │   │ (Auto-Reconnect 5-try) │  │
│  └────────────────────────┘   └────────────────────────┘   └────────────────────────┘  │
└────────────────────────────────────────┬───────────────────────────────────────────────┘
                                         │ ⚡ Isolated FIFO Queue (inbox.json & portalocker)
                                         ▼
                                  ┌──────────────────────────────┐
                                  │   Antigravity IDE Backend    │
                                  │  (Active Developer Session)  │
                                  └──────────────────────────────┘
```

---

## 🌟 Ключевые возможности

1. **🔒 Полная автономность (Zero Coupling):**
   * Мост работает независимо в собственном виртуальном окружении (`venv`) со своей локальной очередью `inbox.json`.
   * Никаких внешних зависимостей от других мостов или сервисов.
2. **🎙 Модульный голосовой стек:**
   * **STT:** Автоматическая расшифровка голосовых заметок ВКонтакте через локальный `Faster-Whisper` (GPU / CPU).
   * **TTS:** Голосовые ответы в формате аудиосообщений VK (`audio_message`).
3. **⏳ Живые квоты Antigravity IDE (`/limits`):**
   * Прямой опрос состояния локального `LanguageServerService` по gRPC.
   * Контроль скользящего 5-часового окна моделей Gemini и расхода миллионного контекста.
4. **📸 Захват экрана рабочего стола (`/screen`):**
   * Моментальный снимок экрана монитора ПК с автоматической загрузкой фото в диалог VK.
5. **🛡 Отказоустойчивость LongPoll:**
   * Защита от ложных срабатываний: фильтрация одиночных сетевых таймаутов, автоматический реконнект без спама инцидентами.
6. **🧹 Авто-очистка временных файлов:**
   * Автоматическая ротация временных файлов в папке `media/` старше 24 часов.

---

## 📋 Доступные команды в диалоге VK

| Кнопка / Команда | Описание |
| :--- | :--- |
| **`📊 Лимиты`** / `/limits` | Телеметрия квот, токенов и лимитов моделей Gemini в IDE |
| **`📸 Скриншот`** / `/screen` | Снимок экрана рабочего стола компьютера |
| **`📋 Задачи`** / `/tasks` | Список запущенных терминалов и фоновых задач |
| **`🎙 Голос`** / `/voice` | Переключение голосовых аудиоответов (ВКЛ / ВЫКЛ) |
| **`📊 Статус`** / `/status` | Состояние подключения демона моста и очереди |
| **`ℹ️ Помощь`** / `/help` | Список всех доступных команд и документация |
| **`✅ Подтвердить`** / `/approve` | Удалённое согласование интерактивного действия в IDE |
| **`❌ Отклонить`** / `/reject` | Отклонение опасного действия в IDE |

---

## 🚀 Быстрый старт и запуск

### 1. Подготовка окружения
```powershell
# Создание изолированного виртуального окружения
python -m venv venv

# Активация окружения (Windows)
.\venv\Scripts\activate

# Установка зависимостей
pip install -r requirements.txt
```

### 2. Настройка параметров (`.env`)
Скопируйте `.env.example` в `.env` и укажите данные вашего сообщества ВКонтакте:
```ini
# Токен сообщества с правами messages, photos, docs:
VK_GROUP_TOKEN="vk1.a.your_group_token"

# ID сообщества (числовой идентификатор группы без знака минус):
VK_GROUP_ID="123456789"

# Белый список ID пользователей VK (разрешённых для работы):
VK_ALLOWED_USER_IDS="123456789"

# Включение голосовых ответов по умолчанию:
ENABLE_VOICE_REPLIES=True
```

### 3. Запуск демона моста
```powershell
python vk_bridge.py
```

### 4. Запуск слушателя в IDE (Background Receiver)
```powershell
python bridge_receiver.py
```

---

## 🛠 Отправка сообщений через CLI (`send_vk.py`)

Утилита `send_vk.py` позволяет отправлять сообщения и медиа в диалог VK из консоли или скриптов автоматизации:

```powershell
# Отправка текста (с автоматической нарезкой, если >4000 символов)
python send_vk.py "Привет! Сборка проекта завершена успешно."

# Отправка фото со снимком экрана
python send_vk.py --photo "path/to/screenshot.png" --caption "Результаты теста"

# Отправка документа
python send_vk.py --doc "path/to/report.pdf" --caption "Финальный отчет"

# Отправка действия (typing / audiomessage)
python send_vk.py --action "typing"
```

---

## 🔒 Безопасность (Zero-Leak Policy)

- Все приватные токены сообщества и ID хранятся исключительно в файле `.env`.
- Файл `.env` внесён в `.gitignore` и никогда не попадает в Git-репозиторий.
- В публичном доступе размещаются только шаблоны конфигурации.

---

## 📄 Лицензия

MIT License © 2026. Разработано для экосистемы Google Antigravity.
