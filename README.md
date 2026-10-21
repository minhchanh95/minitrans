# MiniTrans – App dịch giọng nói real-time (lấy cảm hứng từ Transifyr)

Overlay trong suốt, luôn nổi trên cùng: nghe âm thanh hệ thống (Teams/Zoom/YouTube…) hoặc micro
→ nhận dạng giọng nói → dịch → hiện phụ đề song ngữ.

## Tính năng (MVP)
| Tính năng | Mô tả |
|---|---|
| Dịch real-time | Âm thanh hệ thống (Windows WASAPI loopback, không cần virtual device) hoặc Mic |
| STT | Gemini, OpenAI `gpt-4o-mini-transcribe` hoặc faster-whisper (offline) |
| Engine dịch | OpenAI, Gemini, Google Translate, DeepL |
| Glossary + Context preset | Ép dịch đúng thuật ngữ IT/JP (VD: `本番環境=môi trường Production`) |
| Dịch nhanh | Copy text → `Ctrl+Alt+Q` |
| OCR | `Ctrl+Alt+O` → kéo chọn vùng màn hình → trích xuất + dịch (OpenAI/Gemini vision) |
| Click xuyên | `Ctrl+Alt+X` → overlay không chặn chuột |
| Lịch sử | Mỗi phiên lưu Markdown tại `~/.minitrans/history/` |
| Tải script | Nút ⬇: 1 click lưu toàn bộ câu gốc vào thư mục Downloads (.txt) |

Phím tắt: `Ctrl+Alt+S` Start/Stop · `Ctrl+Alt+Q` dịch nhanh · `Ctrl+Alt+O` OCR · `Ctrl+Alt+X` click xuyên.

## Cài đặt & chạy

### Windows 10/11
1. Cài Python 3.12 từ python.org (tick **Add python.exe to PATH**).
2. Double-click **`setup_windows.bat`** (chỉ lần đầu).
3. Double-click **`run_windows.bat`** để chạy.

Nút 🔊 System thu trực tiếp âm thanh loa/tai nghe (Teams, Zoom, YouTube), không cần cài thêm gì.
Có GPU NVIDIA + CUDA: ⚙ → *Local Whisper chạy trên* = `cuda` (lỗi sẽ tự quay về CPU).

### macOS 13+
```bash
chmod +x *.sh *.command
./setup_mac.sh       # lần đầu
./run_mac.command    # chạy (hoặc double-click trong Finder)
```
Cấp quyền cho Terminal / VS Code trong **System Settings → Privacy & Security**: Microphone,
Accessibility (phím tắt), Screen Recording (OCR). Cấp xong thì thoát hẳn (Cmd+Q) rồi mở lại.

**Thu âm loa trên Mac (🔊 System)** – macOS không cho thu trực tiếp, cần BlackHole:
1. `brew install blackhole-2ch` → khởi động lại máy.
2. Mở **Audio MIDI Setup** → `+` → **Create Multi-Output Device** → tick *loa/tai nghe của bạn* và *BlackHole 2ch*.
3. System Settings → Sound → Output = **Multi-Output Device** (vẫn nghe bình thường, BlackHole nhận bản sao).
4. Trong app bấm **🔊 System** – app tự tìm BlackHole. Tai nghe vẫn dùng được.

### STT engine (`auto` sẽ tự chọn)
| Engine | Máy | Ghi chú |
|---|---|---|
| `mlx` | Mac chip M | Nhanh nhất trên Mac, offline |
| `local` | Windows & Mac | faster-whisper, offline. Máy yếu chọn model `base` |
| `gemini` / `openai` | Mọi máy | Cần API key, tốn quota |

Engine dịch mặc định `free` (không cần key); `gemini`/`openai` dịch hay hơn, lỗi/hết quota sẽ tự quay về `free`.

### Đóng gói
- Windows: `build_windows.bat` → `dist\MiniTrans\MiniTrans.exe`
- Mac: `./build_mac.sh` → `dist/MiniTrans.app`

PyInstaller không build chéo: muốn file .exe phải build trên Windows, .app phải build trên Mac.

## Tinh chỉnh
- Bị bắt cả tiếng ồn → tăng *Ngưỡng VAD* (0.01–0.02). Bị mất câu nói nhỏ → giảm (0.004).
- Muốn câu ngắn hơn/nhanh hơn: sửa `vad.silence_ms`, `vad.max_segment_s` trong `~/.minitrans/config.json`.
- Dịch sai thuật ngữ → thêm vào Glossary; engine OpenAI/Gemini áp dụng glossary tốt nhất.

## Kiến trúc
```
audio.py      thu âm + resample 16kHz + VAD cắt câu
stt.py        speech-to-text (OpenAI / faster-whisper) + lọc câu "ảo giác" của Whisper
translator.py dịch text & ảnh, prompt có preset + glossary + 3 câu trước làm ngữ cảnh
pipeline.py   xử lý song song từng câu (ThreadPool), đẩy kết quả về UI qua Qt Signal
overlay.py    cửa sổ overlay, hotkey, lịch sử
widgets.py    popup dịch nhanh, chọn vùng OCR, Settings
```

## Giới hạn hiện tại / hướng nâng cấp
- Độ trễ ~2–4s/câu (cắt theo khoảng lặng). Muốn ~1s như Transifyr: thay `stt.py` bằng STT streaming
  (Soniox, Deepgram, OpenAI Realtime API) qua WebSocket.
- API key lưu dạng plain text trong config → nên mã hoá (Windows DPAPI / `keyring`) nếu phát hành.
- Chưa có: TTS đọc bản dịch, AI Chat hỏi về transcript, Interview mode, chế độ 2 chiều.
