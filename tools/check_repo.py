"""Static checks that have broken releases before. Run in CI before any build.
python tools/check_repo.py"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)
    print(f"::error::{msg}")


import app_info  # noqa: E402
import updater  # noqa: E402

# 1. version
if not re.fullmatch(r"\d+\.\d+\.\d+", app_info.APP_VERSION):
    err(f"APP_VERSION must be x.y.z, got {app_info.APP_VERSION!r}")
if not updater.repo_configured(app_info.GITHUB_REPO):
    err(f"GITHUB_REPO is not configured: {app_info.GITHUB_REPO!r}")

# 2. line endings / encodings of Windows scripts
for pattern in ("*.bat", "installer/*.iss"):
    for f in ROOT.glob(pattern):
        raw = f.read_bytes()
        try:
            raw.decode("ascii")
        except UnicodeDecodeError:
            err(f"{f.name}: must be pure ASCII (cmd.exe / ISCC mangle UTF-8)")
        if raw.replace(b"\r\n", b"").count(b"\n"):
            err(f"{f.name}: must use CRLF line endings")
for f in list(ROOT.glob("*.sh")) + list(ROOT.glob("*.command")):
    if b"\r\n" in f.read_bytes():
        err(f"{f.name}: must use LF line endings")

# 3. required files
for rel in ("RELEASE_NOTES.md", "TTSCloneStudio.spec", "installer/TTSCloneStudio.iss", "assets/app.ico",
            "assets/app.icns", "assets/app.png", ".gitattributes", "requirements.txt", "requirements-build.txt",
            ".github/workflows/build.yml"):
    if not (ROOT / rel).is_file():
        err(f"missing {rel}")

# 4. asset names in workflow / installer match what the updater looks for
wf = (ROOT / ".github/workflows/build.yml").read_text(encoding="utf-8") if (ROOT / ".github/workflows/build.yml").exists() else ""
iss = (ROOT / "installer/TTSCloneStudio.iss").read_text(encoding="utf-8")
v = "$VERSION"
expect = {
    "win-setup": updater.asset_name(v, "win-setup"),
    "win-portable": updater.asset_name(v, "win-portable"),
    "mac-arm64": updater.asset_name(v, "mac-app", "arm64").replace("arm64", "${{ matrix.arch }}"),
}
for key, name in expect.items():
    if name not in wf:
        err(f"workflow does not produce {name} ({key})")
if f"OutputBaseFilename={app_info.APP_ID}-{{#AppVersion}}-windows-setup" not in iss:
    err("installer OutputBaseFilename does not match the updater's setup asset name")
if f"{app_info.APP_ID}.exe" not in iss:
    err("installer does not reference the app exe")

# 5. every python module the app imports is listed in the spec hiddenimports
spec = (ROOT / "TTSCloneStudio.spec").read_text(encoding="utf-8")
for mod in sorted(p.stem for p in ROOT.glob("*.py") if p.stem not in ("launcher", "self_test")):
    if f'"{mod}"' not in spec:
        err(f"{mod}.py is not in the spec hiddenimports")

# 6. release notes mention this version
notes = (ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8")
if app_info.APP_VERSION not in notes:
    err(f"RELEASE_NOTES.md does not mention {app_info.APP_VERSION}")

print("check_repo:", "FAIL" if errors else "OK")
sys.exit(1 if errors else 0)
