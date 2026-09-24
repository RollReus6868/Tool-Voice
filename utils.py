from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

from media import probe_duration


def safe_filename(value: str, default: str = "audio") -> str:
    value = str(value or "").strip()
    # Excel numbers come back as floats: 1.0 -> "1"
    if re.fullmatch(r"\d+\.0+", value):
        value = value.split(".")[0]
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value[:120] or default


def slug_voice_id(name: str) -> str:
    """MiniMax voice_id: 8-256 chars, starts with a letter, [A-Za-z0-9_-],
    must not end with - or _, must be unique."""
    import unicodedata

    ascii_name = unicodedata.normalize("NFKD", name.replace("đ", "d").replace("Đ", "D"))
    ascii_name = ascii_name.encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", ascii_name.strip()).strip("_-")
    if not base or not base[0].isalpha():
        base = "Voice_" + base
    stamp = datetime.now().strftime("%y%m%d%H%M%S")
    result = f"{base[:200]}_{stamp}"
    return result.rstrip("_-")


SAMPLE_RULES = {
    # provider: (extensions, max_bytes, min_sec, max_sec, note)
    "inworld": ({".wav", ".mp3"}, 15 * 1024 * 1024, 5.0, 30.0,
                "Inworld: WAV/MP3, tốt nhất 10–30 giây (quá 30 giây sẽ bị cắt bớt)."),
    "minimax": ({".wav", ".mp3", ".m4a"}, 20 * 1024 * 1024, 10.0, 300.0,
                "MiniMax: WAV/MP3/M4A, 10 giây – 5 phút, tối đa 20 MB."),
}


def sample_hint(provider: str) -> str:
    return SAMPLE_RULES[provider.lower()][4]


def validate_voice_sample(path: str, provider: str) -> tuple[bool, str]:
    """Returns (ok, message). Warnings keep ok=True but start with '⚠'."""
    if not path:
        return False, "Chưa chọn file giọng mẫu."
    p = Path(path)
    if not p.is_file():
        return False, "Không tìm thấy file giọng mẫu."

    allowed, max_bytes, min_sec, max_sec, _ = SAMPLE_RULES[provider.lower()]
    ext = p.suffix.lower()
    size = p.stat().st_size

    if ext not in allowed:
        pretty = ", ".join(sorted(e[1:].upper() for e in allowed))
        return False, f"Định dạng {ext or '(không có)'} không hỗ trợ. {provider} nhận: {pretty}."
    if size > max_bytes:
        return False, f"File quá lớn: {size / 1024 / 1024:.1f} MB (tối đa {max_bytes // 1024 // 1024} MB)."

    duration = probe_duration(str(p))
    if duration is None:
        return True, "⚠ Không đọc được độ dài file; API sẽ tự kiểm tra."
    if duration < min_sec:
        return False, f"Mẫu quá ngắn: {duration:.1f}s (cần tối thiểu {min_sec:g}s)."
    if duration > max_sec:
        if provider.lower() == "inworld":
            return True, f"⚠ Mẫu dài {duration:.1f}s — Inworld chỉ dùng 30 giây đầu."
        return False, f"Mẫu quá dài: {duration:.1f}s (tối đa {max_sec:g}s)."
    return True, f"✔ Mẫu hợp lệ: {duration:.1f} giây • {size / 1024 / 1024:.2f} MB"


def split_text(text: str, max_chars: int) -> list[str]:
    """Split text at natural boundaries so every chunk is <= max_chars."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    rest = text
    separators = ["\n\n", "\n", ". ", "! ", "? ", "… ", "; ", ": ", ", ", " "]
    while len(rest) > max_chars:
        window = rest[:max_chars]
        cut = -1
        for sep in separators:
            pos = window.rfind(sep)
            if pos > max_chars * 0.5:
                cut = pos + len(sep)
                break
        if cut <= 0:
            cut = max_chars
        chunk = rest[:cut].strip()
        if chunk:
            chunks.append(chunk)
        rest = rest[cut:].strip()
    if rest:
        chunks.append(rest)
    return chunks


def unique_output_path(folder: str, filename: str, extension: str = ".mp3") -> str:
    Path(folder).mkdir(parents=True, exist_ok=True)
    base = safe_filename(Path(filename).stem if Path(filename).suffix.lower() in (".mp3", ".mp4", ".wav") else filename)
    ext = extension if extension.startswith(".") else "." + extension
    candidate = Path(folder) / f"{base}{ext}"
    i = 2
    while candidate.exists():
        candidate = Path(folder) / f"{base}_{i}{ext}"
        i += 1
    return str(candidate)


def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def copy_file(src: str, dst: str) -> None:
    shutil.copyfile(src, dst)


def parse_row_selection(text: str, total: int) -> list[int]:
    """'1-10, 15, 20-' -> sorted unique 1-based numbers within 1..total.
    Empty text = all rows. 'a-' runs to the last row. Raises ValueError with a
    Vietnamese message for anything it cannot read or that is out of range."""
    raw = (text or "").strip()
    if not raw:
        return list(range(1, total + 1))
    norm = raw.replace("–", "-").replace("—", "-").replace("đến", "-").replace("..", "-")
    for sep in (";", "\n", "\t", " "):
        norm = norm.replace(sep, ",")
    picked: set[int] = set()
    for tok in (t.strip() for t in norm.split(",")):
        if not tok:
            continue
        if "-" in tok:
            a, _, b = tok.partition("-")
            a, b = a.strip(), b.strip()
            if not a.isdigit() or (b and not b.isdigit()):
                raise ValueError(f"Không hiểu “{tok}”. Ví dụ đúng: 1-10, 15, 20-25")
            lo, hi = int(a), (int(b) if b else total)
            if lo > hi:
                lo, hi = hi, lo
        elif tok.isdigit():
            lo = hi = int(tok)
        else:
            raise ValueError(f"Không hiểu “{tok}”. Ví dụ đúng: 1-10, 15, 20-25")
        if lo < 1 or hi > total:
            raise ValueError(f"“{tok}” vượt ngoài 1–{total} (file có {total} dòng nội dung).")
        picked.update(range(lo, hi + 1))
    if not picked:
        raise ValueError("Chưa chọn dòng nào.")
    return sorted(picked)
