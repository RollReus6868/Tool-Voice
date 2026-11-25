"""3.3: word timings written into the MP3 for CapCut Draft Studio (Inworld timestamps, OmniVoice + Whisper)."""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ci_annotations  # noqa: E402

ci_annotations.install()

import omni  # noqa: E402
import providers  # noqa: E402
import timings  # noqa: E402
from media import find_ffmpeg, probe_duration  # noqa: E402
from test_features import FakeSession, Resp  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="tts_timings_test_"))


def tearDownModule():
    omni.ENGINE.stop()
    shutil.rmtree(TMP, ignore_errors=True)


def mp3(path: Path, seconds: float, freq: int = 300) -> Path:
    subprocess.run([find_ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"sine=f={freq}:d={seconds}", "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "128k",
                    str(path)], check=True)
    return path


def answer(audio: bytes, words=None, starts=None, ends=None, **extra):
    data = {"audioContent": base64.b64encode(audio).decode(), **extra}
    if words is not None:
        data["timestampInfo"] = {"wordAlignment": {"words": words, "wordStartTimeSeconds": starts,
                                                   "wordEndTimeSeconds": ends}}
    return Resp(data)


class ParseAndTagTests(unittest.TestCase):
    def test_inworld_words(self):
        data = {"timestampInfo": {"wordAlignment": {"words": ["Hello", " world ", ""],
                                                    "wordStartTimeSeconds": [0.0, 0.51234, 0.9],
                                                    "wordEndTimeSeconds": [0.4, 0.9, 1.0]}}}
        self.assertEqual(timings.inworld_words(data), [["Hello", 0.0, 0.4], ["world", 0.512, 0.9]])
        self.assertEqual(timings.inworld_words({"audioContent": "x"}), [])
        # broken arrays never raise
        bad = {"timestampInfo": {"wordAlignment": {"words": ["a", "b"], "wordStartTimeSeconds": [0.1]}}}
        self.assertEqual(timings.inworld_words(bad), [["a", 0.1, 0.1]])

    def test_embed_keeps_audio_and_survives_special_characters(self):
        src = mp3(TMP / "a.mp3", 5.0)
        dst = TMP / "b.mp3"
        shutil.copyfile(src, dst)
        words = [["Ê-li", 0.0, 0.4], ["a=b;c#d\\e", 0.5, 0.9], ["“quote”", 1.0, 1.4]] * 500   # long file
        self.assertTrue(timings.embed(str(dst), words, "inworld"))
        got = timings.read(str(dst))
        self.assertEqual(got["engine"], "inworld")
        self.assertEqual(got["words"], words)
        self.assertAlmostEqual(probe_duration(str(dst)), probe_duration(str(src)), delta=0.03)

        def pcm(p):
            return subprocess.run([find_ffmpeg(), "-v", "error", "-i", str(p), "-f", "s16le", "-"],
                                  capture_output=True, check=True).stdout
        self.assertEqual(pcm(src), pcm(dst))                    # stream copy: not one sample changed
        # writing again replaces, never stacks
        self.assertTrue(timings.embed(str(dst), [["x", 0.0, 1.0]], "whisper"))
        self.assertEqual(timings.read(str(dst))["words"], [["x", 0.0, 1.0]])
        self.assertEqual(list(TMP.glob(".*tag-tmp*")), [])         # no temp file left beside the voice
        with mock.patch("media._run", side_effect=OSError("boom")):
            self.assertFalse(timings.embed(str(dst), words, "x"))   # never raises, file untouched
        self.assertEqual(timings.read(str(dst))["words"], [["x", 0.0, 1.0]])

    def test_nothing_to_embed_or_not_an_mp3(self):
        self.assertFalse(timings.embed(str(TMP / "missing.mp3"), [["a", 0, 1]], "x"))
        f = mp3(TMP / "n.mp3", 1.0)
        self.assertFalse(timings.embed(str(f), [], "x"))
        self.assertIsNone(timings.read(str(f)))
        (TMP / "t.txt").write_text("hello")
        self.assertIsNone(timings.read(str(TMP / "t.txt")))


