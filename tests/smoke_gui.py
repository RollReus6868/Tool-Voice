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
os.environ["INWORLD_API_KEY"] = "fake"
os.environ["TTS_OMNI_FAKE"] = "1"      # OmniVoice engine = engine/omni_server.py writing tones (no torch needed)
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
import dialogs, omni, providers
REAL_BUILD = providers.build_provider
# Inworld is faked; OmniVoice goes through the real provider and the (fake-mode) engine process
workers.build_provider = main.build_provider = dialogs.build_provider = (
    lambda name, *a, **k: REAL_BUILD(name, *a, **k) if name == "OmniVoice" else FakeProv())
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
def wait_workers(limit=30):
    t0 = time.time()
    while any(x.isRunning() for x in list(w.workers)) and time.time() - t0 < limit: pump(2)
    pump(4)
w.open_path = lambda path: None

# ================= 3.0: MiniMax removed, OmniVoice added
assert w.stack.count() == 9 and len(main.NAV) == 9
assert [v["uid"] for v in vs.list()] == ["u2", "u3"], vs.list()            # the MiniMax voice was dropped...
assert (storage.APP_DIR / "voices_removed.json").exists()                   # ...and kept in a backup file
assert storage.ConfigStore().load()["defaults_rev"] == 3
assert "MiniMax" not in w.clone_provider.buttons and "OmniVoice" in w.clone_provider.buttons
assert not hasattr(w, "mm_key") and "OmniVoice" in w.chip_omni.text()
# clone a voice with OmniVoice (transcript left empty -> written by the engine)
sample = tmp / "mau.mp3"
subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=4", "-c:a", "libmp3lame", str(sample)], check=True)
w.go(main.PAGE_CLONE); w.clone_provider.buttons["OmniVoice"].click(); pump()
assert w.clone_language.currentData() == "vi" and w.clone_language.count() > 600
assert not w.clone_ov_box.isHidden() and w.clone_denoise.isHidden()
w.clone_sample.setText(str(sample)); assert w._validate_sample(), w.clone_sample_info.text()
w.transcribe_sample(); wait_workers()
assert w.clone_ref_text.toPlainText() == "lời thoại do máy chép", w.clone_ref_text.toPlainText()
w.clone_ref_text.setPlainText(""); w.clone_name.setText("Giọng nam MC"); w.clone_instruct.setText("male, low pitch")
w.clone_consent.setChecked(True)
w.start_clone(); wait_workers()
ov = [v for v in vs.list() if v["provider"] == "OmniVoice"]
assert len(ov) == 1 and ov[0]["ref_text"] == "lời thoại do máy chép" and ov[0]["instruct"] == "male, low pitch", ov
assert ov[0]["language"] == "vi" and ov[0]["ov_kind"] == "clone"
assert omni.voice_prompt(ov[0]["provider_voice_id"]).is_file() and omni.voice_wav(ov[0]["provider_voice_id"]).is_file()
OV = ov[0]["uid"]
if SHOTS: w.grab().save(str(SHOTS / "clone_omnivoice.png"))

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
w.tts_voice.setCurrentIndex(w.tts_voice.findData(OV)); pump()
assert w.tts_model.itemText(0) == "k2-fsa/OmniVoice" and w.tts_speed.maximum() == 1.5
assert "miễn phí" in w.tts_voice_info.text() and "male, low pitch" in w.tts_voice_info.toolTip()
w.tts_voice.setCurrentIndex(w.tts_voice.findData("u2")); pump()
assert w.tts_model.itemText(0).startswith("inworld") and w.tts_speed.maximum() == 1.5
w.clone_provider.buttons["Inworld"].click(); pump()
assert w.clone_language.currentData() == "vi-VN" and w.clone_ov_box.isHidden() and not w.clone_denoise.isHidden()
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

