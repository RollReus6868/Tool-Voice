from __future__ import annotations

import os
import shutil
import tempfile
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QThread, pyqtSignal

from media import make_video, merge_audio_files, probe_duration
from providers import CancelledError, build_provider


class FuncWorker(QThread):
    """Runs fn(log, cancelled, progress) in a background thread."""

    log = pyqtSignal(str)
    progress = pyqtSignal(int)          # 0..100
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn: Callable, parent=None):
        super().__init__(parent)
        self._fn = fn
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def run(self):
        try:
            result = self._fn(self.log.emit, self.is_cancelled, lambda v: self.progress.emit(int(v)))
            self.done.emit(result)
        except CancelledError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.log.emit("   " + traceback.format_exc(limit=2).strip().splitlines()[-1])
            self.failed.emit(str(exc))


def produce_outputs(
    *, provider, text: str, voice: dict, model: str, speed: float, out_dir: str, name: str,
    fmt: str, video: dict, log, cancelled, progress=None, keep_mp3_dir: str | None = None,
    options: dict | None = None,
) -> dict:
    """Synthesize one text and write MP3 / MP4 according to fmt (mp3|mp4|both).
    Returns {"mp3": path|None, "mp4": path|None, "audio": path_of_mp3_used, "chars": billed_chars}."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    want_mp3 = fmt in ("mp3", "both")
    want_mp4 = fmt in ("mp4", "both")
    final_mp3 = str(Path(out_dir) / f"{name}.mp3")
    final_mp4 = str(Path(out_dir) / f"{name}.mp4")

    tmp_dir = None
    if want_mp3:
        audio_path = final_mp3
    else:
        base = keep_mp3_dir or tempfile.mkdtemp(prefix="tts_audio_")
        tmp_dir = None if keep_mp3_dir else base
        audio_path = str(Path(base) / f"{name}.mp3")
    try:
        if progress:
            progress(5)
        try:
            provider.synthesize(text, voice["provider_voice_id"], audio_path, model=model, speed=speed,
                                language=voice.get("language", ""), options=options)
        except BaseException as exc:
            # chunks already synthesized were billed even if a later one failed
            exc.chars_billed = getattr(provider, "chars_used", 0)
            raise
        if progress:
            progress(60 if want_mp4 else 100)
        result = {"mp3": final_mp3 if want_mp3 else None, "mp4": None, "audio": audio_path,
                  "chars": int(getattr(provider, "chars_used", 0) or 0)}
        if want_mp4:
            if cancelled():
                raise CancelledError("Đã dừng theo yêu cầu.")
            make_video(
                audio_path, final_mp4, image_path=video.get("image", ""), size=video.get("size", (1280, 720)),
                bg_color=video.get("color", "#000000"),
                progress=(lambda f: progress(60 + int(f * 40))) if progress else None,
                should_cancel=cancelled,
            )
            result["mp4"] = final_mp4
        return result
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


class BatchWorker(QThread):
    log = pyqtSignal(str)
    row_status = pyqtSignal(int, str, str)   # task index, state, detail
    progress = pyqtSignal(int, int)          # done, total
    usage = pyqtSignal(str, str, int)        # provider, model, billed characters
    finished_summary = pyqtSignal(dict)

    def __init__(self, *, tasks, voice, model, speed, out_dir, fmt, video, threads, skip_existing,
                 merge_all, merge_name, secrets, config, options=None, parent=None):
        super().__init__(parent)
        self.tasks = tasks
        self.voice = voice
        self.model = model
        self.speed = speed
        self.out_dir = out_dir
        self.fmt = fmt
        self.video = video
        self.threads = max(1, int(threads))
        self.skip_existing = skip_existing
        self.merge_all = merge_all
        self.merge_name = merge_name
        self.secrets = secrets
        self.config = config
        self.options = options or {}
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def _target_exists(self, name: str) -> bool:
        paths = []
        if self.fmt in ("mp3", "both"):
            paths.append(Path(self.out_dir) / f"{name}.mp3")
        if self.fmt in ("mp4", "both"):
            paths.append(Path(self.out_dir) / f"{name}.mp4")
        return all(p.exists() and p.stat().st_size > 0 for p in paths)

    def _one(self, idx: int, task: dict, keep_dir: str | None) -> tuple[str, str | None]:
        if self._cancel.is_set():
            self.row_status.emit(idx, "stopped", "Đã dừng")
            return "stopped", None
        name = task["filename"]
        if self.skip_existing and self._target_exists(name):
            self.row_status.emit(idx, "skipped", "(đã có file)")
            mp3 = Path(self.out_dir) / f"{name}.mp3"
            if not mp3.exists() and keep_dir:
                mp3 = Path(keep_dir) / f"{name}.mp3"
            return "skipped", (str(mp3) if mp3.exists() else None)
        self.row_status.emit(idx, "running", "Đang tạo giọng…")
        try:
            provider = build_provider(self.voice["provider"], self.secrets, self.config,
                                      log=self.log.emit, cancel=self._cancel.is_set)
            res = produce_outputs(
                provider=provider, text=task["text"], voice=self.voice, model=self.model, speed=self.speed,
                out_dir=self.out_dir, name=name, fmt=self.fmt, video=self.video, log=self.log.emit,
                cancelled=self._cancel.is_set, keep_mp3_dir=keep_dir, options=self.options,
            )
            if res.get("chars"):
                self.usage.emit(self.voice["provider"], self.model, int(res["chars"]))
            dur = probe_duration(res["audio"])
            detail = " + ".join(Path(p).name for p in (res["mp3"], res["mp4"]) if p)
            if dur:
                detail += f"  ({dur:.1f}s)"
            self.row_status.emit(idx, "ok", detail)
            self.log.emit(f"✅ Dòng {task['row_no']} → {detail}")
            return "ok", res["audio"]
        except CancelledError as exc:
            self._emit_partial(exc)
            self.row_status.emit(idx, "stopped", "Đã dừng")
            return "stopped", None
        except Exception as exc:  # noqa: BLE001
            self._emit_partial(exc)
            if self._cancel.is_set():
                self.row_status.emit(idx, "stopped", "Đã dừng")
                return "stopped", None
            self.row_status.emit(idx, "error", str(exc))
            self.log.emit(f"❌ Dòng {task['row_no']} lỗi: {exc}")
            return "error", None

    def _emit_partial(self, exc):
        n = int(getattr(exc, "chars_billed", 0) or 0)
        if n:
            self.usage.emit(self.voice["provider"], self.model, n)

    def run(self):
        total = len(self.tasks)
        counts = {"ok": 0, "error": 0, "skipped": 0, "stopped": 0}
        audio_by_idx: dict[int, str] = {}
        keep_dir = tempfile.mkdtemp(prefix="tts_batch_") if (self.merge_all and self.fmt == "mp4") else None
        merged: list[str] = []
        try:
            done = 0
            self.progress.emit(0, total)
            with ThreadPoolExecutor(max_workers=self.threads) as pool:
                futures = {pool.submit(self._one, i, t, keep_dir): i for i, t in enumerate(self.tasks)}
                for fut in as_completed(futures):
                    i = futures[fut]
                    state, audio = fut.result()
                    counts[state] = counts.get(state, 0) + 1
                    if audio:
                        audio_by_idx[i] = audio
                    done += 1
                    self.progress.emit(done, total)

            if self.merge_all and not self._cancel.is_set():
                ordered = [audio_by_idx[i] for i in sorted(audio_by_idx) if os.path.exists(audio_by_idx[i])]
                if len(ordered) < total:
                    self.log.emit(f"⚠ Gộp file: chỉ có {len(ordered)}/{total} đoạn audio sẵn sàng.")
                if ordered:
                    self.log.emit(f"🔗 Đang gộp {len(ordered)} đoạn thành 1 file…")
                    merged_mp3 = str(Path(self.out_dir) / f"{self.merge_name}.mp3")
                    tmp_merge = None
                    if self.fmt == "mp4":
                        tmp_merge = str(Path(keep_dir) / "__merged.mp3")
                        merge_audio_files(ordered, tmp_merge)
                    else:
                        merge_audio_files(ordered, merged_mp3)
                        merged.append(merged_mp3)
                    if self.fmt in ("mp4", "both"):
                        self.log.emit("🎬 Đang dựng video gộp…")
                        merged_mp4 = str(Path(self.out_dir) / f"{self.merge_name}.mp4")
                        make_video(tmp_merge or merged_mp3, merged_mp4, image_path=self.video.get("image", ""),
                                   size=self.video.get("size", (1280, 720)),
                                   bg_color=self.video.get("color", "#000000"), should_cancel=self._cancel.is_set)
                        merged.append(merged_mp4)
                    self.log.emit("✅ Đã gộp: " + ", ".join(Path(m).name for m in merged))
        except Exception as exc:  # noqa: BLE001
            self.log.emit(f"❌ Lỗi batch: {exc}")
            counts["fatal"] = str(exc)
        finally:
            if keep_dir:
                shutil.rmtree(keep_dir, ignore_errors=True)
        counts["merged"] = merged
        counts["cancelled"] = self._cancel.is_set()
        self.finished_summary.emit(counts)
