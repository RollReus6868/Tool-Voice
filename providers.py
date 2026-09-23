from __future__ import annotations

import base64
import binascii
import os
import tempfile
import time
from pathlib import Path
from typing import Callable

import requests

from media import merge_audio_files
from utils import slug_voice_id, split_text

LogFn = Callable[[str], None] | None
CancelFn = Callable[[], bool] | None

# ---------------------------------------------------------------- catalogues
PROVIDERS = ["Inworld", "MiniMax"]

MODELS = {
    "Inworld": ["inworld-tts-2", "inworld-tts-2-flash", "inworld-tts-1.5-max", "inworld-tts-1.5-mini"],
    "MiniMax": ["speech-2.8-hd", "speech-2.8-turbo", "speech-2.6-hd", "speech-2.6-turbo",
                "speech-02-hd", "speech-02-turbo"],
}

SPEED_RANGE = {"Inworld": (0.5, 1.5), "MiniMax": (0.5, 2.0)}

LANGUAGES = {
    # label, API value (Inworld = BCP-47 / empty = auto; MiniMax = language_boost)
    "Inworld": [
        ("Tự động nhận diện", ""), ("Tiếng Việt", "vi-VN"), ("English (US)", "en-US"),
        ("English (UK)", "en-GB"), ("中文 (Chinese)", "zh-CN"), ("日本語 (Japanese)", "ja-JP"),
        ("한국어 (Korean)", "ko-KR"), ("Español", "es-ES"), ("Français", "fr-FR"),
        ("Deutsch", "de-DE"), ("Português", "pt-BR"), ("Русский", "ru-RU"),
    ],
    "MiniMax": [
        ("Tự động nhận diện", "auto"), ("Tiếng Việt", "Vietnamese"), ("English", "English"),
        ("中文 (Chinese)", "Chinese"), ("日本語 (Japanese)", "Japanese"), ("한국어 (Korean)", "Korean"),
        ("ภาษาไทย (Thai)", "Thai"), ("Bahasa Indonesia", "Indonesian"), ("Español", "Spanish"),
        ("Français", "French"), ("Deutsch", "German"), ("Português", "Portuguese"), ("Русский", "Russian"),
    ],
}

_LEGACY_INWORLD = {"AUTO": "", "EN_US": "en-US", "VI_VN": "vi-VN", "ES_ES": "es-ES",
                   "ZH_CN": "zh-CN", "JA_JP": "ja-JP", "KO_KR": "ko-KR"}


def normalize_language(provider: str, value: str | None) -> str:
    value = (value or "").strip()
    if provider == "Inworld":
        return _LEGACY_INWORLD.get(value.upper(), value) if value else ""
    return value or "auto"


def language_label(provider: str, value: str | None) -> str:
    value = normalize_language(provider, value)
    for label, code in LANGUAGES.get(provider, []):
        if code == value:
            return label
    return value or "Tự động"


# ---------------------------------------------------------------- errors
class ProviderError(RuntimeError):
    pass


