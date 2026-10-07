"""OmniVoice (k2-fsa, Apache-2.0) on this computer — free, no API key.

torch + the model weigh several GB, so they are NOT shipped inside the app.
The app installs them once, on request, into  <data dir>/omni/ :

    tools/uv(.exe)   the uv installer, taken from PyPI and checked by SHA-256
    python/          a private Python (downloaded by uv)
    env/             virtual environment: torch, torchaudio, omnivoice
    models/          HuggingFace cache (model weights; Whisper when it is needed)
    voices/          <voice id>.pt = saved voice-clone prompt, <voice id>.wav = its reference audio
    install.json     written last; its presence means "installed"

The engine itself is engine/omni_server.py, run by env's Python and driven over
JSON lines (see that file). No Qt in this module so it can be unit tested.
"""
from __future__ import annotations

import atexit
import functools
import hashlib
import json
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from collections import deque
from pathlib import Path
from typing import Callable

from storage import APP_DIR

DEFAULT_MODEL = "k2-fsa/OmniVoice"
OMNIVOICE_VERSION = "0.2.1"
TORCH_VERSION = "2.8.0"
PYTHON_VERSION = "3.12"
UV_VERSION = "0.12.23"

ROOT = APP_DIR / "omni"
ENV_DIR = ROOT / "env"
MODELS_DIR = ROOT / "models"
VOICES_DIR = ROOT / "voices"
TOOLS_DIR = ROOT / "tools"
MARKER = ROOT / "install.json"

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
LogFn = Callable[[str], None] | None
CancelFn = Callable[[], bool] | None


class ProviderError(RuntimeError):
    pass


class CancelledError(ProviderError):
    pass


def resource(rel: str) -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / rel


def server_script() -> Path:
    return resource("engine/omni_server.py")


# ---------------------------------------------------------------- catalogues (mirror OmniVoice 0.2.1)
_COMMON_LANGS = [("Tiếng Việt", "vi"), ("English", "en"), ("中文 (Chinese)", "zh"), ("日本語 (Japanese)", "ja"),
                 ("한국어 (Korean)", "ko"), ("ภาษาไทย (Thai)", "th"), ("Bahasa Indonesia", "id"), ("Español", "es"),
                 ("Français", "fr"), ("Deutsch", "de"), ("Português", "pt"), ("Русский", "ru")]


def languages() -> list[tuple[str, str]]:
    """(label, OmniVoice language id). '' = let the model detect. 600+ entries, common ones first."""
    out = [("Tự động nhận diện", "")] + list(_COMMON_LANGS)
    seen = {code for _label, code in out}
    rest = []
    try:
        for line in resource("assets/omni_langs.tsv").read_text(encoding="utf-8").splitlines():
            code, _, name = line.partition("\t")
            if code and name and code not in seen:
                rest.append((f"{name} ({code})", code))
    except OSError:
        pass
    return out + sorted(rest, key=lambda x: x[0].lower())


# Voice Design: one choice per category, joined with ", " into `instruct`.
# Accents only affect English text, dialects only Chinese text.
DESIGN = [
    ("gender", "👤 Giới tính", [("male", "Nam"), ("female", "Nữ")]),
    ("age", "🎂 Độ tuổi", [("child", "Trẻ em"), ("teenager", "Thiếu niên"), ("young adult", "Thanh niên"),
                           ("middle-aged", "Trung niên"), ("elderly", "Cao tuổi")]),
    ("pitch", "🎵 Cao độ", [("very low pitch", "Rất trầm"), ("low pitch", "Trầm"), ("moderate pitch", "Vừa"),
                            ("high pitch", "Cao"), ("very high pitch", "Rất cao")]),
    ("style", "🤫 Phong cách", [("whisper", "Thì thầm")]),
    ("accent", "🇬🇧 Giọng tiếng Anh", [
        ("american accent", "Mỹ"), ("british accent", "Anh"), ("australian accent", "Úc"),
        ("canadian accent", "Canada"), ("indian accent", "Ấn Độ"), ("chinese accent", "Trung Quốc"),
        ("korean accent", "Hàn Quốc"), ("japanese accent", "Nhật"), ("portuguese accent", "Bồ Đào Nha"),
        ("russian accent", "Nga")]),
    ("dialect", "🇨🇳 Phương ngữ Trung", [
        ("河南话", "Hà Nam"), ("陕西话", "Thiểm Tây"), ("四川话", "Tứ Xuyên"), ("贵州话", "Quý Châu"),
        ("云南话", "Vân Nam"), ("桂林话", "Quế Lâm"), ("济南话", "Tế Nam"), ("石家庄话", "Thạch Gia Trang"),
        ("甘肃话", "Cam Túc"), ("宁夏话", "Ninh Hạ"), ("青岛话", "Thanh Đảo"), ("东北话", "Đông Bắc")]),
]


