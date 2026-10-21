"""Dịch văn bản và dịch ảnh (OCR) qua nhiều engine."""
import base64

import requests

from .config import parse_glossary

LANG_NAMES = {
    "auto": "auto-detect", "ja": "Japanese", "vi": "Vietnamese", "en": "English",
    "ko": "Korean", "zh": "Chinese (Simplified)", "fr": "French", "de": "German",
    "es": "Spanish", "th": "Thai", "id": "Indonesian",
}

PRESETS = {
    "IT": "The content is from IT/software projects (cloud, AWS, API, infrastructure, testing, "
          "release). Keep technical terms, product names, resource names, code and commands as-is "
          "when the target language normally keeps them in English.",
    "Business": "The content is business communication in a Japanese enterprise. Use polite, "
                "natural business tone.",
    "Meeting": "The content is spoken dialogue in an online meeting. Translate naturally and "
               "concisely, remove filler words (えー, あの, um).",
    "Study": "The content is a lecture. Keep explanations clear and faithful.",
    "General": "",
}


def lang_name(code: str) -> str:
    return LANG_NAMES.get(code, code)


def build_system_prompt(cfg: dict) -> str:
    src, tgt = cfg.get("source_lang", "auto"), cfg.get("target_lang", "vi")
    lines = [
        f"You are a professional real-time interpreter. Translate the user's text from "
        f"{lang_name(src)} into {lang_name(tgt)}.",
        "Output ONLY the translation, no notes, no quotes, no romanization.",
        "The text comes from speech recognition and may contain small errors; infer the "
        "intended meaning.",
    ]
    preset = PRESETS.get(cfg.get("context_preset", "General"), "")
    if preset:
        lines.append(preset)
    glossary = parse_glossary(cfg.get("glossary", ""))
    if glossary:
        lines.append("Always use this glossary (source = target):")
        lines += [f"- {s} = {d}" for s, d in glossary]
    return "\n".join(lines)


def _user_prompt(text: str, context: list[str] | None) -> str:
    if not context:
        return text
    ctx = "\n".join(context[-3:])
    return (f"[Previous sentences, for context only - do NOT translate]\n{ctx}\n\n"
            f"[Translate this]\n{text}")


