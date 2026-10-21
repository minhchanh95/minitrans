import sys

from PySide6.QtWidgets import QApplication

from .config import CONFIG_PATH, load_config, save_config
from .overlay import Overlay


def main():
    # Console Windows mặc định không phải UTF-8 -> in tiếng Nhật/Việt sẽ lỗi
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if sys.platform == "win32":
        try:  # để Windows hiện đúng icon/tên app trên taskbar
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MiniTrans")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("MiniTrans")
    cfg = load_config()
    if not CONFIG_PATH.exists():
        save_config(cfg)
    win = Overlay(cfg)
    win.show()
    from .platform_utils import resolve_stt_engine
    if resolve_stt_engine(cfg) in ("openai", "gemini") and not (cfg.get("openai_api_key") or cfg.get("gemini_api_key")):
        win.set_status("Chưa có STT: chạy setup để cài faster-whisper, hoặc bấm ⚙ nhập API key")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