class CancelledError(ProviderError):
    pass


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

    def synth_chunk(self, text: str, voice_id: str, *, model: str, speed: float, language: str) -> bytes:
        raise NotImplementedError

    def list_voices(self) -> list[dict]:
        raise NotImplementedError

    def synthesize(self, text: str, voice_id: str, output_path: str, *, model: str,
                   speed: float = 1.0, language: str = "") -> str:
        chunks = split_text(text, self.max_chars)
        if not chunks:
            raise ProviderError("Nội dung văn bản trống.")
        with tempfile.TemporaryDirectory(prefix="tts_parts_") as td:
            parts: list[str] = []
            for index, chunk in enumerate(chunks, 1):
                self._check_cancel()
                if len(chunks) > 1:
                    self.log(f"   ↳ {self.name}: đoạn {index}/{len(chunks)} ({len(chunk)} ký tự)")
                audio = self.synth_chunk(chunk, voice_id, model=model, speed=speed, language=language)
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

    def synth_chunk(self, text, voice_id, *, model, speed, language) -> bytes:
        payload: dict = {
            "text": text,
            "voiceId": voice_id,
            "modelId": model or MODELS["Inworld"][0],
            "audioConfig": {"audioEncoding": "MP3", "sampleRateHertz": 44100},
        }
        lo, hi = SPEED_RANGE["Inworld"]
        speed = max(lo, min(hi, float(speed or 1.0)))
        if abs(speed - 1.0) > 1e-3:
            payload["audioConfig"]["speakingRate"] = round(speed, 2)
        lang = normalize_language("Inworld", language)
        if lang:
            payload["language"] = lang
        data = self._request("POST", f"{self.base_url}/tts/v1/voice",
                             headers=self.headers, json=payload, timeout=180)
        audio = data.get("audioContent") or (data.get("result") or {}).get("audioContent")
        if not audio:
            raise ProviderError(f"Inworld không trả audioContent: {str(data)[:300]}")
        return base64.b64decode(audio)

    def list_voices(self) -> list[dict]:
        data = self._request("GET", f"{self.base_url}/voices/v1/voices",
                             headers=self.headers, params={"pageSize": 2000}, timeout=60, retries=2)
        out = []
        for v in data.get("voices") or []:
            src = (v.get("source") or "").upper()
            out.append({
                "voice_id": v.get("voiceId", ""),
                "name": v.get("displayName") or v.get("voiceId", ""),
                "kind": "Hệ thống" if src == "SYSTEM" else "Của tôi",
                "language": v.get("languageCode") or _LEGACY_INWORLD.get(v.get("langCode", ""), v.get("langCode", "")),
            })
        return out


