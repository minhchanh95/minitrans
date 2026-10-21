"""Nhận diện hệ điều hành & thư viện có sẵn để chọn cấu hình phù hợp cho Windows / macOS."""
import importlib.util
import platform
import sys

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_APPLE_SILICON = IS_MAC and platform.machine() == "arm64"


def has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def stt_choices() -> list[str]:
    items = ["auto"]
    if IS_APPLE_SILICON:
        items.append("mlx")
    return items + ["local", "gemini", "openai"]


def resolve_stt_engine(cfg: dict) -> str:
    """'auto' -> chọn engine nhanh nhất đang có trên máy."""
    engine = cfg.get("stt_engine", "auto")
    if engine == "mlx" and not IS_APPLE_SILICON:
        engine = "auto"  # config mang từ Mac sang Windows
    if engine != "auto":
        return engine
    if IS_APPLE_SILICON and has_module("mlx_whisper"):
        return "mlx"
    if has_module("faster_whisper"):
        return "local"
    if cfg.get("gemini_api_key"):
        return "gemini"
    return "openai"


def list_input_devices() -> list[str]:
    try:
        import sounddevice as sd
        return [d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0]
    except Exception:
        return []


def find_loopback_device_mac() -> str | None:
    """macOS không cho thu âm loa trực tiếp -> tìm thiết bị ảo BlackHole / Loopback / Soundflower."""
    for name in list_input_devices():
        low = name.lower()
        if any(k in low for k in ("blackhole", "loopback", "soundflower")):
            return name
    return None