# the Chinese spelling OmniVoice also accepts for the first four categories
_DESIGN_ZH = [["男", "女"], ["儿童", "少年", "青年", "中年", "老年"],
              ["极低音调", "低音调", "中音调", "高音调", "极高音调"], ["耳语"], [], []]


def build_instruct(values) -> str:
    return ", ".join(v.strip() for v in values if v and v.strip())


def check_instruct(text: str) -> str:
    """'' when OmniVoice will accept this instruct, otherwise what is wrong (it rejects
    unknown words, two choices of one category, and an English accent together with a Chinese dialect)."""
    items = [x.strip().lower() for x in re.split(r"[,，]", text or "") if x.strip()]
    seen: dict[str, str] = {}
    for item in items:
        cat = next((key for (key, _t, options), zh in zip(DESIGN, _DESIGN_ZH)
                    if item in [v for v, _vn in options] or item in zh), None)
        if cat is None:
            valid = ", ".join(v for _k, _t, options in DESIGN[:5] for v, _vn in options)
            return f"OmniVoice không hiểu “{item}”. Chỉ dùng các từ khoá: {valid}, hoặc tên phương ngữ tiếng Trung."
        if cat in seen:
            return f"“{seen[cat]}” và “{item}” cùng một nhóm — mỗi nhóm chỉ chọn một."
        seen[cat] = item
    if "accent" in seen and "dialect" in seen:
        return "Không dùng chung giọng tiếng Anh và phương ngữ tiếng Trung trong một giọng."
    return ""


NONVERBAL_TAGS = [
    ("[laughter]", "Cười"), ("[sigh]", "Thở dài"), ("[confirmation-en]", "Ừ, xác nhận"),
    ("[question-en]", "Hả? (kiểu Anh)"), ("[question-ah]", "A?"), ("[question-oh]", "Ồ?"),
    ("[question-ei]", "Ê?"), ("[question-yi]", "Ý?"), ("[surprise-ah]", "A! ngạc nhiên"),
    ("[surprise-oh]", "Ồ! ngạc nhiên"), ("[surprise-wa]", "Oa!"), ("[surprise-yo]", "Yo!"),
    ("[dissatisfaction-hnn]", "Hừm, không hài lòng"),
]

# OmniVoiceGenerationConfig defaults. Saved in config.json as "ov_<name>".
GEN_DEFAULTS = {
    "num_step": 32, "guidance_scale": 2.0, "denoise": True, "t_shift": 0.1,
    "position_temperature": 5.0, "class_temperature": 0.0, "layer_penalty_factor": 5.0,
    "preprocess_prompt": True, "postprocess_output": True, "pad_duration": 0.1, "fade_duration": 0.1,
    "audio_chunk_duration": 15.0, "audio_chunk_threshold": 30.0,
}
EXTRA_DEFAULTS = {"duration": 0.0, "normalize_text": False}      # generate() arguments, not config fields
ALL_DEFAULTS = {**GEN_DEFAULTS, **EXTRA_DEFAULTS}