# ---------------------------------------------------------------- MiniMax
class MiniMaxProvider(BaseProvider):
    name = "MiniMax"
    max_chars = 5000  # API limit < 10,000; smaller chunks are more reliable

    RETRY_CODES = {1000, 1001, 1002, 1039}

    def __init__(self, api_key: str, base_url: str = "https://api.minimax.io", group_id: str = "",
                 log: LogFn = None, cancel: CancelFn = None) -> None:
        super().__init__(api_key, base_url or "https://api.minimax.io", log, cancel)
        self.group_id = (group_id or "").strip()
        if self.api_key.lower().startswith("bearer "):
            self.api_key = self.api_key[7:].strip()

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _params(self) -> dict | None:
        return {"GroupId": self.group_id} if self.group_id else None

    def _check_payload(self, data: dict) -> None:
        base = data.get("base_resp") or {}
        code = base.get("status_code", 0)
        if code in (0, None):
            return
        msg = base.get("status_msg", "")
        if code in self.RETRY_CODES:
            raise _Retryable(f"MiniMax bận/giới hạn tốc độ ({code}: {msg})")
        hints = {
            1004: "API key sai hoặc hết hạn",
            1008: "Tài khoản hết số dư",
            1026: "Nội dung bị bộ lọc an toàn chặn",
            1042: "Văn bản chứa quá nhiều ký tự không hợp lệ",
            2013: "Tham số không hợp lệ (kiểm tra Voice ID / model / ngôn ngữ)",
            2037: "Độ dài file mẫu không phù hợp",
            2038: "Tài khoản chưa được phép clone giọng",
            2039: "Voice ID đã tồn tại",
            2042: "Không có quyền dùng Voice ID này (có thể đã bị xóa do 7 ngày không dùng)",
        }
        hint = hints.get(code, "")
        raise ProviderError(f"MiniMax lỗi {code}: {msg}" + (f" — {hint}" if hint else ""))

    def clone_voice(self, sample_path, display_name, language="auto", denoise=False) -> str:
        self.log("📤 Đang upload mẫu giọng lên MiniMax…")
        with open(sample_path, "rb") as f:
            data = self._request(
                "POST", f"{self.base_url}/v1/files/upload", headers=self.headers, params=self._params(),
                files={"file": (os.path.basename(sample_path), f)}, data={"purpose": "voice_clone"},
                timeout=300, retries=1,
            )
        try:
            file_id = int(data["file"]["file_id"])
        except Exception as exc:
            raise ProviderError(f"MiniMax không trả file_id: {str(data)[:300]}") from exc

        voice_id = slug_voice_id(display_name)
        payload = {
            "file_id": file_id,
            "voice_id": voice_id,
            "need_noise_reduction": bool(denoise),
            "need_volume_normalization": True,
        }
        lang = normalize_language("MiniMax", language)
        if lang and lang != "auto":
            payload["language_boost"] = lang
        self.log(f"🧬 Đang tạo giọng MiniMax (voice_id={voice_id})…")
        self._request("POST", f"{self.base_url}/v1/voice_clone",
                      headers={**self.headers, "Content-Type": "application/json"},
                      params=self._params(), json=payload, timeout=300, retries=2)
        return voice_id

    def synth_chunk(self, text, voice_id, *, model, speed, language) -> bytes:
        lo, hi = SPEED_RANGE["MiniMax"]
        payload = {
            "model": model or MODELS["MiniMax"][0],
            "text": text,
            "stream": False,
            "voice_setting": {"voice_id": voice_id, "speed": round(max(lo, min(hi, float(speed or 1.0))), 2),
                              "vol": 1.0, "pitch": 0},
            "audio_setting": {"sample_rate": 44100, "bitrate": 128000, "format": "mp3", "channel": 1},
            "language_boost": normalize_language("MiniMax", language),
            "output_format": "hex",
        }
        data = self._request("POST", f"{self.base_url}/v1/t2a_v2",
                             headers={**self.headers, "Content-Type": "application/json"},
                             params=self._params(), json=payload, timeout=300)
        audio = (data.get("data") or {}).get("audio")
        if not audio:
            raise ProviderError(f"MiniMax không trả audio: {str(data)[:300]}")
        if isinstance(audio, str) and audio.startswith(("http://", "https://")):
            return self._request("GET", audio, timeout=180, json_body=False).content
        try:
            return binascii.unhexlify(audio)
        except (binascii.Error, TypeError) as exc:
            raise ProviderError("Audio MiniMax trả về không hợp lệ.") from exc

    def list_voices(self) -> list[dict]:
        data = self._request("POST", f"{self.base_url}/v1/get_voice",
                             headers={**self.headers, "Content-Type": "application/json"},
                             params=self._params(), json={"voice_type": "all"}, timeout=60, retries=2)
        out = []
        for key, kind in (("voice_cloning", "Của tôi"), ("voice_generation", "Của tôi"), ("system_voice", "Hệ thống")):
            for v in data.get(key) or []:
                desc = v.get("description") or []
                out.append({
                    "voice_id": v.get("voice_id", ""),
                    "name": v.get("voice_name") or v.get("voice_id", ""),
                    "kind": kind,
                    "language": (desc[0] if isinstance(desc, list) and desc else "")[:40],
                })
        return out


# ---------------------------------------------------------------- factory
def build_provider(provider_name: str, secrets: dict, config: dict, log: LogFn = None,
                   cancel: CancelFn = None) -> BaseProvider:
    if provider_name == "Inworld":
        key = (secrets.get("inworld_api_key") or "").strip()
        if not key:
            raise ProviderError("Chưa nhập Inworld API key (mục ⚙ Cài đặt).")
        return InworldProvider(key, config.get("inworld_base_url", ""), log=log, cancel=cancel)
    key = (secrets.get("minimax_api_key") or "").strip()
    if not key:
        raise ProviderError("Chưa nhập MiniMax API key (mục ⚙ Cài đặt).")
    return MiniMaxProvider(key, config.get("minimax_base_url", ""), config.get("minimax_group_id", ""),
                           log=log, cancel=cancel)