# ================= 2.2 features
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
w.tts_voice.setCurrentIndex(w.tts_voice.findData(OV)); pump()
assert o["box"].isHidden() and not w.ov_boxes["tts"].isHidden()
w.tts_voice.setCurrentIndex(w.tts_voice.findData("u2")); pump()
assert w.ov_boxes["tts"].isHidden()
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
# usage page: sync with the numbers from Inworld's Billing / Usage pages
w.go(main.PAGE_USAGE); pump()
sd = dialogs.SyncUsageDialog(w._usage_data(), w)
sd.balance.setText("$24.97"); sd.total.setText("2,755 characters")
sd.model_edits["inworld-tts-2-flash"].setText("2.5K"); sd.model_edits["inworld-tts-2"].setText("270"); pump()
assert sd.ok_btn.isEnabled() and "2.485" in sd.preview.text(), sd.preview.text()
shot("dialog_sync", sd)
bal, chars, days = sd._parse()
assert (bal, chars, days) == (24.97, {"inworld-tts-2-flash": 2485, "inworld-tts-2": 270}, 30), (bal, chars, days)
sd.total.setText("abc"); pump()
assert not sd.ok_btn.isEnabled() and "⚠" in sd.preview.text()
sd.close()
w.apply_usage_sync(bal, chars, days); pump()
d = w._usage_data()
se = main.usage.series(d, "30d")
assert se["sync_included"] and se["totals"]["inworld-tts-2"]["chars"] >= 270, se["totals"]
assert w.usage_view.value() == "30d"
assert w.usage_table.rowCount() == len(se["models"]) + 1
assert w.usage_table.item(w.usage_table.rowCount() - 1, 1).text() == main.usage.fmt_int(se["chars"])
assert "đồng bộ" in w.usage_legend.text() and "vừa xong" in w.u_tile_sync.value.text()
su = main.usage.summary(d)
assert su["source"] == "sync" and 0 < su["remaining"] <= 24.97, su
w.usage_view.set_value("24h", emit=True); pump()
assert "30 ngày" in w.usage_note.text(), w.usage_note.text()
w.usage_group.set_value("total", emit=True); pump()
assert w.usage_table.rowCount() == 1
w.usage_group.set_value("model", emit=True); w.usage_view.set_value("30d", emit=True); pump()
# chip opens the usage page
w.go(main.PAGE_TTS); w.chip_usage.mousePressEvent(None); pump()
assert w.stack.currentIndex() == main.PAGE_USAGE
# the 100 % credit only drives "remaining" until a balance is synced
w.usage_budget.setValue(25.0); w._usage_settings_changed()
before = main.usage.summary(w._usage_data())["remaining"]
w._record_usage("Inworld", "inworld-tts-2-flash", 1_000_000)   # $10 on Creator
after = main.usage.summary(w._usage_data())["remaining"]
assert abs((before - after) - 10.0) < 1e-6, (before, after)
assert "%" in w.chip_usage.text(), w.chip_usage.text()

# ================= 3.0: OmniVoice end to end (fake engine) =================
w.go(main.PAGE_OMNI); pump()
assert "Đã cài" in w.omni_status.text() and w.omni_load_btn.isEnabled(), w.omni_status.text()
# generation settings are saved as soon as they change and travel with every request
w.ov_fields["num_step"].setValue(16); w.ov_fields["denoise"].setChecked(False); w.ov_fields["normalize_text"].setChecked(True); pump()
cfg = storage.ConfigStore().load()
assert (cfg["ov_num_step"], cfg["ov_denoise"], cfg["ov_normalize_text"]) == (16, False, True), cfg
REQS = []
_real_request = omni.ENGINE.request
def _spy(req, **kw):
    REQS.append(dict(req)); return _real_request(req, **kw)
