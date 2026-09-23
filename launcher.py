"""Entry point used by run.bat and the packaged .exe.

Catches any startup crash (missing DLL, broken install…), writes it to a log
file beside the app and shows it in a message box instead of silently closing.
"""
from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _fatal(text: str) -> None:
    log = _app_dir() / "TTSCloneStudio_crash.log"
    try:
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"\n==== {datetime.now():%Y-%m-%d %H:%M:%S} ====\n{text}\n")
    except Exception:
        log = Path("(không ghi được log)")
    msg = f"TTS Clone Studio không khởi động được.\n\n{text[-1500:]}\n\nChi tiết: {log}"
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, msg, "TTS Clone Studio - Lỗi", 0x10)
            return
        except Exception:
            pass
    print(msg, file=sys.stderr)


if __name__ == "__main__":
    try:
        import main

        main.main()
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001
        _fatal(traceback.format_exc())
        sys.exit(1)
