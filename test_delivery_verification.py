import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vk_api_client as vk

class TestDeliveryVerification(unittest.TestCase):
    def test_verify_existing_message(self):
        # 126 was an audio message
        is_delivered = vk.verify_message_delivered(126, expect_attachment="audio_message")
        self.assertTrue(is_delivered, "Message 126 should be verified with audio_message")

    def test_verify_nonexistent_message(self):
        is_delivered = vk.verify_message_delivered(999999999)
        self.assertFalse(is_delivered, "Nonexistent message must return False")

if __name__ == "__main__":
    unittest.main()
