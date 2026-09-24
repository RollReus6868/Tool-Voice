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

SYNTH_CALLS = []
class FakeProv:
    def __init__(self, fail_on=None): self.fail_on = fail_on; self.chars_used = 0
    def synthesize(self, text, vid, out, **kw):
        time.sleep(0.05)
        SYNTH_CALLS.append((text, kw))
        if "LỖI" in text: raise RuntimeError("Giả lập lỗi API")
        shutil.copyfile(tone, out); self.chars_used += len(text); return out
    def list_voices(self):
        return [
            {"voice_id": "Sarah", "name": "Sarah", "kind": "Hệ thống", "language": "en-US", "gender": "Nữ",
             "description": "Support agent", "tags": ["calm"], "source": "SYSTEM"},
            {"voice_id": "Mai", "name": "Mai", "kind": "Hệ thống", "language": "vi-VN", "gender": "Nữ",
             "description": "Giọng miền Bắc", "tags": [], "source": "SYSTEM"},
            {"voice_id": "ws__toi", "name": "Giọng clone của tôi", "kind": "Của tôi", "language": "vi-VN",
             "gender": "", "description": "", "tags": [], "source": "IVC"},
        ]
import dialogs
workers.build_provider = main.build_provider = dialogs.build_provider = lambda *a, **k: FakeProv()
# settings from 2.1: old default model, before the 2.2 migration; auto-sync tested explicitly below
storage.ConfigStore().save({"model_Inworld": "inworld-tts-2", "defaults_rev": 0, "inworld_auto_sync": False})

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

def shot(name, widget=None):
    pump(4)
    if SHOTS:
        (widget or w).grab().save(str(SHOTS / f"{name}.png"))

def wait_workers(limit=30):
    t0 = time.time()
    while any(x.isRunning() for x in list(w.workers)) and time.time() - t0 < limit: pump(2)
    pump(4)

# ================= 2.2 features
w.open_path = lambda path: None
# default model migrated to flash
assert storage.ConfigStore().load()["model_Inworld"] == "inworld-tts-2-flash"
w.tts_voice.setCurrentIndex(w.tts_voice.findData("u2")); pump()
assert w.tts_model.currentText() == "inworld-tts-2-flash", w.tts_model.currentText()
# Inworld-only options follow the voice / model
o = w.iw_opts["tts"]
assert not o["box"].isHidden()
assert not o["instruction"].isEnabled()
w.tts_model.setCurrentText("inworld-tts-2"); pump()
assert o["instruction"].isEnabled()
w.tts_voice.setCurrentIndex(w.tts_voice.findData("u1")); pump()
assert o["box"].isHidden()
w.tts_voice.setCurrentIndex(w.tts_voice.findData("u2")); pump()
w.tts_model.setCurrentText("inworld-tts-2-flash"); pump()

# usage: budget + TTS run recorded
w.go(main.PAGE_SETTINGS); pump()
w.usage_plan.setCurrentIndex(w.usage_plan.findData("creator")); pump()
assert abs(w.usage_budget.value() - 25.0) < 1e-6, w.usage_budget.value()
o["delivery"].setCurrentIndex(o["delivery"].findData("CREATIVE")); o["enhance"].setChecked(True)
w.tts_text.setPlainText("Xin chào thế giới"); w.tts_format.buttons["mp3"].click(); w.tts_filename.setText("dung_thu")
SYNTH_CALLS.clear()
c_before = main.usage.summary(storage.ConfigStore().load()["inworld_usage"])["chars"]
w.start_tts(); wait_workers()
assert SYNTH_CALLS and SYNTH_CALLS[-1][1]["options"]["delivery"] == "CREATIVE", SYNTH_CALLS[-1:]
assert SYNTH_CALLS[-1][1]["options"]["enhance"] is True
su = main.usage.summary(storage.ConfigStore().load()["inworld_usage"])
assert su["chars"] - c_before == len("Xin chào thế giới") and su["plan"] == "creator", su
assert "%" in w.chip_usage.text() and "Inworld còn" in w.tts_usage.text(), (w.chip_usage.text(), w.tts_usage.text())
# options are shared with the batch page
assert w.iw_opts["batch"]["delivery"].currentData() == "CREATIVE"

