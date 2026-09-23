"""Self-updater backed by GitHub Releases (no Qt in here — unit-testable).

Release assets MUST follow these fixed names (the workflow produces them):
    TTSCloneStudio-<ver>-windows-setup.exe     installed copy (Inno Setup, per-user)
    TTSCloneStudio-<ver>-windows-portable.exe  single-file copy
    TTSCloneStudio-<ver>-mac-arm64.zip         Apple Silicon .app (ditto zip)
    TTSCloneStudio-<ver>-mac-x64.zip           Intel .app
    SHA256SUMS.txt                             checksums of all of the above

Install flow: download -> verify sha256 -> write a small helper script that
waits for this process to exit, swaps the files, and relaunches -> app quits.
"""
from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import requests

from app_info import APP_ID, APP_VERSION, GITHUB_REPO

API_BASE = os.getenv("TTS_UPDATE_API", "https://api.github.com").rstrip("/")
_NO_WINDOW = 0x08000000
_NEW_GROUP = 0x00000200

KIND_TEXT = {
    "win-setup": "Bản cài đặt Windows",
    "win-portable": "Bản chạy 1 file (portable) Windows",
    "mac-app": "Ứng dụng macOS",
    "mac-manual": "Ứng dụng macOS (chưa nằm trong thư mục Applications)",
    "source": "Chạy từ mã nguồn Python",
}


class UpdateError(RuntimeError):
    pass


@dataclass
class ReleaseInfo:
    version: str
    tag: str
    notes: str
    html_url: str
    published_at: str = ""
    assets: list[dict] = field(default_factory=list)


# ------------------------------------------------------------------ versions
def parse_version(text: str) -> tuple:
    """'v2.10.1' -> (2, 10, 1, 1); pre-releases sort before finals: '2.1.0-beta' -> (2,1,0,0)."""
    m = re.match(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(.*)$", str(text or ""))
    if not m:
        return (0, 0, 0, 0)
    major, minor, patch, rest = m.groups()
    return (int(major), int(minor or 0), int(patch or 0), 0 if rest.strip(" .-+") else 1)


def is_newer(remote: str, local: str = APP_VERSION) -> bool:
    return parse_version(remote) > parse_version(local)


def repo_configured(repo: str = GITHUB_REPO) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo or "")) and not repo.startswith("OWNER/")


# ------------------------------------------------------------------ install kind
def mac_arch() -> str:
    """arm64 also when an Intel build runs under Rosetta on Apple Silicon."""
    if platform.machine().lower() in ("arm64", "aarch64"):
        return "arm64"
    try:
        out = subprocess.run(["sysctl", "-in", "sysctl.proc_translated"], capture_output=True, text=True, timeout=5)
        if out.stdout.strip() == "1":
            return "arm64"
    except Exception:
        pass
    return "x64"


def app_bundle_of(exe: str) -> Path | None:
    for parent in Path(exe).resolve().parents:
        if parent.suffix == ".app":
            return parent
    return None


def install_kind(frozen: bool | None = None, exe: str | None = None, system: str | None = None) -> str:
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    exe = exe or sys.executable
    system = system or platform.system()
    if not frozen:
        return "source"
    if system == "Windows":
        return "win-setup" if (Path(exe).parent / "unins000.exe").exists() else "win-portable"
    if system == "Darwin":
        app = app_bundle_of(exe)
        if app is None:
            return "source"
        if "/AppTranslocation/" in str(app) or not os.access(str(app.parent), os.W_OK):
            return "mac-manual"
        return "mac-app"
    return "source"


def asset_name(version: str, kind: str, arch: str | None = None) -> str | None:
    v = str(version).lstrip("v")
    if kind == "win-setup":
        return f"{APP_ID}-{v}-windows-setup.exe"
    if kind == "win-portable":
        return f"{APP_ID}-{v}-windows-portable.exe"
    if kind in ("mac-app", "mac-manual"):
        return f"{APP_ID}-{v}-mac-{arch or mac_arch()}.zip"
    return None


def pick_asset(rel: ReleaseInfo, kind: str, arch: str | None = None) -> dict | None:
    want = asset_name(rel.version, kind, arch)
    return next((a for a in rel.assets if a.get("name") == want), None) if want else None


# ------------------------------------------------------------------ GitHub
def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Accept": "application/vnd.github+json", "User-Agent": f"{APP_ID}/{APP_VERSION}",
                      "X-GitHub-Api-Version": "2022-11-28"})
    return s


