import datetime
import json
import os
import tempfile
import unittest
from unittest import mock

import clipboard_reader
from clipboard_reader import (
    DEFAULT_MODEL,
    DEFAULT_TONE_LLM_BASE_URL,
    DEFAULT_TONE_LLM_MODEL,
    DEFAULT_VOICE_ID,
    VOICE_PRESETS,
    build_cache_record,
    build_cache_id,
    build_t2a_payload,
    config_with_voice_adjustments,
    enhance_text_for_tts,
    has_tts_markup,
    mark_cache_record_failed,
    normalize_config,
    normalize_pitch,
    normalize_volume,
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

    def test_normalize_volume_and_pitch_clamp(self):
        self.assertEqual(normalize_volume("bad"), 1.0)
        self.assertEqual(normalize_volume(-1), 0.1)
        self.assertEqual(normalize_volume(99), 10.0)
        self.assertEqual(normalize_pitch("bad"), 0)
        self.assertEqual(normalize_pitch(-99), -12)
        self.assertEqual(normalize_pitch(99), 12)

    def test_normalize_config_cleans_bad_values(self):
        config = normalize_config(
            {
                "api_key": " key ",
                "model": "",
                "voice_id": "",
                "speed": "nan",
                "volume": "bad",
                "pitch": "bad",
                "enhancement_mode": "unknown",
            }
        )
        self.assertEqual(config["api_key"], "key")
        self.assertEqual(config["model"], DEFAULT_MODEL)
        self.assertEqual(config["voice_id"], DEFAULT_VOICE_ID)
        self.assertEqual(config["speed"], 1.0)
        self.assertEqual(config["volume"], 1.0)
        self.assertEqual(config["pitch"], 0)
        self.assertEqual(config["tone_llm_model"], DEFAULT_TONE_LLM_MODEL)
        self.assertEqual(config["tone_llm_base_url"], DEFAULT_TONE_LLM_BASE_URL)

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
        self.assertIn("(gasps)", enhanced)

    def test_auto_enhancement_detects_tone_per_sentence(self):
        enhanced = enhance_text_for_tts("他轻声说，没关系。突然，门外传来脚步声！太好了，我们成功了！", "auto")
        self.assertIn("(breath) 他轻声说，没关系。", enhanced)
        self.assertIn("(gasps) 突然，门外传来脚步声！", enhanced)
        self.assertIn("太好了，我们成功了！<#0.45#> (laughs)", enhanced)

    def test_auto_enhancement_can_use_llm_tones(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                body = {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "sentences": [
                                            {"index": 0, "tone": "sad", "speed": 0.8, "pitch": -3},
                                            {"index": 1, "tone": "energetic", "speed": 1.4, "pitch": 2},
                                        ],
                                    }
                                )
                            }
                        }
                    ]
                }
                return json.dumps(body).encode("utf-8")

        metadata = {}
        config = {"tone_llm_api_key": "llm-secret", "tone_llm_model": "tone-model"}
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse()):
            enhanced = enhance_text_for_tts("他沉默着说对不起。太好了，我们成功了！", "auto", config, metadata)

        self.assertIn("(sighs) 他沉默着说对不起。", enhanced)
        self.assertIn("太好了，我们成功了！<#0.45#> (laughs)", enhanced)
        self.assertEqual(metadata["tone_provider"], "llm")
        self.assertEqual(metadata["tone_model"], "tone-model")
        self.assertEqual(metadata["sentences"][0]["tone"], "sad")
        self.assertEqual(metadata["sentences"][0]["speed"], 0.8)
        self.assertEqual(metadata["sentences"][1]["pitch"], 2)
        self.assertEqual(metadata["voice_adjustments"], {"speed": 1.1, "pitch": 0})

    def test_voice_adjustments_are_applied_to_tts_payload(self):
        config = {
            "model": "speech-2.8-hd",
            "voice_id": "female-shaonv",
            "speed": 1.0,
            "volume": 1.0,
            "pitch": 0,
        }
        adjusted = config_with_voice_adjustments(config, {"speed": 3, "volume": "0.5", "pitch": -99})
        payload = build_t2a_payload("hello", adjusted)

        self.assertEqual(payload["voice_setting"]["speed"], 2.0)
        self.assertEqual(payload["voice_setting"]["vol"], 1.0)
        self.assertEqual(payload["voice_setting"]["pitch"], -12)

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
                    "tone_llm_api_key": "llm-secret",
                    "tone_llm_model": "tone-model",
                    "tone_llm_base_url": "https://example.test/v1/chat/completions",
                }
                metadata = {
                    "tone_provider": "llm",
                    "tone_model": "tone-model",
                    "tone_base_url": "https://example.test/v1/chat/completions",
                    "voice_adjustments": {"speed": 1.35, "pitch": -1},
                    "sentences": [{"text": "原文", "tone": "gentle", "speed": 1.35, "pitch": -1}],
                }
                effective_config = config_with_voice_adjustments(config, metadata["voice_adjustments"])
                record = build_cache_record(
                    cache_id,
                    " 原文 ",
                    "增强<#0.4#>",
                    "增强<#0.4#>",
                    effective_config,
                    "测试",
                    False,
                    metadata,
                )
                record_path = save_cache_record(record)
                audio_path = save_audio(b"mp3", cache_id)

                self.assertEqual(os.path.basename(record_path), f"{cache_id}.json")
                self.assertEqual(os.path.basename(audio_path), f"{cache_id}.mp3")
                with open(record_path, encoding="utf-8") as f:
                    saved = json.load(f)
                self.assertEqual(saved["texts"]["original"], "原文")
                self.assertEqual(saved["texts"]["enhanced"], "增强<#0.4#>")
                self.assertNotIn("tts_text", saved["texts"])
                self.assertEqual(saved["tts"]["payload"]["text"], "增强<#0.4#>")
                self.assertEqual(saved["tts"]["model"], "speech-2.8-hd")
                self.assertEqual(saved["tts"]["voice_id"], "female-shaonv")
                self.assertEqual(saved["tts"]["speed"], 1.35)
                self.assertEqual(saved["tts"]["volume"], 0.8)
                self.assertEqual(saved["tts"]["pitch"], -1)
                self.assertEqual(saved["enhancement"]["tone_provider"], "llm")
                self.assertEqual(saved["enhancement"]["tone_model"], "tone-model")
                self.assertEqual(saved["enhancement"]["voice_adjustments"]["speed"], 1.35)
                self.assertNotIn("volume", saved["enhancement"]["voice_adjustments"])
                self.assertEqual(saved["enhancement"]["sentences"][0]["tone"], "gentle")
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

    def test_mark_cache_record_failed_updates_record(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_record = clipboard_reader.RECORD_CACHE_DIR
            old_audio = clipboard_reader.AUDIO_CACHE_DIR
            try:
                clipboard_reader.RECORD_CACHE_DIR = os.path.join(tmpdir, "Records")
                clipboard_reader.AUDIO_CACHE_DIR = os.path.join(tmpdir, "Audio")
                cache_id = "clipboard-20260617-093001-abcdef1234"
                record = build_cache_record(cache_id, "原文", "增强", "增强", {}, "测试", False)

                mark_cache_record_failed(record, RuntimeError("boom"))

                with open(record["files"]["record"], encoding="utf-8") as f:
                    saved = json.load(f)
                self.assertEqual(saved["result"]["status"], "failed")
                self.assertEqual(saved["result"]["error_type"], "RuntimeError")
                self.assertEqual(saved["result"]["error"], "boom")
            finally:
                clipboard_reader.RECORD_CACHE_DIR = old_record
                clipboard_reader.AUDIO_CACHE_DIR = old_audio


if __name__ == "__main__":
    unittest.main()
