"""Cửa sổ overlay chính: trong suốt, luôn nổi trên cùng, có thể click xuyên."""
import html
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QPushButton, QSizeGrip, QSlider,
    QTextBrowser,
    QVBoxLayout, QWidget,
)

from .config import HISTORY_DIR, save_config
from .hotkeys import HotkeyManager
from .pipeline import Bridge, Pipeline
from .translator import Translator
from .widgets import RegionSelector, SettingsDialog, TranslatePopup

import sys

FONT = ('"Segoe UI", "Yu Gothic UI", "Meiryo UI", "Segoe UI Emoji"' if sys.platform == "win32"
        else '"-apple-system", "Hiragino Sans", "Apple Color Emoji"')

CSS = """
QWidget { font-family: %s; }
QLabel { color: #e5e9f0; }
QLabel#handle { font-weight: bold; padding: 0 6px; }
QLabel#status { color: #a3be8c; font-size: 12px; }
QPushButton { background: rgba(255,255,255,30); color: #eceff4; border: none;
    border-radius: 6px; padding: 4px 9px; font-size: 13px; }
QPushButton:hover { background: rgba(255,255,255,60); }
QPushButton#start[running="true"] { background: #bf616a; }
QPushButton#start[running="false"] { background: #4c6ef5; }
QTextBrowser { background: transparent; border: none; }
QSlider::groove:horizontal { height: 4px; background: rgba(255,255,255,60); }
QSlider::handle:horizontal { width: 12px; margin: -5px 0; border-radius: 6px; background: #eceff4; }
""" % FONT


