"""Giới hạn số lần gọi API/phút và xử lý lỗi 429 (hết quota)."""
import re
import threading
import time


class QuotaError(RuntimeError):
    pass


class RateLimiter:
    def __init__(self, rpm: int):
        self.interval = 60.0 / max(int(rpm or 1), 1)
        self.lock = threading.Lock()
        self.next_at = 0.0
        self.blocked_until = 0.0

    def wait(self):
        with self.lock:
            now = time.time()
            if now < self.blocked_until:
                raise QuotaError(f"Đang tạm dừng do hết quota, thử lại sau {int(self.blocked_until - now)}s")
            at = max(now, self.next_at)
            self.next_at = at + self.interval
        time.sleep(max(0.0, at - time.time()))

    def on_error(self, e: Exception):
        msg = str(e)
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
            m = re.search(r"retry in ([0-9.]+)s", msg) or re.search(r"retryDelay[^0-9]*([0-9.]+)s", msg)
            delay = float(m.group(1)) if m else 60.0
            with self.lock:
                self.blocked_until = time.time() + delay
            daily = "PerDay" in msg or "per day" in msg.lower()
            hint = ("Hết quota THEO NGÀY của Gemini free → đổi STT engine = local, "
                    "hoặc bật billing / dùng key khác." if daily else
                    f"Vượt giới hạn/phút của Gemini → tự thử lại sau {int(delay)}s.")
            raise QuotaError(f"429 – {hint}") from None
        raise e


_limiters: dict = {}


def limiter(name: str, rpm: int) -> RateLimiter:
    if name not in _limiters or abs(_limiters[name].interval - 60.0 / max(rpm, 1)) > 1e-6:
        _limiters[name] = RateLimiter(rpm)
    return _limiters[name]