def gen_options(config: dict) -> dict:
    """Generation settings from the app config, typed like their defaults."""
    out = {}
    for key, default in ALL_DEFAULTS.items():
        value = config.get(f"ov_{key}", default)
        try:
            out[key] = type(default)(value) if value is not None else default
        except (TypeError, ValueError):
            out[key] = default
    return out


def tts_request(text: str, out: str, *, language: str = "", prompt: str = "", instruct: str | None = None,
                speed: float | None = None, options: dict | None = None) -> dict:
    o = options or {}
    req: dict = {
        "cmd": "tts", "text": text, "out": out, "language": (language or "").strip() or None,
        "prompt": prompt or None,
        "instruct": ((o.get("instruct") if instruct is None else instruct) or "").strip() or None,
        "normalize_text": bool(o.get("normalize_text")),
        "config": {k: o[k] for k in GEN_DEFAULTS if k in o},
    }
    duration = float(o.get("duration") or 0)
    if duration > 0:
        req["duration"] = duration                      # overrides speed, like model.generate()
    elif speed and abs(float(speed) - 1.0) > 1e-3:
        req["speed"] = round(float(speed), 2)
    return req


# ---------------------------------------------------------------- voices on disk
def new_voice_id() -> str:
    return "ov_" + uuid.uuid4().hex[:10]


def _voice_file(voice_id: str, ext: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", voice_id or ""):
        raise ProviderError("Voice ID OmniVoice không hợp lệ.")
    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    return VOICES_DIR / f"{voice_id}{ext}"


def voice_prompt(voice_id: str) -> Path:
    return _voice_file(voice_id, ".pt")


def voice_wav(voice_id: str) -> Path:
    return _voice_file(voice_id, ".wav")


def delete_voice(voice_id: str) -> None:
    for ext in (".pt", ".wav"):
        try:
            _voice_file(voice_id, ext).unlink(missing_ok=True)
        except (OSError, ProviderError):
            pass


# ---------------------------------------------------------------- install state
def fake_mode() -> bool:
    return bool(os.getenv("TTS_OMNI_FAKE"))


def env_python() -> Path:
    return ENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def is_installed() -> bool:
    return fake_mode() or (MARKER.is_file() and env_python().is_file())


def install_info() -> dict:
    try:
        return json.loads(MARKER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def unsupported_reason() -> str:
    """Empty when this computer can run OmniVoice."""
    if fake_mode():
        return ""
    if sys.platform == "darwin" and platform.machine().lower() in ("x86_64", "amd64", "i386"):
        return ("OmniVoice cần PyTorch ≥ 2.4, mà PyTorch không còn phát hành cho máy Mac chip Intel. "
                "Hãy dùng máy Mac chip Apple (M1 trở lên) hoặc Windows.")
    return ""


@functools.lru_cache(maxsize=1)
def has_nvidia() -> bool:
    exe = shutil.which("nvidia-smi")
    if not exe and os.name == "nt":
        cand = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe"
        exe = str(cand) if cand.is_file() else None
    if not exe:
        return False
    try:
        p = subprocess.run([exe, "-L"], capture_output=True, text=True, timeout=15, creationflags=_NO_WINDOW)
        return p.returncode == 0 and "GPU" in p.stdout
    except (OSError, subprocess.SubprocessError):
        return False


HARDWARE = [("auto", "Tự động (khuyên dùng)"), ("cuda", "GPU NVIDIA (CUDA 12.8)"), ("cpu", "Chỉ CPU")]


def torch_plan(hardware: str = "auto") -> dict:
    """Which PyTorch build to install: {"key", "label", "specs", "index", "gb"} (gb = free disk wanted)."""
    pair = lambda suffix: [f"torch=={TORCH_VERSION}{suffix}", f"torchaudio=={TORCH_VERSION}{suffix}"]  # noqa: E731
    if sys.platform == "darwin":
        return {"key": "mps", "label": "GPU Apple Silicon (MPS)", "specs": pair(""), "index": "", "gb": 8}
    if hardware == "cuda" or (hardware == "auto" and has_nvidia()):
        return {"key": "cuda", "label": "GPU NVIDIA (CUDA 12.8)", "specs": pair("+cu128"),
                "index": "https://download.pytorch.org/whl/cu128", "gb": 14}
    # PyPI's own Windows build of torch is the CPU one, so no extra index is needed
    return {"key": "cpu", "label": "CPU", "specs": pair(""), "index": "", "gb": 8}


def child_env(extra: dict | None = None) -> dict:
    """Environment for uv / the engine: nothing leaking from the frozen app, everything inside ROOT."""
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(("_PYI", "_MEI")) or key in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP",
                                                       "QT_QPA_PLATFORM", "QT_PLUGIN_PATH"):
            env.pop(key)
    if getattr(sys, "frozen", False):
        for var in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):     # PyInstaller keeps the original in *_ORIG
            orig = env.pop(var + "_ORIG", None)
            env.pop(var, None)
            if orig:
                env[var] = orig
    env.update({
        "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1",
        "HF_HOME": str(MODELS_DIR), "HF_HUB_DISABLE_SYMLINKS_WARNING": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "UV_PYTHON_INSTALL_DIR": str(ROOT / "python"), "UV_CACHE_DIR": str(ROOT / "cache"),
        "UV_HTTP_TIMEOUT": "600",
    })
    env.update(extra or {})
    return env


