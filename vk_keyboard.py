def get_main_keyboard(voice_enabled: bool = True) -> dict:
    """Returns persistent interactive VK Reply Keyboard"""
    voice_label = "🎙 Голос: ВКЛ" if voice_enabled else "🔇 Голос: ВЫКЛ"
    voice_color = "positive" if voice_enabled else "negative"
    
    return {
        "one_time": False,
        "buttons": [
            [
                {
                    "action": {"type": "text", "label": "📊 Лимиты", "payload": '{"command": "limits"}'},
                    "color": "primary"
                },
                {
                    "action": {"type": "text", "label": "📸 Скриншот", "payload": '{"command": "screen"}'},
                    "color": "primary"
                }
            ],
            [
                {
                    "action": {"type": "text", "label": "📋 Задачи", "payload": '{"command": "tasks"}'},
                    "color": "secondary"
                },
                {
                    "action": {"type": "text", "label": voice_label, "payload": '{"command": "voice"}'},
                    "color": voice_color
                }
            ],
            [
                {
                    "action": {"type": "text", "label": "ℹ️ Помощь", "payload": '{"command": "help"}'},
                    "color": "secondary"
                }
            ],
            [
                {
                    "action": {"type": "text", "label": "🚨 SOS / Проверить логи", "payload": '{"command": "sos"}'},
                    "color": "secondary"
                }
            ]
        ]
    }

def get_inline_status_keyboard() -> dict:
    """Returns inline action buttons attached under responses"""
    return {
        "inline": True,
        "buttons": [
            [
                {
                    "action": {"type": "text", "label": "📊 Квоты", "payload": '{"command": "limits"}'},
                    "color": "primary"
                },
                {
                    "action": {"type": "text", "label": "📸 Экран", "payload": '{"command": "screen"}'},
                    "color": "secondary"
                }
            ]
        ]
    }
