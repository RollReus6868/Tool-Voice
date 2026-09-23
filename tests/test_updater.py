"""Updater tests — run on Linux, Windows and macOS in CI:  python -m unittest discover -s tests -v"""
from __future__ import annotations

import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import updater  # noqa: E402
from app_info import APP_ID, APP_VERSION  # noqa: E402


class _Handler(http.server.BaseHTTPRequestHandler):
    routes: dict = {}

    def do_GET(self):  # noqa: N802
        body, status = self.routes.get(self.path, (b"not found", 404))
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class FakeGitHub:
    def __enter__(self):
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self._old = updater.API_BASE
        updater.API_BASE = self.base
        _Handler.routes = {}
        return self

    def __exit__(self, *a):
        updater.API_BASE = self._old
        self.srv.shutdown()

    def release(self, version, files: dict[str, bytes], digest=True, sums=False, bad_digest=False):
        assets = []
        for name, data in files.items():
            _Handler.routes[f"/dl/{name}"] = (data, 200)
            sha = hashlib.sha256(data).hexdigest()
            if bad_digest:
                sha = "0" * 64
            assets.append({"name": name, "browser_download_url": f"{self.base}/dl/{name}", "size": len(data),
                           "digest": f"sha256:{sha}" if digest else None})
        if sums:
            text = "".join(f"{hashlib.sha256(d).hexdigest()}  {n}\n" for n, d in files.items()).encode()
            _Handler.routes["/dl/SHA256SUMS.txt"] = (text, 200)
            assets.append({"name": "SHA256SUMS.txt", "browser_download_url": f"{self.base}/dl/SHA256SUMS.txt",
                           "size": len(text), "digest": None})
        rel = {"tag_name": f"v{version}", "body": "## Mới\n- sửa lỗi", "html_url": f"{self.base}/rel",
               "assets": assets}
        _Handler.routes["/repos/me/app/releases/latest"] = (json.dumps(rel).encode(), 200)


class VersionTests(unittest.TestCase):
    def test_compare(self):
        self.assertTrue(updater.is_newer("2.1.1", "2.1.0"))
        self.assertTrue(updater.is_newer("v2.10.0", "2.9.9"))
        self.assertFalse(updater.is_newer("2.1.0", "2.1.0"))
        self.assertFalse(updater.is_newer("2.0.9", "2.1.0"))
        self.assertTrue(updater.is_newer("2.1.0", "2.1.0-beta"))
        self.assertFalse(updater.is_newer("2.1.0-beta", "2.1.0"))
        self.assertFalse(updater.is_newer("rác", "2.1.0"))

    def test_repo_configured(self):
        self.assertFalse(updater.repo_configured("OWNER/TTS-Clone-Studio"))
        self.assertFalse(updater.repo_configured(""))
        self.assertFalse(updater.repo_configured("a/b/c"))
        self.assertTrue(updater.repo_configured("someone/TTS-Clone-Studio"))

    def test_app_version_format(self):
        self.assertRegex(APP_VERSION, r"^\d+\.\d+\.\d+$")


class AssetTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(updater.asset_name("2.3.4", "win-setup"), f"{APP_ID}-2.3.4-windows-setup.exe")
        self.assertEqual(updater.asset_name("v2.3.4", "win-portable"), f"{APP_ID}-2.3.4-windows-portable.exe")
        self.assertEqual(updater.asset_name("2.3.4", "mac-app", "arm64"), f"{APP_ID}-2.3.4-mac-arm64.zip")
        self.assertEqual(updater.asset_name("2.3.4", "mac-manual", "x64"), f"{APP_ID}-2.3.4-mac-x64.zip")
        self.assertIsNone(updater.asset_name("2.3.4", "source"))

    def test_pick_never_confuses_setup_and_portable(self):
        names = [updater.asset_name("3.0.0", k, a) for k, a in
                 [("win-portable", None), ("win-setup", None), ("mac-app", "x64"), ("mac-app", "arm64")]]
        for order in (names, list(reversed(names))):
            rel = updater.ReleaseInfo("3.0.0", "v3.0.0", "", "", assets=[{"name": n} for n in order])
            self.assertEqual(updater.pick_asset(rel, "win-setup")["name"], f"{APP_ID}-3.0.0-windows-setup.exe")
            self.assertEqual(updater.pick_asset(rel, "win-portable")["name"], f"{APP_ID}-3.0.0-windows-portable.exe")
            self.assertEqual(updater.pick_asset(rel, "mac-app", "arm64")["name"], f"{APP_ID}-3.0.0-mac-arm64.zip")
            self.assertEqual(updater.pick_asset(rel, "mac-app", "x64")["name"], f"{APP_ID}-3.0.0-mac-x64.zip")
        self.assertIsNone(updater.pick_asset(updater.ReleaseInfo("3.0.0", "", "", "", []), "win-setup"))