_SPAWN_LOCK = threading.Lock()


def popen(cmd: list[str], **kw) -> subprocess.Popen:
    """Start an external program. A frozen Windows app points the DLL search path at its own
    folder and children inherit that: reset it for the spawn so the other Python loads its own DLLs."""
    kw.setdefault("creationflags", _NO_WINDOW)
    meipass = getattr(sys, "_MEIPASS", None)
    if os.name != "nt" or not meipass:
        return subprocess.Popen(cmd, **kw)
    import ctypes

    with _SPAWN_LOCK:
        ctypes.windll.kernel32.SetDllDirectoryW(None)
        try:
            return subprocess.Popen(cmd, **kw)
        finally:
            ctypes.windll.kernel32.SetDllDirectoryW(meipass)


# ---------------------------------------------------------------- installer
def uv_path() -> Path:
    return TOOLS_DIR / ("uv.exe" if os.name == "nt" else "uv")


def uv_wheel_tag() -> str:
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if os.name == "nt":
        return "win_arm64" if arm else "win_amd64"
    if sys.platform == "darwin":
        return "macosx_11_0_arm64" if arm else "macosx_10_12_x86_64"
    return "manylinux_2_28_aarch64" if arm else "manylinux_2_17_x86_64"


def pick_uv_wheel(meta: dict, tag: str) -> dict:
    for item in meta.get("urls") or []:
        name = item.get("filename", "")
        if name.endswith(".whl") and f"-none-{tag}" in name:
            return item
    raise ProviderError(f"Không tìm thấy bản uv {UV_VERSION} cho máy này ({tag}).")


