import unittest

from clipboard_reader import (
    DEFAULT_MODEL,
    DEFAULT_VOICE_ID,
    build_t2a_payload,
    normalize_speed,
    trim_text_for_tts,
)


class ClipboardReaderTests(unittest.TestCase):
    def test_trim_text_for_tts_normalizes_and_marks_truncated(self):
        text, truncated = trim_text_for_tts("  你好\t世界  \n\n\n第二段  ", max_length=8)
        self.assertEqual(text, "你好 世界\n\n第")
        self.assertTrue(truncated)

    def test_normalize_speed_clamps(self):
        self.assertEqual(normalize_speed(0.1), 0.5)
        self.assertEqual(normalize_speed(3), 2.0)
        self.assertEqual(normalize_speed("1.25"), 1.25)

    def test_build_t2a_payload_defaults(self):
        payload = build_t2a_payload("hello", {})
        self.assertEqual(payload["model"], DEFAULT_MODEL)
        self.assertEqual(payload["voice_setting"]["voice_id"], DEFAULT_VOICE_ID)
        self.assertEqual(payload["audio_setting"]["format"], "mp3")
        self.assertEqual(payload["output_format"], "hex")


if __name__ == "__main__":
    unittest.main()
