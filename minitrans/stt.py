"""Speech-to-Text: OpenAI (cloud) hoặc faster-whisper (offline)."""
import io
import re
import wave

import numpy as np

from .config import parse_glossary

# Whisper hay "ảo giác" ra các câu này khi gặp đoạn ồn / im lặng
HALLUCINATIONS = {
    "ご視聴ありがとうございました", "ご視聴ありがとうございました。", "ありがとうございました。",
    "チャンネル登録お願いします", "thank you.", "thanks for watching!", "thank you for watching.",
    "subtitles by the amara.org community", "cảm ơn các bạn đã theo dõi",
    "hãy subscribe cho kênh ghiền mì gõ để không bỏ lỡ những video hấp dẫn",
}


def is_hallucination(text: str, cfg: dict | None = None) -> bool:
    t = text.strip().lower()
    if not t or t in HALLUCINATIONS or len(t) <= 1:
        return True
    # Whisper "lặp lại prompt": khi đoạn âm thanh không rõ lời (nhạc, ồn), nó chép lại
    # danh sách thuật ngữ glossary -> bỏ câu chỉ gồm các thuật ngữ đó
    if cfg:
        terms = {src for src, _ in parse_glossary(cfg.get("glossary", ""))}
        parts = [x.strip(" 。.、,，") for x in re.split(r"[、,，。.\s]+", text) if x.strip(" 。.、,，")]
        if parts and terms and all(x in terms for x in parts):
            return True
    return False


def to_wav_bytes(audio: np.ndarray, sr: int = 16000) -> bytes:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def _glossary_prompt(cfg: dict) -> str:
    # Đưa thuật ngữ gốc vào prompt giúp STT nhận đúng từ chuyên ngành, NHƯNG Whisper hay
    # chép lại nguyên prompt khi gặp nhạc/ồn -> mặc định TẮT
    if not cfg.get("stt_glossary_hint", False):
        return ""
    terms = [src for src, _ in parse_glossary(cfg.get("glossary", ""))]
    return "、".join(terms[:50])


class OpenAISTT:
    def __init__(self, cfg: dict):
        from openai import OpenAI

        if not cfg.get("openai_api_key"):
            raise RuntimeError("Chưa nhập OpenAI API key (Settings).")
        self.client = OpenAI(api_key=cfg["openai_api_key"])
        self.model = cfg.get("stt_model", "gpt-4o-mini-transcribe")
        self.lang = None if cfg.get("source_lang") == "auto" else cfg.get("source_lang")
        self.prompt = _glossary_prompt(cfg)

    def transcribe(self, audio: np.ndarray) -> str:
        kwargs = {"model": self.model, "file": ("segment.wav", to_wav_bytes(audio), "audio/wav")}
        if self.lang:
            kwargs["language"] = self.lang
        if self.prompt:
            kwargs["prompt"] = self.prompt
        res = self.client.audio.transcriptions.create(**kwargs)
        return (res.text or "").strip()


class LocalWhisperSTT:
    _model_cache: dict = {}

    def __init__(self, cfg: dict):
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise RuntimeError("Chưa cài faster-whisper: pip install faster-whisper") from None

        name = cfg.get("local_whisper_model", "small")
        if name not in self._model_cache:  # load 1 lần, lần đầu sẽ tự tải model
            import os
            device = cfg.get("whisper_device", "cpu")  # "cuda" nếu Windows có GPU NVIDIA + CUDA/cuDNN
            try:
                self._model_cache[name] = WhisperModel(
                    name, device=device, compute_type="int8" if device == "cpu" else "float16",
                    cpu_threads=os.cpu_count() or 4)
            except Exception as e:
                if device == "cpu":
                    raise
                print(f"[STT] Không dùng được {device}: {e} -> chuyển CPU", flush=True)
                self._model_cache[name] = WhisperModel(name, device="cpu", compute_type="int8",
                                                       cpu_threads=os.cpu_count() or 4)
        self.model = self._model_cache[name]
        self.lang = None if cfg.get("source_lang") == "auto" else cfg.get("source_lang")
        self.prompt = _glossary_prompt(cfg) or None

    def transcribe(self, audio: np.ndarray) -> str:
        # Đã tự cắt câu bằng VAD -> tắt các bước thừa để nhanh hơn
        segments, _ = self.model.transcribe(
            audio, language=self.lang, vad_filter=False, initial_prompt=self.prompt, beam_size=1,
            best_of=1, temperature=0.0, condition_on_previous_text=False, without_timestamps=True,
        )
        return "".join(s.text for s in segments).strip()


