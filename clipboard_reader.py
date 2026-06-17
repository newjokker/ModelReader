#!/usr/bin/env python3
"""
📋 剪贴板朗读 - macOS 菜单栏朗读工具

流程:
    复制文字 -> 点击菜单栏「朗读剪贴板」-> MiniMax T2A -> afplay 自动播放
"""

__app_name__ = "📋 剪贴板朗读"
__bundle_id__ = "com.clipboardreader.app"

import datetime
import hashlib
import json
import math
import os
import plistlib
import re
import subprocess
import sys
import tempfile
import threading
import traceback
import urllib.error
import urllib.request

import rumps

from app_version import __version__

try:
    import AppKit
    import Foundation
    import objc
except Exception:
    AppKit = None
    Foundation = None
    objc = None


MINIMAX_T2A_URL = "https://api.minimax.io/v1/t2a_v2"
DEFAULT_MODEL = "speech-2.8-turbo"
DEFAULT_VOICE_ID = "male-qn-qingse"
DEFAULT_TONE_LLM_BASE_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_TONE_LLM_MODEL = "deepseek-v4-flash"
VOICE_PRESETS = [
    ("male-qn-qingse", "青涩男声"),
    ("male-qn-jingying", "精英男声"),
    ("male-qn-badao", "霸道男声"),
    ("female-shaonv", "少女女声"),
    ("female-yujie", "御姐女声"),
    ("female-tianmei", "甜美女声"),
    ("presenter_male", "男播音员"),
    ("presenter_female", "女播音员"),
    ("audiobook_male_1", "男有声书"),
    ("audiobook_female_1", "女有声书"),
]
DEFAULT_SPEED = 1.0
DEFAULT_VOLUME = 1.0
DEFAULT_PITCH = 0
MAX_TEXT_LENGTH = 10000
DEFAULT_ENHANCEMENT_MODE = "auto"
ENHANCEMENT_MODES = {
    "plain": "原文朗读",
    "auto": "自动增强",
    "gentle": "温柔",
    "energetic": "坚定",
    "news": "新闻播报",
    "suspense": "悬疑",
}
TTS_MARKUP_RE = re.compile(
    r"<#\d+(?:\.\d+)?#>|\((?:laughs|sighs|breath|exhale|gasps|emm)\)",
    re.IGNORECASE,
)
SENTENCE_TONE_RULES = [
    (
        "sad",
        re.compile(r"难过|失去|离开|孤独|遗憾|哭|眼泪|沉默|抱歉|对不起|再也|最后一次"),
    ),
    (
        "suspense",
        re.compile(r"等等|不对劲|忽然|突然|安静|错误|藏|发现|线索|门外|脚步|危险|秘密|奇怪"),
    ),
    (
        "gentle",
        re.compile(r"没关系|别怕|放心|慢慢|温柔|照顾|珍贵|辛苦|累|谢谢|轻声"),
    ),
    (
        "news",
        re.compile(r"今天|上午|下午|消息|表示|目前|完成|发布|宣布|测试人员|数据显示|记者"),
    ),
    (
        "energetic",
        re.compile(r"成了|成功|太好了|漂亮|开工|继续|坚持|加油|一定|必须|现在就|立刻"),
    ),
]
TONE_PAUSES = {
    "gentle": "<#0.65#>",
    "sad": "<#0.7#>",
    "suspense": "<#0.65#>",
    "news": "<#0.3#>",
    "energetic": "<#0.35#>",
    "plain": "<#0.4#>",
}
VALID_TONES = set(TONE_PAUSES)

APP_SUPPORT_DIR = os.path.expanduser("~/Library/Application Support/ClipboardReader")
CONFIG_FILE = os.path.join(APP_SUPPORT_DIR, "config.json")
AUDIO_CACHE_DIR = os.path.join(APP_SUPPORT_DIR, "Audio")
RECORD_CACHE_DIR = os.path.join(APP_SUPPORT_DIR, "Records")
ERROR_LOG_DIR = os.path.expanduser("~/Library/Logs/ClipboardReader")
ERROR_LOG_FILE = os.path.join(ERROR_LOG_DIR, "error.log")
LAUNCH_AGENT_LABEL = __bundle_id__
LAUNCH_AGENT_DIR = os.path.expanduser("~/Library/LaunchAgents")
LAUNCH_AGENT_FILE = os.path.join(LAUNCH_AGENT_DIR, f"{LAUNCH_AGENT_LABEL}.plist")


if AppKit is not None and objc is not None:
    class _TextServiceProvider(AppKit.NSObject):
        """macOS Services provider: receives selected text from right-click Services."""

        def readSelection_userData_error_(self, pasteboard, user_data, error):
            text = pasteboard.stringForType_(AppKit.NSPasteboardTypeString)
            if not text and hasattr(AppKit, "NSStringPboardType"):
                text = pasteboard.stringForType_(AppKit.NSStringPboardType)
            if not text:
                safe_notification(title=__app_name__, subtitle="没有可朗读文本", message="请先选中一段文字。")
                return
            self.reader_app.speak_text(str(text), source="所选文本")
