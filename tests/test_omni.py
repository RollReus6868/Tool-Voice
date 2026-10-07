"""OmniVoice integration without Qt and without torch: catalogues, request building, the installer's
commands, the engine process (driven through engine/omni_server.py in fake mode) and the provider."""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import omni  # noqa: E402
import providers  # noqa: E402
import storage  # noqa: E402
from media import find_ffmpeg, probe_duration  # noqa: E402
from utils import validate_voice_sample  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="tts_omni_test_"))
_SAVED: dict = {}


def setUpModule():
    # keep every file of these tests out of the real data folder
    for name, sub in (("ROOT", ""), ("ENV_DIR", "env"), ("MODELS_DIR", "models"), ("VOICES_DIR", "voices"),
                      ("TOOLS_DIR", "tools"), ("MARKER", "install.json")):
        _SAVED[name] = getattr(omni, name)
        setattr(omni, name, TMP / "omni" / sub if sub else TMP / "omni")
    _SAVED["fake"] = os.environ.get("TTS_OMNI_FAKE")
    os.environ["TTS_OMNI_FAKE"] = "1"


def tearDownModule():
    omni.ENGINE.stop()
    for name in ("ROOT", "ENV_DIR", "MODELS_DIR", "VOICES_DIR", "TOOLS_DIR", "MARKER"):
        setattr(omni, name, _SAVED[name])
    if _SAVED["fake"] is None:
        os.environ.pop("TTS_OMNI_FAKE", None)
    else:
        os.environ["TTS_OMNI_FAKE"] = _SAVED["fake"]
    shutil.rmtree(TMP, ignore_errors=True)


def tone(path: Path, seconds: float) -> str:
    subprocess.run([find_ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=duration={seconds}",
                    str(path)], check=True)
    return str(path)


class CatalogueTests(unittest.TestCase):
    def test_languages(self):
        langs = omni.languages()
        codes = [c for _l, c in langs]
        self.assertGreater(len(langs), 600)
        self.assertEqual(langs[0], ("Tự động nhận diện", ""))
        self.assertEqual(langs[1], ("Tiếng Việt", "vi"))
        self.assertEqual(len(codes), len(set(codes)))
        self.assertIn(("Cantonese (yue)", "yue"), langs)
        self.assertEqual(providers.LANGUAGES["OmniVoice"], langs)
        self.assertEqual(providers.language_label("OmniVoice", "vi"), "Tiếng Việt")
        self.assertEqual(providers.normalize_language("OmniVoice", None), "")

    def test_providers_catalogue_has_no_minimax(self):
        self.assertEqual(providers.PROVIDERS, ["Inworld", "OmniVoice"])
        self.assertEqual(set(providers.MODELS), {"Inworld", "OmniVoice"})
        self.assertFalse(hasattr(providers, "MiniMaxProvider"))
        with self.assertRaises(providers.ProviderError):
            providers.build_provider("MiniMax", {"minimax_api_key": "k"}, {})

    def test_design_instruct(self):
        self.assertEqual(omni.build_instruct(["female", "", None, "low pitch", " british accent "]),
                         "female, low pitch, british accent")
        self.assertEqual(omni.build_instruct(["", ""]), "")
        keys = [k for k, _t, _o in omni.DESIGN]
        self.assertEqual(keys, ["gender", "age", "pitch", "style", "accent", "dialect"])
        self.assertEqual(len(omni.NONVERBAL_TAGS), 13)

    def test_check_instruct(self):
        for good in ("", "female", "Female, Low Pitch", "male, elderly, low pitch, whisper, british accent",
                     "女，青年，四川话", "female, young adult, 四川话"):
            self.assertEqual(omni.check_instruct(good), "", good)
        self.assertIn("không hiểu “deep voice”", omni.check_instruct("male, deep voice"))
        self.assertIn("cùng một nhóm", omni.check_instruct("male, female"))
        self.assertIn("cùng một nhóm", omni.check_instruct("low pitch, 高音调"))
        self.assertIn("Không dùng chung", omni.check_instruct("british accent, 四川话"))

    def test_gen_options_are_typed_and_survive_garbage(self):
        o = omni.gen_options({"ov_num_step": "16", "ov_guidance_scale": 3, "ov_denoise": 0, "ov_duration": "abc",
                              "ov_t_shift": None})
        self.assertEqual((o["num_step"], o["guidance_scale"], o["denoise"]), (16, 3.0, False))
        self.assertEqual((o["duration"], o["t_shift"], o["normalize_text"]), (0.0, 0.1, False))
        self.assertEqual(set(o), set(omni.ALL_DEFAULTS))


