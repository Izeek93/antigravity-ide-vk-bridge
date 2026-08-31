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
import voice_engine

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
        self.assertEqual(group["id"], 149687922)
        print(f"\n[VK Test] Connected to group ID: {group['id']}, Name: {group.get('name')}")

    def test_03_vk_longpoll_server(self):
        """Test fetching VK Bots LongPoll server."""
        lp = vk.call_api("groups.getLongPollServer", {"group_id": 149687922})
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

if __name__ == "__main__":
    unittest.main(verbosity=2)
