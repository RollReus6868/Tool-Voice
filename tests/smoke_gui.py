"""GUI smoke test (fake TTS provider, real ffmpeg). Run: QT_QPA_PLATFORM=offscreen python tests/smoke_gui.py [shots_dir|- W H]"""
import os, sys, shutil, tempfile, time, subprocess, traceback
from pathlib import Path
APP = Path(__file__).resolve().parents[1]
SHOTS = Path(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] != "-" else None
if SHOTS:
    SHOTS.mkdir(parents=True, exist_ok=True)
W, H = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (1400, 900)
tmp = Path(tempfile.mkdtemp()); os.environ["APPDATA"] = str(tmp / "appdata")
os.environ["TTS_NO_UPDATE_CHECK"] = "1"
os.environ["INWORLD_API_KEY"] = "fake"; os.environ["MINIMAX_API_KEY"] = "fake"
sys.path.insert(0, str(APP))
errors = []
sys.excepthook = lambda t, e, tb: (errors.append("".join(traceback.format_exception(t, e, tb))), print("EXC:", "".join(traceback.format_exception(t, e, tb))[-1500:]))

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QTimer
import storage, main, workers, media
# never block on dialogs
for n in ("information", "warning", "critical"):
    setattr(QMessageBox, n, staticmethod(lambda *a, **k: errors.append(f"DIALOG {a[1:3]}") or QMessageBox.StandardButton.Ok))
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
QMessageBox.exec = lambda self: 0

ff = media.find_ffmpeg()
tone = tmp / "tone.mp3"
subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=1.5", "-c:a", "libmp3lame", str(tone)], check=True)
bg = tmp / "bg.jpg"
subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=1280x720", "-frames:v", "1", str(bg)], check=True)

class FakeProv:
    def __init__(self, fail_on=None): self.fail_on = fail_on
    def synthesize(self, text, vid, out, **kw):
        time.sleep(0.05)
        if "LỖI" in text: raise RuntimeError("Giả lập lỗi API")
        shutil.copyfile(tone, out); return out
workers.build_provider = main.build_provider = lambda *a, **k: FakeProv()

vs = storage.VoiceStore()
now = "2026-09-24T10:00:00"
vs.add({"uid": "u1", "local_name": "Giọng nam MC", "provider": "MiniMax", "provider_voice_id": "Giong_nam_MC_260924100000", "language": "Vietnamese", "created_at": now})
vs.add({"uid": "u2", "local_name": "Narrator EN", "provider": "Inworld", "provider_voice_id": "workspace__narrator_en_1727", "language": "en-US", "created_at": now})
vs.add({"uid": "u3", "local_name": "Chị Lan kể chuyện", "provider": "Inworld", "provider_voice_id": "workspace__chi_lan_1727", "language": "VI_VN", "created_at": now})

app = QApplication(sys.argv); app.setStyle("Fusion")
w = main.MainWindow(); w.resize(W, H); w.show()
def pump(n=5):
    for _ in range(n):
        app.processEvents(); time.sleep(0.02)
pump()

# excel
from openpyxl import Workbook
xl = tmp / "kich_ban.xlsx"; wb = Workbook(); ws = wb.active
ws.append(["STT", "Nội dung", "Ghi chú"])
rows = ["Xin chào các bạn, hôm nay mình sẽ hướng dẫn cách tạo giọng đọc tự động.", "Bước một: chuẩn bị file Excel với cột nội dung.",
        "LỖI giả lập dòng này", "Bước ba: bấm chạy hàng loạt và chờ kết quả.", "", "Cảm ơn các bạn đã theo dõi, hẹn gặp lại!"]
for i, r in enumerate(rows, 1): ws.append([i, r, ""])
ws.append([1, "Trùng tên file với dòng 1", ""])
wb.save(xl)
w._open_batch_file(str(xl)); pump()
assert w.batch_text_col.currentText().endswith("Nội dung"), w.batch_text_col.currentText()
assert w.batch_name_col.currentText().endswith("STT"), w.batch_name_col.currentText()
names = [t["filename"] for t in w.batch_tasks]
assert names == ["1", "2", "3", "4", "6", "1_2"], names

# bindings
w.tts_format.buttons["mp4"].click(); pump()
assert w.batch_format.value() == "mp4" and storage.ConfigStore().load()["output_format"] == "mp4"
w.tts_voice.setCurrentIndex(w.tts_voice.findData("u1")); pump()
assert w.tts_model.itemText(0).startswith("speech") and w.tts_speed.maximum() == 2.0
w.tts_voice.setCurrentIndex(w.tts_voice.findData("u2")); pump()
assert w.tts_model.itemText(0).startswith("inworld") and w.tts_speed.maximum() == 1.5
w.clone_provider.buttons["MiniMax"].click(); pump()
assert w.clone_language.currentData() == "Vietnamese"
w.clone_provider.buttons["Inworld"].click(); pump()
assert w.clone_language.currentData() == "vi-VN"
w.tts_text.setPlainText("Xin chào! " * 300); pump()
assert "2.999" in w.tts_counter.text(), w.tts_counter.text()
w._set_video_image(str(bg)); pump()

# full TTS run (fake provider) mp3+mp4
out = tmp / "out"; w.tts_output_dir.setText(str(out)); w.batch_output_dir.setText(str(out))
w.tts_format.buttons["both"].click(); w.tts_filename.setText("thu_nghiem")
w.start_tts()
t0 = time.time()
while (w.tts_worker.isRunning() or not w.tts_generate.isEnabled()) and time.time() - t0 < 60: pump(2)
pump()
assert (out / "thu_nghiem.mp3").exists() and (out / "thu_nghiem.mp4").exists(), list(out.iterdir())
assert w.tts_progress.value() == 100 and "✅" in w.tts_result.text(), w.tts_result.text()

# batch with merge
w.batch_merge.setChecked(True); w.batch_threads.setValue(3)
w.start_batch()
t0 = time.time()
while (w.batch_worker.isRunning() or not w.batch_run.isEnabled()) and time.time() - t0 < 120: pump(2)
pump()
st = w.batch_state
assert st.count("ok") == 5 and st.count("error") == 1, st
assert (out / "kich_ban_GOP.mp3").exists() and (out / "kich_ban_GOP.mp4").exists(), sorted(p.name for p in out.iterdir())
d = media.probe_duration(str(out / "kich_ban_GOP.mp4")); assert 6.5 < d < 8.5, d
assert w.batch_retry.isEnabled()
# rerun with skip -> all skipped except error row
w.batch_merge.setChecked(False)
w.start_batch()
t0 = time.time()
while (w.batch_worker.isRunning() or not w.batch_run.isEnabled()) and time.time() - t0 < 60: pump(2)
pump()
assert w.batch_state.count("skipped") == 5, w.batch_state
print("files:", sorted(p.name for p in out.iterdir()))

def shot(name):
    pump(4)
    if SHOTS:
        w.grab().save(str(SHOTS / f"{name}.png"))

w.tts_format.buttons["mp3"].click()
for mode in ("dark", "light"):
    w.apply_theme(mode); pump()
    for i, n in enumerate(["clone", "tts", "batch", "video", "settings", "update", "guide"]):
        w.go(i)
        if n == "video": w._update_video_preview()
        shot(f"{mode}_{i}_{n}")
w.close(); pump()
print("errors:", len(errors))
for e in errors: print(e[:600])
sys.exit(1 if errors else 0)