omni.ENGINE.request = _spy
# read text with the cloned OmniVoice voice: free, so the Inworld usage must not move
w.go(main.PAGE_TTS); w.tts_voice.setCurrentIndex(w.tts_voice.findData(OV)); pump()
assert "miễn phí" in w.tts_usage.text() and not w.tts_usage.isHidden(), w.tts_usage.text()
tags = w.ov_boxes["tts"].findChild(main.QComboBox)
w.tts_text.setPlainText(""); tags.setCurrentIndex(1); tags.activated.emit(1); pump()
assert w.tts_text.toPlainText() == "[laughter] " and tags.currentIndex() == 0, w.tts_text.toPlainText()
w.tts_text.setPlainText("[laughter] Xin chào từ OmniVoice. " * 24)       # 800+ chars -> 2 requests
assert "2 đoạn" in w.tts_counter.text() and "💵" not in w.tts_counter.text(), w.tts_counter.text()
w.tts_speed.setValue(1.2); w.tts_format.buttons["both"].click(); w.tts_filename.setText("omni_doc")
u0 = main.usage.summary(storage.ConfigStore().load()["inworld_usage"])["chars"]
w.start_tts(); wait_workers(60)
assert (out / "omni_doc.mp3").exists() and (out / "omni_doc.mp4").exists(), w.tts_result.text()
tts = [r for r in REQS if r["cmd"] == "tts"]
assert len(tts) == 2 and tts[0]["prompt"].endswith(ov[0]["provider_voice_id"] + ".pt"), tts
assert tts[0]["instruct"] == "male, low pitch" and tts[0]["speed"] == 1.2 and tts[0]["language"] == "vi", tts[0]
assert tts[0]["config"]["num_step"] == 16 and tts[0]["config"]["denoise"] is False and tts[0]["normalize_text"] is True
assert main.usage.summary(storage.ConfigStore().load()["inworld_usage"])["chars"] == u0
# fixed duration: one request for the whole text, speed ignored
w.ov_fields["duration"].setValue(2.0); pump(); REQS.clear()
w.tts_filename.setText("omni_2s"); w.tts_format.buttons["mp3"].click(); w.start_tts(); wait_workers(60)
tts = [r for r in REQS if r["cmd"] == "tts"]
assert len(tts) == 1 and tts[0]["duration"] == 2.0 and "speed" not in tts[0], tts
assert 1.7 < media.probe_duration(str(out / "omni_2s.mp3")) < 2.4
w.ov_fields["duration"].setValue(0.0); pump()
# voice design: preview, then keep exactly that voice
w.go(main.PAGE_OMNI); pump(); REQS.clear()
w.design_combos[0].setCurrentIndex(w.design_combos[0].findData("female"))
w.design_combos[2].setCurrentIndex(w.design_combos[2].findData("high pitch"))
assert w._design_instruct() == "female, high pitch"
assert not w.design_save_btn.isEnabled()
w.design_preview(); wait_workers(60)
assert w.design_last and Path(w.design_last["wav"]).is_file() and w.design_save_btn.isEnabled(), w.design_status.text()
assert REQS[-1]["instruct"] == "female, high pitch" and REQS[-1]["prompt"] is None and REQS[-1]["language"] == "vi", REQS[-1]
w.design_name.setText("Nữ trẻ giọng cao"); w.design_save(); wait_workers(60)
des = [v for v in vs.list() if v.get("ov_kind") == "design"]
assert len(des) == 1 and des[0]["instruct"] == "female, high pitch" and des[0]["ref_text"] == main.DESIGN_TEXT["vi"], des
assert REQS[-1]["cmd"] == "prompt" and REQS[-1]["ref_text"] == main.DESIGN_TEXT["vi"]
assert w._voice_from_combo(w.tts_voice)["uid"] == des[0]["uid"]            # selected for reading right away
for c in w.design_combos: c.setCurrentIndex(0)
assert w._design_instruct() == ""                                           # all "Tự động" = Auto Voice
shot("omni_page")
# batch with the designed voice: the "LỖI" row fails inside the engine, the others are written
w.go(main.PAGE_BATCH); w.batch_voice.setCurrentIndex(w.batch_voice.findData(des[0]["uid"])); pump()
assert not w.ov_boxes["batch"].isHidden() and w.iw_opts["batch"]["box"].isHidden()
w.batch_rows.setText(""); w._batch_load_tasks(); pump()
assert "💵" not in w.batch_status.text(), w.batch_status.text()
out3 = tmp / "out_omni"; w.batch_output_dir.setText(str(out3)); w.batch_threads.setValue(3); w.batch_merge.setChecked(True)
w.start_batch()
t0 = time.time()
while (w.batch_worker.isRunning() or not w.batch_run.isEnabled()) and time.time() - t0 < 120: pump(2)
pump()
assert w.batch_state.count("ok") == 5 and w.batch_state.count("error") == 1, w.batch_state
assert "Giả lập lỗi" in w.batch_table.item(2, main.B_STATUS).text(), w.batch_table.item(2, main.B_STATUS).text()
assert (out3 / "kich_ban_GOP.mp3").exists(), sorted(p.name for p in out3.iterdir())
w.batch_merge.setChecked(False); w.batch_rows.setText("2, 5-")
# preview + delete: an OmniVoice voice lives only on this computer, so deleting removes its files
w._preview_voice("OmniVoice", des[0]["provider_voice_id"], des[0]["local_name"], "vi", "pv_omni"); wait_workers(60)
assert (storage.APP_DIR / "preview" / "pv_omni.mp3").exists()
w.go(main.PAGE_CLONE); w.voice_table.selectRow(w.voice_table.rowCount() - 1); pump()
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
w.remove_selected_voice(); pump()
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
assert not [v for v in vs.list() if v.get("ov_kind") == "design"]
assert not omni.voice_prompt(des[0]["provider_voice_id"]).exists()
# engine controls
assert omni.ENGINE.running()
w.omni_load(); wait_workers(30); assert omni.ENGINE.device == "giả lập" and "giả lập" in w.omni_status.text()
w.omni_stop(); pump(); assert not omni.ENGINE.running() and not w.omni_stop_btn.isEnabled()
omni.ENGINE.request = _real_request
# not installed: nothing is sent, the user is taken to the OmniVoice page (the warning box counts as 1 dialog)
n_err = len(errors)
os.environ.pop("TTS_OMNI_FAKE"); w._refresh_omni(); pump()
# (a Mac with an Intel chip cannot run OmniVoice at all: the page says so instead of offering the install)
expect = "không chạy được" if omni.unsupported_reason() else "Chưa cài"
assert expect in w.omni_status.text() and "⚪" in w.chip_omni.text() and not w.omni_load_btn.isEnabled(), w.omni_status.text()
assert w.omni_install_btn.isEnabled() == (not omni.unsupported_reason())
assert "Cài đặt bộ máy" in w.omni_install_btn.text()
w.go(main.PAGE_TTS); w.tts_voice.setCurrentIndex(w.tts_voice.findData(OV)); pump()
assert not w._provider_ready("OmniVoice") and w.stack.currentIndex() == main.PAGE_OMNI
assert len(errors) == n_err + 1 and "Chưa cài OmniVoice" in errors[-1], errors[n_err:]
del errors[n_err:]
os.environ["TTS_OMNI_FAKE"] = "1"; w._refresh_omni(); pump()
w.ov_fields["num_step"].setValue(8); w._ov_reset(); pump()
assert w.ov_fields["num_step"].value() == 32 and w.ov_fields["denoise"].isChecked() and not w.ov_fields["normalize_text"].isChecked()

