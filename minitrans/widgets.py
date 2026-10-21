"""Các cửa sổ phụ: popup dịch nhanh, chọn vùng OCR, Settings."""
from PySide6.QtCore import QBuffer, QIODevice, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QTextBrowser, QVBoxLayout, QWidget,
)

from .platform_utils import IS_MAC, list_input_devices, stt_choices
from .translator import LANG_NAMES, PRESETS

POPUP_CSS = """
QWidget#popup { background: #1f2430; border: 1px solid #3b4252; border-radius: 10px; }
QLabel { color: #e5e9f0; font-weight: bold; }
QPlainTextEdit, QTextBrowser { background: #2b3140; color: #eceff4; border: none;
    border-radius: 6px; padding: 6px; font-size: 14px; }
QPushButton { background: #4c6ef5; color: white; border: none; border-radius: 6px; padding: 5px 12px; }
QPushButton#flat { background: transparent; color: #d8dee9; font-size: 15px; }
"""


class TranslatePopup(QWidget):
    """Popup nổi: nhập/dán text -> dịch. Dùng chung cho Quick Translate và OCR."""
    request_translate = Signal(str)

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setObjectName("popup")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(POPUP_CSS)
        self.resize(460, 360)

        self.title = QLabel("Dịch nhanh")
        close = QPushButton("✕", objectName="flat")
        close.clicked.connect(self.hide)
        head = QHBoxLayout()
        head.addWidget(self.title)
        head.addStretch()
        head.addWidget(close)

        self.src = QPlainTextEdit()
        self.src.setPlaceholderText("Dán hoặc gõ nội dung cần dịch… (Ctrl+Enter để dịch)")
        self.src.setMaximumHeight(110)
        self.out = QTextBrowser()
        btn_tr = QPushButton("Dịch")
        btn_tr.clicked.connect(self._do_translate)
        btn_copy = QPushButton("Copy bản dịch")
        btn_copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.out.toPlainText()))
        btns = QHBoxLayout()
        btns.addStretch()
        btns.addWidget(btn_copy)
        btns.addWidget(btn_tr)

        lay = QVBoxLayout(self)
        lay.addLayout(head)
        lay.addWidget(self.src)
        lay.addWidget(self.out, 1)
        lay.addLayout(btns)
        self._drag = None

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and e.modifiers() & Qt.ControlModifier:
            self._do_translate()
        elif e.key() == Qt.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(e)

    def _do_translate(self):
        text = self.src.toPlainText().strip()
        if text:
            self.out.setPlainText("Đang dịch…")
            self.request_translate.emit(text)

    def open_with(self, title: str, src_text: str, result: str = "Đang dịch…"):
        self.title.setText(title)
        self.src.setPlainText(src_text)
        self.out.setPlainText(result)
        pos = QCursor.pos() + QPoint(16, 16)
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        pos.setX(min(pos.x(), geo.right() - self.width()))
        pos.setY(min(pos.y(), geo.bottom() - self.height()))
        self.move(pos)
        self.show()
        self.raise_()
        self.activateWindow()

    def set_result(self, text: str):
        self.out.setPlainText(text)

    # kéo popup bằng chuột
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None


class RegionSelector(QWidget):
    """Chụp màn hình (màn hình đang có chuột), cho người dùng kéo chọn vùng."""
    selected = Signal(bytes)  # PNG

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setCursor(Qt.CrossCursor)
        self.origin = self.current = None
        self.shot = QPixmap()

    def start(self):
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        self.shot = screen.grabWindow(0)
        self.setGeometry(screen.geometry())
        self.origin = self.current = None
        self.showFullScreen()
        self.activateWindow()

    def paintEvent(self, _):
        p = QPainter(self)
        p.drawPixmap(self.rect(), self.shot)
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))
        if self.origin and self.current:
            r = QRect(self.origin, self.current).normalized()
            dpr = self.shot.devicePixelRatio()
            src = QRect(int(r.x() * dpr), int(r.y() * dpr), int(r.width() * dpr), int(r.height() * dpr))
            p.drawPixmap(r, self.shot, src)
            p.setPen(QPen(QColor("#4c6ef5"), 2))
            p.drawRect(r)

    def mousePressEvent(self, e):
        self.origin = self.current = e.position().toPoint()
        self.update()

    def mouseMoveEvent(self, e):
        self.current = e.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, e):
        r = QRect(self.origin, e.position().toPoint()).normalized() if self.origin else QRect()
        self.hide()
        if r.width() < 8 or r.height() < 8:
            return
        dpr = self.shot.devicePixelRatio()
        crop = self.shot.copy(int(r.x() * dpr), int(r.y() * dpr), int(r.width() * dpr), int(r.height() * dpr))
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        crop.save(buf, "PNG")
        self.selected.emit(bytes(buf.data()))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.hide()