class Overlay(QWidget):
    def __init__(self, cfg: dict):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.cfg = cfg
        self.setWindowTitle("MiniTrans")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet(CSS)
        self.resize(720, 260)
        self.click_through = False
        self.entries: dict[int, list[str]] = {}
        self.session_start = None
        self.times: dict[int, datetime] = {}  # thời điểm câu xuất hiện (cho SRT / timestamp)

        self.bridge = Bridge()
        self.pipeline = Pipeline(cfg, self.bridge)
        self.bridge.original.connect(self.on_original)
        self.bridge.translated.connect(self.on_translated)
        self.bridge.status.connect(self.set_status)
        self.bridge.level.connect(lambda t: self.meter.setText(t))
        self.bridge.hotkey.connect(self.on_hotkey)
        self.bridge.popup.connect(lambda _t, text: self.popup.set_result(text))

        self.popup = TranslatePopup()
        self.popup.request_translate.connect(self.quick_translate)
        self.selector = RegionSelector()
        self.selector.selected.connect(self.on_region)

        self._build_ui()
        self.hotkeys = HotkeyManager(cfg["hotkeys"], self.bridge.hotkey.emit)
        self.hotkeys.start()
        self._place_bottom_center()

    # ---------------- UI ----------------
    def _build_ui(self):
        self.handle = QLabel("⠿ MiniTrans", objectName="handle")
        self.handle.setCursor(Qt.SizeAllCursor)
        self.handle.installEventFilter(self)

        self.btn_start = QPushButton("▶ Start", objectName="start")
        self.btn_start.setProperty("running", False)
        self.btn_start.clicked.connect(self.toggle)
        self.btn_src = QPushButton()
        self.btn_src.clicked.connect(self.switch_source)
        self.lbl_lang = QLabel()
        btn_quick = QPushButton("文A")
        btn_quick.setToolTip("Dịch nhanh clipboard")
        btn_quick.clicked.connect(lambda: self.on_hotkey("quick"))
        btn_ocr = QPushButton("OCR")
        btn_ocr.setToolTip("Chụp vùng màn hình và dịch")
        btn_ocr.clicked.connect(lambda: self.on_hotkey("ocr"))
        btn_orig = QPushButton("原")
        btn_orig.setToolTip("Ẩn/hiện câu gốc")
        btn_orig.clicked.connect(self.toggle_original)
        btn_dl = QPushButton("⬇")
        btn_dl.setToolTip("Tải câu gốc về thư mục Downloads")
        btn_dl.clicked.connect(self.download_original)
        btn_clear = QPushButton("🗑")
        btn_clear.setToolTip("Xóa màn hình")
        btn_clear.clicked.connect(self.clear)
        btn_set = QPushButton("⚙")
        btn_set.clicked.connect(self.open_settings)
        btn_close = QPushButton("✕")
        btn_close.clicked.connect(self.quit_app)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        for w in (self.handle, self.btn_start, self.btn_src, self.lbl_lang):
            bar.addWidget(w)
        bar.addStretch()
        for w in (btn_quick, btn_ocr, btn_orig, btn_dl, btn_clear, btn_set, btn_close):
            bar.addWidget(w)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(False)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.status = QLabel("Sẵn sàng", objectName="status")
        self.status.setWordWrap(True)
        self.meter = QLabel("", objectName="status")
        self.alpha = QSlider(Qt.Horizontal)
        self.alpha.setRange(40, 255)
        self.alpha.setValue(self.cfg["bg_alpha"])
        self.alpha.setFixedWidth(110)
        self.alpha.setToolTip("Độ đậm nền")
        self.alpha.valueChanged.connect(self._set_alpha)
        bottom = QHBoxLayout()
        bottom.addWidget(self.status, 1)
        bottom.addWidget(self.meter)
        bottom.addWidget(QLabel("◐"))
        bottom.addWidget(self.alpha)
        bottom.addWidget(QSizeGrip(self), 0, Qt.AlignBottom | Qt.AlignRight)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 6)
        lay.addLayout(bar)
        lay.addWidget(self.view, 1)
        lay.addLayout(bottom)
        self._refresh_labels()

    def _refresh_labels(self):
        self.btn_src.setText("🔊 System" if self.cfg["audio_source"] == "system" else "🎙 Mic")
        engine = self.cfg["translate_engine"]
        if engine == "openai" and not self.cfg.get("openai_api_key") and self.cfg.get("gemini_api_key"):
            engine = "gemini"
        self.lbl_lang.setText(f"{self.cfg['source_lang']} → {self.cfg['target_lang']} · {engine}")

    def _place_bottom_center(self):
        geo = QGuiApplication.primaryScreen().availableGeometry()
        self.move(geo.center().x() - self.width() // 2, geo.bottom() - self.height() - 40)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(18, 20, 26, self.cfg["bg_alpha"]))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(self.rect(), 12, 12)

    def eventFilter(self, obj, ev):
        # kéo cửa sổ bằng thanh tiêu đề
        if obj is self.handle and ev.type() == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
            self.windowHandle().startSystemMove()
            return True
        return super().eventFilter(obj, ev)

    def _set_alpha(self, v):
        self.cfg["bg_alpha"] = v
        self.update()

    # ---------------- transcript ----------------
    def on_original(self, sid, text):
        self.times.setdefault(sid, datetime.now())
        self.entries.setdefault(sid, ["", ""])[0] = text
        self.render()

    def on_translated(self, sid, text):
        self.entries.setdefault(sid, ["", ""])[1] = text
        self.render()

    def render(self):
        sb = self.view.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 30
        fs = self.cfg["font_size"]
        parts = []
        for sid in sorted(self.entries)[-60:]:
            orig, trans = self.entries[sid]
            if self.cfg.get("show_original", True) and orig:
                parts.append(f'<div style="color:#9aa4b2;font-size:{fs - 3}px">{html.escape(orig)}</div>')
            body = html.escape(trans) if trans else '<span style="color:#666">…</span>'
            color = "#ff8a8a" if trans.startswith("[Lỗi") else "#ffffff"
            parts.append(f'<div style="color:{color};font-size:{fs}px;margin-bottom:8px">{body}</div>')
        self.view.setHtml("".join(parts))
        if at_bottom:
            sb.setValue(sb.maximum())

    def toggle_original(self):
        self.cfg["show_original"] = not self.cfg.get("show_original", True)
        self.render()

    # ---------------- download script ----------------
    def _rows(self):
        rows = []
        for sid in sorted(self.entries):
            o, t = self.entries[sid]
            if o or t:
                rows.append((self.times.get(sid), o.strip(), t.lstrip("↺ ").strip()))
        return rows

    def build_script(self, fmt: str) -> str:
        import csv
        import io
        rows = self._rows()
        base = self.session_start or (rows[0][0] if rows and rows[0][0] else datetime.now())

        def rel(ts):  # giây tính từ lúc Start
            return max(0.0, (ts - base).total_seconds()) if ts else 0.0

        def hms(sec, srt=False):
            h, rem = divmod(sec, 3600)
            m, s_ = divmod(rem, 60)
            if srt:
                return f"{int(h):02}:{int(m):02}:{int(s_):02},{int((s_ % 1) * 1000):03}"
            return f"{int(h):02}:{int(m):02}:{int(s_):02}"

        lang = f"{self.cfg['source_lang']} → {self.cfg['target_lang']}"
        if fmt == "txt_tr":
            return "\n".join(t for _, _, t in rows if t)
        if fmt == "txt_src":
            return "\n".join(o for _, o, _ in rows if o)
        if fmt == "txt":
            out = [f"MiniTrans – {base:%Y-%m-%d %H:%M} ({lang})", ""]
            for ts, o, t in rows:
                out += [f"[{hms(rel(ts))}] {o}", f"           {t}", ""]
            return "\n".join(out)
        if fmt == "md":
            out = [f"# MiniTrans – {base:%Y-%m-%d %H:%M}", f"_{lang}_", "",
                   "| Thời gian | Câu gốc | Bản dịch |", "|---|---|---|"]
            esc = lambda x: x.replace("|", "\\|").replace("\n", " ")
            out += [f"| {hms(rel(ts))} | {esc(o)} | {esc(t)} |" for ts, o, t in rows]
            return "\n".join(out)
        if fmt == "srt":
            out = []
            for i, (ts, o, t) in enumerate(rows):
                start = rel(ts)
                nxt = rel(rows[i + 1][0]) if i + 1 < len(rows) else start + 4
                end = max(start + 1.0, min(nxt, start + 8))
                text = f"{t}\n{o}" if self.cfg.get("show_original", True) else t
                out += [str(i + 1), f"{hms(start, True)} --> {hms(end, True)}", text, ""]
            return "\n".join(out)
        buf = io.StringIO()  # csv
        w = csv.writer(buf)
        w.writerow(["time", "original", "translation"])
        w.writerows([hms(rel(ts)), o, t] for ts, o, t in rows)
        return buf.getvalue()

    def download_original(self):
        """1 click: lưu toàn bộ câu gốc vào ~/Downloads, không hỏi gì."""
        text = self.build_script("txt_src")
        if not text.strip():
            self.set_status("Chưa có nội dung để tải")
            return
        folder = Path.home() / "Downloads"
        folder.mkdir(parents=True, exist_ok=True)
        start = self.session_start or datetime.now()
        path = folder / f"MiniTrans_{start:%Y%m%d_%H%M%S}.txt"
        # Cùng 1 phiên -> ghi đè file cũ, luôn là bản mới nhất
        path.write_text(text + "\n", encoding="utf-8")
        self.set_status(f"⬇ Đã lưu: {path}")

    def copy_script(self):
        QApplication.clipboard().setText(self.build_script("txt_tr"))
        self.set_status("Đã copy toàn bộ bản dịch")

    def clear(self):
        self.times.clear()
        self.entries.clear()
        self.render()

    def set_status(self, text):
        self.status.setText(text)

    # ---------------- actions ----------------
    def toggle(self):
        if self.pipeline.running:
            self.pipeline.stop()
            self.meter.setText("")
            self.save_history()
        else:
            try:
                self.pipeline.start()
                if not self.entries or self.session_start is None:
                    self.session_start = datetime.now()
            except Exception as e:
                self.set_status(f"Không thể bắt đầu: {e}")
                return
        self.btn_start.setText("■ Stop" if self.pipeline.running else "▶ Start")
        self.btn_start.setProperty("running", self.pipeline.running)
        self.btn_start.style().unpolish(self.btn_start)
        self.btn_start.style().polish(self.btn_start)

    def switch_source(self):
        was_running = self.pipeline.running
        if was_running:
            self.toggle()
        self.cfg["audio_source"] = "mic" if self.cfg["audio_source"] == "system" else "system"
        save_config(self.cfg)
        self._refresh_labels()
        if was_running:
            self.toggle()

    def toggle_click_through(self):
        self.click_through = not self.click_through
        self.setWindowFlag(Qt.WindowTransparentForInput, self.click_through)
        self.show()  # đổi window flag cần show lại
        hk = self.cfg["hotkeys"]["click_through"]
        self.set_status(f"Click xuyên: BẬT (nhấn {hk} để tắt)" if self.click_through else "Click xuyên: TẮT")

    def on_hotkey(self, name):
        if name == "toggle":
            self.toggle()
        elif name == "click_through":
            self.toggle_click_through()
        elif name == "quick":
            text = QApplication.clipboard().text().strip()
            self.popup.open_with("Dịch nhanh (clipboard)", text, "Đang dịch…" if text else "")
            if text:
                self.quick_translate(text)
        elif name == "ocr":
            self.hide()  # ẩn overlay để không lọt vào ảnh chụp
            QTimer.singleShot(200, self._start_ocr)

    def _start_ocr(self):
        self.selector.start()
        self.show()
        self.selector.raise_()
        self.selector.activateWindow()

    def _run_bg(self, fn):
        def job():
            try:
                result = fn()
            except Exception as e:
                result = f"[Lỗi: {e}]"
            self.bridge.popup.emit("", result)
        threading.Thread(target=job, daemon=True).start()

    def quick_translate(self, text):
        tr = Translator(self.cfg)
        self._run_bg(lambda: tr.translate(text))

    def on_region(self, png: bytes):
        self.popup.open_with("OCR – Dịch vùng màn hình", "(ảnh vùng đã chọn)")
        tr = Translator(self.cfg)
        self._run_bg(lambda: tr.translate_image(png))

    def open_settings(self):
        dlg = SettingsDialog(self.cfg, self)
        dlg.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        if dlg.exec():
            new_cfg = dlg.values()
            was_running = self.pipeline.running
            if was_running:
                self.toggle()
            self.cfg.clear()
            self.cfg.update(new_cfg)
            save_config(self.cfg)
            self._refresh_labels()
            self.render()
            if was_running:
                self.toggle()

    def save_history(self):
        if not self.entries:
            return
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        start = self.session_start or datetime.now()
        path = HISTORY_DIR / f"{start:%Y%m%d_%H%M%S}.md"
        lines = [f"# Session {start:%Y-%m-%d %H:%M}",
                 f"{self.cfg['source_lang']} → {self.cfg['target_lang']}", ""]
        for sid in sorted(self.entries):
            o, t = self.entries[sid]
            lines += [f"- {o}", f"  - {t}"]
        path.write_text("\n".join(lines), encoding="utf-8")
        self.set_status(f"■ Đã dừng – lưu lịch sử: {path}")

    def quit_app(self):
        if self.pipeline.running:
            self.pipeline.stop()
            self.save_history()
        save_config(self.cfg)
        self.hotkeys.stop()
        QApplication.quit()
