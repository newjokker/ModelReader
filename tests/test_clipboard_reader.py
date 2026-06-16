import unittest

from clipboard_reader import (
    DEFAULT_MODEL,
    DEFAULT_VOICE_ID,
    VOICE_PRESETS,
    build_t2a_payload,
    enhance_text_for_tts,
    has_tts_markup,
    normalize_voice_id,
    normalize_speed,
    trim_text_for_tts,
    voice_preset_label,
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

    def test_default_voice_is_in_presets(self):
        self.assertIn(DEFAULT_VOICE_ID, [voice_id for voice_id, _label in VOICE_PRESETS])
        self.assertEqual(voice_preset_label(DEFAULT_VOICE_ID), "青涩男声")

    def test_normalize_voice_id_falls_back_to_default(self):
        self.assertEqual(normalize_voice_id(""), DEFAULT_VOICE_ID)
        self.assertEqual(normalize_voice_id(" custom-voice "), "custom-voice")

    def test_plain_enhancement_mode_keeps_text(self):
        text = "你好世界。"
        self.assertEqual(enhance_text_for_tts(text, "plain"), text)

    def test_auto_enhancement_preserves_existing_markup(self):
        text = "等等，<#0.4#>这里不对劲。(gasps)"
        self.assertEqual(enhance_text_for_tts(text, "auto"), text)

    def test_auto_enhancement_adds_tts_markup(self):
        enhanced = enhance_text_for_tts("等等，这里不对劲。线索终于出来了！", "auto")
        self.assertTrue(has_tts_markup(enhanced))
        self.assertIn("<#0.65#>", enhanced)
        self.assertIn("(breath)", enhanced)


if __name__ == "__main__":
    unittest.main()
