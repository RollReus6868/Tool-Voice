"""End-to-end update flow through the real window, against a fake GitHub server.
check -> chip + notes -> install -> download + sha256 -> helper launched -> app quits.
Run: QT_QPA_PLATFORM=offscreen python tests/update_gui_test.py"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
os.environ["APPDATA"] = tempfile.mkdtemp()
os.environ["TTS_NO_UPDATE_CHECK"] = "1"

from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import main  # noqa: E402
import updater  # noqa: E402
from test_updater import FakeGitHub  # noqa: E402

QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: (_ for _ in ()).throw(AssertionError(f"warning: {a[1:3]}")))

app = QApplication(sys.argv)


def pump(until, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        app.processEvents()
        if until():
            return True
        time.sleep(0.02)
    return False


with FakeGitHub() as gh:
    new_ver = "99.0.0"
    name = updater.asset_name(new_ver, "win-portable")
    payload = os.urandom(200_000)
    gh.release(new_ver, {name: payload})

    real_fetch = updater.fetch_latest
    updater.fetch_latest = lambda repo="me/app", timeout=20: real_fetch("me/app", timeout)
    updater.repo_configured = lambda repo=None: True
    updater.install_kind = lambda *a, **k: "win-portable"
    target = Path(tempfile.mkdtemp()) / "TTSCloneStudio.exe"
    target.write_bytes(b"old")
    updater.current_target = lambda kind: str(target)
    launched = {}
    updater.launch_helper = lambda kind, **kw: launched.update(kind=kind, **kw) or "script"

    w = main.MainWindow()
    w.show()
    quit_called = []
    app.quit = lambda: quit_called.append(True)

    # 1. check -> newer found
    w.check_updates(silent=False)
    assert pump(lambda: w.upd_install_btn.isEnabled()), w.upd_status.text()
    assert "99.0.0" in w.upd_status.text(), w.upd_status.text()
    assert not w.update_chip.isHidden(), "update chip must be visible"
    assert "99.0.0" in w.upd_notes.toPlainText()

    # 2. install -> download, verify, launch helper, quit
    w.install_update(confirm=True)
    assert pump(lambda: bool(launched) and quit_called, 30), (w.upd_status.text(), launched)
    assert launched["kind"] == "win-portable"
    assert Path(launched["new_path"]).read_bytes() == payload
    assert launched["target"] == str(target)
    assert launched["log"].endswith("update_log.txt")
    assert w._quitting_for_update

    # 3. same version -> "latest" message, chip hidden
    w2 = main.MainWindow()
    gh.release(main.APP_VERSION, {})
    w2.check_updates(silent=False)
    assert pump(lambda: "mới nhất" in w2.upd_status.text()), w2.upd_status.text()
    assert w2.update_chip.isHidden() and not w2.upd_install_btn.isEnabled()

    # 4. release lacks this platform's file -> warning, no helper
    launched.clear()
    gh.release("99.0.1", {updater.asset_name("99.0.1", "win-setup"): b"x"})
    w2.check_updates(silent=False)
    assert pump(lambda: "99.0.1" in w2.upd_status.text())
    warned = []
    QMessageBox.warning = staticmethod(lambda *a, **k: warned.append(a[1]))
    main.QDesktopServices.openUrl = staticmethod(lambda url: True)
    w2.install_update(confirm=False)
    assert warned and not launched, warned

print("update GUI test passed")