class RequestTests(unittest.TestCase):
    def test_speed_only_when_not_default(self):
        r = omni.tts_request("a", "o.wav", language="vi", prompt="v.pt", speed=1.0, options=omni.gen_options({}))
        self.assertNotIn("speed", r)
        self.assertNotIn("duration", r)
        self.assertEqual((r["language"], r["prompt"], r["instruct"]), ("vi", "v.pt", None))
        self.assertEqual(set(r["config"]), set(omni.GEN_DEFAULTS))        # only real config fields
        self.assertEqual(omni.tts_request("a", "o", speed=1.25)["speed"], 1.25)

    def test_duration_overrides_speed(self):
        r = omni.tts_request("a", "o", speed=1.3, options={"duration": 10})
        self.assertEqual(r["duration"], 10.0)
        self.assertNotIn("speed", r)

    def test_instruct_from_voice_or_explicit(self):
        self.assertEqual(omni.tts_request("a", "o", options={"instruct": " female "})["instruct"], "female")
        self.assertEqual(omni.tts_request("a", "o", instruct="male", options={"instruct": "female"})["instruct"], "male")
        self.assertIsNone(omni.tts_request("a", "o", instruct="", options={"instruct": "female"})["instruct"])
        self.assertIsNone(omni.tts_request("a", "o", language="")["language"])

    def test_voice_ids_cannot_leave_the_voices_folder(self):
        vid = omni.new_voice_id()
        self.assertEqual(omni.voice_prompt(vid).parent, omni.VOICES_DIR)
        for bad in ("../x", "a/b", "", "a b", "..\\x"):
            with self.assertRaises(omni.ProviderError):
                omni.voice_prompt(bad)


