import unittest
import os
import sys
import time

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import config
import vk_api_client as vk
import vk_formatter
import bridge_health_watchdog as watchdog
import task_notifier

class TestVKAdvancedFeatures(unittest.TestCase):

    def test_01_vk_formatter_cleanliness(self):
        """Ensure VK formatter strips all raw markdown asterisks and converts code nicely."""
        raw_md = "**Жирный заголовок**\n• Элемент `code_item`\n```python\nprint(1)\n```"
        formatted = vk_formatter.format_for_vk(raw_md)
        self.assertNotIn("**", formatted, "Formatted text must not contain double asterisks")
        self.assertNotIn("`", formatted, "Formatted text must not contain backticks")
        self.assertIn("«code_item»", formatted)

    def test_02_health_watchdog(self):
        """Test VK self-healing health check routine."""
        diag = watchdog.run_self_healing_health_check()
        self.assertEqual(diag["status"], "healthy")
        self.assertIn("pending_inbox_messages", diag)

    def test_03_document_upload(self):
        """Test uploading a document file to VK Messages Docs server."""
        test_doc = "test_vk_upload_sample.txt"
        with open(test_doc, "w", encoding="utf-8") as f:
            f.write("Antigravity IDE VK Bridge Test Document\nStatus: OK\n")
            
        try:
            target_uid = list(config.VK_ALLOWED_USER_IDS)[0] if config.VK_ALLOWED_USER_IDS else 14901004
            doc_att = vk.upload_document(target_uid, test_doc, "test_doc.txt")
            self.assertTrue(doc_att.startswith("doc"), f"Attachment string must start with 'doc': {doc_att}")
        finally:
            if os.path.exists(test_doc):
                os.remove(test_doc)

    def test_04_task_notifier(self):
        """Test task completion notification builder."""
        target_uid = list(config.VK_ALLOWED_USER_IDS)[0] if config.VK_ALLOWED_USER_IDS else 14901004
        success = task_notifier.notify_task_finished("Тестовый автотест", "SUCCESS", "Все проверки пройдены", 1.2, target_uid)
        self.assertTrue(success)

if __name__ == "__main__":
    unittest.main(verbosity=2)
