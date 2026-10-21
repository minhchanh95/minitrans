"""Audio -> câu -> STT -> dịch. Mỗi câu xử lý song song, UI sắp xếp theo thứ tự id."""
import itertools
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Signal

from .audio import AudioCapture, Segmenter
from .stt import is_hallucination, make_stt
from .translator import Translator


class Bridge(QObject):
    """Cầu nối thread nền -> UI thread (Qt signal an toàn giữa các thread)."""
    original = Signal(int, str)
    translated = Signal(int, str)
    status = Signal(str)
    hotkey = Signal(str)
    popup = Signal(str, str)  # (title, text)
    level = Signal(str)       # thanh mức âm, tách riêng để không đè thông báo lỗi


class Pipeline:
    def __init__(self, cfg: dict, bridge: Bridge):
        self.cfg = cfg
        self.bridge = bridge
        self.running = False
        self.stop_event = threading.Event()
        self.ids = itertools.count(1)
        self.recent: deque[str] = deque(maxlen=3)
        self.pool: ThreadPoolExecutor | None = None
        self.capture: AudioCapture | None = None

    def start(self):
        if self.running:
            return
        self.stt = make_stt(self.cfg)          # lỗi key sẽ raise ngay tại đây
        self.translator = Translator(self.cfg)
        self.stop_event = threading.Event()
        # Gemini: xử lý tuần tự 1 câu/lần để không bắn request dồn dập
        workers = 1 if hasattr(self.stt, "transcribe_and_translate") else 4
        self.pool = ThreadPoolExecutor(max_workers=workers)
        self.combined = (hasattr(self.stt, "transcribe_and_translate")
                         and self.translator.engine == "gemini")
        self.src_name = "âm thanh hệ thống" if self.cfg["audio_source"] == "system" else "micro"
        self.zero_blocks = 0
        self.heard = False
        seg = Segmenter(self.cfg["vad"], self._on_segment, self._on_level)
        self.capture = AudioCapture(self.cfg["audio_source"], seg, self.stop_event, self.bridge.status.emit,
                                    self.cfg.get("input_device", ""))
        self.capture.start()
        self.running = True
        src = "âm thanh hệ thống" if self.cfg["audio_source"] == "system" else "micro"
        self.bridge.status.emit(f"● Đang nghe {src}…")

    def stop(self):
        if not self.running:
            return
        self.stop_event.set()
        self.running = False
        if self.pool:
            self.pool.shutdown(wait=False)
        self.bridge.status.emit("■ Đã dừng")

    def _on_level(self, level: float, thr: float, voiced: bool):
        if self.stop_event.is_set():
            return
        if level > 0.0:
            self.heard = True
        self.zero_blocks = self.zero_blocks + 1 if level == 0.0 else 0
        if self.zero_blocks >= 6 and not getattr(self, "heard", False):  # ~3s toàn số 0 -> gần như chắc chắn chưa cấp quyền mic
            self.bridge.level.emit(
                "⚠ Mic không thu được tín hiệu (toàn 0). Vào System Settings → Privacy & Security → "
                "Microphone, bật cho Terminal/VS Code rồi mở lại app.")
            return
        bars = min(int(level / max(thr, 1e-6) * 5), 10)
        meter = "█" * bars + "·" * max(0, 10 - bars)
        state = "🗣" if voiced else ""
        self.bridge.level.emit(f"{meter} {level:.3f}/{thr:.3f} {state}")

    def _on_segment(self, audio):
        if self.pool is None or self.stop_event.is_set():
            return
        sid = next(self.ids)
        try:
            self.pool.submit(self._process, sid, audio)
        except RuntimeError:  # pool đã shutdown
            pass

    def _process(self, sid: int, audio):
        import time
        t0 = time.time()
        dur = len(audio) / 16000
        self.bridge.status.emit(f"⏳ Đang nhận dạng câu #{sid} ({dur:.1f}s)…")
        context = list(self.recent)
        pre_translated = None
        try:
            if self.combined:
                text, pre_translated = self.stt.transcribe_and_translate(audio, context)
            else:
                text = self.stt.transcribe(audio)
        except Exception as e:
            print(f"[LỖI STT #{sid}] {e}", flush=True)
            short = str(e).split("{")[0].strip()[:200]
            self.bridge.status.emit(f"⚠ Lỗi STT: {short}")
            return
        t1 = time.time()
        print(f"[STT #{sid}] {t1 - t0:.1f}s {text!r}", flush=True)
        if is_hallucination(text, self.cfg):
            self.bridge.status.emit(f"Câu #{sid}: không nhận ra lời nói (STT trả về rỗng)")
            return
        self.bridge.original.emit(sid, text)
        self.recent.append(text)
        try:
            out = pre_translated or self.translator.translate(text, context)
        except Exception as e:
            out = f"[Lỗi dịch: {str(e).split('{')[0].strip()[:200]}]"
        t2 = time.time()
        print(f"[DỊCH #{sid}] {t2 - t1:.1f}s {out!r}", flush=True)
        self.bridge.status.emit(
            f"Câu #{sid}: dài {dur:.1f}s · nhận dạng {t1 - t0:.1f}s · dịch {t2 - t1:.1f}s")
        self.bridge.translated.emit(sid, out)
