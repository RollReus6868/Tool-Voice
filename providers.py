from __future__ import annotations

import base64
import os
import tempfile
import time
from pathlib import Path
from typing import Callable

import requests

import omni
from media import merge_audio_files, to_wav, wav_to_mp3
from omni import CancelledError, ProviderError   # defined in omni.py; re-exported for the rest of the app
from utils import split_text

LogFn = Callable[[str], None] | None
CancelFn = Callable[[], bool] | None

# ---------------------------------------------------------------- catalogues
PROVIDERS = ["Inworld", "OmniVoice"]
FREE_PROVIDERS = {"OmniVoice"}          # run on this computer: no API key, no per-character fee

MODELS = {
    # first entry = default (fast and cheapest per character)
    "Inworld": ["inworld-tts-2-flash", "inworld-tts-2", "inworld-tts-1.5-max", "inworld-tts-1.5-mini"],
    # a HuggingFace repo id, or the folder of a checkpoint on this computer (the box is editable)
    "OmniVoice": [omni.DEFAULT_MODEL],
}

SPEED_RANGE = {"Inworld": (0.5, 1.5), "OmniVoice": (0.5, 1.5)}

# Inworld "Delivery" (the Playground slider). inworld-tts-2 reads deliveryMode;
# older/flash models read temperature instead (each model ignores the other field).
DELIVERY = [("STABLE", "🧊 Ổn định", 0.7), ("BALANCED", "⚖ Cân bằng", 1.0), ("CREATIVE", "🎨 Sáng tạo", 1.3)]
DELIVERY_TEMPERATURE = {code: temp for code, _label, temp in DELIVERY}
INSTRUCTION_MODELS = {"inworld-tts-2"}   # models that accept a speaking-style instruction

LANGUAGES = {
    # label, API value (Inworld = BCP-47 / empty = auto; OmniVoice = its language id / empty = auto)
    "Inworld": [
        ("Tự động nhận diện", ""), ("Tiếng Việt", "vi-VN"), ("English (US)", "en-US"),
        ("English (UK)", "en-GB"), ("中文 (Chinese)", "zh-CN"), ("日本語 (Japanese)", "ja-JP"),
        ("한국어 (Korean)", "ko-KR"), ("Español", "es-ES"), ("Français", "fr-FR"),
        ("Deutsch", "de-DE"), ("Português", "pt-BR"), ("Русский", "ru-RU"),
    ],
    "OmniVoice": omni.languages(),
}

_LEGACY_INWORLD = {"AUTO": "", "EN_US": "en-US", "VI_VN": "vi-VN", "ES_ES": "es-ES",
                   "ZH_CN": "zh-CN", "JA_JP": "ja-JP", "KO_KR": "ko-KR"}


def normalize_language(provider: str, value: str | None) -> str:
    value = (value or "").strip()
    if provider == "Inworld":
        return _LEGACY_INWORLD.get(value.upper(), value) if value else ""
    return value


def language_label(provider: str, value: str | None) -> str:
    value = normalize_language(provider, value)
    for label, code in LANGUAGES.get(provider, []):
        if code == value:
            return label
    return value or "Tự động"


# ---------------------------------------------------------------- errors
class _Retryable(Exception):
    pass


def _friendly_http(status: int, body: str) -> str:
    body = (body or "").strip().replace("\n", " ")[:400]
    if status in (401, 403):
        return f"API key sai, hết hạn hoặc không có quyền (HTTP {status}). {body}"
    if status == 404:
        return f"Không tìm thấy tài nguyên (HTTP 404) — kiểm tra Base URL / Voice ID. {body}"
    if status == 402:
        return f"Tài khoản hết số dư/quota (HTTP 402). {body}"
    if status == 413:
        return "Dữ liệu gửi lên quá lớn (HTTP 413) — dùng file mẫu nhỏ hơn."
    if status == 429:
        return f"Gửi quá nhiều yêu cầu (HTTP 429) — giảm số luồng hoặc thử lại sau. {body}"
    return f"HTTP {status}: {body}"


