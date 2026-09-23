"""ffmpeg helpers: locate ffmpeg, read durations, merge audio, build MP4."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from typing import Callable

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
_FFMPEG_CACHE: str | None = None

VIDEO_SIZES = {
    "1920×1080 (Full HD ngang)": (1920, 1080),
    "1280×720 (HD ngang)": (1280, 720),
    "1080×1920 (Dọc – Shorts/TikTok)": (1080, 1920),
    "1080×1080 (Vuông)": (1080, 1080),
}


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def find_ffmpeg() -> str | None:
    """Beside the app > PATH > bundled imageio-ffmpeg binary."""
    global _FFMPEG_CACHE
    if _FFMPEG_CACHE and Path(_FFMPEG_CACHE).exists():
        return _FFMPEG_CACHE
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    base = _app_dir()
    for cand in (base / exe, base / "ffmpeg" / exe, base / "ffmpeg" / "bin" / exe):
        if cand.is_file():
            _FFMPEG_CACHE = str(cand)
            return _FFMPEG_CACHE
    # TTS_FFMPEG_BUNDLED_ONLY=1 (CI) proves the copy shipped inside the app works
    found = None if os.getenv("TTS_FFMPEG_BUNDLED_ONLY") else shutil.which("ffmpeg")
    if found:
        _FFMPEG_CACHE = found
        return found
    try:
        import imageio_ffmpeg

        path = imageio_ffmpeg.get_ffmpeg_exe()
        if path and Path(path).exists():
            _FFMPEG_CACHE = path
            return path
    except Exception:
        pass
    return None


def _run(cmd: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, check=False, creationflags=_NO_WINDOW,
    )


def probe_duration(path: str) -> float | None:
    p = Path(path)
    if p.suffix.lower() == ".wav":
        try:
            with wave.open(str(p), "rb") as wf:
                return wf.getnframes() / float(wf.getframerate())
        except Exception:
            pass
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None
    try:
        proc = _run([ffmpeg, "-hide_banner", "-i", str(p)], timeout=30)
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr)
        if m:
            h, mi, s = m.groups()
            return int(h) * 3600 + int(mi) * 60 + float(s)
    except Exception:
        pass
    return None


def merge_audio_files(parts: list[str], output_path: str) -> None:
    """Join MP3 parts into one file (lossless concat, re-encode fallback)."""
    if not parts:
        raise ValueError("Không có đoạn audio nào để ghép.")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    if len(parts) == 1:
        shutil.copyfile(parts[0], output_path)
        return

    ffmpeg = find_ffmpeg()
    if ffmpeg:
        with tempfile.TemporaryDirectory(prefix="ttsmerge_") as td:
            manifest = Path(td) / "concat.txt"
            with manifest.open("w", encoding="utf-8") as f:
                for part in parts:
                    escaped = str(Path(part).resolve()).replace("\\", "/").replace("'", "'\\''")
                    f.write(f"file '{escaped}'\n")
            base = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "concat", "-safe", "0", "-i", str(manifest)]
            for codec in (["-c", "copy"], ["-c:a", "libmp3lame", "-b:a", "192k"]):
                proc = _run(base + codec + [output_path])
                if proc.returncode == 0 and Path(output_path).exists() and Path(output_path).stat().st_size > 0:
                    return

    # Last resort: MP3 is frame based, plain byte concat plays in most players.
    with open(output_path, "wb") as out:
        for part in parts:
            with open(part, "rb") as src:
                shutil.copyfileobj(src, out)


def _hex_to_ffmpeg_color(color: str) -> str:
    color = (color or "#000000").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        return "0x" + color[1:]
    return "black"


def make_video(
    audio_path: str,
    output_path: str,
    *,
    image_path: str = "",
    size: tuple[int, int] = (1280, 720),
    bg_color: str = "#000000",
    progress: Callable[[float], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> str:
    """Still image (or solid colour) + audio -> H.264/AAC MP4."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(
            "Không tìm thấy ffmpeg để tạo MP4. Hãy chạy lại install.bat "
            "(cài imageio-ffmpeg) hoặc đặt ffmpeg.exe cạnh ứng dụng."
        )
    w, h = size
    w -= w % 2
    h -= h % 2
    color = _hex_to_ffmpeg_color(bg_color)
    duration = probe_duration(audio_path) or 0.0
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Step 1: encode a short looping clip of the still frame (cheap), then
    # step 2: loop it with stream copy under the audio. Encoding every frame of
    # a long video would take minutes; this is audio-encode bound instead.
    workdir = tempfile.mkdtemp(prefix="ttsvideo_")
    clip = str(Path(workdir) / "clip.mp4")
    clip_len = 10
    fps = 24
    if image_path and Path(image_path).is_file():
        clip_in = ["-loop", "1", "-framerate", str(fps), "-i", str(image_path)]
        vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
              f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={color},setsar=1,format=yuv420p")
    else:
        clip_in = ["-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}:r={fps}"]
        vf = "setsar=1,format=yuv420p"
    proc = _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *clip_in, "-vf", vf, "-t", str(clip_len),
                 "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
                 "-g", str(fps * clip_len), "-an", clip])
    if proc.returncode != 0 or not Path(clip).exists():
        shutil.rmtree(workdir, ignore_errors=True)
        raise RuntimeError("ffmpeg không đọc được ảnh nền: " + (proc.stderr.strip()[-400:] or f"mã {proc.returncode}"))

    cmd = [
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostats",
        "-stream_loop", "-1", "-i", clip,
        "-i", str(audio_path),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
        "-shortest", *(["-t", f"{duration:.3f}"] if duration > 0 else []),
        "-movflags", "+faststart",
        "-progress", "pipe:1",
        str(output_path),
    ]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
    )
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if should_cancel and should_cancel():
                proc.kill()
                proc.wait()
                Path(output_path).unlink(missing_ok=True)
                raise RuntimeError("Đã dừng tạo video.")
            if progress and duration > 0 and line.startswith("out_time_us="):
                try:
                    us = int(line.split("=", 1)[1])
                    progress(min(us / 1_000_000 / duration, 1.0))
                except ValueError:
                    pass
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
        shutil.rmtree(workdir, ignore_errors=True)
    err = proc.stderr.read() if proc.stderr else ""
    if proc.returncode != 0 or not Path(output_path).exists():
        raise RuntimeError("ffmpeg lỗi khi tạo MP4: " + (err.strip()[-600:] or f"mã {proc.returncode}"))
    if progress:
        progress(1.0)
    return output_path
