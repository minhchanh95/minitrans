"""Load / save cấu hình. File lưu tại ~/.minitrans/config.json"""
import copy
import sys
import json
import os
from pathlib import Path

APP_DIR = Path.home() / ".minitrans"
CONFIG_PATH = APP_DIR / "config.json"
HISTORY_DIR = APP_DIR / "history"

DEFAULTS = {
    "source_lang": "ja",            # "auto" để tự nhận diện
    "target_lang": "vi",
    # Windows: thu loa trực tiếp (WASAPI). macOS: mặc định Mic (thu loa cần BlackHole)
    "audio_source": "system" if sys.platform == "win32" else "mic",
    "input_device": "",             # tên (một phần) thiết bị input, để trống = mặc định
    "stt_engine": "auto",           # auto = mlx (Mac M) > local > gemini > openai         # "gemini" | "openai" | "local" (faster-whisper) | "mlx" (Apple Silicon, nhanh nhất trên Mac)
    "mlx_model": "mlx-community/whisper-large-v3-turbo",
    "stt_model": "gpt-4o-mini-transcribe",
    "local_whisper_model": "small",
    "whisper_device": "cpu",        # "cuda" nếu có GPU NVIDIA (Windows)
    "translate_engine": "free",   # "free" | "openai" | "gemini" | "google" | "deepl"
    "auto_fallback": True,          # engine chính lỗi -> tự dùng "free"
    "openai_model": "gpt-4o-mini",
    "gemini_model": "gemini-3.8-flash",
    "openai_api_key": "",
    "gemini_api_key": "",
    "gemini_rpm": 8,                # số request/phút tối đa gửi tới Gemini (free tier nên để thấp)
    "google_api_key": "",
    "deepl_api_key": "",
    "deepl_free": True,
    "context_preset": "IT",
    "stt_glossary_hint": False,     # gửi glossary cho STT làm gợi ý (dễ bị lặp lại khi có nhạc nền)
    "glossary": (
        "API管理基盤=nền tảng API Management\n"
        "本番環境=môi trường Production\n"
        "検証環境=môi trường Staging\n"
        "疎通確認=kiểm tra kết nối\n"
        "切り戻し=rollback"
    ),
    "font_size": 15,
    "bg_alpha": 200,                # 0-255, độ đậm nền overlay
    "show_original": True,
    "hotkeys": {
        "toggle": "<ctrl>+<alt>+s",         # Bắt đầu / dừng nghe
        "quick": "<ctrl>+<alt>+q",          # Dịch nhanh nội dung clipboard
        "ocr": "<ctrl>+<alt>+o",            # Chụp vùng màn hình -> dịch
        "click_through": "<ctrl>+<alt>+x",  # Bật/tắt click xuyên overlay
    },
    "vad": {
        "energy_threshold": 0.008,  # tăng nếu bị bắt cả tiếng ồn
        "silence_ms": 450,          # im lặng bao lâu thì cắt câu
        "max_segment_s": 5.0,       # câu dài quá thì cắt cưỡng bức
        "min_segment_s": 0.5,
    },
}

ENV_KEYS = {
    "openai_api_key": "OPENAI_API_KEY",
    "gemini_api_key": "GEMINI_API_KEY",
    "google_api_key": "GOOGLE_TRANSLATE_API_KEY",
    "deepl_api_key": "DEEPL_API_KEY",
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg = _merge(cfg, json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception as e:  # file hỏng -> dùng mặc định
            print(f"[config] Không đọc được config: {e}")
    # Model Gemini cũ đã ngừng cấp cho user mới -> tự nâng cấp
    if cfg.get("gemini_model") in ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"):
        cfg["gemini_model"] = DEFAULTS["gemini_model"]
    # Nâng cấp cấu hình VAD cũ (cắt câu chậm) lên giá trị nhanh hơn
    vad = cfg["vad"]
    if vad.get("silence_ms") in (600, 700):
        vad["silence_ms"] = DEFAULTS["vad"]["silence_ms"]
    if vad.get("max_segment_s") in (6.0, 8.0, 10.0):
        vad["max_segment_s"] = DEFAULTS["vad"]["max_segment_s"]
    # Biến môi trường được ưu tiên nếu config để trống
    for key, env in ENV_KEYS.items():
        if not cfg.get(key) and os.environ.get(env):
            cfg[key] = os.environ[env]
    return cfg


def save_config(cfg: dict) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_glossary(text: str) -> list[tuple[str, str]]:
    pairs = []
    for line in (text or "").splitlines():
        if "=" in line:
            src, dst = line.split("=", 1)
            if src.strip() and dst.strip():
                pairs.append((src.strip(), dst.strip()))
    return pairs