else:
    _TextServiceProvider = None


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def is_main_thread():
    return Foundation is None or bool(Foundation.NSThread.isMainThread())


def run_on_main_thread(func, *args, **kwargs):
    if is_main_thread():
        return func(*args, **kwargs)

    def _call():
        try:
            func(*args, **kwargs)
        except Exception as e:
            log_exception("主线程回调失败", e)

    Foundation.NSOperationQueue.mainQueue().addOperationWithBlock_(_call)
    return None


def atomic_write_json(path, data):
    directory = os.path.dirname(path) or "."
    ensure_dir(directory)
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".json",
        dir=directory,
        delete=False,
    )
    try:
        json.dump(data, tmp, indent=2, ensure_ascii=False)
        tmp.write("\n")
        tmp.flush()
        os.fsync(tmp.fileno())
    finally:
        tmp.close()
    os.replace(tmp.name, path)


def write_error_log(context, exc_info=None, message=None):
    try:
        ensure_dir(ERROR_LOG_DIR)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            "=" * 80,
            f"[{now}] {context}",
            f"Version: {__version__}",
        ]
        if message:
            lines.append(str(message))
        if exc_info:
            lines.append("Traceback:")
            lines.extend(traceback.format_exception(*exc_info))
        lines.append("")
        with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return ERROR_LOG_FILE
    except Exception as log_error:
        sys.stderr.write(f"[ClipboardReader] 写入错误日志失败: {log_error}\n")
        return None


def log_exception(context, exc):
    return write_error_log(context, (type(exc), exc, exc.__traceback__))


def install_exception_logging():
    original_excepthook = sys.excepthook

    def _excepthook(exc_type, exc, tb):
        if exc_type is KeyboardInterrupt:
            original_excepthook(exc_type, exc, tb)
            return
        write_error_log("未处理异常", (exc_type, exc, tb))
        original_excepthook(exc_type, exc, tb)

    sys.excepthook = _excepthook

    if hasattr(threading, "excepthook"):
        original_threading_excepthook = threading.excepthook

        def _threading_excepthook(args):
            write_error_log(
                f"线程未处理异常: {getattr(args.thread, 'name', 'unknown')}",
                (args.exc_type, args.exc_value, args.exc_traceback),
            )
            original_threading_excepthook(args)

        threading.excepthook = _threading_excepthook


def safe_alert(**kwargs):
    if not is_main_thread():
        return run_on_main_thread(safe_alert, **kwargs)
    try:
        return rumps.alert(**kwargs)
    except Exception as e:
        log_exception("显示提示框失败", e)
        return None


def safe_notification(**kwargs):
    if not is_main_thread():
        return run_on_main_thread(safe_notification, **kwargs)
    try:
        rumps.notification(**kwargs)
    except Exception as e:
        log_exception("发送系统通知失败", e)


def normalize_text(text):
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def trim_text_for_tts(text, max_length=MAX_TEXT_LENGTH):
    text = normalize_text(text)
    if len(text) <= max_length:
        return text, False
    return text[:max_length].rstrip(), True


def has_tts_markup(text):
    return bool(TTS_MARKUP_RE.search(text or ""))


def normalize_enhancement_mode(mode):
    mode = str(mode or "").strip()
    return mode if mode in ENHANCEMENT_MODES else DEFAULT_ENHANCEMENT_MODE


def normalize_voice_id(voice_id):
    voice_id = str(voice_id or "").strip()
    return voice_id or DEFAULT_VOICE_ID


def voice_preset_label(voice_id):
    voice_id = normalize_voice_id(voice_id)
    for preset_id, label in VOICE_PRESETS:
        if preset_id == voice_id:
            return label
    return None


def normalize_tone_llm_base_url(url):
    url = str(url or "").strip()
    return url or DEFAULT_TONE_LLM_BASE_URL


def normalize_tone_llm_model(model):
    model = str(model or "").strip()
    return model or DEFAULT_TONE_LLM_MODEL