class KindTests(unittest.TestCase):
    def test_source(self):
        self.assertEqual(updater.install_kind(frozen=False), "source")

    def test_windows(self):
        with tempfile.TemporaryDirectory() as td:
            exe = Path(td) / "TTSCloneStudio.exe"
            exe.write_bytes(b"x")
            self.assertEqual(updater.install_kind(True, str(exe), "Windows"), "win-portable")
            (Path(td) / "unins000.exe").write_bytes(b"x")
            self.assertEqual(updater.install_kind(True, str(exe), "Windows"), "win-setup")

    @unittest.skipIf(os.name == "nt", "POSIX path semantics")
    def test_mac(self):
        with tempfile.TemporaryDirectory() as td:
            macos = Path(td) / "Apps" / "TTSCloneStudio.app" / "Contents" / "MacOS"
            macos.mkdir(parents=True)
            exe = macos / "TTSCloneStudio"
            exe.write_bytes(b"x")
            self.assertEqual(updater.install_kind(True, str(exe), "Darwin"), "mac-app")
            self.assertEqual(updater.app_bundle_of(str(exe)).name, "TTSCloneStudio.app")
            tr = Path(td) / "private" / "var" / "folders" / "AppTranslocation" / "X" / "d" / "TTSCloneStudio.app"
            (tr / "Contents" / "MacOS").mkdir(parents=True)
            (tr / "Contents" / "MacOS" / "TTSCloneStudio").write_bytes(b"x")
            self.assertEqual(updater.install_kind(True, str(tr / "Contents/MacOS/TTSCloneStudio"), "Darwin"),
                             "mac-manual")


class NetworkTests(unittest.TestCase):
    def test_fetch_download_verify(self):
        payload = os.urandom(300_000)
        name = f"{APP_ID}-9.9.9-windows-setup.exe"
        with FakeGitHub() as gh, tempfile.TemporaryDirectory() as td:
            gh.release("9.9.9", {name: payload})
            rel = updater.fetch_latest("me/app")
            self.assertEqual(rel.version, "9.9.9")
            self.assertTrue(updater.is_newer(rel.version))
            self.assertIn("sửa lỗi", rel.notes)
            seen = []
            path = updater.download_asset(rel, updater.pick_asset(rel, "win-setup"), td,
                                          progress=lambda g, t: seen.append((g, t)))
            self.assertEqual(Path(path).read_bytes(), payload)
            self.assertEqual(seen[-1], (len(payload), len(payload)))
            self.assertFalse(list(Path(td).glob("*.part")))

    def test_sha256sums_fallback(self):
        payload = b"mac zip bytes" * 1000
        name = f"{APP_ID}-9.9.9-mac-arm64.zip"
        with FakeGitHub() as gh, tempfile.TemporaryDirectory() as td:
            gh.release("9.9.9", {name: payload}, digest=False, sums=True)
            rel = updater.fetch_latest("me/app")
            asset = updater.pick_asset(rel, "mac-app", "arm64")
            self.assertEqual(updater.expected_sha256(rel, asset), hashlib.sha256(payload).hexdigest())
            self.assertEqual(Path(updater.download_asset(rel, asset, td)).read_bytes(), payload)

    def test_bad_checksum_is_deleted(self):
        name = f"{APP_ID}-9.9.9-windows-portable.exe"
        with FakeGitHub() as gh, tempfile.TemporaryDirectory() as td:
            gh.release("9.9.9", {name: b"tampered"}, bad_digest=True)
            rel = updater.fetch_latest("me/app")
            with self.assertRaises(updater.UpdateError) as cm:
                updater.download_asset(rel, updater.pick_asset(rel, "win-portable"), td)
            self.assertIn("SHA-256", str(cm.exception))
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_no_release(self):
        with FakeGitHub():
            with self.assertRaises(updater.UpdateError) as cm:
                updater.fetch_latest("me/app")
            self.assertIn("Public", str(cm.exception))

    def test_unconfigured_repo(self):
        with self.assertRaises(updater.UpdateError):
            updater.fetch_latest("OWNER/TTS-Clone-Studio")