class BaseProvider:
    name = "Base"
    max_chars = 1500

    def __init__(self, api_key: str, base_url: str, log: LogFn = None, cancel: CancelFn = None) -> None:
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or "").rstrip("/")
        self.log = log or (lambda _msg: None)
        self.cancel = cancel or (lambda: False)
        self.session = requests.Session()
        self.chars_used = 0          # characters billed by the provider (reported or counted)

    def _check_cancel(self):
        if self.cancel():
            raise CancelledError("Đã dừng theo yêu cầu.")

    def _check_payload(self, data: dict) -> None:
        """Provider specific in-body error check. Raise _Retryable or ProviderError."""

    def _request(self, method: str, url: str, *, retries: int = 4, json_body: bool = True, **kwargs):
        last = ""
        for attempt in range(1, retries + 1):
            self._check_cancel()
            try:
                resp = self.session.request(method, url, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last = f"Lỗi mạng: {exc.__class__.__name__}"
                if attempt >= retries:
                    raise ProviderError(last + " — kiểm tra kết nối Internet.") from exc
                self._sleep(attempt, last)
                continue

            if resp.status_code in (408, 429, 500, 502, 503, 504):
                last = _friendly_http(resp.status_code, resp.text)
                if attempt >= retries:
                    raise ProviderError(last)
                self._sleep(attempt, f"Máy chủ bận (HTTP {resp.status_code})")
                continue
            if resp.status_code >= 400:
                raise ProviderError(_friendly_http(resp.status_code, resp.text))
            if not json_body:
                return resp
            try:
                data = resp.json()
            except ValueError as exc:
                raise ProviderError(f"Phản hồi không phải JSON: {resp.text[:200]}") from exc
            try:
                self._check_payload(data)
            except _Retryable as exc:
                last = str(exc)
                if attempt >= retries:
                    raise ProviderError(last)
                self._sleep(attempt, last)
                continue
            return data
        raise ProviderError(last or "Yêu cầu thất bại.")

    def _sleep(self, attempt: int, reason: str):
        wait = min(2 ** attempt, 20)
        self.log(f"⏳ {reason}. Thử lại sau {wait}s (lần {attempt + 1})…")
        for _ in range(wait * 10):
            self._check_cancel()
            time.sleep(0.1)

    # --- API surface -----------------------------------------------------
    def clone_voice(self, sample_path: str, display_name: str, language: str = "",
                    denoise: bool = False) -> str:
        raise NotImplementedError

    def synth_chunk(self, text: str, voice_id: str, *, model: str, speed: float, language: str,
                    options: dict | None = None) -> bytes:
        raise NotImplementedError

    def list_voices(self) -> list[dict]:
        raise NotImplementedError

    def synthesize(self, text: str, voice_id: str, output_path: str, *, model: str,
                   speed: float = 1.0, language: str = "", options: dict | None = None) -> str:
        chunks = split_text(text, self.max_chars)
        if not chunks:
            raise ProviderError("Nội dung văn bản trống.")
        with tempfile.TemporaryDirectory(prefix="tts_parts_") as td:
            parts: list[str] = []
            for index, chunk in enumerate(chunks, 1):
                self._check_cancel()
                if len(chunks) > 1:
                    self.log(f"   ↳ {self.name}: đoạn {index}/{len(chunks)} ({len(chunk)} ký tự)")
                audio = self.synth_chunk(chunk, voice_id, model=model, speed=speed, language=language,
                                         options=options)
                if not audio:
                    raise ProviderError("API trả về audio rỗng.")
                part = Path(td) / f"part_{index:04d}.mp3"
                part.write_bytes(audio)
                parts.append(str(part))
            tmp_out = output_path + ".part"
            merge_audio_files(parts, tmp_out)
            os.replace(tmp_out, output_path)
        return output_path


# ---------------------------------------------------------------- Inworld
class InworldProvider(BaseProvider):
    name = "Inworld"
    max_chars = 1800  # API limit: 2,000 UTF-16 code units per request

    def __init__(self, api_key: str, base_url: str = "https://api.inworld.ai", log: LogFn = None,
                 cancel: CancelFn = None) -> None:
        super().__init__(api_key, base_url or "https://api.inworld.ai", log, cancel)
        key = self.api_key
        if key.lower().startswith("basic "):
            key = key[6:].strip()
        self.api_key = key

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Basic {self.api_key}", "Content-Type": "application/json"}

    def clone_voice(self, sample_path, display_name, language="", denoise=False) -> str:
        self.log("📤 Đang mã hóa và gửi mẫu giọng lên Inworld…")
        audio_b64 = base64.b64encode(Path(sample_path).read_bytes()).decode("ascii")
        payload: dict = {
            "displayName": display_name.strip(),
            "voiceSamples": [{"audioData": audio_b64}],
        }
        lang = normalize_language("Inworld", language)
        if lang:
            payload["languageCode"] = lang
        if denoise:
            payload["audioProcessingConfig"] = {"removeBackgroundNoise": True}
        data = self._request("POST", f"{self.base_url}/voices/v1/voices:clone",
                             headers=self.headers, json=payload, timeout=300, retries=3)
        voice_id = (data.get("voice") or {}).get("voiceId")
        if not voice_id:
            raise ProviderError(f"Inworld không trả voiceId: {str(data)[:300]}")
        return voice_id

    OPTION_FIELDS = ("deliveryMode", "temperature", "enhanceGeneration", "instruction")

    @staticmethod
    def apply_options(payload: dict, model: str, options: dict | None) -> dict:
        """Delivery / quality / instruction, sent only when they differ from the API defaults."""
        o = options or {}
        delivery = (o.get("delivery") or "BALANCED").upper()
        if delivery in DELIVERY_TEMPERATURE and delivery != "BALANCED":
            if model == "inworld-tts-2":
                payload["deliveryMode"] = delivery
            else:
                payload["temperature"] = DELIVERY_TEMPERATURE[delivery]
        if o.get("enhance"):
            payload["enhanceGeneration"] = True
        instruction = (o.get("instruction") or "").strip()
        if instruction and model in INSTRUCTION_MODELS:
            payload["instruction"] = instruction[:500]
        return payload

    def synth_chunk(self, text, voice_id, *, model, speed, language, options=None) -> bytes:
        model = model or MODELS["Inworld"][0]
        payload: dict = {
            "text": text,
            "voiceId": voice_id,
            "modelId": model,
            "audioConfig": {"audioEncoding": "MP3", "sampleRateHertz": 44100},
        }
        self.apply_options(payload, model, options)
        lo, hi = SPEED_RANGE["Inworld"]
        speed = max(lo, min(hi, float(speed or 1.0)))
        if abs(speed - 1.0) > 1e-3:
            payload["audioConfig"]["speakingRate"] = round(speed, 2)
        lang = normalize_language("Inworld", language)
        if lang:
            payload["language"] = lang
        extras = [k for k in self.OPTION_FIELDS if k in payload]
        try:
            data = self._request("POST", f"{self.base_url}/tts/v1/voice",
                                 headers=self.headers, json=payload, timeout=180)
        except ProviderError as exc:
            # A model that does not accept one of the style options answers 400:
            # read the text plainly instead of failing the whole job.
            if not extras or not str(exc).startswith("HTTP 400"):
                raise
            for k in extras:
                payload.pop(k, None)
            self.log(f"⚠ {model} không nhận tùy chọn {', '.join(extras)} — đọc lại với thiết lập mặc định.")
            data = self._request("POST", f"{self.base_url}/tts/v1/voice",
                                 headers=self.headers, json=payload, timeout=180)
        audio = data.get("audioContent") or (data.get("result") or {}).get("audioContent")
        if not audio:
            raise ProviderError(f"Inworld không trả audioContent: {str(data)[:300]}")
        used = (data.get("usage") or {}).get("processedCharactersCount")
        self.chars_used += int(used) if isinstance(used, (int, float)) and used > 0 else len(text)
        return base64.b64decode(audio)

    def list_voices(self) -> list[dict]:
        out: list[dict] = []
        token = ""
        for _page in range(20):  # safety bound: 20 pages x 2000 voices
            params = {"pageSize": 2000}
            if token:
                params["pageToken"] = token
            data = self._request("GET", f"{self.base_url}/voices/v1/voices",
                                 headers=self.headers, params=params, timeout=60, retries=2)
            for v in data.get("voices") or []:
                src = (v.get("source") or "").upper()
                mine = bool(v.get("owned")) or src in ("IVC", "PVC", "TVD")
                tags = [str(t) for t in (v.get("tags") or []) if t]
                out.append({
                    "voice_id": v.get("voiceId", ""),
                    "name": v.get("displayName") or v.get("voiceId", ""),
                    "kind": "Của tôi" if mine or (src and src != "SYSTEM") else "Hệ thống",
                    "language": v.get("languageCode")
                    or _LEGACY_INWORLD.get(v.get("langCode", ""), v.get("langCode", "")),
                    "gender": {"male": "Nam", "female": "Nữ", "neutral": "Trung tính"}.get(
                        (v.get("gender") or "").lower(), ""),
                    "description": (v.get("description") or "").strip(),
                    "tags": tags,
                    "source": src,
                })
            token = data.get("nextPageToken") or ""
            if not token:
                break
        return out


# ---------------------------------------------------------------- OmniVoice (free, on this computer)
class OmniVoiceProvider(BaseProvider):
    """Talks to the local OmniVoice engine (omni.py). A library voice is a saved
    voice-clone prompt, so the same voice comes back for every row of a batch."""

    name = "OmniVoice"
    max_chars = 500   # short requests = steady progress and a quick stop; the engine joins them seamlessly

    def __init__(self, config: dict | None = None, log: LogFn = None, cancel: CancelFn = None) -> None:
        super().__init__("", "", log, cancel)
        self.config = config or {}
        self.session.close()             # no HTTP here
        self.last_ref_text = ""

    def _ask(self, req: dict, model: str = "") -> dict:
        req["model"] = (model or "").strip() or omni.DEFAULT_MODEL
        return omni.ENGINE.request(req, log=self.log, cancel=self.cancel)

    def _wav_request(self, req: dict, model: str) -> bytes:
        with tempfile.TemporaryDirectory(prefix="tts_omni_") as td:
            wav, mp3 = str(Path(td) / "a.wav"), str(Path(td) / "a.mp3")
            self._ask({**req, "out": wav}, model)
            wav_to_mp3(wav, mp3)
            return Path(mp3).read_bytes()

    def clone_voice(self, sample_path, display_name, language="", denoise=False, ref_text: str = "",
                    model: str = "") -> str:
        """Encode the sample once into a reusable prompt. Empty ref_text = Whisper writes it."""
        voice_id = omni.new_voice_id()
        wav = omni.voice_wav(voice_id)
        self.log("🎚 Đang chuẩn bị file mẫu (WAV 24 kHz)…")
        to_wav(sample_path, str(wav))
        if not ref_text.strip():
            self.log("📝 Chưa có lời thoại của mẫu — OmniVoice tự chép lại bằng Whisper "
                     "(lần đầu phải tải model Whisper ~1,6 GB)…")
        try:
            res = self._ask({"cmd": "prompt", "audio": str(wav), "ref_text": ref_text.strip() or None,
                             "preprocess": bool(self.config.get("ov_preprocess_prompt", True)),
                             "out": str(omni.voice_prompt(voice_id))}, model)
        except BaseException:
            omni.delete_voice(voice_id)
            raise
        self.last_ref_text = res.get("ref_text") or ref_text.strip()
        return voice_id

    def transcribe(self, sample_path: str, model: str = "") -> str:
        with tempfile.TemporaryDirectory(prefix="tts_omni_") as td:
            wav = str(Path(td) / "ref.wav")
            to_wav(sample_path, wav)
            return self._ask({"cmd": "transcribe", "audio": wav}, model).get("text", "")

    def design(self, text: str, instruct: str, output_wav: str, *, language: str = "", model: str = "",
               options: dict | None = None) -> str:
        """Voice Design / Auto Voice: no reference, the engine invents a voice matching `instruct`."""
        self._ask(omni.tts_request(text, output_wav, language=language, instruct=instruct, options=options), model)
        return output_wav

    def synthesize(self, text, voice_id, output_path, *, model="", speed=1.0, language="", options=None) -> str:
        # a fixed duration applies to one request, so the text must not be split by the app then
        self.max_chars = 10 ** 9 if float((options or {}).get("duration") or 0) > 0 else type(self).max_chars
        return super().synthesize(text, voice_id, output_path, model=model, speed=speed, language=language,
                                  options=options)

    def synth_chunk(self, text, voice_id, *, model, speed, language, options=None) -> bytes:
        prompt = omni.voice_prompt(voice_id)
        if not prompt.is_file():
            raise ProviderError("Không tìm thấy dữ liệu của giọng OmniVoice này trên máy (đã bị xoá hoặc được tạo ở "
                                "máy khác) — hãy clone/thiết kế lại giọng.")
        lo, hi = SPEED_RANGE["OmniVoice"]
        req = omni.tts_request(text, "", language=language, prompt=str(prompt),
                               speed=max(lo, min(hi, float(speed or 1.0))), options=options)
        audio = self._wav_request(req, model)
        self.chars_used += len(text)
        return audio


# ---------------------------------------------------------------- factory
def build_provider(provider_name: str, secrets: dict, config: dict, log: LogFn = None,
                   cancel: CancelFn = None) -> BaseProvider:
    if provider_name == "OmniVoice":
        return OmniVoiceProvider(config, log=log, cancel=cancel)
    if provider_name != "Inworld":
        raise ProviderError(f"Nhà cung cấp “{provider_name}” không còn được hỗ trợ.")
    key = (secrets.get("inworld_api_key") or "").strip()
    if not key:
        raise ProviderError("Chưa nhập Inworld API key (mục ⚙ Cài đặt).")
    return InworldProvider(key, config.get("inworld_base_url", ""), log=log, cancel=cancel)