def get_tone_llm_api_key(config):
    return (
        (config or {}).get("tone_llm_api_key")
        or os.environ.get("TONE_LLM_API_KEY")
        or os.environ.get("DEEPSEEK_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    ).strip()


def split_sentences(text):
    return [part.strip() for part in re.split(r"(?<=[。！？!?；;])\s*", text) if part.strip()]


def pause_for_sentence(sentence, mode):
    if sentence.endswith(("？", "?")):
        return "<#0.5#>"
    if sentence.endswith(("！", "!")):
        return "<#0.45#>"
    return TONE_PAUSES.get(mode, TONE_PAUSES["plain"])


def detect_sentence_tone(sentence, fallback="plain"):
    for tone, pattern in SENTENCE_TONE_RULES:
        if pattern.search(sentence):
            return tone
    if re.search(r"(^|\n)\s*[^:\n：]{1,8}[:：]", sentence):
        return "energetic"
    return fallback if fallback in TONE_PAUSES else "plain"


def emotion_marker_for_sentence(sentence, tone):
    if tone == "sad":
        return "(sighs) ", ""
    if tone == "suspense":
        if re.search(r"等等|不对劲|忽然|突然|危险|发现|线索|门外|脚步", sentence):
            return "(gasps) ", ""
        return "(breath) ", ""
    if tone == "gentle":
        return "(breath) ", ""
    if tone == "energetic" and re.search(r"成了|成功|太好了|漂亮|加油", sentence):
        return "", " (laughs)"
    return "", ""


def enhance_sentence(sentence, mode, tone=None):
    tone = tone or (detect_sentence_tone(sentence) if mode == "auto" else mode)
    if tone not in VALID_TONES:
        tone = "plain"
    prefix, suffix = emotion_marker_for_sentence(sentence, tone)
    return f"{prefix}{sentence}{pause_for_sentence(sentence, tone)}{suffix}".strip()


def _extract_json_object(text):
    text = str(text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    if text.startswith("{"):
        return json.loads(text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("语气模型没有返回 JSON 对象")


def post_tone_llm_chat_completion(base_url, api_key, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        base_url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def classify_sentence_tones_with_llm(sentences, config):
    api_key = get_tone_llm_api_key(config)
    if not api_key:
        return None

    base_url = normalize_tone_llm_base_url((config or {}).get("tone_llm_base_url"))
    model = normalize_tone_llm_model((config or {}).get("tone_llm_model"))
    sentence_items = [{"index": index, "text": sentence} for index, sentence in enumerate(sentences)]
    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是朗读语气标注器。只判断每个句子的朗读语气，不改写文本。"
                    "语气只能从 plain, gentle, suspense, sad, news, energetic 中选择。"
                    "返回严格 JSON：{\"tones\":[{\"index\":0,\"tone\":\"plain\"}]}。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"sentences": sentence_items}, ensure_ascii=False),
            },
        ],
    }
    if "deepseek.com" in base_url or model.startswith("deepseek-v4-"):
        payload["thinking"] = {"type": "disabled"}
    try:
        data = post_tone_llm_chat_completion(base_url, api_key, payload)
    except urllib.error.HTTPError as e:
        if e.code not in (400, 422):
            raise
        payload = dict(payload)
        payload.pop("response_format", None)
        data = post_tone_llm_chat_completion(base_url, api_key, payload)

    content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    parsed = _extract_json_object(content)
    tones = ["plain"] * len(sentences)
    for item in parsed.get("tones", []):
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        tone = str(item.get("tone", "")).strip()
        if 0 <= index < len(tones) and tone in VALID_TONES:
            tones[index] = tone
    return {
        "provider": "llm",
        "model": model,
        "base_url": base_url,
        "tones": tones,
    }


def classify_sentence_tones(sentences, mode, config=None):
    if mode != "auto":
        return {
            "provider": "forced",
            "tones": [mode if mode in VALID_TONES else "plain" for _ in sentences],
        }
    try:
        llm_result = classify_sentence_tones_with_llm(sentences, config or {})
        if llm_result:
            return llm_result
    except Exception as e:
        log_exception("语气模型判断失败，已回退到本地规则", e)
    return {
        "provider": "rules",
        "tones": [detect_sentence_tone(sentence) for sentence in sentences],
    }


def enhance_sentences(sentences, mode, tones):
    enhanced = []
    for index, sentence in enumerate(sentences):
        sentence = sentence.strip()
        if not sentence:
            continue
        enhanced.append(enhance_sentence(sentence, mode, tones[index]))
    return "\n".join(enhanced).strip()


def enhance_paragraph(paragraph, mode, config=None, metadata=None):
    sentences = split_sentences(paragraph)
    if not sentences:
        return paragraph.strip()

    tone_result = classify_sentence_tones(sentences, mode, config)
    tones = tone_result["tones"]
    if metadata is not None:
        metadata.setdefault("tone_provider", tone_result.get("provider"))
        if tone_result.get("model"):
            metadata.setdefault("tone_model", tone_result.get("model"))
        if tone_result.get("base_url"):
            metadata.setdefault("tone_base_url", tone_result.get("base_url"))
        metadata.setdefault("sentences", []).extend(
            {"text": sentence, "tone": tones[index]} for index, sentence in enumerate(sentences)
        )

    return enhance_sentences(sentences, mode, tones)


def enhance_text_for_tts(text, mode=DEFAULT_ENHANCEMENT_MODE, config=None, metadata=None):
    text = normalize_text(text)
    mode = normalize_enhancement_mode(mode)
    if not text or mode == "plain" or has_tts_markup(text):
        if metadata is not None:
            metadata["tone_provider"] = "none"
        return text

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    paragraph_sentences = [split_sentences(paragraph) for paragraph in paragraphs]
    all_sentences = [sentence for sentences in paragraph_sentences for sentence in sentences]
    if not all_sentences:
        return text

    tone_result = classify_sentence_tones(all_sentences, mode, config)
    tones = tone_result["tones"]
    if metadata is not None:
        metadata["tone_provider"] = tone_result.get("provider")
        if tone_result.get("model"):
            metadata["tone_model"] = tone_result.get("model")
        if tone_result.get("base_url"):
            metadata["tone_base_url"] = tone_result.get("base_url")
        metadata["sentences"] = [
            {"text": sentence, "tone": tones[index]} for index, sentence in enumerate(all_sentences)
        ]

    enhanced = []
    offset = 0
    for sentences in paragraph_sentences:
        enhanced.append(enhance_sentences(sentences, mode, tones[offset : offset + len(sentences)]))
        offset += len(sentences)
    return "\n\n".join(enhanced)


def normalize_speed(value):
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return DEFAULT_SPEED
    if not math.isfinite(speed):
        return DEFAULT_SPEED
    return min(2.0, max(0.5, round(speed, 2)))


def normalize_volume(value):
    try:
        volume = float(value)
    except (TypeError, ValueError):
        return DEFAULT_VOLUME
    if not math.isfinite(volume):
        return DEFAULT_VOLUME
    return min(10.0, max(0.1, round(volume, 2)))


def normalize_pitch(value):
    try:
        pitch = int(value)
    except (TypeError, ValueError):
        return DEFAULT_PITCH
    return min(12, max(-12, pitch))


def normalize_config(config):
    normalized = dict(config or {})
    normalized["api_key"] = str(normalized.get("api_key", "") or "").strip()
    normalized["model"] = str(normalized.get("model", DEFAULT_MODEL) or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    normalized["voice_id"] = normalize_voice_id(normalized.get("voice_id", DEFAULT_VOICE_ID))
    normalized["speed"] = normalize_speed(normalized.get("speed", DEFAULT_SPEED))
    normalized["volume"] = normalize_volume(normalized.get("volume", DEFAULT_VOLUME))
    normalized["pitch"] = normalize_pitch(normalized.get("pitch", DEFAULT_PITCH))
    normalized["enhancement_mode"] = normalize_enhancement_mode(
        normalized.get("enhancement_mode", DEFAULT_ENHANCEMENT_MODE)
    )
    normalized["tone_llm_api_key"] = str(normalized.get("tone_llm_api_key", "") or "").strip()
    normalized["tone_llm_model"] = normalize_tone_llm_model(normalized.get("tone_llm_model", DEFAULT_TONE_LLM_MODEL))
    normalized["tone_llm_base_url"] = normalize_tone_llm_base_url(
        normalized.get("tone_llm_base_url", DEFAULT_TONE_LLM_BASE_URL)
    )
    return normalized


def get_clipboard_text():
    if AppKit is not None:
        pasteboard = AppKit.NSPasteboard.generalPasteboard()
        text = pasteboard.stringForType_(AppKit.NSPasteboardTypeString)
        if text:
            return str(text)

    result = subprocess.run(
        ["pbpaste"],
        capture_output=True,
        text=True,
        timeout=3,
    )
    return result.stdout


def build_t2a_payload(text, config):
    return {
        "model": config.get("model") or DEFAULT_MODEL,
        "text": text,
        "stream": False,
        "language_boost": "auto",
        "output_format": "hex",
        "voice_setting": {
            "voice_id": normalize_voice_id(config.get("voice_id", DEFAULT_VOICE_ID)),
            "speed": normalize_speed(config.get("speed", DEFAULT_SPEED)),
            "vol": normalize_volume(config.get("volume", DEFAULT_VOLUME)),
            "pitch": normalize_pitch(config.get("pitch", DEFAULT_PITCH)),
        },
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": "mp3",
            "channel": 1,
        },
    }


def minimax_t2a(text, config):
    api_key = (config.get("api_key") or os.environ.get("MINIMAX_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("还没有配置 MiniMax API Key")

    body = json.dumps(build_t2a_payload(text, config), ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        MINIMAX_T2A_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        details = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"MiniMax 请求失败: HTTP {e.code} {details}") from e

    base_resp = data.get("base_resp") or {}
    status_code = base_resp.get("status_code", 0)
    if status_code not in (0, "0", None):
        status_msg = base_resp.get("status_msg") or "unknown error"
        raise RuntimeError(f"MiniMax 返回错误 {status_code}: {status_msg}")

    audio_hex = (data.get("data") or {}).get("audio")
    if not audio_hex:
        raise RuntimeError(f"MiniMax 没有返回音频数据: {data}")

    return bytes.fromhex(audio_hex), data


def build_cache_id(raw_text, now=None):
    if now is None:
        now = datetime.datetime.now()
    timestamp = now.strftime("%Y%m%d-%H%M%S")
    digest = hashlib.sha256(normalize_text(raw_text).encode("utf-8")).hexdigest()[:10]
    return f"clipboard-{timestamp}-{digest}"


def build_cache_record(cache_id, raw_text, enhanced_text, tts_text, config, source, was_trimmed, enhancement_metadata=None):
    payload = build_t2a_payload(tts_text, config)
    voice_setting = payload["voice_setting"]
    audio_setting = payload["audio_setting"]
    return {
        "cache_id": cache_id,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "app_version": __version__,
        "source": source,
        "was_trimmed": bool(was_trimmed),
        "texts": {
            "original": normalize_text(raw_text),
            "enhanced": normalize_text(enhanced_text),
        },
        "enhancement": {
            "mode": normalize_enhancement_mode(config.get("enhancement_mode", DEFAULT_ENHANCEMENT_MODE)),
            "tone_provider": (enhancement_metadata or {}).get("tone_provider", "rules"),
            "tone_model": (enhancement_metadata or {}).get("tone_model"),
            "tone_base_url": (enhancement_metadata or {}).get("tone_base_url"),
            "sentences": (enhancement_metadata or {}).get("sentences", []),
        },
        "tts": {
            "provider": "minimax",
            "endpoint": MINIMAX_T2A_URL,
            "model": payload["model"],
            "voice_id": voice_setting["voice_id"],
            "speed": voice_setting["speed"],
            "volume": voice_setting["vol"],
            "pitch": voice_setting["pitch"],
            "enhancement_mode": normalize_enhancement_mode(config.get("enhancement_mode", DEFAULT_ENHANCEMENT_MODE)),
            "language_boost": payload["language_boost"],
            "audio_setting": audio_setting,
            "payload": payload,
        },
        "files": {
            "record": os.path.join(RECORD_CACHE_DIR, f"{cache_id}.json"),
            "audio": os.path.join(AUDIO_CACHE_DIR, f"{cache_id}.mp3"),
        },
        "result": None,
    }


def save_cache_record(record):
    path = record["files"]["record"]
    atomic_write_json(path, record)
    return path


def sanitize_minimax_response(response):
    sanitized = {}
    for key, value in (response or {}).items():
        if key == "data" and isinstance(value, dict):
            sanitized[key] = {k: v for k, v in value.items() if k != "audio"}
        else:
            sanitized[key] = value
    return sanitized


def mark_cache_record_failed(record, error):
    record["result"] = {
        "status": "failed",
        "failed_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "error_type": type(error).__name__,
        "error": str(error),
    }
    try:
        save_cache_record(record)
    except OSError as cache_error:
        log_exception("保存失败朗读记录缓存失败", cache_error)
    return record


def save_audio(audio_bytes, cache_id=None):
    ensure_dir(AUDIO_CACHE_DIR)
    if cache_id is None:
        cache_id = build_cache_id("")
    path = os.path.join(AUDIO_CACHE_DIR, f"{cache_id}.mp3")
    with open(path, "wb") as f:
        f.write(audio_bytes)
    return path


def get_running_app_path():
    marker = ".app/Contents/"
    executable = os.path.abspath(sys.argv[0])
    if marker not in executable:
        return None
    return executable.split(marker, 1)[0] + ".app"


def build_launch_agent_plist(app_path):
    return {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": ["/usr/bin/open", "-gj", app_path],
        "RunAtLoad": True,
        "KeepAlive": False,
    }


def install_launch_agent(app_path=None):
    if app_path is None:
        app_path = get_running_app_path()
    if not app_path:
        raise RuntimeError("当前不是打包后的 .app，无法设置开机自启")
    ensure_dir(LAUNCH_AGENT_DIR)
    with open(LAUNCH_AGENT_FILE, "wb") as f:
        plistlib.dump(build_launch_agent_plist(app_path), f)


def uninstall_launch_agent():
    if os.path.exists(LAUNCH_AGENT_FILE):
        os.remove(LAUNCH_AGENT_FILE)


def is_launch_agent_enabled():
    return os.path.exists(LAUNCH_AGENT_FILE)


class ClipboardReader(rumps.App):
    """菜单栏剪贴板朗读应用。"""

    def __init__(self):
        super().__init__("🔊", quit_button=None)
        self.config = self._load_config()
        self.play_process = None
        self.worker = None
        self.service_provider = None
        self.busy = False
        self.last_audio_path = None
        self.last_status = "待命"
        self._build_menu()
        self._register_services_provider()
        self._set_status("待命")

    def _load_config(self):
        config = {
            "api_key": "",
            "model": DEFAULT_MODEL,
            "voice_id": DEFAULT_VOICE_ID,
            "speed": DEFAULT_SPEED,
            "volume": DEFAULT_VOLUME,
            "pitch": DEFAULT_PITCH,
            "enhancement_mode": DEFAULT_ENHANCEMENT_MODE,
            "tone_llm_api_key": "",
            "tone_llm_model": DEFAULT_TONE_LLM_MODEL,
            "tone_llm_base_url": DEFAULT_TONE_LLM_BASE_URL,
        }
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                if isinstance(saved, dict):
                    config.update(saved)
            except (json.JSONDecodeError, OSError) as e:
                log_exception("加载配置失败", e)
        return normalize_config(config)

    def _save_config(self):
        try:
            atomic_write_json(CONFIG_FILE, self.config)
        except OSError as e:
            log_exception("保存配置失败", e)

    def _menu_callback(self, label, callback):
        def _wrapped(sender):
            try:
                return callback(sender)
            except Exception as e:
                log_exception(f"菜单操作失败: {label}", e)
                safe_alert(title="操作失败", message=f"「{label}」执行失败，详情已写入错误日志。")
                return None

        return _wrapped

    def _build_menu(self):
        self.read_item = rumps.MenuItem("朗读剪贴板", callback=self._menu_callback("朗读剪贴板", self.read_clipboard))
        self.stop_item = rumps.MenuItem("停止播放", callback=self._menu_callback("停止播放", self.stop_playback))
        self.status_item = rumps.MenuItem("状态: 待命", callback=None)

        self.settings_menu = rumps.MenuItem("设置")
        self.api_key_item = rumps.MenuItem("设置 MiniMax API Key", callback=self._menu_callback("设置 API Key", self.set_api_key))
        self.voice_menu = rumps.MenuItem("声音 Voice ID")
        self._rebuild_voice_menu()
        self.model_item = rumps.MenuItem("设置模型", callback=self._menu_callback("设置模型", self.set_model))
        self.speed_menu = rumps.MenuItem("语速")
        self._rebuild_speed_menu()
        self.enhancement_menu = rumps.MenuItem("朗读模式")
        self._rebuild_enhancement_menu()
        self.tone_llm_menu = rumps.MenuItem("语气模型")
        self.tone_llm_menu.add(
            rumps.MenuItem("设置 API Key", callback=self._menu_callback("设置语气模型 API Key", self.set_tone_llm_api_key))
        )
        self.tone_llm_menu.add(
            rumps.MenuItem("设置模型", callback=self._menu_callback("设置语气模型", self.set_tone_llm_model))
        )
        self.tone_llm_menu.add(
            rumps.MenuItem("设置接口地址", callback=self._menu_callback("设置语气模型接口", self.set_tone_llm_base_url))
        )
        self.launch_at_login_item = rumps.MenuItem("开机自启", callback=self._menu_callback("开机自启", self.toggle_launch_at_login))
        self._update_launch_at_login_item()

        self.settings_menu.add(self.api_key_item)
        self.settings_menu.add(self.voice_menu)
        self.settings_menu.add(self.model_item)
        self.settings_menu.add(self.speed_menu)
        self.settings_menu.add(self.enhancement_menu)
        self.settings_menu.add(self.tone_llm_menu)
        self.settings_menu.add(None)
        self.settings_menu.add(self.launch_at_login_item)

        self.open_cache_item = rumps.MenuItem("打开缓存目录", callback=self._menu_callback("打开缓存目录", self.open_cache_dir))
        self.open_logs_item = rumps.MenuItem("打开错误日志", callback=self._menu_callback("打开错误日志", self.open_error_logs))

        self.menu = [
            self.read_item,
            self.stop_item,
            None,
            self.status_item,
            None,
            self.settings_menu,
            self.open_cache_item,
            self.open_logs_item,
            None,
            rumps.MenuItem("关于", callback=self._menu_callback("关于", self.show_about)),
            rumps.MenuItem("退出", callback=self._menu_callback("退出", self.quit_app)),
        ]

    def _rebuild_speed_menu(self):
        if getattr(self.speed_menu, "_menu", None) is not None:
            self.speed_menu.clear()
        current = normalize_speed(self.config.get("speed", DEFAULT_SPEED))
        for speed in [0.75, 0.9, 1.0, 1.1, 1.25, 1.5]:
            item = rumps.MenuItem(f"{speed:g}x", callback=self._menu_callback(f"语速 {speed:g}x", self.set_speed))
            item.state = speed == current
            self.speed_menu.add(item)

    def _rebuild_enhancement_menu(self):
        if getattr(self.enhancement_menu, "_menu", None) is not None:
            self.enhancement_menu.clear()
        current = normalize_enhancement_mode(self.config.get("enhancement_mode", DEFAULT_ENHANCEMENT_MODE))
        for mode, label in ENHANCEMENT_MODES.items():
            item = rumps.MenuItem(label, callback=self._menu_callback(f"朗读模式 {label}", self.set_enhancement_mode))
            item.state = mode == current
            item._enhancement_mode = mode
            self.enhancement_menu.add(item)

    def _rebuild_voice_menu(self):
        if getattr(self.voice_menu, "_menu", None) is not None:
            self.voice_menu.clear()
        current = normalize_voice_id(self.config.get("voice_id", DEFAULT_VOICE_ID))
        current_is_preset = False
        for voice_id, label in VOICE_PRESETS:
            title = f"{label} · {voice_id}"
            item = rumps.MenuItem(title, callback=self._menu_callback(f"声音 {label}", self.set_voice_preset))
            item.state = voice_id == current
            item._voice_id = voice_id
            current_is_preset = current_is_preset or item.state
            self.voice_menu.add(item)
        if not current_is_preset:
            self.voice_menu.add(None)
            current_item = rumps.MenuItem(f"当前自定义 · {current}", callback=None)
            current_item.state = True
            self.voice_menu.add(current_item)
        self.voice_menu.add(None)
        self.voice_menu.add(rumps.MenuItem("自定义 Voice ID…", callback=self._menu_callback("自定义声音", self.set_custom_voice_id)))

    def _set_status(self, text):
        if not is_main_thread():
            run_on_main_thread(self._set_status, text)
            return
        self.last_status = text
        self.status_item.title = f"状态: {text}"
        self.title = "🔊…" if self.busy else "🔊"

    def _has_api_key(self):
        return bool((self.config.get("api_key") or os.environ.get("MINIMAX_API_KEY") or "").strip())

    def read_clipboard(self, _):
        self.speak_text(get_clipboard_text(), source="剪贴板")

    def speak_text(self, raw_text, source="文本"):
        if self.busy:
            safe_notification(title=__app_name__, subtitle="正在生成", message="上一段朗读还没处理完。")
            return
        if not self._has_api_key():
            self.set_api_key(None)
            if not self._has_api_key():
                return

        raw_text = normalize_text(raw_text)
        if not raw_text:
            safe_alert(title="没有可朗读文字", message="请先复制或选中一段文字。")
            return

        self.busy = True
        self.read_item.set_callback(None)
        self._set_status(f"分析语气 · {source}")
        self.worker = threading.Thread(
            target=self._prepare_generate_and_play,
            args=(raw_text, source),
            name="MiniMaxTTSWorker",
            daemon=True,
        )
        self.worker.start()

    def _prepare_generate_and_play(self, raw_text, source):
        try:
            mode = normalize_enhancement_mode(self.config.get("enhancement_mode", DEFAULT_ENHANCEMENT_MODE))
            enhancement_metadata = {}
            enhanced_text = enhance_text_for_tts(raw_text, mode, self.config, enhancement_metadata)
            text, was_trimmed = trim_text_for_tts(enhanced_text)
            cache_id = build_cache_id(raw_text)
            cache_record = build_cache_record(
                cache_id,
                raw_text,
                enhanced_text,
                text,
                self.config,
                source,
                was_trimmed,
                enhancement_metadata,
            )
            try:
                save_cache_record(cache_record)
            except OSError as e:
                log_exception("保存朗读记录缓存失败", e)
            self._set_status(f"生成中 · {source}")
            self._generate_and_play(text, was_trimmed, cache_id, cache_record)
        except Exception as e:
            log_exception("准备朗读失败", e)
            self._set_status("失败")
            safe_alert(title="朗读失败", message=f"{e}\n\n详情已写入错误日志。")
            run_on_main_thread(self._finish_generation)

    def _register_services_provider(self):
        if _TextServiceProvider is None or AppKit is None:
            return
        try:
            self.service_provider = _TextServiceProvider.alloc().init()
            self.service_provider.reader_app = self
            AppKit.NSApplication.sharedApplication().setServicesProvider_(self.service_provider)
            if hasattr(AppKit, "NSUpdateDynamicServices"):
                AppKit.NSUpdateDynamicServices()
        except Exception as e:
            log_exception("注册右键服务失败", e)

    def _generate_and_play(self, text, was_trimmed, cache_id, cache_record):
        try:
            if was_trimmed:
                safe_notification(title=__app_name__, subtitle="文本过长", message="已截取前 10000 个字符朗读。")
            audio_bytes, response = minimax_t2a(text, self.config)
            audio_path = save_audio(audio_bytes, cache_id)
            cache_record["files"]["audio"] = audio_path
            cache_record["result"] = {
                "status": "success",
                "audio_bytes": len(audio_bytes),
                "response": sanitize_minimax_response(response),
            }
            save_cache_record(cache_record)
            self.last_audio_path = audio_path
            self._start_playback(audio_path)
            usage = (response.get("extra_info") or {}).get("usage_characters", len(text))
            self._set_status(f"播放中 · {usage} 字")
            safe_notification(title=__app_name__, subtitle="开始播放", message="MiniMax 语音已生成。")
        except Exception as e:
            log_exception("朗读剪贴板失败", e)
            mark_cache_record_failed(cache_record, e)
            self._set_status("失败")
            safe_alert(title="朗读失败", message=f"{e}\n\n详情已写入错误日志。")
        finally:
            run_on_main_thread(self._finish_generation)

    def _finish_generation(self):
        self.busy = False
        self.read_item.set_callback(self._menu_callback("朗读剪贴板", self.read_clipboard))
        self.title = "🔊"

    def _start_playback(self, audio_path):
        self._stop_playback_process()
        self.play_process = subprocess.Popen(["afplay", audio_path])

    def _stop_playback_process(self):
        if self.play_process is not None and self.play_process.poll() is None:
            self.play_process.terminate()
            try:
                self.play_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.play_process.kill()
        self.play_process = None

    def stop_playback(self, _):
        self._stop_playback_process()
        self._set_status("已停止")

    def set_api_key(self, _):
        default = self.config.get("api_key", "")
        win = rumps.Window(
            message="填入 MiniMax API Key。也可以不保存，改用环境变量 MINIMAX_API_KEY。",
            title="MiniMax API Key",
            default_text=default,
            ok="保存",
            cancel="取消",
            dimensions=(420, 24),
        )
        response = win.run()
        if response.clicked:
            self.config["api_key"] = response.text.strip()
            self._save_config()
            self._set_status("API Key 已保存")

    def set_voice_preset(self, sender):
        voice_id = normalize_voice_id(getattr(sender, "_voice_id", None))
        self.config["voice_id"] = voice_id
        self._save_config()
        self._rebuild_voice_menu()
        label = voice_preset_label(voice_id) or voice_id
        self._set_status(f"声音: {label}")

    def set_custom_voice_id(self, _):
        win = rumps.Window(
            message="填入 MiniMax voice_id。",
            title="声音 Voice ID",
            default_text=normalize_voice_id(self.config.get("voice_id", DEFAULT_VOICE_ID)),
            ok="保存",
            cancel="取消",
            dimensions=(360, 24),
        )
        response = win.run()
        if response.clicked and response.text.strip():
            self.config["voice_id"] = normalize_voice_id(response.text)
            self._save_config()
            self._rebuild_voice_menu()
            self._set_status(f"声音: {self.config['voice_id']}")

    def set_model(self, _):
        win = rumps.Window(
            message="常用: speech-2.8-turbo / speech-2.8-hd / speech-2.6-turbo",
            title="MiniMax 模型",
            default_text=self.config.get("model", DEFAULT_MODEL),
            ok="保存",
            cancel="取消",
            dimensions=(360, 24),
        )
        response = win.run()
        if response.clicked and response.text.strip():
            self.config["model"] = response.text.strip()
            self._save_config()
            self._set_status(f"模型: {self.config['model']}")

    def set_tone_llm_api_key(self, _):
        win = rumps.Window(
            message="用于自动判断每句话语气。也可以不保存，改用环境变量 TONE_LLM_API_KEY 或 OPENAI_API_KEY。",
            title="语气模型 API Key",
            default_text=self.config.get("tone_llm_api_key", ""),
            ok="保存",
            cancel="取消",
            dimensions=(460, 24),
        )
        response = win.run()
        if response.clicked:
            self.config["tone_llm_api_key"] = response.text.strip()
            self._save_config()
            self._set_status("语气模型 API Key 已保存")

    def set_tone_llm_model(self, _):
        win = rumps.Window(
            message="OpenAI-compatible Chat Completions 模型名。",
            title="语气模型",
            default_text=normalize_tone_llm_model(self.config.get("tone_llm_model")),
            ok="保存",
            cancel="取消",
            dimensions=(420, 24),
        )
        response = win.run()
        if response.clicked and response.text.strip():
            self.config["tone_llm_model"] = normalize_tone_llm_model(response.text)
            self._save_config()
            self._set_status(f"语气模型: {self.config['tone_llm_model']}")

    def set_tone_llm_base_url(self, _):
        win = rumps.Window(
            message="OpenAI-compatible /chat/completions 接口地址。",
            title="语气模型接口地址",
            default_text=normalize_tone_llm_base_url(self.config.get("tone_llm_base_url")),
            ok="保存",
            cancel="取消",
            dimensions=(520, 24),
        )
        response = win.run()
        if response.clicked and response.text.strip():
            self.config["tone_llm_base_url"] = normalize_tone_llm_base_url(response.text)
            self._save_config()
            self._set_status("语气模型接口已保存")

    def set_speed(self, sender):
        text = sender.title.replace("x", "")
        self.config["speed"] = normalize_speed(text)
        self._save_config()
        self._rebuild_speed_menu()
        self._set_status(f"语速: {self.config['speed']:g}x")

    def set_enhancement_mode(self, sender):
        mode = normalize_enhancement_mode(getattr(sender, "_enhancement_mode", None))
        self.config["enhancement_mode"] = mode
        self._save_config()
        self._rebuild_enhancement_menu()
        self._set_status(f"模式: {ENHANCEMENT_MODES[mode]}")

    def toggle_launch_at_login(self, _):
        if is_launch_agent_enabled():
            uninstall_launch_agent()
        else:
            install_launch_agent()
        self._update_launch_at_login_item()

    def _update_launch_at_login_item(self):
        self.launch_at_login_item.state = is_launch_agent_enabled()

    def open_cache_dir(self, _):
        ensure_dir(RECORD_CACHE_DIR)
        ensure_dir(AUDIO_CACHE_DIR)
        subprocess.run(["open", APP_SUPPORT_DIR], check=False)

    def open_error_logs(self, _):
        ensure_dir(ERROR_LOG_DIR)
        subprocess.run(["open", ERROR_LOG_DIR], check=False)

    def show_about(self, _):
        source = "环境变量 MINIMAX_API_KEY" if os.environ.get("MINIMAX_API_KEY") else "本地配置"
        safe_alert(
            title=__app_name__,
            message=(
                f"版本: {__version__}\n"
                "技术路线: 剪贴板 -> MiniMax T2A -> afplay\n"
                f"API Key 来源: {source}\n"
                f"模型: {self.config.get('model', DEFAULT_MODEL)}\n"
                f"声音: {self.config.get('voice_id', DEFAULT_VOICE_ID)}\n"
                f"朗读模式: {ENHANCEMENT_MODES[normalize_enhancement_mode(self.config.get('enhancement_mode'))]}\n"
                f"语气模型: {normalize_tone_llm_model(self.config.get('tone_llm_model'))}"
            ),
        )

    def quit_app(self, _):
        self._stop_playback_process()
        rumps.quit_application()


if __name__ == "__main__":
    install_exception_logging()
    ClipboardReader().run()