class InstallPlanTests(unittest.TestCase):
    def test_torch_plan(self):
        with mock.patch.object(omni.sys, "platform", "win32"), mock.patch.object(omni, "has_nvidia", lambda: True):
            cuda = omni.torch_plan("auto")
            self.assertEqual(omni.torch_plan("cpu")["key"], "cpu")
        self.assertEqual(cuda["specs"], ["torch==2.8.0+cu128", "torchaudio==2.8.0+cu128"])
        self.assertTrue(cuda["index"].endswith("/whl/cu128"))
        with mock.patch.object(omni.sys, "platform", "win32"), mock.patch.object(omni, "has_nvidia", lambda: False):
            cpu = omni.torch_plan("auto")
            self.assertEqual(omni.torch_plan("cuda")["key"], "cuda")      # the user can force it
        self.assertEqual((cpu["key"], cpu["specs"], cpu["index"]), ("cpu", ["torch==2.8.0", "torchaudio==2.8.0"], ""))
        with mock.patch.object(omni.sys, "platform", "darwin"), mock.patch.object(omni, "has_nvidia", lambda: True):
            self.assertEqual(omni.torch_plan("cuda")["key"], "mps")

    def test_install_commands(self):
        with mock.patch.object(omni.sys, "platform", "win32"):
            steps = omni.install_commands("UV", omni.torch_plan("cuda"))
        venv, torch, ov = (cmd for _what, cmd in steps)
        self.assertEqual(venv[:4], ["UV", "venv", "--python", omni.PYTHON_VERSION])
        self.assertIn("--managed-python", venv)
        self.assertEqual(venv[-1], str(omni.ENV_DIR))
        self.assertEqual(torch[:5], ["UV", "pip", "install", "--python", str(omni.env_python())])
        self.assertIn("torch==2.8.0+cu128", torch)
        self.assertEqual(torch[torch.index("--extra-index-url") + 1], "https://download.pytorch.org/whl/cu128")
        self.assertEqual(torch[torch.index("--index-strategy") + 1], "unsafe-best-match")
        self.assertIn(f"omnivoice=={omni.OMNIVOICE_VERSION}", ov)
        self.assertNotIn("--extra-index-url", ov)
        with mock.patch.object(omni.sys, "platform", "win32"):
            cpu = omni.install_commands("UV", omni.torch_plan("cpu"), python="3.13")
        self.assertNotIn("--managed-python", cpu[0][1])
        self.assertNotIn("--extra-index-url", cpu[1][1])

    def test_uv_wheel_choice(self):
        names = ["uv-1-py3-none-win32.whl", "uv-1-py3-none-win_amd64.whl", "uv-1-py3-none-win_arm64.whl",
                 "uv-1-py3-none-macosx_10_12_x86_64.whl", "uv-1-py3-none-macosx_11_0_arm64.whl",
                 "uv-1-py3-none-musllinux_1_1_x86_64.whl",
                 "uv-1-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
                 "uv-1-py3-none-manylinux_2_28_aarch64.whl", "uv-1.tar.gz"]
        meta = {"urls": [{"filename": n} for n in names]}
        for tag in ("win_amd64", "win_arm64", "macosx_11_0_arm64", "macosx_10_12_x86_64", "manylinux_2_17_x86_64",
                    "manylinux_2_28_aarch64"):
            self.assertIn(f"-none-{tag}", omni.pick_uv_wheel(meta, tag)["filename"])
        self.assertEqual(omni.pick_uv_wheel(meta, "win_amd64")["filename"], "uv-1-py3-none-win_amd64.whl")
        self.assertIn(omni.uv_wheel_tag(), [n.split("-none-")[1].split(".")[0] for n in names[:-1]])
        with self.assertRaises(omni.ProviderError):
            omni.pick_uv_wheel(meta, "plan9")

    def test_child_env_is_clean_and_self_contained(self):
        dirty = {"_MEIPASS2": "x", "_PYI_APPLICATION_HOME_DIR": "x", "PYTHONHOME": "x", "PYTHONPATH": "x",
                 "QT_QPA_PLATFORM": "offscreen", "KEEP": "1"}
        with mock.patch.dict(os.environ, dirty):
            env = omni.child_env({"EXTRA": "2"})
        for key in ("_MEIPASS2", "_PYI_APPLICATION_HOME_DIR", "PYTHONHOME", "PYTHONPATH", "QT_QPA_PLATFORM"):
            self.assertNotIn(key, env)
        self.assertEqual((env["KEEP"], env["EXTRA"], env["PYTHONUTF8"]), ("1", "2", "1"))
        for key in ("HF_HOME", "UV_PYTHON_INSTALL_DIR", "UV_CACHE_DIR"):
            self.assertTrue(env[key].startswith(str(omni.ROOT)), key)

    def test_unsupported_only_on_intel_mac(self):
        self.addCleanup(os.environ.__setitem__, "TTS_OMNI_FAKE", "1")
        self.assertEqual(omni.unsupported_reason(), "")                     # the test engine runs anywhere
        os.environ.pop("TTS_OMNI_FAKE")
        with mock.patch.object(omni.sys, "platform", "darwin"), mock.patch.object(omni.platform, "machine", lambda: "x86_64"):
            self.assertIn("Intel", omni.unsupported_reason())
        with mock.patch.object(omni.sys, "platform", "darwin"), mock.patch.object(omni.platform, "machine", lambda: "arm64"):
            self.assertEqual(omni.unsupported_reason(), "")
        with mock.patch.object(omni.sys, "platform", "win32"), mock.patch.object(omni.platform, "machine", lambda: "AMD64"):
            self.assertEqual(omni.unsupported_reason(), "")

    def test_friendly_errors(self):
        self.assertIn("Hết bộ nhớ", omni.friendly_error("torch.OutOfMemoryError: CUDA out of memory. Tried…"))
        self.assertIn("HuggingFace", omni.friendly_error("ProxyError: 403 Forbidden"))
        self.assertEqual(omni.friendly_error("ValueError: x"), "ValueError: x")


