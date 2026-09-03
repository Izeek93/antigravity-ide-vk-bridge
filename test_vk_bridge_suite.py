import unittest
import os
import sys
import json
import time

# Ensure UTF-8 output
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import config
import vk_api_client as vk
import vk_keyboard
import vk_formatter
import limits_checker
import tasks_checker
import queue_manager
import command_router
import screenshot
import send_vk

class TestVKBridgeSuite(unittest.TestCase):

    def test_01_vk_config_and_token(self):
        """Verify VK token loading and voice preferences."""
        self.assertTrue(len(config.VK_GROUP_TOKEN) > 20, "VK Group token must be loaded from .env")
        orig = config.is_voice_enabled()
        config.set_voice_enabled(False)
        self.assertFalse(config.is_voice_enabled())
        config.set_voice_enabled(True)
        self.assertTrue(config.is_voice_enabled())
        config.set_voice_enabled(orig)

    def test_02_vk_api_connectivity(self):
        """Test live connection to VK API via groups.getById."""
        resp = vk.call_api("groups.getById", {})
        self.assertIn("groups", resp)
        group = resp["groups"][0]
        self.assertEqual(group["id"], config.VK_GROUP_ID)
        print(f"\n[VK Test] Connected to group ID: {group['id']}, Name: {group.get('name')}")

    def test_03_vk_longpoll_server(self):
        """Test fetching VK Bots LongPoll server."""
        lp = vk.call_api("groups.getLongPollServer", {"group_id": config.VK_GROUP_ID})
        self.assertIn("server", lp)
        self.assertIn("key", lp)
        self.assertIn("ts", lp)

    def test_04_vk_keyboards(self):
        """Test VK Reply Keyboard and Inline Keyboard JSON structures."""
        main_kb = vk_keyboard.get_main_keyboard(voice_enabled=True)
        self.assertIn("buttons", main_kb)
        self.assertFalse(main_kb["one_time"])
        
        inline_kb = vk_keyboard.get_inline_status_keyboard()
        self.assertTrue(inline_kb["inline"])

    def test_05_vk_formatter(self):
        """Test Markdown-to-VK text formatting."""
        md = "# Заголовок\n\n**Жирный текст** и [Ссылка](https://vk.com)\n```python\nprint('hello')\n```"
        formatted = vk_formatter.format_for_vk(md)
        self.assertIn("📌 Заголовок", formatted)
        self.assertIn("Ссылка (https://vk.com)", formatted)

    def test_06_limits_and_tasks_checkers(self):
        """Test limits and background tasks helpers in vk-bot."""
        limits_rep = limits_checker.format_limits_report()
        tasks_rep = tasks_checker.get_background_tasks_report()
        self.assertIn("Gemini", limits_rep)
        self.assertIn("фоновые", tasks_rep.lower())

    def test_07_isolated_queue_operations(self):
        """Test FIFO queue operations in local vk-bot inbox.json via portalocker."""
        # Drain queue first
        queue_manager.pop_messages()

        payload1 = {"chat_id": 99001, "user": "test_vk_user", "text": "VK Message 1", "timestamp": time.time()}
        payload2 = {"chat_id": 99001, "user": "test_vk_user", "text": "VK Message 2", "timestamp": time.time()}

        queue_manager.push_message(payload1)
        queue_manager.push_message(payload2)

        popped = queue_manager.pop_messages()
        self.assertEqual(len(popped), 2)
        self.assertEqual(popped[0]["text"], "VK Message 1")
        self.assertEqual(popped[1]["text"], "VK Message 2")

        # Verify queue is empty after pop
        empty_check = queue_manager.pop_messages()
        self.assertEqual(len(empty_check), 0)

        # Verify lock file and inbox file are localized in vk-bot
        self.assertTrue("vk-bot" in queue_manager.INBOX_FILE)
        self.assertTrue("vk-bot" in queue_manager.LOCK_FILE)

    def test_08_command_router_dispatch(self):
        """Simulate command handling in command_router to ensure zero crashes."""
        test_commands = [
            "/start", "/help", "/status", "/limits", "/tasks", "/voice", "/voice on", "/voice off"
        ]
        test_user = next(iter(config.VK_ALLOWED_USER_IDS)) if config.VK_ALLOWED_USER_IDS else 123456789

        # Mock send_message to avoid actual VK API calls during command simulation
        orig_send = vk.send_message
        try:
            vk.send_message = lambda *args, **kwargs: 123456
            for cmd in test_commands:
                res = command_router.dispatch_command(test_user, cmd)
                self.assertTrue(res, f"Command '{cmd}' should be handled by command_router")

            # Non-command should return False
            self.assertFalse(command_router.dispatch_command(test_user, "Обычный текст для агента"))
        finally:
            vk.send_message = orig_send

    def test_09_desktop_screenshot_capture(self):
        """Test desktop screenshot capture function."""
        test_shot = "test_screen_vk.png"
        try:
            out = screenshot.capture_desktop(test_shot)
            self.assertTrue(os.path.exists(out), "Screenshot file should exist")
            self.assertTrue(os.path.getsize(out) > 1000, "Screenshot file should not be empty")
        finally:
            if os.path.exists(test_shot):
                os.remove(test_shot)

    def test_10_send_vk_text_splitter(self):
        """Test text splitter for messages exceeding VK 4096 character limit."""
        short_text = "Короткое сообщение"
        self.assertEqual(send_vk.split_message_text(short_text), [short_text])

        # 10,000 characters text
        long_text = "\n".join([f"Строка {i}: Тестовый контент для проверки сплиттера сообщений." for i in range(250)])
        self.assertTrue(len(long_text) > 8000)

        chunks = send_vk.split_message_text(long_text, chunk_size=4000)
        self.assertTrue(len(chunks) >= 2)
        for chunk in chunks:
            self.assertTrue(len(chunk) <= 4000, "Chunk should not exceed chunk_size")

        # Verify full content is preserved
        joined = "\n".join(chunks)
        self.assertEqual(len(joined.split("\n")), len(long_text.split("\n")))

if __name__ == "__main__":
    unittest.main(verbosity=2)