# batch: only chosen STT rows run
w.batch_voice.setCurrentIndex(w.batch_voice.findData("u2")); pump()
assert "💵" in w.batch_status.text(), w.batch_status.text()
w.batch_rows.setText("9"); pump()
assert "vượt ngoài" in w.batch_rows_hint.text() and w._selection_error(), w.batch_rows_hint.text()
w.batch_rows.setText("2, 5-"); w._batch_load_tasks(); pump()
assert w.batch_selected == {1, 4, 5}, w.batch_selected
assert w.batch_state[0] == "unselected" and "Không chạy" in w.batch_table.item(0, main.B_STATUS).text()
assert w.tile_total.value.text() == "3/6", w.tile_total.value.text()
out2 = tmp / "out_stt"; w.batch_output_dir.setText(str(out2)); w.batch_skip.setChecked(False)
w.batch_format.buttons["mp3"].click()
before = main.usage.summary(storage.ConfigStore().load()["inworld_usage"])["chars"]
w.start_batch()
t0 = time.time()
while (w.batch_worker.isRunning() or not w.batch_run.isEnabled()) and time.time() - t0 < 60: pump(2)
pump()
made = sorted(p.name for p in out2.iterdir())
assert made == ["1_2.mp3", "2.mp3", "6.mp3"], made
assert w.batch_state == ["unselected", "ok", "unselected", "unselected", "ok", "ok"], w.batch_state
after = main.usage.summary(storage.ConfigStore().load()["inworld_usage"])["chars"]
exp = sum(len(w.batch_tasks[i]["text"]) for i in (1, 4, 5))
assert after - before == exp, (after - before, exp)
assert storage.ConfigStore().load()["batch_rows"] == "2, 5-"

# voice browser dialog
dlg = dialogs.ImportVoicesDialog("Inworld", {}, {}, {"Sarah"}, w, kind="Tất cả", preview=lambda v: w._preview_voice(
    "Inworld", v["voice_id"], v["name"], v.get("language", ""), "pv_" + v["voice_id"]))
dlg.resize(1100, 560); dlg.show()
t0 = time.time()
while not dlg.voices and time.time() - t0 < 10: pump(2)
pump()
assert dlg.table.rowCount() == 2, dlg.table.rowCount()   # auto-filtered to vi-VN
assert dlg.lang.currentData() == "vi-VN"
dlg.lang.setCurrentIndex(0); pump()
assert dlg.table.rowCount() == 3
assert dlg.table.item(0, 0).text().startswith("Giọng clone")    # own voices first
dlg.search.setText("support"); pump()
assert dlg.table.rowCount() == 1 and "đã có" in dlg.table.item(0, 0).text()
dlg.search.setText(""); dlg.gender.setCurrentIndex(dlg.gender.findData("Nữ")); pump()
assert dlg.table.rowCount() == 2
shot("dialog_voices", dlg)
dlg.table.selectRow(1); pump()
assert dlg.use_btn.isEnabled() and dlg.preview_btn.isEnabled()
chars0 = main.usage.summary(storage.ConfigStore().load()["inworld_usage"])["chars"]
dlg._preview(); wait_workers()
assert main.usage.summary(storage.ConfigStore().load()["inworld_usage"])["chars"] > chars0
chosen = dlg.selected()[0]
dlg._use_now(); pump()
assert dlg.use_now == chosen and dlg.result() == 1
w._add_voice("Inworld", chosen["voice_id"], chosen["name"], chosen["language"]); w.refresh_voices()
w.use_voice_id("Inworld", chosen["voice_id"]); pump()
assert w._voice_from_combo(w.tts_voice)["provider_voice_id"] == chosen["voice_id"]

# sync adds only the user's own voices
n0 = len(w.voice_store.list())
w.sync_inworld_voices(silent=True); wait_workers()
names = [v["local_name"] for v in w.voice_store.list()]
assert len(names) == n0 + 1 and "Giọng clone của tôi" in names and "Mai" not in names, names
w.sync_inworld_voices(silent=True); wait_workers()
assert len(w.voice_store.list()) == n0 + 1
# new period
main.QInputDialog.getDouble = staticmethod(lambda *a, **k: (10.0, True))
w.reset_usage(); pump()
su = main.usage.summary(storage.ConfigStore().load()["inworld_usage"])
assert su["chars"] == 0 and su["budget"] == 10.0 and su["plan"] == "creator", su
w.usage_budget.setValue(25.0); w._usage_settings_changed()
w._record_usage("Inworld", "inworld-tts-2-flash", 1_000_000)   # $10 of $25 on Creator
assert "60%" in w.chip_usage.text(), w.chip_usage.text()

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