class _FakeResp:
    def __init__(self, payload=None, body=b""):
        self.payload, self.body = payload, body

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload

    def iter_content(self, _n):
        yield self.body[: len(self.body) // 2]
        yield self.body[len(self.body) // 2:]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class UvDownloadTests(unittest.TestCase):
    def _wheel(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("uv-1.data/scripts/uv.exe" if os.name == "nt" else "uv-1.data/scripts/uv", b"#!fake uv\n")
            z.writestr("uv-1.dist-info/METADATA", "x")
        return buf.getvalue()

    def _session(self, sha: str, body: bytes):
        item = {"filename": f"uv-1-py3-none-{omni.uv_wheel_tag()}.whl", "url": "https://files/uv.whl",
                "digests": {"sha256": sha}}
        calls = []

        class S:
            def get(self, url, **kw):
                calls.append(url)
                return _FakeResp({"urls": [item]}) if url.endswith("/json") else _FakeResp(body=body)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return S, calls

    def setUp(self):
        shutil.rmtree(omni.TOOLS_DIR, ignore_errors=True)

    def test_download_checks_sha256_and_extracts(self):
        body = self._wheel()
        S, calls = self._session(hashlib.sha256(body).hexdigest(), body)
        with mock.patch("requests.Session", S):
            exe = omni.ensure_uv()
        self.assertEqual(exe.read_bytes(), b"#!fake uv\n")
        self.assertEqual(calls[0], f"https://pypi.org/pypi/uv/{omni.UV_VERSION}/json")
        self.assertFalse((omni.TOOLS_DIR / "uv.whl").exists())
        with mock.patch("requests.Session", side_effect=AssertionError("must not download twice")):
            self.assertEqual(omni.ensure_uv(), exe)

    def test_wrong_digest_is_refused(self):
        body = self._wheel()
        S, _calls = self._session("0" * 64, body)
        with mock.patch("requests.Session", S), self.assertRaises(omni.ProviderError) as cm:
            omni.ensure_uv()
        self.assertIn("SHA-256", str(cm.exception))
        self.assertFalse(omni.uv_path().exists())


class InstallFlowTests(unittest.TestCase):
    """install() with the downloads and commands replaced: order, marker, clean-up."""

    def setUp(self):
        os.environ.pop("TTS_OMNI_FAKE", None)
        self.addCleanup(os.environ.__setitem__, "TTS_OMNI_FAKE", "1")
        omni.MARKER.unlink(missing_ok=True)
        shutil.rmtree(omni.ENV_DIR, ignore_errors=True)

    def test_steps_and_marker(self):
        ran, marks, logs = [], [], []

        def run_step(cmd, log, cancelled, what):
            ran.append(cmd)
            if cmd[1] == "venv":
                omni.env_python().parent.mkdir(parents=True)
                omni.env_python().write_text("")
                (omni.ROOT / "cache").mkdir(exist_ok=True)
            return 'OMNI_OK {"omnivoice": "0.2.1", "torch": "2.8.0+cu128", "cuda": false, "gpu": ""}'

        self.assertFalse(omni.is_installed())
        disk = mock.Mock(free=50 * 1024 ** 3)
        with mock.patch.object(omni, "ensure_uv", lambda log, cancelled: Path("UV")), \
                mock.patch.object(omni, "_run_step", run_step), \
                mock.patch.object(omni.sys, "platform", "win32"), \
                mock.patch.object(omni.shutil, "disk_usage", lambda _p: disk), \
                mock.patch.object(omni, "unsupported_reason", lambda: ""):
            info = omni.install(logs.append, None, marks.append, hardware="cuda")
        self.assertEqual([c[1] for c in ran[:3]], ["venv", "pip", "pip"])
        self.assertEqual(ran[3][0], str(omni.env_python()))
        self.assertEqual((info["plan"], info["omnivoice"]), ("cuda", "0.2.1"))
        self.assertTrue(omni.is_installed())
        self.assertEqual(omni.install_info()["torch"], "2.8.0+cu128")
        self.assertEqual(marks[-1], 100)
        self.assertEqual(marks, sorted(marks))
        self.assertTrue(any("không thấy GPU" in m for m in logs))          # CUDA build but no GPU seen
        self.assertFalse((omni.ROOT / "cache").exists())
        omni.uninstall()
        self.assertFalse(omni.is_installed())
        self.assertFalse(omni.ENV_DIR.exists())

    def test_low_disk_is_refused_before_downloading(self):
        disk = mock.Mock(free=3 * 1024 ** 3)
        with mock.patch.object(omni, "ensure_uv", side_effect=AssertionError("must not download")), \
                mock.patch.object(omni.shutil, "disk_usage", lambda _p: disk), \
                mock.patch.object(omni, "unsupported_reason", lambda: ""), \
                self.assertRaises(omni.ProviderError) as cm:
            omni.install(lambda m: None)
        self.assertIn("3.0 GB trống", str(cm.exception))

    def test_failed_step_leaves_it_not_installed(self):
        def run_step(cmd, log, cancelled, what):
            raise omni.ProviderError(what + " thất bại")

        disk = mock.Mock(free=50 * 1024 ** 3)
        with mock.patch.object(omni, "ensure_uv", lambda log, cancelled: Path("UV")), \
                mock.patch.object(omni.shutil, "disk_usage", lambda _p: disk), \
                mock.patch.object(omni, "_run_step", run_step), self.assertRaises(omni.ProviderError):
            omni.install(lambda m: None)
        self.assertFalse(omni.is_installed())

    def test_run_step_reports_output_and_failure(self):
        omni.ROOT.mkdir(parents=True, exist_ok=True)
        out = omni._run_step([sys.executable, "-c", "print('hello'); print('OMNI_OK {}')"], lambda m: None, None, "thử")
        self.assertIn("OMNI_OK {}", out)
        with self.assertRaises(omni.ProviderError) as cm:
            omni._run_step([sys.executable, "-c", "import sys; print('boom'); sys.exit(3)"], lambda m: None, None, "Bước X")
        self.assertIn("Bước X thất bại (mã 3)", str(cm.exception))
        self.assertIn("boom", str(cm.exception))
        with self.assertRaises(omni.CancelledError):
            omni._run_step([sys.executable, "-c", "import time; time.sleep(30)"], lambda m: None, lambda: True, "x")


class EngineTests(unittest.TestCase):
    def tearDown(self):
        omni.ENGINE.stop()

    def test_roundtrip_logs_errors_and_restart(self):
        logs = []
        hello = omni.ENGINE.request({"cmd": "hello"}, log=logs.append)
        self.assertTrue(hello["fake"])
        self.assertTrue(omni.ENGINE.running())
        self.assertTrue(any("khởi động" in m for m in logs))
        self.assertEqual(omni.ENGINE.request({"cmd": "load", "model": "m"}, log=logs.append)["device"], "giả lập")
        self.assertEqual(omni.ENGINE.device, "giả lập")
        self.assertTrue(any("nạp model" in m for m in logs))               # {"event": "log"} lines reach the log
        wav = str(TMP / "e.wav")
        r = omni.ENGINE.request(omni.tts_request("Tiếng Việt có dấu “ngoặc”", wav, language="vi"))
        self.assertEqual(r["echo"]["text"], "Tiếng Việt có dấu “ngoặc”")      # UTF-8 both ways
        self.assertAlmostEqual(probe_duration(wav), r["seconds"], delta=0.05)
        with self.assertRaises(omni.ProviderError) as cm:
            omni.ENGINE.request(omni.tts_request("LỖI", wav))
        self.assertIn("Giả lập lỗi", str(cm.exception))
        self.assertTrue(omni.ENGINE.running())                             # an error does not kill the engine
        omni.ENGINE.stop()
        self.assertFalse(omni.ENGINE.running())
        self.assertTrue(omni.ENGINE.request({"cmd": "hello"})["fake"])     # starts again by itself

    def test_cancel(self):
        with self.assertRaises(omni.CancelledError):
            omni.ENGINE.request({"cmd": "hello"}, cancel=lambda: True)
        self.assertFalse(omni.ENGINE.running())

    def test_engine_death_is_reported(self):
        omni.ENGINE.request({"cmd": "hello"})
        with mock.patch.object(omni.ENGINE, "command", lambda: [sys.executable, "-c", "import sys; sys.stderr.write('no torch here'); sys.exit(1)"]):
            omni.ENGINE.stop()
            with self.assertRaises(omni.ProviderError) as cm:
                omni.ENGINE.request({"cmd": "hello"})
        self.assertIn("dừng đột ngột", str(cm.exception))
        self.assertIn("no torch here", str(cm.exception))

    def test_not_installed_message(self):
        with mock.patch.object(omni, "is_installed", lambda: False), self.assertRaises(omni.ProviderError) as cm:
            omni.ENGINE.request({"cmd": "hello"})
        self.assertIn("Chưa cài bộ máy", str(cm.exception))


class ProviderTests(unittest.TestCase):
    def tearDown(self):
        omni.ENGINE.stop()

    def test_clone_then_read(self):
        logs = []
        p = providers.build_provider("OmniVoice", {}, {"ov_preprocess_prompt": False}, log=logs.append)
        self.assertIsInstance(p, providers.OmniVoiceProvider)
        sample = tone(TMP / "sample.mp3", 4)
        vid = p.clone_voice(sample, "Thử", "vi", ref_text="")
        self.assertTrue(vid.startswith("ov_"))
        self.assertEqual(p.last_ref_text, "lời thoại do máy chép")          # empty transcript -> written by the engine
        self.assertAlmostEqual(probe_duration(str(omni.voice_wav(vid))), 4.0, delta=0.2)   # reference kept as WAV
        saved = json.loads(omni.voice_prompt(vid).read_text(encoding="utf-8"))
        self.assertEqual(saved["fake_prompt"], str(omni.voice_wav(vid)))
        vid2 = p.clone_voice(sample, "Thử 2", "vi", ref_text="xin chào các bạn")
        self.assertEqual(p.last_ref_text, "xin chào các bạn")

        out = str(TMP / "read.mp3")
        text = "Xin chào các bạn. " * 70                                    # 1,260 chars -> 3 requests of <= 500
        p.synthesize(text, vid, out, model="", speed=1.2, language="vi", options={**omni.gen_options({}), "instruct": "female"})
        self.assertEqual(sum("đoạn" in m for m in logs), 3)
        self.assertAlmostEqual(p.chars_used, len(text.strip()), delta=4)     # chunks are stripped at the cuts
        self.assertGreater(probe_duration(out), 5)

        logs.clear()
        p.synthesize(text, vid2, out, options={"duration": 2.0})          # fixed duration = one request, never split
        self.assertEqual(sum("đoạn" in m for m in logs), 0)
        self.assertAlmostEqual(probe_duration(out), 2.0, delta=0.3)

        omni.delete_voice(vid)
        with self.assertRaises(providers.ProviderError) as cm:
            p.synth_chunk("a", vid, model="", speed=1, language="")
        self.assertIn("Không tìm thấy dữ liệu", str(cm.exception))

    def test_failed_clone_leaves_no_files(self):
        p = providers.OmniVoiceProvider({})
        before = set(omni.VOICES_DIR.glob("*")) if omni.VOICES_DIR.exists() else set()
        with mock.patch.object(omni.ENGINE, "request", side_effect=omni.ProviderError("hỏng")), \
                self.assertRaises(omni.ProviderError):
            p.clone_voice(tone(TMP / "s2.wav", 3), "x", "vi")
        self.assertEqual(set(omni.VOICES_DIR.glob("*")), before)

    def test_design_and_transcribe(self):
        p = providers.OmniVoiceProvider({})
        seen = []
        real = omni.ENGINE.request

        def spy(req, **kw):
            seen.append(dict(req))
            return real(req, **kw)

        with mock.patch.object(omni.ENGINE, "request", spy):
            wav = p.design("Hello there", "female, british accent", str(TMP / "d.wav"), language="en",
                           model="/my/checkpoint", options=omni.gen_options({"ov_num_step": 16}))
            text = p.transcribe(tone(TMP / "t.mp3", 2))
        self.assertTrue(Path(wav).is_file())
        self.assertEqual((seen[0]["instruct"], seen[0]["prompt"], seen[0]["model"]),
                         ("female, british accent", None, "/my/checkpoint"))
        self.assertEqual(seen[0]["config"]["num_step"], 16)
        self.assertEqual((seen[1]["cmd"], seen[1]["model"]), ("transcribe", omni.DEFAULT_MODEL))
        self.assertEqual(text, "lời thoại do máy chép")


class StorageTests(unittest.TestCase):
    def test_minimax_voices_are_dropped_with_a_backup(self):
        folder = TMP / "store"
        folder.mkdir()
        voices = [{"uid": "1", "provider": "MiniMax", "local_name": "A"}, {"uid": "2", "provider": "Inworld"},
                  {"uid": "3", "provider": "OmniVoice"}, {"uid": "4", "provider": "MiniMax"}]
        with mock.patch.object(storage, "VOICES_PATH", folder / "voices.json"), mock.patch.object(storage, "APP_DIR", folder):
            storage._save_json(storage.VOICES_PATH, voices)
            vs = storage.VoiceStore()
            self.assertEqual(vs.drop_providers(storage.REMOVED_PROVIDERS), 2)
            self.assertEqual([v["uid"] for v in vs.list()], ["2", "3"])
            self.assertEqual(vs.drop_providers(storage.REMOVED_PROVIDERS), 0)
        kept = json.loads((folder / "voices_removed.json").read_text(encoding="utf-8"))
        self.assertEqual([v["uid"] for v in kept], ["1", "4"])

    def test_sample_rules(self):
        self.assertFalse(validate_voice_sample(str(TMP / "missing.wav"), "OmniVoice")[0])
        bad = TMP / "x.txt"
        bad.write_text("x")
        ok, msg = validate_voice_sample(str(bad), "OmniVoice")
        self.assertFalse(ok)
        self.assertIn("FLAC", msg)
        ok, msg = validate_voice_sample(tone(TMP / "one.wav", 1), "OmniVoice")
        self.assertFalse(ok)
        self.assertIn("quá ngắn", msg)


if __name__ == "__main__":
    unittest.main()