def fetch_latest(repo: str = GITHUB_REPO, timeout: float = 20) -> ReleaseInfo:
    if not repo_configured(repo):
        raise UpdateError("Chưa cấu hình kho GitHub để kiểm tra cập nhật.")
    url = f"{API_BASE}/repos/{repo}/releases/latest"
    try:
        with _session() as s:
            r = s.get(url, timeout=timeout)
    except requests.RequestException as exc:
        raise UpdateError(f"Không kết nối được GitHub: {exc.__class__.__name__}. Kiểm tra Internet.") from exc
    if r.status_code == 404:
        raise UpdateError("Chưa có bản phát hành nào trên GitHub (hoặc kho chưa để Public).")
    if r.status_code == 403 and "rate limit" in r.text.lower():
        raise UpdateError("GitHub tạm giới hạn số lần kiểm tra, hãy thử lại sau 1 giờ.")
    if r.status_code >= 400:
        raise UpdateError(f"GitHub trả lỗi HTTP {r.status_code}.")
    d = r.json()
    tag = d.get("tag_name") or ""
    assets = [{"name": a.get("name", ""), "url": a.get("browser_download_url", ""), "size": a.get("size", 0),
               "digest": a.get("digest") or ""} for a in d.get("assets") or []]
    return ReleaseInfo(version=tag.lstrip("v"), tag=tag, notes=d.get("body") or "",
                       html_url=d.get("html_url") or f"https://github.com/{repo}/releases",
                       published_at=d.get("published_at") or "", assets=assets)


def expected_sha256(rel: ReleaseInfo, asset: dict, timeout: float = 20) -> str | None:
    dig = asset.get("digest") or ""
    if dig.startswith("sha256:") and len(dig) == 71:
        return dig[7:].lower()
    sums = next((a for a in rel.assets if a.get("name") == "SHA256SUMS.txt"), None)
    if not sums:
        return None
    try:
        with _session() as s:
            text = s.get(sums["url"], timeout=timeout).text
    except requests.RequestException:
        return None
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and parts[1].lstrip("*") == asset["name"]:
            return parts[0].lower()
    return None


