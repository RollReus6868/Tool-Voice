from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

from app_info import APP_NAME, APP_VERSION

__all__ = ["APP_NAME", "APP_VERSION", "APP_DIR", "CONFIG_PATH", "VOICES_PATH", "LOG_PATH",
           "ConfigStore", "VoiceStore", "SecretStore"]

def _data_root() -> Path:
    if os.getenv("APPDATA"):
        return Path(os.environ["APPDATA"])          # Windows (and test override)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.getenv("XDG_CONFIG_HOME") or Path.home() / ".config")


APP_DIR = _data_root() / "TTSCloneStudio"
CONFIG_PATH = APP_DIR / "config.json"
VOICES_PATH = APP_DIR / "voices.json"
LOG_PATH = APP_DIR / "app.log"

_LOCK = threading.RLock()


def _ensure_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path, default: Any) -> Any:
    _ensure_dir()
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # Keep a copy of a corrupt file instead of silently losing it.
        try:
            path.replace(path.with_suffix(path.suffix + ".broken"))
        except Exception:
            pass
        return default


def _save_json(path: Path, data: Any) -> None:
    _ensure_dir()
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    temp.replace(path)


DEFAULT_OUTPUT = str(Path.home() / "Documents" / "TTS_Output")

DEFAULT_CONFIG = {
    "minimax_base_url": "https://api.minimax.io",
    "minimax_group_id": "",
    "inworld_base_url": "https://api.inworld.ai",
    "last_output_dir": DEFAULT_OUTPUT,
    "theme": "dark",
    "output_format": "mp3",          # mp3 | mp4 | both
    "video_size": "1920×1080 (Full HD ngang)",
    "video_image": "",
    "video_color": "#101828",
    "batch_threads": 2,
    "batch_skip_existing": True,
    "batch_merge_all": False,
    "window_geometry": "",
    "auto_update": True,
    "skip_version": "",
    "last_update_check": "",
    # 2.2
    "iw_delivery": "BALANCED",       # STABLE | BALANCED | CREATIVE
    "iw_enhance": False,             # enhanceGeneration (denoise)
    "iw_instruction": "",            # speaking-style instruction (inworld-tts-2)
    "inworld_auto_sync": True,       # add the user's own Inworld voices at start-up
    "batch_rows": "",                # row selection, e.g. "1-10, 15"
    "inworld_usage": None,           # see usage.py
    "defaults_rev": 0,
}

DEFAULTS_REV = 2


def migrate(data: dict) -> dict:
    """One-time changes to saved settings when the app's defaults change."""
    rev = int(data.get("defaults_rev") or 0)
    changes: dict = {}
    if rev < 2:
        # 2.2: the default Inworld model became inworld-tts-2-flash
        changes["model_Inworld"] = "inworld-tts-2-flash"
    if rev < DEFAULTS_REV:
        changes["defaults_rev"] = DEFAULTS_REV
    return changes


class ConfigStore:
    def load(self) -> dict:
        with _LOCK:
            data = DEFAULT_CONFIG.copy()
            loaded = _load_json(CONFIG_PATH, {})
            if isinstance(loaded, dict):
                data.update(loaded)
            return data

    def save(self, updates: dict) -> dict:
        with _LOCK:
            data = self.load()
            data.update(updates)
            _save_json(CONFIG_PATH, data)
            return data


class VoiceStore:
    def list(self) -> list[dict]:
        with _LOCK:
            voices = _load_json(VOICES_PATH, [])
            return [v for v in voices if isinstance(v, dict)] if isinstance(voices, list) else []

    def add(self, voice: dict) -> None:
        with _LOCK:
            voices = self.list()
            voices.append(voice)
            _save_json(VOICES_PATH, voices)

    def update(self, uid: str, changes: dict) -> None:
        with _LOCK:
            voices = self.list()
            for v in voices:
                if v.get("uid") == uid:
                    v.update(changes)
            _save_json(VOICES_PATH, voices)

    def remove(self, uid: str) -> None:
        with _LOCK:
            voices = [v for v in self.list() if v.get("uid") != uid]
            _save_json(VOICES_PATH, voices)

    def get(self, uid: str) -> dict | None:
        for voice in self.list():
            if voice.get("uid") == uid:
                return voice
        return None

    def exists(self, provider: str, voice_id: str) -> bool:
        return any(v.get("provider") == provider and v.get("provider_voice_id") == voice_id
                   for v in self.list())


class SecretStore:
    """API keys go to the OS credential store (Windows Credential Manager)
    via keyring. They are never written to config.json."""

    SERVICE = "TTSCloneStudio"
    ENV = {"minimax_api_key": "MINIMAX_API_KEY", "inworld_api_key": "INWORLD_API_KEY"}

    def __init__(self) -> None:
        self._memory: dict[str, str] = {}

    def get(self, name: str) -> str:
        if name in self._memory:
            return self._memory[name]
        env_value = os.getenv(self.ENV.get(name, name.upper()), "").strip()
        if env_value:
            return env_value
        try:
            import keyring
            return (keyring.get_password(self.SERVICE, name) or "").strip()
        except Exception:
            return ""

    def set(self, name: str, value: str) -> bool:
        value = (value or "").strip()
        self._memory[name] = value
        try:
            import keyring
            if value:
                keyring.set_password(self.SERVICE, name, value)
            else:
                try:
                    keyring.delete_password(self.SERVICE, name)
                except Exception:
                    pass
            return True
        except Exception:
            return False
