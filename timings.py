"""Word timings ("mốc thời gian từng từ") saved inside the MP3 (3.3.0).

CapCut Draft Studio shows on-screen text graphics exactly when the voice says
them. It needs to know when every word is spoken, so the app keeps that next to
the audio, INSIDE the MP3 (an ID3 TXXX frame named ``WORD_TIMINGS``): copying
the MP3 into a project carries the timings along, nothing extra to remember.

Payload (compact JSON):  {"v": 1, "engine": "inworld"|"whisper", "words": [["Hello", 0.0, 0.42], ...]}
times are seconds from the start of THIS file.

Sources:
* Inworld: the TTS request asks for ``timestampType: WORD`` and the answer carries
  ``timestampInfo.wordAlignment`` (exact, free).
* OmniVoice: Whisper (already part of the engine) listens to the finished file
  with word timestamps.
"""
from __future__ import annotations

import json
import os
import struct
import tempfile
from pathlib import Path

TAG = "WORD_TIMINGS"
Word = list   # [text, start, end]


def inworld_words(data: dict) -> list[Word]:
    """wordAlignment of an Inworld /tts/v1/voice answer → [[word, start, end]] (may be [])."""
    info = data.get("timestampInfo") or (data.get("result") or {}).get("timestampInfo") or {}
    wa = info.get("wordAlignment") or info.get("word_alignment") or {}
    words = wa.get("words") or []
    starts = wa.get("wordStartTimeSeconds") or wa.get("word_start_time_seconds") or []
    ends = wa.get("wordEndTimeSeconds") or wa.get("word_end_time_seconds") or []
    out: list[Word] = []
    for i, w in enumerate(words):
        try:
            s = float(starts[i])
            e = float(ends[i]) if i < len(ends) else s
        except (IndexError, TypeError, ValueError):
            continue
        text = str(w).strip()
        if text:
            out.append([text, round(s, 3), round(max(s, e), 3)])
    return out


def shift(words: list[Word], offset: float) -> list[Word]:
    return [[w, round(s + offset, 3), round(e + offset, 3)] for w, s, e in words]


def payload(words: list[Word], engine: str) -> str:
    return json.dumps({"v": 1, "engine": engine, "words": words}, ensure_ascii=False, separators=(",", ":"))


def _ffmeta_escape(value: str) -> str:
    out = []
    for ch in value:
        if ch in "=;#\\\n":
            out.append("\\")
        out.append(ch)
    return "".join(out)


def embed(mp3: str, words: list[Word], engine: str) -> bool:
    """Write the timings into the MP3 (audio is stream-copied, not re-encoded).
    Returns False (file untouched) when it could not be done; never raises."""
    try:
        return _embed(Path(mp3), words, engine)
    except Exception:  # noqa: BLE001 - the voice file matters more than its timings
        return False


def _embed(src: Path, words: list[Word], engine: str) -> bool:
    from media import _run, find_ffmpeg, probe_duration

    ffmpeg = find_ffmpeg()
    if not words or not ffmpeg or not src.is_file():
        return False
    # temp output beside the file: os.replace cannot move between drives (Windows C: -> D:)
    tmp = src.with_name(f".{src.stem}.tag-tmp{src.suffix}")
    with tempfile.TemporaryDirectory(prefix="tts_tag_") as td:
        meta = Path(td) / "meta.txt"
        # ffmetadata file: no command-line length limit for long files
        meta.write_text(";FFMETADATA1\n" + f"{TAG}=" + _ffmeta_escape(payload(words, engine)) + "\n",
                        encoding="utf-8")
        try:
            proc = _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-i", str(meta),
                         "-map", "0:a", "-map_metadata", "1", "-c", "copy", "-id3v2_version", "3",
                         "-write_xing", "1", str(tmp)])
            if proc.returncode != 0 or not tmp.is_file() or read(str(tmp)) is None:
                return False
            before, after = probe_duration(str(src)), probe_duration(str(tmp))
            if not after or (before and abs(after - before) > 0.05):
                return False                     # never replace the voice with something shorter
            os.replace(tmp, src)
            return True
        finally:
            tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------- reading back (tests, self-check)
def _syncsafe(b: bytes) -> int:
    return (b[0] << 21) | (b[1] << 14) | (b[2] << 7) | b[3]


def read(mp3: str) -> dict | None:
    """The WORD_TIMINGS payload of an MP3 (ID3v2.3/2.4 TXXX), or None."""
    try:
        with open(mp3, "rb") as f:
            head = f.read(10)
            if len(head) < 10 or head[:3] != b"ID3":
                return None
            ver, flags = head[3], head[5]
            body = f.read(_syncsafe(head[6:10]))
    except OSError:
        return None
    pos = 0
    if flags & 0x40 and len(body) >= 4:              # extended header
        pos = (_syncsafe(body[:4]) if ver == 4 else struct.unpack(">I", body[:4])[0] + 4)
    while pos + 10 <= len(body):
        fid = body[pos:pos + 4]
        if fid == b"\0\0\0\0":
            break
        size = _syncsafe(body[pos + 4:pos + 8]) if ver == 4 else struct.unpack(">I", body[pos + 4:pos + 8])[0]
        data = body[pos + 10:pos + 10 + size]
        pos += 10 + size
        if fid != b"TXXX" or not data:
            continue
        enc, rest = data[0], data[1:]
        if enc in (1, 2):
            codec, sep = ("utf-16" if enc == 1 else "utf-16-be"), b"\0\0"
            i = 0
            while True:
                i = rest.find(sep, i)
                if i < 0 or i % 2 == 0:
                    break
                i += 1
        else:
            codec, sep = ("latin-1" if enc == 0 else "utf-8"), b"\0"
            i = rest.find(sep)
        if i < 0:
            continue
        desc = rest[:i].decode(codec, "replace")
        if desc != TAG:
            continue
        value = rest[i + len(sep):].decode(codec, "replace").rstrip("\0")
        try:
            obj = json.loads(value)
        except ValueError:
            return None
        return obj if isinstance(obj, dict) and isinstance(obj.get("words"), list) else None
    return None