def ensure_uv(log: LogFn = None, cancelled: CancelFn = None) -> Path:
    """uv = one small program that downloads Python and installs packages (the app has no pip of its own)."""
    exe = uv_path()
    if exe.is_file():
        return exe
    import requests

    log = log or (lambda _m: None)
    log(f"⬇ Đang tải trình cài đặt uv {UV_VERSION} từ PyPI…")
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    whl = TOOLS_DIR / "uv.whl"
    try:
        with requests.Session() as s:
            r = s.get(f"https://pypi.org/pypi/uv/{UV_VERSION}/json", timeout=60)
            r.raise_for_status()
            item = pick_uv_wheel(r.json(), uv_wheel_tag())
            digest = hashlib.sha256()
            with s.get(item["url"], stream=True, timeout=120) as resp, open(whl, "wb") as f:
                resp.raise_for_status()
                for chunk in resp.iter_content(1 << 18):
                    if cancelled and cancelled():
                        raise CancelledError("Đã dừng theo yêu cầu.")
                    f.write(chunk)
                    digest.update(chunk)
        if digest.hexdigest() != item["digests"]["sha256"]:
            raise ProviderError("File uv tải về không khớp mã SHA-256 — hãy thử lại.")
        with zipfile.ZipFile(whl) as z:
            member = next((n for n in z.namelist() if n.endswith(("/scripts/uv.exe", "/scripts/uv"))), None)
            if not member:
                raise ProviderError("Gói uv tải về không chứa chương trình uv.")
            tmp = exe.with_suffix(exe.suffix + ".part")
            with z.open(member) as src, open(tmp, "wb") as dst:
                shutil.copyfileobj(src, dst)
            os.chmod(tmp, 0o755)
            os.replace(tmp, exe)
    except requests.RequestException as exc:
        raise ProviderError(f"Không tải được uv từ PyPI ({exc.__class__.__name__}) — kiểm tra kết nối Internet.") from exc
    finally:
        whl.unlink(missing_ok=True)
    return exe


def _run_step(cmd: list[str], log: Callable[[str], None], cancelled: CancelFn, what: str) -> str:
    """Run one installer command, stream its output to the log, return the output."""
    proc = popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                 env=child_env(), cwd=str(ROOT))
    lines: deque = deque(maxlen=25)

    def reader():
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if line:
                lines.append(line)
                log("   " + line[:300])

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    try:
        while proc.poll() is None:
            if cancelled and cancelled():
                raise CancelledError("Đã dừng cài đặt.")
            time.sleep(0.2)
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        t.join(5)
        proc.stdout.close()
    if proc.returncode != 0:
        raise ProviderError(f"{what} thất bại (mã {proc.returncode}):\n" + "\n".join(list(lines)[-8:]))
    return "\n".join(lines)


def install_commands(uv: str, plan: dict, python: str = "") -> list[tuple[str, list[str]]]:
    """(description, command) for each step after uv itself is in place."""
    py = str(env_python())
    venv = [uv, "venv", "--python", python or PYTHON_VERSION]
    if not python:
        venv.append("--managed-python")      # always uv's own Python, never whatever is on the PC
    torch = [uv, "pip", "install", "--python", py, *plan["specs"]]
    if plan["index"]:
        # both indexes are searched; the pinned +cu128 build can only come from pytorch.org
        torch += ["--extra-index-url", plan["index"], "--index-strategy", "unsafe-best-match"]
    return [
        (f"Tạo môi trường Python {python or PYTHON_VERSION} riêng cho OmniVoice", venv + [str(ENV_DIR)]),
        (f"Cài PyTorch {TORCH_VERSION} cho {plan['label']} (file lớn, có thể mất 5–30 phút)", torch),
        (f"Cài OmniVoice {OMNIVOICE_VERSION}",
         [uv, "pip", "install", "--python", py, f"omnivoice=={OMNIVOICE_VERSION}", "num2words"]),
    ]


_VERIFY = ("import json, torch, omnivoice; "
           "print('OMNI_OK ' + json.dumps({'omnivoice': omnivoice.__version__, 'torch': torch.__version__, "
           "'cuda': bool(torch.cuda.is_available()), "
           "'gpu': torch.cuda.get_device_name(0) if torch.cuda.is_available() else ''}))")