class SettingsDialog(QDialog):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MiniTrans – Settings")
        self.cfg = cfg
        self.setMinimumWidth(520)
        # Ghi đè style trắng của overlay (nếu không label sẽ bị mờ, khó đọc)
        self.setStyleSheet("QLabel { color: palette(window-text); font-weight: normal; }")
        f = QFormLayout()

        def combo(items, value, editable=False):
            c = QComboBox()
            c.setEditable(editable)
            c.addItems(items)
            c.setCurrentText(str(value))
            return c

        langs = list(LANG_NAMES.keys())
        self.source = combo(langs, cfg["source_lang"], True)
        self.target = combo([l for l in langs if l != "auto"], cfg["target_lang"], True)
        self.audio = combo(["system", "mic"], cfg["audio_source"])
        self.stt = combo(stt_choices(), cfg["stt_engine"])
        self.device = combo(["(mặc định)"] + list_input_devices(), cfg.get("input_device") or "(mặc định)")
        self.whisper_device = combo(["cpu", "cuda"], cfg.get("whisper_device", "cpu"))
        self.stt_model = QLineEdit(cfg["stt_model"])
        self.local_model = combo(["tiny", "base", "small", "medium", "large-v3"], cfg["local_whisper_model"], True)
        self.engine = combo(["free", "gemini", "openai", "google", "deepl"], cfg["translate_engine"])
        self.openai_model = QLineEdit(cfg["openai_model"])
        self.gemini_model = QLineEdit(cfg["gemini_model"])
        self.keys = {}
        for k in ("openai_api_key", "gemini_api_key", "google_api_key", "deepl_api_key"):
            e = QLineEdit(cfg.get(k, ""))
            e.setEchoMode(QLineEdit.Password)
            self.keys[k] = e
        self.stt_hint = QCheckBox("Gửi glossary cho STT làm gợi ý (có thể bị lặp khi có nhạc nền)")
        self.stt_hint.setChecked(cfg.get("stt_glossary_hint", False))
        self.fallback = QCheckBox("Engine dịch lỗi/hết quota → tự dùng 'free'")
        self.fallback.setChecked(cfg.get("auto_fallback", True))
        self.deepl_free = QCheckBox("DeepL Free API")
        self.deepl_free.setChecked(cfg.get("deepl_free", True))
        self.preset = combo(list(PRESETS.keys()), cfg["context_preset"])
        self.glossary = QPlainTextEdit(cfg.get("glossary", ""))
        self.glossary.setPlaceholderText("Mỗi dòng: thuật ngữ gốc=bản dịch mong muốn")
        self.glossary.setMinimumHeight(120)
        self.font = QSpinBox()
        self.font.setRange(10, 36)
        self.font.setValue(cfg["font_size"])
        self.thr = QLineEdit(str(cfg["vad"]["energy_threshold"]))
        self.silence = QSpinBox()
        self.silence.setRange(200, 2000)
        self.silence.setSingleStep(50)
        self.silence.setValue(int(cfg["vad"].get("silence_ms", 450)))
        self.maxseg = QSpinBox()
        self.maxseg.setRange(2, 15)
        self.maxseg.setValue(int(cfg["vad"].get("max_segment_s", 5)))
        self.rpm = QSpinBox()
        self.rpm.setRange(1, 1000)
        self.rpm.setValue(int(cfg.get("gemini_rpm", 8)))

        f.addRow("Ngôn ngữ nguồn", self.source)
        f.addRow("Ngôn ngữ đích", self.target)
        f.addRow("Nguồn âm thanh", self.audio)
        f.addRow("Thiết bị input (Mic)", self.device)
        f.addRow("STT engine", self.stt)
        f.addRow("OpenAI STT model", self.stt_model)
        f.addRow("Local Whisper model", self.local_model)
        if not IS_MAC:
            f.addRow("Local Whisper chạy trên", self.whisper_device)
        f.addRow("Engine dịch", self.engine)
        f.addRow("", self.fallback)
        f.addRow("OpenAI model", self.openai_model)
        f.addRow("Gemini model", self.gemini_model)
        f.addRow("OpenAI API key", self.keys["openai_api_key"])
        f.addRow("Gemini API key", self.keys["gemini_api_key"])
        f.addRow("Google Translate key", self.keys["google_api_key"])
        f.addRow("DeepL API key", self.keys["deepl_api_key"])
        f.addRow("", self.deepl_free)
        f.addRow("Context preset", self.preset)
        f.addRow("Glossary", self.glossary)
        f.addRow("", self.stt_hint)
        f.addRow("Cỡ chữ", self.font)
        f.addRow("Ngưỡng VAD (0.002–0.05)", self.thr)
        f.addRow("Khoảng lặng cắt câu (ms)", self.silence)
        f.addRow("Câu dài tối đa (giây)", self.maxseg)
        f.addRow("Gemini request/phút", self.rpm)

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(f)
        lay.addWidget(bb)

    def values(self) -> dict:
        c = dict(self.cfg)
        c.update({
            "source_lang": self.source.currentText().strip() or "auto",
            "target_lang": self.target.currentText().strip() or "vi",
            "audio_source": self.audio.currentText(),
            "stt_engine": self.stt.currentText(),
            "input_device": "" if self.device.currentText() == "(mặc định)" else self.device.currentText(),
            "whisper_device": self.whisper_device.currentText(),
            "stt_model": self.stt_model.text().strip(),
            "local_whisper_model": self.local_model.currentText().strip(),
            "translate_engine": self.engine.currentText(),
            "openai_model": self.openai_model.text().strip(),
            "gemini_model": self.gemini_model.text().strip(),
            "deepl_free": self.deepl_free.isChecked(),
            "auto_fallback": self.fallback.isChecked(),
            "stt_glossary_hint": self.stt_hint.isChecked(),
            "context_preset": self.preset.currentText(),
            "glossary": self.glossary.toPlainText(),
            "font_size": self.font.value(),
            "gemini_rpm": self.rpm.value(),
        })
        for k, e in self.keys.items():
            c[k] = e.text().strip()
        vad = dict(c["vad"])
        try:
            vad["energy_threshold"] = min(max(float(self.thr.text()), 0.0005), 0.2)
        except ValueError:
            pass
        vad["silence_ms"] = self.silence.value()
        vad["max_segment_s"] = float(self.maxseg.value())
        c["vad"] = vad
        return c
