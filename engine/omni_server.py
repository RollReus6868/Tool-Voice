"""OmniVoice engine process for TTS Clone Studio.

Runs with the Python of the engine environment (torch + omnivoice), NOT inside
the app. The app (omni.py) starts it, writes one JSON request per line on stdin
and reads JSON lines from stdout:

    {"event": "log", "text": "..."}        progress, any number of them
    {"ok": true, ...} / {"ok": false, "error": "..."}   exactly one, ends the request

Requests ("model" = HuggingFace repo id or a local checkpoint folder, loaded on first use):
    {"cmd": "hello"}
    {"cmd": "load", "model": m}
    {"cmd": "prompt", "model": m, "audio": wav, "ref_text": str|null, "preprocess": bool, "out": file}
    {"cmd": "transcribe", "model": m, "audio": wav}
    {"cmd": "tts", "model": m, "text": str, "out": wav, "language": str|null, "prompt": file|null,
     "instruct": str|null, "speed": float?, "duration": float?, "normalize_text": bool, "config": {...}}

Only the standard library is imported at the top, so TTS_OMNI_FAKE=1 (tests, CI)
works with any Python: it writes a tone instead of speech and echoes the request.
"""
from __future__ import annotations

import json
import math
import os
import struct
import sys
import traceback
import wave

PROTO = sys.stdout.buffer
sys.stdout = sys.stderr          # stray prints from libraries must not corrupt the protocol
FAKE = bool(os.environ.get("TTS_OMNI_FAKE"))

STATE: dict = {"model": None, "name": None, "device": None, "prompts": {}}


def send(obj: dict) -> None:
    PROTO.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
    PROTO.flush()


def say(text: str) -> None:
    send({"event": "log", "text": text})


# ---------------------------------------------------------------- real engine
def pick_device(torch) -> str:
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch, "xpu") and torch.xpu.is_available():
        return "xpu"
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def device_label(torch, device: str) -> str:
    if device == "cuda":
        try:
            return f"GPU {torch.cuda.get_device_name(0)}"
        except Exception:  # noqa: BLE001
            return "GPU NVIDIA"
    return {"mps": "GPU Apple Silicon", "xpu": "GPU Intel Arc", "cpu": "CPU (chậm hơn GPU nhiều lần)"}[device]


def ensure_model(name: str):
    name = name or "k2-fsa/OmniVoice"
    if STATE["model"] is not None and STATE["name"] == name:
        return STATE["model"]
    import torch
    from omnivoice import OmniVoice

    device = pick_device(torch)
    say(f"🧠 Đang nạp model {name} lên {device_label(torch, device)} — lần đầu phải tải model về máy (vài GB), "
        "các lần sau chỉ mất ít giây…")
    STATE["model"] = None        # free the previous checkpoint first
    STATE["prompts"].clear()
    dtype = torch.float32 if device == "cpu" else torch.float16
    model = OmniVoice.from_pretrained(name, device_map=device, dtype=dtype)
    STATE.update(model=model, name=name, device=device_label(torch, device))
    say(f"✅ Model đã sẵn sàng trên {STATE['device']}.")
    return model


def load_prompt(path: str):
    from omnivoice import VoiceClonePrompt

    key = (path, os.path.getmtime(path))
    cache = STATE["prompts"]
    if key not in cache:
        if len(cache) > 16:
            cache.clear()
        cache[key] = VoiceClonePrompt.load(path)
    return cache[key]


def do_prompt(req: dict) -> dict:
    model = ensure_model(req.get("model"))
    ref_text = (req.get("ref_text") or "").strip() or None
    if ref_text is None:
        say("📝 Đang chép lời thoại của mẫu bằng Whisper…")
    prompt = model.create_voice_clone_prompt(ref_audio=req["audio"], ref_text=ref_text,
                                             preprocess_prompt=bool(req.get("preprocess", True)))
    prompt.save(req["out"])
    return {"ref_text": prompt.ref_text}


def do_transcribe(req: dict) -> dict:
    model = ensure_model(req.get("model"))
    if getattr(model, "_asr_pipe", None) is None:
        say("📝 Đang nạp Whisper (lần đầu phải tải ~1,6 GB)…")
        model.load_asr_model()
    # pass samples, not the path: with a path the Whisper pipeline needs an ffmpeg program on PATH
    from omnivoice.utils.audio import load_audio

    return {"text": model.transcribe((load_audio(req["audio"], model.sampling_rate), model.sampling_rate))}


def do_tts(req: dict) -> dict:
    import soundfile as sf
    from omnivoice import OmniVoiceGenerationConfig

    model = ensure_model(req.get("model"))
    kw: dict = {"text": req["text"], "language": req.get("language") or None,
                "generation_config": OmniVoiceGenerationConfig.from_dict(req.get("config") or {})}
    if req.get("prompt"):
        kw["voice_clone_prompt"] = load_prompt(req["prompt"])
    if req.get("instruct"):
        kw["instruct"] = req["instruct"]
    if req.get("duration"):
        kw["duration"] = float(req["duration"])
    elif req.get("speed"):
        kw["speed"] = float(req["speed"])
    if req.get("normalize_text"):
        try:
            audio = model.generate(normalize_text=True, **kw)
        except ImportError:
            say("⚠ Chuẩn hoá số cho tiếng Anh/Trung cần gói WeTextProcessing (chưa cài) — đọc nguyên văn.")
            audio = model.generate(**kw)
    else:
        audio = model.generate(**kw)
    sf.write(req["out"], audio[0], model.sampling_rate)
    return {"seconds": round(len(audio[0]) / float(model.sampling_rate), 3)}


# ---------------------------------------------------------------- fake engine (tests)
def fake_wav(path: str, seconds: float) -> None:
    rate = 24000
    n = int(rate * seconds)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(9000 * math.sin(2 * math.pi * 330 * i / rate)))
                               for i in range(n)))


def fake(req: dict) -> dict:
    cmd = req["cmd"]
    if cmd == "load":
        say("🧠 (giả lập) nạp model")
        return {"device": "giả lập"}
    if cmd == "prompt":
        with open(req["out"], "w", encoding="utf-8") as f:
            json.dump({"fake_prompt": req["audio"], "ref_text": req.get("ref_text")}, f)
        return {"ref_text": req.get("ref_text") or "lời thoại do máy chép", "echo": req}
    if cmd == "transcribe":
        return {"text": "lời thoại do máy chép", "echo": req}
    if cmd == "tts":
        if "LỖI" in req["text"]:
            raise RuntimeError("Giả lập lỗi bộ máy")
        seconds = float(req.get("duration") or max(0.4, min(3.0, len(req["text"]) * 0.03)))
        fake_wav(req["out"], seconds)
        return {"seconds": seconds, "echo": req}
    raise ValueError(f"unknown cmd {cmd!r}")


def handle(req: dict) -> dict:
    cmd = req.get("cmd")
    if cmd == "hello":
        return {"fake": FAKE, "python": sys.version.split()[0]}
    if FAKE:
        return fake(req)
    if cmd == "load":
        ensure_model(req.get("model"))
        return {"device": STATE["device"]}
    if cmd == "prompt":
        return do_prompt(req)
    if cmd == "transcribe":
        return do_transcribe(req)
    if cmd == "tts":
        return do_tts(req)
    raise ValueError(f"unknown cmd {cmd!r}")


def main() -> int:
    for raw in sys.stdin.buffer:
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            if req.get("cmd") == "quit":
                break
            send({"ok": True, **handle(req)})
        except BaseException as exc:  # noqa: BLE001 - report everything, keep serving
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            traceback.print_exc()
            send({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
