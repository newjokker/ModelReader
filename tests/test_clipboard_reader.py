import datetime
import json
import os
import tempfile
import unittest

import clipboard_reader
from clipboard_reader import (
    DEFAULT_MODEL,
    DEFAULT_VOICE_ID,
    VOICE_PRESETS,
    build_cache_record,
    build_cache_id,
    build_t2a_payload,
    enhance_text_for_tts,
    has_tts_markup,
    normalize_voice_id,
    save_audio,
    save_cache_record,
    sanitize_minimax_response,
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

    def test_cache_id_includes_timestamp_and_text_hash(self):
        cache_id = build_cache_id(" 你好 世界 ", datetime.datetime(2026, 6, 17, 9, 30, 1))
        self.assertRegex(cache_id, r"^clipboard-20260617-093001-[0-9a-f]{10}$")

    def test_record_and_audio_caches_share_cache_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            record_dir = os.path.join(tmpdir, "Records")
            audio_dir = os.path.join(tmpdir, "Audio")
            old_record = clipboard_reader.RECORD_CACHE_DIR
            old_audio = clipboard_reader.AUDIO_CACHE_DIR
            try:
                clipboard_reader.RECORD_CACHE_DIR = record_dir
                clipboard_reader.AUDIO_CACHE_DIR = audio_dir
                cache_id = "clipboard-20260617-093001-abcdef1234"
                config = {
                    "api_key": "secret",
                    "model": "speech-2.8-hd",
                    "voice_id": "female-shaonv",
                    "speed": 1.25,
                    "volume": 0.8,
                    "pitch": 1,
                    "enhancement_mode": "gentle",
                }
                record = build_cache_record(cache_id, " 原文 ", "增强<#0.4#>", "增强<#0.4#>", config, "测试", False)
                record_path = save_cache_record(record)
                audio_path = save_audio(b"mp3", cache_id)

                self.assertEqual(os.path.basename(record_path), f"{cache_id}.json")
                self.assertEqual(os.path.basename(audio_path), f"{cache_id}.mp3")
                with open(record_path, encoding="utf-8") as f:
                    saved = json.load(f)
                self.assertEqual(saved["texts"]["original"], "原文")
                self.assertEqual(saved["texts"]["enhanced"], "增强<#0.4#>")
                self.assertEqual(saved["tts"]["model"], "speech-2.8-hd")
                self.assertEqual(saved["tts"]["voice_id"], "female-shaonv")
                self.assertEqual(saved["tts"]["speed"], 1.25)
                self.assertEqual(saved["tts"]["volume"], 0.8)
                self.assertEqual(saved["tts"]["pitch"], 1)
                self.assertNotIn("secret", json.dumps(saved, ensure_ascii=False))
            finally:
                clipboard_reader.RECORD_CACHE_DIR = old_record
                clipboard_reader.AUDIO_CACHE_DIR = old_audio

    def test_sanitize_minimax_response_removes_audio_hex(self):
        response = {"data": {"audio": "deadbeef", "status": 2}, "base_resp": {"status_code": 0}}
        self.assertEqual(
            sanitize_minimax_response(response),
            {"data": {"status": 2}, "base_resp": {"status_code": 0}},
        )


if __name__ == "__main__":
    unittest.main()