# ================= 3.0: two looks (classic / Youwee), both modes, every page
w.tts_voice.setCurrentIndex(w.tts_voice.findData("u2")); pump()
w.tts_format.buttons["mp3"].click()
PAGES = ["clone", "tts", "batch", "video", "omni", "settings", "usage", "update", "guide"]
assert w.ui_style.value() == "classic" and not w.ui_theme.isEnabled()
for style in ("classic", "youwee"):
    w.ui_style.set_value(style, emit=True); pump()
    assert storage.ConfigStore().load()["ui_style"] == style
    for mode in ("dark", "light"):
        w.apply_theme(mode); pump()
        for i, n in enumerate(PAGES):
            w.go(i)
            if n == "video": w._update_video_preview()
            sa = w.stack.widget(i).findChild(main.QScrollArea)
            assert sa.horizontalScrollBar().maximum() == 0, (style, mode, n, sa.horizontalScrollBar().maximum())
            shot(f"{style}_{mode}_{i}_{n}")
assert w.ui_theme.isEnabled() and "Nunito" in app.styleSheet()
w.ui_theme.set_value("sunset", emit=True); pump()
assert storage.ConfigStore().load()["ui_theme"] == "sunset" and main.youwee_colors("light", "sunset")["primary"] in app.styleSheet()
shot("youwee_sunset_settings", None) if not w.go(main.PAGE_SETTINGS) else None
w.ui_style.set_value("classic", emit=True); pump()
assert "Nunito" not in app.styleSheet()
w.close(); pump()
assert not omni.ENGINE.running()
print("errors:", len(errors))
for e in errors: print(e[:600])
sys.exit(1 if errors else 0)