class Translator:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.engine = cfg.get("translate_engine", "openai")
        # Chọn openai nhưng chỉ có Gemini key -> tự chuyển sang Gemini
        if self.engine == "openai" and not cfg.get("openai_api_key") and cfg.get("gemini_api_key"):
            self.engine = "gemini"
        self.system_prompt = build_system_prompt(cfg)
        self._openai = None
        self._gemini = None

    # ---------- clients ----------
    def openai(self):
        if self._openai is None:
            from openai import OpenAI
            if not self.cfg.get("openai_api_key"):
                raise RuntimeError("Chưa nhập OpenAI API key.")
            self._openai = OpenAI(api_key=self.cfg["openai_api_key"])
        return self._openai

    def gemini(self):
        if self._gemini is None:
            from google import genai
            if not self.cfg.get("gemini_api_key"):
                raise RuntimeError("Chưa nhập Gemini API key.")
            self._gemini = genai.Client(api_key=self.cfg["gemini_api_key"])
        return self._gemini

    # ---------- text ----------
    def translate(self, text: str, context: list[str] | None = None) -> str:
        text = text.strip()
        if not text:
            return ""
        if self.engine == "free":
            return self._google_free(text)
        try:
            if self.engine == "gemini":
                return self._gemini_text(text, context)
            if self.engine == "google":
                return self._google(text)
            if self.engine == "deepl":
                return self._deepl(text)
            return self._openai_text(text, context)
        except Exception as e:
            # Engine chính lỗi (hết quota, sai key...) -> tự chuyển sang Google miễn phí
            if not self.cfg.get("auto_fallback", True):
                raise
            print(f"[FALLBACK] {self.engine} lỗi: {str(e)[:120]} -> dùng free", flush=True)
            return "↺ " + self._google_free(text)

    def _google_free(self, text):
        """Google Translate web endpoint, không cần key (không chính thức, có thể bị chặn nếu
        gọi quá nhiều). Glossary chỉ áp dụng được bằng thay thế thô."""
        src = self.cfg.get("source_lang", "auto")
        r = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": src if src else "auto",
                    "tl": self.cfg.get("target_lang", "vi"), "dt": "t", "q": text},
            timeout=15,
        )
        r.raise_for_status()
        out = "".join(seg[0] for seg in r.json()[0] if seg and seg[0])
        return _apply_glossary_post(out, self.cfg)

    def _openai_text(self, text, context):
        res = self.openai().chat.completions.create(
            model=self.cfg.get("openai_model", "gpt-4o-mini"),
            temperature=0.2,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": _user_prompt(text, context)},
            ],
        )
        return (res.choices[0].message.content or "").strip()

    def _gemini_text(self, text, context):
        from google.genai import types
        from .ratelimit import limiter
        lim = limiter("gemini", self.cfg.get("gemini_rpm", 8))
        lim.wait()
        try:
            res = self.gemini().models.generate_content(
                model=self.cfg.get("gemini_model", "gemini-3.8-flash"),
                contents=_user_prompt(text, context),
                config=types.GenerateContentConfig(system_instruction=self.system_prompt, temperature=0.2),
            )
        except Exception as e:
            lim.on_error(e)
        return (res.text or "").strip()

    def _google(self, text):
        key = self.cfg.get("google_api_key")
        if not key:
            raise RuntimeError("Chưa nhập Google Translate API key.")
        data = {"q": text, "target": self.cfg.get("target_lang", "vi"), "format": "text"}
        if self.cfg.get("source_lang") != "auto":
            data["source"] = self.cfg["source_lang"]
        r = requests.post("https://translation.googleapis.com/language/translate/v2",
                          params={"key": key}, data=data, timeout=15)
        r.raise_for_status()
        out = r.json()["data"]["translations"][0]["translatedText"]
        return _apply_glossary_post(out, self.cfg)

    def _deepl(self, text):
        key = self.cfg.get("deepl_api_key")
        if not key:
            raise RuntimeError("Chưa nhập DeepL API key.")
        host = "api-free.deepl.com" if self.cfg.get("deepl_free", True) else "api.deepl.com"
        tgt = self.cfg.get("target_lang", "vi").upper()
        tgt = {"EN": "EN-US", "ZH": "ZH-HANS"}.get(tgt, tgt)
        data = {"text": text, "target_lang": tgt}
        if self.cfg.get("source_lang") != "auto":
            data["source_lang"] = self.cfg["source_lang"].upper()
        r = requests.post(f"https://{host}/v2/translate",
                          headers={"Authorization": f"DeepL-Auth-Key {key}"}, data=data, timeout=15)
        r.raise_for_status()
        return r.json()["translations"][0]["text"]

    # ---------- image (OCR + dịch) ----------
    def translate_image(self, png: bytes) -> str:
        prompt = (
            "Extract all readable text in this screenshot, then translate it into "
            f"{lang_name(self.cfg.get('target_lang', 'vi'))}.\n"
            "Format:\n【原文 / Original】\n...\n\n【Bản dịch】\n...\n\n" + self.system_prompt
        )
        # Google/DeepL không đọc được ảnh -> dùng OpenAI hoặc Gemini nếu có key
        use_gemini = self.engine == "gemini" or (
            not self.cfg.get("openai_api_key") and self.cfg.get("gemini_api_key"))
        if use_gemini:
            from google.genai import types
            res = self.gemini().models.generate_content(
                model=self.cfg.get("gemini_model", "gemini-3.8-flash"),
                contents=[types.Part.from_bytes(data=png, mime_type="image/png"), prompt],
            )
            return (res.text or "").strip()
        b64 = base64.b64encode(png).decode()
        res = self.openai().chat.completions.create(
            model=self.cfg.get("openai_model", "gpt-4o-mini"),
            temperature=0.2,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]}],
        )
        return (res.choices[0].message.content or "").strip()


def _apply_glossary_post(text: str, cfg: dict) -> str:
    """Google Translate không nhận glossary qua API v2 -> thay thế thô sau khi dịch
    (chỉ có tác dụng khi thuật ngữ gốc còn sót nguyên văn trong bản dịch)."""
    for src, dst in parse_glossary(cfg.get("glossary", "")):
        text = text.replace(src, dst)
    return text