class InworldTimingTests(unittest.TestCase):
    def setUp(self):
        providers.InworldProvider._ts_refused.clear()

    def test_request_asks_for_word_timestamps_only_when_wanted(self):
        p = providers.InworldProvider("k")
        p.session = FakeSession([answer(b"ID3", ["Hi"], [0.0], [0.3])])
        p.synth_chunk("Hi", "v", model="inworld-tts-2", speed=1, language="")
        self.assertNotIn("timestampType", p.session.calls[0][2]["json"])
        self.assertIsNone(p._chunk_words)

        p = providers.build_provider("Inworld", {"inworld_api_key": "k"}, {})
        self.assertTrue(p.want_timings)                                     # on by default
        p.session = FakeSession([answer(b"ID3", ["Hi", "there"], [0.05, 0.3], [0.28, 0.7])])
        p.synth_chunk("Hi there", "v", model="inworld-tts-2", speed=1, language="")
        self.assertEqual(p.session.calls[0][2]["json"]["timestampType"], "WORD")
        self.assertEqual(p._chunk_words, [["Hi", 0.05, 0.28], ["there", 0.3, 0.7]])
        self.assertFalse(providers.build_provider("Inworld", {"inworld_api_key": "k"},
                                                  {"word_timings": False}).want_timings)

    def test_model_refusing_timestamps_still_reads_and_is_remembered(self):
        logs = []
        p = providers.build_provider("Inworld", {"inworld_api_key": "k"}, {}, log=logs.append)
        p.session = FakeSession([Resp({"error": "timestampType not supported"}, status=400),
                                 answer(b"ID3"), answer(b"ID3")])
        p.synth_chunk("abc", "v", model="inworld-tts-1.5-mini", speed=1, language="")
        first, second = (c[2]["json"] for c in p.session.calls)
        self.assertIn("timestampType", first)
        self.assertNotIn("timestampType", second)
        self.assertTrue(any("không trả mốc thời gian" in m for m in logs))
        # next row (new provider) does not ask again: one request, not two
        p2 = providers.build_provider("Inworld", {"inworld_api_key": "k"}, {})
        p2.session = FakeSession([answer(b"ID3")])
        p2.synth_chunk("abc", "v", model="inworld-tts-1.5-mini", speed=1, language="")
        self.assertNotIn("timestampType", p2.session.calls[0][2]["json"])

    def test_style_option_refused_keeps_timestamps(self):
        p = providers.build_provider("Inworld", {"inworld_api_key": "k"}, {})
        p.session = FakeSession([Resp({"error": "unknown field temperature"}, status=400),
                                 answer(b"ID3", ["a"], [0.1], [0.2])])
        p.synth_chunk("a", "v", model="inworld-tts-2-flash", speed=1, language="", options={"delivery": "CREATIVE"})
        second = p.session.calls[1][2]["json"]
        self.assertNotIn("temperature", second)
        self.assertEqual(second["timestampType"], "WORD")
        self.assertEqual(p._chunk_words, [["a", 0.1, 0.2]])

    def test_long_text_chunks_are_offset_and_written_into_the_mp3(self):
        import workers
        one, two = mp3(TMP / "c1.mp3", 2.0).read_bytes(), mp3(TMP / "c2.mp3", 3.0, 500).read_bytes()
        p = providers.build_provider("Inworld", {"inworld_api_key": "k"}, {})
        p.max_chars = 20
        p.session = FakeSession([answer(one, ["First", "part."], [0.1, 0.8], [0.7, 1.5]),
                                 answer(two, ["Second", "part."], [0.2, 1.0], [0.9, 2.5])])
        out = TMP / "out"
        res = workers.produce_outputs(provider=p, text="First part. Second part.", voice={"provider_voice_id": "v"},
                                      model="inworld-tts-2", speed=1.0, out_dir=str(out), name="7", fmt="mp3",
                                      video={}, log=lambda m: None, cancelled=lambda: False)
        self.assertEqual(res["timings"], 4)
        tag = timings.read(res["mp3"])
        self.assertEqual(tag["engine"], "inworld")
        got = tag["words"]
        self.assertEqual([w for w, _s, _e in got], ["First", "part.", "Second", "part."])
        off = probe_duration(str(TMP / "c1.mp3"))
        self.assertAlmostEqual(got[2][1], 0.2 + off, delta=0.01)          # 2nd chunk starts after the 1st
        self.assertAlmostEqual(got[3][2], 2.5 + off, delta=0.01)

    def test_a_chunk_without_timings_means_none_for_the_file(self):
        import workers
        p = providers.build_provider("Inworld", {"inworld_api_key": "k"}, {})
        p.max_chars = 20
        a = mp3(TMP / "d1.mp3", 1.0).read_bytes()
        p.session = FakeSession([answer(a, ["First", "part."], [0.1, 0.5], [0.4, 0.9]), answer(a)])
        res = workers.produce_outputs(provider=p, text="First part. Second part.", voice={"provider_voice_id": "v"},
                                      model="inworld-tts-2", speed=1.0, out_dir=str(TMP / "o2"), name="8",
                                      fmt="mp3", video={}, log=lambda m: None, cancelled=lambda: False)
        self.assertEqual(res["timings"], 0)
        self.assertIsNone(timings.read(res["mp3"]))