def sha256_of(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download_asset(rel: ReleaseInfo, asset: dict, dest_dir: str | Path,
                   progress: Callable[[int, int], None] | None = None,
                   cancelled: Callable[[], bool] | None = None) -> str:
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / asset["name"]
    part = final.with_name(final.name + ".part")
    want = expected_sha256(rel, asset)
    try:
        with _session() as s, s.get(asset["url"], stream=True, timeout=60,
                                     headers={"Accept": "application/octet-stream"}) as r:
            if r.status_code >= 400:
                raise UpdateError(f"Tải bản cập nhật lỗi HTTP {r.status_code}.")
            total = int(r.headers.get("Content-Length") or asset.get("size") or 0)
            got = 0
            with open(part, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    if cancelled and cancelled():
                        raise UpdateError("Đã hủy tải bản cập nhật.")
                    f.write(chunk)
                    got += len(chunk)
                    if progress:
                        progress(got, total)
    except requests.RequestException as exc:
        part.unlink(missing_ok=True)
        raise UpdateError(f"Mất kết nối khi tải: {exc.__class__.__name__}.") from exc
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    if asset.get("size") and part.stat().st_size != int(asset["size"]):
        part.unlink(missing_ok=True)
        raise UpdateError("File tải về không đủ dung lượng — hãy thử lại.")
    if want:
        got_sha = sha256_of(part)
        if got_sha != want:
            part.unlink(missing_ok=True)
            raise UpdateError("Mã kiểm tra (SHA-256) không khớp — file tải về bị hỏng, đã xóa.")
    os.replace(part, final)
    return str(final)


# ------------------------------------------------------------------ macOS helpers
def extract_mac_zip(zip_path: str, dest_dir: str) -> Path:
    """Unzip with ditto (keeps symlinks, permissions, signatures). Returns the .app."""
    dest = Path(dest_dir)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    tool = shutil.which("ditto")
    cmd = [tool, "-x", "-k", zip_path, str(dest)] if tool else ["unzip", "-q", zip_path, "-d", str(dest)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise UpdateError("Giải nén bản cập nhật lỗi: " + (proc.stderr or "").strip()[-300:])
    apps = sorted(dest.glob("*.app"))
    if not apps:
        raise UpdateError("Không thấy ứng dụng .app trong file cập nhật.")
    return apps[0]


# ------------------------------------------------------------------ helper scripts
def windows_script(kind: str) -> str:
    """cmd.exe helper. Paths/PID arrive as environment variables (TTS_PID,
    TTS_NEW, TTS_TARGET, TTS_LOG): the environment block is UTF-16, so folders
    with Vietnamese names survive, while the script itself stays pure ASCII.
    Only goto (no parenthesised blocks) so %VAR% expands live; ping instead of
    `timeout`, which fails when there is no console."""
    lines = [
        "@echo off",
        "setlocal EnableExtensions",
        'set "PID=%TTS_PID%"',
        'set "NEW=%TTS_NEW%"',
        'set "TARGET=%TTS_TARGET%"',
        'set "LOG=%TTS_LOG%"',
        'echo [%date% %time%] bat dau cap nhat >> "%LOG%"',
        "set /a N=0",
        ":wait",
        'tasklist /FI "PID eq %PID%" /NH 2>nul | find " %PID% " >nul',
        "if errorlevel 1 goto gone",
        "set /a N+=1",
        "if %N% GEQ 120 goto gone",
        "ping -n 2 127.0.0.1 >nul",
        "goto wait",
        ":gone",
        'echo [%date% %time%] app da thoat sau %N% lan cho >> "%LOG%"',
    ]
    if kind == "win-setup":
        lines += [
            'for %%I in ("%TARGET%") do set "DIR=%%~dpI"',
            'if "%DIR:~-1%"=="\\" set "DIR=%DIR:~0,-1%"',
            'start "" /wait "%NEW%" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /DIR="%DIR%" /LOG="%LOG%.setup.txt"',
            'echo [%date% %time%] setup ket thuc, ma %errorlevel% >> "%LOG%"',
        ]
    else:
        lines += [
            "set /a T=0",
            ":move",
            'move /y "%NEW%" "%TARGET%" >nul 2>&1',
            "if not errorlevel 1 goto moved",
            "set /a T+=1",
            "if %T% GEQ 30 goto movefail",
            "ping -n 2 127.0.0.1 >nul",
            "goto move",
            ":movefail",
            'echo [%date% %time%] KHONG thay duoc file - dang bi khoa >> "%LOG%"',
            "goto launch",
            ":moved",
            'echo [%date% %time%] da thay file >> "%LOG%"',
        ]
    lines += [
        ":launch",
        "if defined TTS_UPDATE_NO_RELAUNCH goto done",
        'start "" "%TARGET%"',
        ":done",
        'echo [%date% %time%] xong >> "%LOG%"',
        '(goto) 2>nul & del "%~f0"',
    ]
    return "\r\n".join(lines) + "\r\n"


def mac_script(*, new_app: str, target_app: str, pid: int, log: str, staging: str) -> str:
    def q(s):
        return "'" + str(s).replace("'", "'\\''") + "'"

    return f"""#!/bin/bash
PID={int(pid)}
NEW_APP={q(new_app)}
TARGET={q(target_app)}
LOG={q(log)}
STAGING={q(staging)}
echo "[$(date)] bat dau cap nhat" >> "$LOG"
for i in $(seq 1 120); do kill -0 "$PID" 2>/dev/null || break; sleep 1; done
BACKUP="${{TARGET%.app}}.old-$$.app"
if ! mv "$TARGET" "$BACKUP" 2>>"$LOG"; then
  echo "[$(date)] khong di chuyen duoc app cu" >> "$LOG"
  [ -z "$TTS_UPDATE_NO_RELAUNCH" ] && open "$TARGET"
  exit 1
fi
if command -v ditto >/dev/null 2>&1; then COPY="ditto"; else COPY="cp -R"; fi
if $COPY "$NEW_APP" "$TARGET" 2>>"$LOG"; then
  rm -rf "$BACKUP"
  echo "[$(date)] da thay app" >> "$LOG"
else
  echo "[$(date)] loi chep app moi - hoan tac" >> "$LOG"
  rm -rf "$TARGET"
  mv "$BACKUP" "$TARGET"
fi
xattr -dr com.apple.quarantine "$TARGET" 2>/dev/null
rm -rf "$STAGING"
[ -z "$TTS_UPDATE_NO_RELAUNCH" ] && open "$TARGET"
echo "[$(date)] xong" >> "$LOG"
rm -f "$0"
"""


# keep a reference to the detached helper: a dropped Popen of a still-running
# process only triggers a ResourceWarning, but holding it keeps logs clean
_HELPERS: list[subprocess.Popen] = []


def launch_helper(kind: str, *, new_path: str, target: str, log: str, staging: str = "",
                  pid: int | None = None) -> str:
    """Write the helper script and start it detached. Returns the script path.
    The caller must quit the app right after."""
    pid = pid or os.getpid()
    tmp = Path(tempfile.mkdtemp(prefix="tts_update_"))
    if kind in ("win-setup", "win-portable"):
        script = tmp / "cap_nhat.cmd"
        script.write_bytes(windows_script(kind).encode("ascii"))
        env = dict(os.environ, TTS_PID=str(pid), TTS_NEW=new_path, TTS_TARGET=target, TTS_LOG=log)
        _HELPERS.append(subprocess.Popen(["cmd.exe", "/c", str(script)], creationflags=_NO_WINDOW | _NEW_GROUP,
                                         close_fds=True, cwd=str(tmp), env=env))
    elif kind == "mac-app":
        script = tmp / "cap_nhat.sh"
        script.write_text(mac_script(new_app=new_path, target_app=target, pid=pid, log=log, staging=staging),
                          encoding="utf-8")
        script.chmod(0o755)
        _HELPERS.append(subprocess.Popen(["/bin/bash", str(script)], start_new_session=True, close_fds=True,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    else:
        raise UpdateError("Kiểu cài đặt này không tự cập nhật được.")
    return str(script)


def current_target(kind: str) -> str:
    """The file / bundle the update replaces."""
    if kind in ("win-setup", "win-portable"):
        return str(Path(sys.executable).resolve())
    if kind == "mac-app":
        app = app_bundle_of(sys.executable)
        if app:
            return str(app)
    raise UpdateError("Không xác định được vị trí ứng dụng.")