def install(log: Callable[[str], None], cancelled: CancelFn = None, progress: Callable[[int], None] | None = None,
            hardware: str = "auto") -> dict:
    """Download and install everything. Safe to run again (starts from a clean env)."""
    reason = unsupported_reason()
    if reason:
        raise ProviderError(reason)
    progress = progress or (lambda _v: None)
    ENGINE.stop()
    ROOT.mkdir(parents=True, exist_ok=True)
    plan = torch_plan(hardware)
    free_gb = shutil.disk_usage(ROOT).free / 1024 ** 3
    if free_gb < plan["gb"]:
        raise ProviderError(f"Ổ đĩa chứa {ROOT} chỉ còn {free_gb:.1f} GB trống — cần khoảng {plan['gb']} GB "
                            "cho PyTorch, OmniVoice và model.")
    log(f"🧩 Cài OmniVoice cho {plan['label']} vào {ROOT} (còn {free_gb:.0f} GB trống).")
    MARKER.unlink(missing_ok=True)
    progress(3)
    uv = str(ensure_uv(log, cancelled))
    shutil.rmtree(ENV_DIR, ignore_errors=True)
    steps = install_commands(uv, plan, os.getenv("TTS_OMNI_PYTHON", ""))
    marks = [10, 20, 75, 92]
    for i, (what, cmd) in enumerate(steps):
        progress(marks[i])
        log(f"🧩 Bước {i + 1}/{len(steps) + 1}: {what}…")
        _run_step(cmd, log, cancelled, what)
    progress(marks[-1])
    log(f"🧩 Bước {len(steps) + 1}/{len(steps) + 1}: Kiểm tra bộ máy…")
    out = _run_step([str(env_python()), "-W", "ignore", "-c", _VERIFY], log, cancelled, "Kiểm tra bộ máy")
    m = re.search(r"OMNI_OK (\{.*\})", out)
    if not m:
        raise ProviderError("Bộ máy đã cài nhưng không chạy thử được:\n" + out[-600:])
    info = json.loads(m.group(1))
    info.update(plan=plan["key"], label=plan["label"], at=time.strftime("%Y-%m-%d %H:%M"))
    if plan["key"] == "cuda" and not info["cuda"]:
        log("⚠ Đã cài bản CUDA nhưng PyTorch không thấy GPU — cập nhật driver NVIDIA; tạm thời sẽ chạy bằng CPU.")
    MARKER.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.rmtree(ROOT / "cache", ignore_errors=True)     # packages are in env/ now
    progress(100)
    return info


def uninstall(keep_models: bool = False) -> None:
    """Remove the engine (and the downloaded models). Saved voices stay."""
    ENGINE.stop()
    MARKER.unlink(missing_ok=True)
    for name in ("env", "python", "cache", "tools") + (() if keep_models else ("models",)):
        shutil.rmtree(ROOT / name, ignore_errors=True)


# ---------------------------------------------------------------- engine process
_BAR = re.compile(r"\|[^|]*\|")


def friendly_error(text: str) -> str:
    low = text.lower()
    if "out of memory" in low:
        return ("Hết bộ nhớ GPU/RAM khi tạo giọng. Đóng bớt chương trình khác, giảm “Độ dài mỗi đoạn” "
                "ở trang OmniVoice hoặc dùng mẫu giọng ngắn hơn (3–10 giây). Chi tiết: " + text[:200])
    if any(k in low for k in ("connectionerror", "connecterror", "proxyerror", "maxretryerror", "localentrynotfound",
                              "offline", "name resolution", "timed out", "couldn't connect", "could not connect")):
        return ("Không tải được model từ HuggingFace — kiểm tra kết nối Internet rồi thử lại "
                "(model chỉ cần tải một lần). Chi tiết: " + text[:200])
    return text


