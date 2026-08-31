import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from voice_engine import synthesize_voice
import vk_api_client as vk
import send_vk

class TestRealVoiceDelivery(unittest.TestCase):
    def test_voice_synthesis_and_upload(self):
        text = "Тестовая проверка голосового синтеза OmniVoice и верификации доставки в ВК."
        out_ogg = os.path.join(os.path.dirname(__file__), "media", "test_autotest_voice.ogg")
        if os.path.exists(out_ogg):
            os.remove(out_ogg)
            
        synthesize_voice(text, out_ogg)
        self.assertTrue(os.path.exists(out_ogg), "OGG file must exist after synthesis")
        self.assertGreater(os.path.getsize(out_ogg), 1000, "OGG file size must be > 1KB")
        
        # Upload and send
        msg_id = send_vk.send_voice_to_user(14901004, out_ogg)
        self.assertIsNotNone(msg_id, "Message ID must be returned")
        
        # Verify read-back
        verified = vk.verify_message_delivered(msg_id, expect_attachment="audio_message")
        self.assertTrue(verified, f"Message {msg_id} must have audio_message attachment on VK")

if __name__ == "__main__":
    unittest.main()