class ScriptTests(unittest.TestCase):
    def test_windows_script_shape(self):
        for kind in ("win-setup", "win-portable"):
            s = updater.windows_script(kind)
            s.encode("ascii")  # pure ASCII: paths come in via environment variables
            self.assertNotIn("\n", s.replace("\r\n", ""))  # CRLF only
            self.assertNotIn("timeout ", s)                # fails without a console
            body = s.replace("(goto) 2>nul", "")
            self.assertNotIn("(", body.replace('("%TARGET%")', ""))  # no parenthesised blocks
            for var in ("TTS_PID", "TTS_NEW", "TTS_TARGET", "TTS_LOG"):
                self.assertIn(f"%{var}%", s)
        self.assertIn("/VERYSILENT", updater.windows_script("win-setup"))
        self.assertIn("move /y", updater.windows_script("win-portable"))

    @unittest.skipUnless(shutil.which("bash"), "needs bash")
    def test_mac_script_syntax(self):
        s = updater.mac_script(new_app="/tmp/a b/New.app", target_app="/Applications/X's.app", pid=1,
                               log="/tmp/l.txt", staging="/tmp/s")
        with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
            f.write(s)
        try:
            r = subprocess.run(["bash", "-n", f.name], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
        finally:
            os.unlink(f.name)

    @unittest.skipIf(os.name == "nt", "POSIX only")
    def test_mac_script_swaps_and_rolls_back(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            for case in ("swap", "rollback"):
                target = td / "Ứng dụng" / "TTSCloneStudio.app"
                if target.parent.exists():
                    shutil.rmtree(target.parent)
                (target / "Contents").mkdir(parents=True)
                (target / "Contents" / "old.txt").write_text("old")
                staging = td / f"staging_{case}"
                new_app = staging / "TTSCloneStudio.app"
                if case == "swap":
                    (new_app / "Contents").mkdir(parents=True)
                    (new_app / "Contents" / "new.txt").write_text("new")
                else:
                    staging.mkdir()
                sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"])
                # reap it as soon as it exits, like launchd reaps the real app (a zombie still answers kill -0)
                threading.Thread(target=sleeper.wait, daemon=True).start()
                log = td / f"log_{case}.txt"
                script = td / f"s_{case}.sh"
                script.write_text(updater.mac_script(new_app=str(new_app), target_app=str(target),
                                                     pid=sleeper.pid, log=str(log), staging=str(staging)))
                t0 = time.time()
                r = subprocess.run(["bash", str(script)], env=dict(os.environ, TTS_UPDATE_NO_RELAUNCH="1"),
                                   capture_output=True, text=True, timeout=60)
                self.assertGreaterEqual(time.time() - t0, 1.0, "script must wait for the app to exit")
                if case == "swap":
                    self.assertTrue((target / "Contents" / "new.txt").exists(), log.read_text())
                    self.assertFalse((target / "Contents" / "old.txt").exists())
                else:
                    self.assertTrue((target / "Contents" / "old.txt").exists(), log.read_text())
                self.assertFalse(staging.exists())
                self.assertEqual([p.name for p in target.parent.iterdir()], ["TTSCloneStudio.app"],
                                 "backup must be removed")
                self.assertIn("xong", log.read_text())
                self.assertFalse(script.exists(), "script deletes itself")
                del r


@unittest.skipUnless(os.name == "nt", "real cmd.exe test")
class WindowsHelperTests(unittest.TestCase):
    """Runs the generated .cmd helper for real (CI windows runner)."""

    def _run_helper(self, kind, new, target, log):
        sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3)"])
        os.environ["TTS_UPDATE_NO_RELAUNCH"] = "1"
        try:
            updater.launch_helper(kind, new_path=str(new), target=str(target), log=str(log), pid=sleeper.pid)
        finally:
            del os.environ["TTS_UPDATE_NO_RELAUNCH"]
        sleeper.wait()
        deadline = time.time() + 240
        while time.time() < deadline:
            if log.exists() and "xong" in log.read_text(errors="replace"):
                return log.read_text(errors="replace")
            time.sleep(1)
        self.fail("helper did not finish: " + (log.read_text(errors="replace") if log.exists() else "no log"))

    def test_portable_swap_unicode_folder(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td) / "Thư mục Việt có dấu"
            folder.mkdir()
            target = folder / "TTSCloneStudio.exe"
            target.write_bytes(b"old version")
            new = folder / "TTSCloneStudio-9.9.9-windows-portable.exe"
            new.write_bytes(b"new version")
            text = self._run_helper("win-portable", new, target, Path(td) / "update_log.txt")
            self.assertEqual(target.read_bytes(), b"new version", text)
            self.assertFalse(new.exists())
            self.assertIn("da thay file", text)

    @unittest.skipUnless(os.environ.get("TTS_CI_SETUP_EXE"), "needs the built setup.exe")
    def test_setup_silent_update(self):
        setup = Path(os.environ["TTS_CI_SETUP_EXE"])
        with tempfile.TemporaryDirectory() as td:
            app_dir = Path(td) / "Cài đặt" / "TTS Clone Studio"
            r = subprocess.run([str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/DIR={app_dir}"],
                               timeout=600)
            self.assertEqual(r.returncode, 0)
            exe = app_dir / "TTSCloneStudio.exe"
            self.assertTrue(exe.exists() and (app_dir / "unins000.exe").exists())
            marker = app_dir / "_internal" / "stale_file_from_old_version.txt"
            marker.write_text("stale")
            text = self._run_helper("win-setup", setup, exe, Path(td) / "update_log.txt")
            self.assertIn("setup ket thuc, ma 0", text)
            self.assertTrue(exe.exists())
            self.assertFalse(marker.exists(), "installer must wipe old _internal files")
            subprocess.run([str(app_dir / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=300)
            for _ in range(60):
                if not exe.exists():
                    break
                time.sleep(1)
            self.assertFalse(exe.exists(), "uninstall must remove the app")


@unittest.skipUnless(sys.platform == "darwin" and os.environ.get("TTS_CI_MAC_ZIP"), "real macOS update test (CI)")
class MacRealUpdateTests(unittest.TestCase):
    """Real .app from the release zip: extract with ditto, swap with the helper, re-verify the signature."""

    def test_swap_real_app(self):
        zip_path = os.environ["TTS_CI_MAC_ZIP"]
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            apps = td / "Applications thử"
            apps.mkdir()
            old = updater.extract_mac_zip(zip_path, str(td / "old_x"))
            target = apps / "TTSCloneStudio.app"
            subprocess.run(["ditto", str(old), str(target)], check=True)
            (target / "Contents" / "OLD_MARKER").write_text("old")
            staging = td / "updates" / "mac_9.9.9"
            new_app = updater.extract_mac_zip(zip_path, str(staging))
            sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"])
            threading.Thread(target=sleeper.wait, daemon=True).start()
            log = td / "update_log.txt"
            os.environ["TTS_UPDATE_NO_RELAUNCH"] = "1"
            try:
                updater.launch_helper("mac-app", new_path=str(new_app), target=str(target), log=str(log),
                                      staging=str(staging), pid=sleeper.pid)
            finally:
                del os.environ["TTS_UPDATE_NO_RELAUNCH"]
            deadline = time.time() + 180
            while time.time() < deadline and not (log.exists() and "xong" in log.read_text()):
                time.sleep(1)
            text = log.read_text() if log.exists() else "no log"
            self.assertIn("da thay app", text)
            self.assertFalse((target / "Contents" / "OLD_MARKER").exists())
            self.assertFalse(staging.exists())
            r = subprocess.run(["codesign", "--verify", "--deep", "--strict", str(target)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(sorted(p.name for p in apps.iterdir()), ["TTSCloneStudio.app"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
