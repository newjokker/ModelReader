#!/usr/bin/env python3
"""MiniMax TTS smoke test for the clipboard reader app."""

import os
import subprocess

from clipboard_reader import DEFAULT_VOICE_ID, minimax_t2a, save_audio


def main():
    api_key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("请先设置环境变量 MINIMAX_API_KEY，再运行 python3 test.py")

    config = {
        "api_key": api_key,
        "model": "speech-2.8-turbo",
        "voice_id": os.environ.get("MINIMAX_VOICE_ID", DEFAULT_VOICE_ID),
        "speed": 1.0,
        "volume": 1.0,
        "pitch": 0,
    }
    audio_bytes, _ = minimax_t2a("你好，这是一次 MiniMax 语音合成 API 测试。", config)
    audio_path = save_audio(audio_bytes)
    print(f"已保存: {audio_path}")
    subprocess.run(["afplay", audio_path], check=False)


if __name__ == "__main__":
    main()