class GeminiSTT:
    """Dùng Gemini nghe file audio và chép lại lời nói (chỉ cần Gemini API key)."""

    def __init__(self, cfg: dict):
        from google import genai

        if not cfg.get("gemini_api_key"):
            raise RuntimeError("Chưa nhập Gemini API key (Settings).")
        self.client = genai.Client(api_key=cfg["gemini_api_key"])
        self.model = cfg.get("gemini_model", "gemini-3.8-flash")
        lang = cfg.get("source_lang", "auto")
        self.prompt = (
            "Transcribe the speech in this audio verbatim"
            + ("" if lang == "auto" else f" (language code: {lang})")
            + ". Output ONLY the transcript. If there is no clear speech, output nothing."
        )
        terms = _glossary_prompt(cfg)
        if terms:
            self.prompt += f" Domain terms that may appear: {terms}"

        from .ratelimit import limiter
        self.limiter = limiter("gemini", cfg.get("gemini_rpm", 8))
        self.cfg = cfg

    def _call(self, audio, prompt):
        from google.genai import types

        self.limiter.wait()
        try:
            res = self.client.models.generate_content(
                model=self.model,
                contents=[types.Part.from_bytes(data=to_wav_bytes(audio), mime_type="audio/wav"), prompt],
                config=types.GenerateContentConfig(temperature=0),
            )
        except Exception as e:
            self.limiter.on_error(e)
        return (res.text or "").strip()

    def transcribe(self, audio: np.ndarray) -> str:
        return self._call(audio, self.prompt)

    def transcribe_and_translate(self, audio: np.ndarray, context=None) -> tuple[str, str]:
        """Nghe + dịch trong 1 request (tiết kiệm quota)."""
        import json
        from .translator import build_system_prompt

        ctx = ("\nPrevious sentences (context only): " + " / ".join(context[-3:])) if context else ""
        prompt = (
            self.prompt + "\nThen translate the transcript.\n" + build_system_prompt(self.cfg) + ctx +
            '\nReturn ONLY JSON: {"original": "<transcript>", "translation": "<translation>"}. '
            'If no clear speech, return {"original": "", "translation": ""}.'
        )
        raw = self._call(audio, prompt).strip().strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        try:
            d = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
            return str(d.get("original", "")).strip(), str(d.get("translation", "")).strip()
        except Exception:
            return raw, ""


class MlxWhisperSTT:
    """Whisper chạy trên GPU Apple Silicon (M1/M2/M3/M4) qua MLX - nhanh hơn faster-whisper nhiều."""

    def __init__(self, cfg: dict):
        try:
            import mlx_whisper
        except ImportError:
            raise RuntimeError("Chưa cài mlx-whisper: pip install mlx-whisper (chỉ Mac chip M)") from None

        self.mlx = mlx_whisper
        self.repo = cfg.get("mlx_model", "mlx-community/whisper-large-v3-turbo")
        self.lang = None if cfg.get("source_lang") == "auto" else cfg.get("source_lang")
        self.prompt = _glossary_prompt(cfg) or None

    def transcribe(self, audio: np.ndarray) -> str:
        res = self.mlx.transcribe(
            audio, path_or_hf_repo=self.repo, language=self.lang, initial_prompt=self.prompt,
            condition_on_previous_text=False, temperature=0.0, without_timestamps=True,
        )
        return (res.get("text") or "").strip()


def make_stt(cfg: dict):
    from .platform_utils import resolve_stt_engine
    engine = resolve_stt_engine(cfg)
    print(f"[STT] engine = {engine}", flush=True)
    # Chọn openai nhưng không có OpenAI key mà có Gemini key -> tự chuyển sang Gemini
    if engine == "openai" and not cfg.get("openai_api_key") and cfg.get("gemini_api_key"):
        engine = "gemini"
    if engine == "local":
        return LocalWhisperSTT(cfg)
    if engine == "mlx":
        return MlxWhisperSTT(cfg)
    if engine == "gemini":
        return GeminiSTT(cfg)
    return OpenAISTT(cfg)