class OmniVoiceTimingTests(unittest.TestCase):
    def setUp(self):
        self.saved = {n: getattr(omni, n) for n in ("ROOT", "ENV_DIR", "MODELS_DIR", "VOICES_DIR", "TOOLS_DIR",
                                                    "MARKER")}
        for name, sub in (("ROOT", ""), ("ENV_DIR", "env"), ("MODELS_DIR", "models"), ("VOICES_DIR", "voices"),
                          ("TOOLS_DIR", "tools"), ("MARKER", "install.json")):
            setattr(omni, name, TMP / "omni" / sub if sub else TMP / "omni")
        self.fake = os.environ.get("TTS_OMNI_FAKE")
        os.environ["TTS_OMNI_FAKE"] = "1"

    def tearDown(self):
        omni.ENGINE.stop()
        for k, v in self.saved.items():
            setattr(omni, k, v)
        if self.fake is None:
            os.environ.pop("TTS_OMNI_FAKE", None)
        else:
            os.environ["TTS_OMNI_FAKE"] = self.fake

    def _voice(self, p):
        return p.clone_voice(str(mp3(TMP / "s.mp3", 4.0)), "T", "en", ref_text="hello there")

    def test_whisper_timings_after_paused_reading(self):
        import workers
        logs = []
        p = providers.build_provider("OmniVoice", {}, {}, log=logs.append)
        vid = self._voice(p)
        text = "Gold. pearls, silk"
        res = workers.produce_outputs(provider=p, text=text, voice={"provider_voice_id": vid}, model="", speed=1.0,
                                      out_dir=str(TMP / "ov"), name="3", fmt="mp3", video={}, log=logs.append,
                                      cancelled=lambda: False,
                                      options={**omni.gen_options({}), **omni.PAUSE_DEFAULTS, "pause_enabled": True})
        tag = timings.read(res["mp3"])
        self.assertEqual(tag["engine"], "whisper")
        self.assertEqual([w for w, _s, _e in tag["words"]], text.split())       # fake engine echoes the text
        self.assertAlmostEqual(tag["words"][-1][2], probe_duration(res["mp3"]), delta=0.1)
        self.assertTrue(any("Whisper dò mốc" in m for m in logs))
        omni.delete_voice(vid)

    def test_whisper_failure_never_fails_the_row(self):
        logs = []
        p = providers.build_provider("OmniVoice", {}, {}, log=logs.append)
        vid = self._voice(p)
        out = str(TMP / "f.mp3")
        p.synthesize("ALIGNFAIL here", vid, out, options=omni.gen_options({}))
        self.assertTrue(Path(out).is_file())
        self.assertIsNone(p.word_timings)
        self.assertTrue(any("Không dò được mốc" in m for m in logs))
        omni.delete_voice(vid)

    def test_off_means_no_whisper_request(self):
        p = providers.build_provider("OmniVoice", {}, {"word_timings": False})
        vid = self._voice(p)
        seen, real = [], omni.ENGINE.request

        def spy(req, **kw):
            seen.append(req["cmd"])
            return real(req, **kw)

        with mock.patch.object(omni.ENGINE, "request", spy):
            p.synthesize("Hello there", vid, str(TMP / "g.mp3"), options=omni.gen_options({}))
        self.assertNotIn("align", seen)
        self.assertIsNone(p.word_timings)
        omni.delete_voice(vid)


if __name__ == "__main__":
    unittest.main()
