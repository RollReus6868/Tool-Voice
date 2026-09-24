"""Launch a BUILT app in self-check mode and verify its JSON report (used by CI).

usage: python tools/ci_selfcheck.py <path-to-exe-or-.app> <expected-kind> [report.json]
expected-kind: win-portable | win-setup | mac-app | source | any
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def main() -> int:
    target = Path(sys.argv[1]).resolve()
    want_kind = sys.argv[2]
    report = Path(sys.argv[3] if len(sys.argv) > 3 else tempfile.mktemp(suffix=".json")).resolve()
    exe = target
    if target.suffix == ".app":
        exe = target / "Contents" / "MacOS" / target.stem
    if not exe.exists():
        print(f"::error::executable not found: {exe}")
        return 1
    report.unlink(missing_ok=True)
    appdata = Path(tempfile.mkdtemp(prefix="tts_ci_appdata_"))
    env = dict(os.environ, TTS_SELFCHECK=str(report), TTS_SELFCHECK_SHOT=str(report.with_suffix(".png")),
               TTS_NO_UPDATE_CHECK="1", APPDATA=str(appdata), QT_QPA_PLATFORM="offscreen",
               TTS_FFMPEG_BUNDLED_ONLY="1")
    t0 = time.time()
    proc = subprocess.Popen([str(exe)], env=env, cwd=str(appdata))
    try:
        code = proc.wait(timeout=300)
    except subprocess.TimeoutExpired:
        proc.kill()
        print("::error::app did not exit within 300 s")
        return 1
    print(f"app exited with code {code} after {time.time() - t0:.1f}s")
    crash = exe.parent / "TTSCloneStudio_crash.log"
    if crash.exists():
        print("---- crash log ----\n" + crash.read_text(encoding="utf-8", errors="replace"))
    if not report.exists():
        log = appdata / "TTSCloneStudio" / "app.log"
        if log.exists():
            print("---- app.log ----\n" + log.read_text(encoding="utf-8", errors="replace")[-3000:])
        print("::error::self-check report was not written")
        return 1
    data = json.loads(report.read_text(encoding="utf-8"))
    print(json.dumps(data, ensure_ascii=False, indent=2))
    problems = list(data.get("errors") or [])
    if not data.get("ok"):
        problems.append("report ok=false")
    if want_kind != "any" and data.get("kind") != want_kind:
        problems.append(f"install kind {data.get('kind')!r} != expected {want_kind!r}")
    if data.get("frozen") and "imageio_ffmpeg" not in str(data.get("ffmpeg")):
        problems.append(f"ffmpeg is not the bundled copy: {data.get('ffmpeg')}")
    if data.get("pages", 0) < 8:
        problems.append(f"only {data.get('pages')} pages rendered")
    if code != 0:
        problems.append(f"exit code {code}")
    for p in problems:
        print(f"::error::{p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
