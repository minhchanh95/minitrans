"""Thu âm hệ thống (WASAPI loopback - Windows) hoặc micro, chuyển về 16kHz mono
và cắt thành từng câu bằng VAD đơn giản dựa trên năng lượng."""
import queue
import sys
import threading

import numpy as np

TARGET_SR = 16000
BLOCK_S = 0.1  # mỗi block 100ms


def to_mono_16k(data: np.ndarray, sr: int, channels: int) -> np.ndarray:
    if channels > 1:
        usable = len(data) - (len(data) % channels)
        data = data[:usable].reshape(-1, channels).mean(axis=1)
    if sr != TARGET_SR and len(data):
        n_out = int(len(data) * TARGET_SR / sr)
        if n_out <= 0:
            return np.zeros(0, dtype=np.float32)
        x_old = np.linspace(0.0, 1.0, num=len(data), endpoint=False)
        x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
        data = np.interp(x_new, x_old, data)
    return data.astype(np.float32)


class Segmenter:
    """Gom các block âm thanh thành 1 đoạn (câu) dựa trên năng lượng + khoảng lặng."""

    def __init__(self, vad_cfg: dict, on_segment, on_level=None):
        self.thr = float(vad_cfg.get("energy_threshold", 0.008))
        self.silence_need = int(TARGET_SR * vad_cfg.get("silence_ms", 600) / 1000)
        self.max_len = int(TARGET_SR * vad_cfg.get("max_segment_s", 8.0))
        self.min_len = int(TARGET_SR * vad_cfg.get("min_segment_s", 0.6))
        self.preroll_len = int(TARGET_SR * 0.3)
        self.on_segment = on_segment
        self.on_level = on_level
        # Ngưỡng thích nghi: theo dõi mức nền (nhạc/ồn) trong ~3s gần nhất
        self.hist: list[float] = []
        self._lvl_max = 0.0
        self._lvl_count = 0
        self._reset()
        self.preroll: list[np.ndarray] = []

    def _reset(self):
        self.buf: list[np.ndarray] = []
        self.buf_len = 0
        self.voiced = False
        self.silence = 0

    def feed(self, chunk: np.ndarray):
        if not len(chunk):
            return
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        self.hist.append(rms)
        if len(self.hist) > 30:
            self.hist.pop(0)
        floor = float(np.percentile(self.hist, 20)) if len(self.hist) >= 10 else 0.0
        thr = max(self.thr, floor * 1.8)
        # Báo mức âm lượng mỗi ~0.5s để người dùng biết mic có thu được không
        self._lvl_max = max(self._lvl_max, rms)
        self._lvl_count += 1
        if self.on_level and self._lvl_count >= 5:
            self.on_level(self._lvl_max, thr, self.voiced)
            self._lvl_max = 0.0
            self._lvl_count = 0
        if rms > thr:
            if not self.voiced:  # bắt đầu câu: thêm 300ms trước đó cho khỏi mất âm đầu
                self.buf.extend(self.preroll)
                self.buf_len += sum(len(c) for c in self.preroll)
                self.preroll = []
            self.voiced = True
            self.silence = 0
            self.buf.append(chunk)
            self.buf_len += len(chunk)
        elif self.voiced:
            self.buf.append(chunk)
            self.buf_len += len(chunk)
            self.silence += len(chunk)
        else:
            self.preroll.append(chunk)
            while sum(len(c) for c in self.preroll) > self.preroll_len:
                self.preroll.pop(0)

        if self.voiced and (self.silence >= self.silence_need or self.buf_len >= self.max_len):
            self.flush()

    def flush(self):
        if self.buf and self.buf_len >= self.min_len:
            self.on_segment(np.concatenate(self.buf))
        self._reset()


class AudioCapture(threading.Thread):
    def __init__(self, source: str, segmenter: Segmenter, stop_event: threading.Event, on_error,
                 input_device: str = ""):
        super().__init__(daemon=True)
        self.source = source
        self.input_device = input_device
        self.seg = segmenter
        self.stop_event = stop_event
        self.on_error = on_error
        self.raw_q: queue.Queue = queue.Queue()

    def run(self):
        try:
            if self.source == "system":
                self._run_system()
            else:
                self._run_mic()
        except Exception as e:
            self.on_error(f"Lỗi thu âm: {e}")
        finally:
            self.seg.flush()

    def _pump(self, sr: int, channels: int):
        """Lấy dữ liệu từ queue. Khi loa im lặng hoàn toàn, WASAPI loopback không gửi
        packet nào -> tự bơm block im lặng để VAD vẫn cắt được câu."""
        silent = np.zeros(int(TARGET_SR * BLOCK_S), dtype=np.float32)
        while not self.stop_event.is_set():
            try:
                raw = self.raw_q.get(timeout=BLOCK_S * 1.5)
            except queue.Empty:
                self.seg.feed(silent)
                continue
            arr = np.frombuffer(raw, dtype=np.float32)
            self.seg.feed(to_mono_16k(arr, sr, channels))

    def _run_system(self):
        if sys.platform == "darwin":
            from .platform_utils import find_loopback_device_mac
            dev = find_loopback_device_mac()
            if not dev:
                raise RuntimeError(
                    "macOS cần thiết bị ảo để thu âm loa: cài BlackHole 2ch "
                    "(brew install blackhole-2ch) rồi tạo Multi-Output Device – xem README. "
                    "Hoặc chuyển sang 🎙 Mic.")
            return self._run_mic(dev)
        if sys.platform != "win32":
            raise RuntimeError("Thu âm hệ thống chỉ hỗ trợ Windows/macOS. Hãy dùng 🎙 Mic.")
        import pyaudiowpatch as pyaudio

        p = pyaudio.PyAudio()
        stream = None
        try:
            dev = p.get_default_wasapi_loopback()
            sr = int(dev["defaultSampleRate"])
            ch = int(dev["maxInputChannels"])

            def cb(in_data, frame_count, time_info, status):
                self.raw_q.put(in_data)
                return (None, pyaudio.paContinue)

            stream = p.open(
                format=pyaudio.paFloat32, channels=ch, rate=sr, input=True,
                input_device_index=dev["index"], frames_per_buffer=int(sr * BLOCK_S),
                stream_callback=cb,
            )
            stream.start_stream()
            self._pump(sr, ch)
        finally:
            if stream is not None:
                stream.stop_stream()
                stream.close()
            p.terminate()

    def _run_mic(self, device: str | None = None):
        import sounddevice as sd

        device = device or self.input_device or None
        if device:
            matches = [i for i, d in enumerate(sd.query_devices())
                       if d["max_input_channels"] > 0 and device.lower() in d["name"].lower()]
            if not matches:
                raise RuntimeError(f"Không tìm thấy thiết bị input '{device}'")
            device = matches[0]
        info = sd.query_devices(device, "input")
        # Mở theo sample rate gốc của thiết bị (Windows/BlackHole thường không nhận 16kHz) rồi tự resample
        sr = int(info["default_samplerate"]) or TARGET_SR
        ch = 2 if info["max_input_channels"] >= 2 else 1

        def cb(indata, frames, time_info, status):
            self.raw_q.put(indata.copy().tobytes())

        with sd.InputStream(device=device, samplerate=sr, channels=ch, dtype="float32",
                            blocksize=int(sr * BLOCK_S), callback=cb):
            self.on_error(f"● Đang nghe: {info['name']}")
            self._pump(sr, ch)
