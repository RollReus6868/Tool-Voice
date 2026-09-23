"""Built-app self check, used by CI on every OS.

Enabled with env TTS_SELFCHECK=<report.json>. The app opens normally, visits
every page, runs ffmpeg for real (tone -> MP3 -> MP4), checks the keyring
backend and the updater's view of how it was installed, writes a JSON report
and quits with exit code 0 (report["ok"] tells pass/fail).
Optional TTS_SELFCHECK_SHOT=<png> also saves a screenshot.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path


def run(window, app) -> None:
    report: dict = {"ok": False, "errors": []}
    path = os.environ.get("TTS_SELFCHECK", "")
    try:
        from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR

        import updater
        from app_info import APP_VERSION
        from media import find_ffmpeg, make_video, probe_duration

        report.update(version=APP_VERSION, platform=sys.platform, machine=platform.machine(),
                      frozen=bool(getattr(sys, "frozen", False)), executable=sys.executable,
                      qt=QT_VERSION_STR, pyqt=PYQT_VERSION_STR, kind=updater.install_kind())
        if sys.platform == "darwin":
            report["mac_arch"] = updater.mac_arch()

        # every page renders
        pages = window.stack.count()
        for i in range(pages):
            window.go(i)
            app.processEvents()
        window.apply_theme("light")
        app.processEvents()
        window.apply_theme("dark")
        app.processEvents()
        report["pages"] = pages

        # ffmpeg really runs and can encode MP3 + H.264/AAC
        ff = find_ffmpeg()
        report["ffmpeg"] = ff
        if not ff:
            report["errors"].append("ffmpeg not found")
        else:
            flags = 0x08000000 if os.name == "nt" else 0
            with tempfile.TemporaryDirectory() as td:
                mp3 = str(Path(td) / "tone.mp3")
                p = subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=2",
                                    "-c:a", "libmp3lame", mp3], capture_output=True, text=True, creationflags=flags)
                if p.returncode != 0:
                    report["errors"].append("ffmpeg mp3 failed: " + p.stderr[-300:])
                else:
                    mp4 = str(Path(td) / "v.mp4")
                    make_video(mp3, mp4, size=(1280, 720), bg_color="#224466")
                    d = probe_duration(mp4)
                    report["video_seconds"] = d
                    if not d or not (1.5 < d < 2.6):
                        report["errors"].append(f"bad video duration {d}")

        # keyring backend (Windows Credential Manager / macOS Keychain)
        try:
            import keyring

            report["keyring"] = type(keyring.get_keyring()).__module__ + "." + type(keyring.get_keyring()).__name__
        except Exception as exc:  # noqa: BLE001
            report["errors"].append(f"keyring: {exc}")

        # HTTPS stack (certifi bundle) is present
        try:
            import certifi

            report["certifi"] = Path(certifi.where()).is_file()
            if not report["certifi"]:
                report["errors"].append("certifi bundle missing")
        except Exception as exc:  # noqa: BLE001
            report["errors"].append(f"certifi: {exc}")

        shot = os.environ.get("TTS_SELFCHECK_SHOT")
        if shot:
            window.go(0)
            app.processEvents()
            window.grab().save(shot)
        report["ok"] = not report["errors"]
    except Exception:  # noqa: BLE001
        report["errors"].append(traceback.format_exc())
    finally:
        if path:
            Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        app.quit()