class Engine:
    """One background engine process, shared by the whole app. Requests run one at a time
    (the GPU cannot do two at once anyway); the model stays loaded between them."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._q: queue.Queue = queue.Queue()
        self._tail: deque = deque(maxlen=30)
        self._log: Callable[[str], None] = lambda _m: None
        self._last_progress = 0.0
        self._threads: list[threading.Thread] = []
        self.device = ""            # filled by the first "load"
        self.model = ""

    # -- process
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def command(self) -> list[str]:
        py = sys.executable if fake_mode() and not getattr(sys, "frozen", False) else str(env_python())
        return [py, "-u", "-W", "ignore", str(server_script())]

    def _start(self) -> None:
        if not is_installed():
            raise ProviderError("Chưa cài bộ máy OmniVoice — mở trang 🌍 OmniVoice và bấm “Cài đặt bộ máy”.")
        self._log("⏳ Đang khởi động bộ máy OmniVoice…")
        self._q = queue.Queue()
        self._tail.clear()
        ROOT.mkdir(parents=True, exist_ok=True)
        try:
            self._proc = popen(self.command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env=child_env(), cwd=str(ROOT))
        except OSError as exc:
            raise ProviderError(f"Không khởi động được bộ máy OmniVoice: {exc}") from exc
        self._threads = [threading.Thread(target=self._read_out, args=(self._proc, self._q), daemon=True),
                         threading.Thread(target=self._read_err, args=(self._proc,), daemon=True)]
        for t in self._threads:
            t.start()

    @staticmethod
    def _read_out(proc: subprocess.Popen, q: queue.Queue) -> None:
        for raw in proc.stdout:
            try:
                q.put(json.loads(raw.decode("utf-8", "replace")))
            except ValueError:
                pass
        q.put(None)

    def _read_err(self, proc: subprocess.Popen) -> None:
        buf = b""
        while True:
            chunk = proc.stderr.read1(4096)
            if not chunk:
                break
            buf += chunk
            *lines, buf = re.split(rb"[\r\n]", buf)
            for raw in lines:
                self._stderr_line(raw.decode("utf-8", "replace").strip())
        self._stderr_line(buf.decode("utf-8", "replace").strip())

    def _stderr_line(self, line: str) -> None:
        if not line:
            return
        if "%|" in line:                      # download progress bar: at most one line every 3 s
            now = time.time()
            if now - self._last_progress >= 3:
                self._last_progress = now
                self._log("   ⬇ " + _BAR.sub(" ", line)[:200])
            return
        self._tail.append(line)

    def _died(self) -> ProviderError:
        self.stop()                           # reap it and let the stderr reader finish first
        tail = "\n".join(list(self._tail)[-6:])
        return ProviderError(friendly_error("Bộ máy OmniVoice dừng đột ngột.\n" + tail))

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        self.device = ""
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.kill()
            proc.wait(10)
        except (OSError, subprocess.SubprocessError):
            pass
        for t in self._threads:              # the readers end at EOF; close the pipes only after them
            t.join(3)
        for pipe in (proc.stdin, proc.stdout, proc.stderr):
            try:
                pipe.close()
            except (OSError, ValueError):
                pass

    # -- requests
    def request(self, req: dict, log: LogFn = None, cancel: CancelFn = None) -> dict:
        cancel = cancel or (lambda: False)
        while not self._lock.acquire(timeout=0.2):       # another row is being read: wait, but stay stoppable
            if cancel():
                raise CancelledError("Đã dừng theo yêu cầu.")
        try:
            if cancel():
                raise CancelledError("Đã dừng theo yêu cầu.")
            self._log = log or (lambda _m: None)
            if not self.running():
                self._start()
            proc, q = self._proc, self._q
            try:
                proc.stdin.write((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
                proc.stdin.flush()
            except (OSError, ValueError) as exc:
                raise self._died() from exc
            while True:
                try:
                    msg = q.get(timeout=0.2)
                except queue.Empty:
                    if cancel():
                        self.stop()          # the only way to interrupt a generation; the model reloads next time
                        raise CancelledError("Đã dừng theo yêu cầu.")
                    continue
                if msg is None:
                    raise self._died()
                if "event" in msg:
                    self._log(str(msg.get("text", "")))
                    continue
                if msg.get("ok"):
                    if req.get("cmd") in ("load", "tts", "prompt", "transcribe"):
                        self.model = req.get("model", "")
                    if msg.get("device"):
                        self.device = msg["device"]
                    return msg
                raise ProviderError(friendly_error(str(msg.get("error") or "Bộ máy OmniVoice báo lỗi.")))
        finally:
            self._log = lambda _m: None
            self._lock.release()


ENGINE = Engine()
atexit.register(ENGINE.stop)      # never leave the engine (and its GPU memory) behind
