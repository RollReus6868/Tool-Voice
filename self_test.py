"""Offline self-test: mocks HTTP, exercises providers, chunking, merging and MP4.
Run:  python self_test.py"""
from __future__ import annotations

import base64
import subprocess
import tempfile
from pathlib import Path

import providers
from media import find_ffmpeg, make_video, merge_audio_files, probe_duration
from providers import InworldProvider, ProviderError
from utils import safe_filename, split_text, validate_voice_sample


class Resp:
    def __init__(self, data=None, content=b"", status=200, text=""):
        self._data = data if data is not None else {}
        self.content = content
        self.status_code = status
        self.text = text or str(self._data)

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def tone(path: Path, seconds: float):
    ff = find_ffmpeg()
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}",
                    "-c:a", "libmp3lame", "-b:a", "64k", str(path)], check=True)
    return path.read_bytes()


def run():
    providers.BaseProvider._sleep = lambda self, a, r: None  # no waiting in tests
    ok = 0
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        mp3 = tone(td / "t.mp3", 1.0)

        # --- split_text never exceeds the limit
        long = ("Câu thứ nhất rất dài. " * 400) + ("khongdaucau" * 500)
        parts = split_text(long, 1800)
        assert all(len(p) <= 1800 for p in parts) and "".join(parts).replace(" ", "") == long.replace(" ", "")
        ok += 1

        sample = td / "s.wav"
        sample.write_bytes(b"RIFF0000")

        # --- Inworld clone + TTS, 503 retried, speed + language sent
        iw = InworldProvider("Basic abc")
        assert iw.api_key == "abc"
        iw.session = FakeSession([Resp({"voice": {"voiceId": "ws__v1"}})])
        assert iw.clone_voice(str(sample), "Test", "vi-VN", denoise=True) == "ws__v1"
        cb = iw.session.calls[0][2]["json"]
        assert cb["languageCode"] == "vi-VN" and cb["audioProcessingConfig"]["removeBackgroundNoise"]
        iw.session = FakeSession([Resp(status=503, text="busy"),
                                  Resp({"audioContent": base64.b64encode(mp3).decode()})])
        out2 = td / "iw.mp3"
        iw.synthesize("hello", "ws__v1", str(out2), model="inworld-tts-2", speed=1.2, language="VI_VN")
        req = iw.session.calls[-1][2]["json"]
        assert req["audioConfig"]["speakingRate"] == 1.2 and req["language"] == "vi-VN" and out2.read_bytes() == mp3
        ok += 1

        # --- Inworld 401 -> friendly message, no retry
        iw.session = FakeSession([Resp(status=401, text="unauthorized")])
        try:
            iw.synth_chunk("x", "v", model="inworld-tts-2", speed=1, language="")
            raise AssertionError("should fail")
        except ProviderError as e:
            assert "API key" in str(e)
        ok += 1

        # --- list voices parsing
        iw.session = FakeSession([Resp({"voices": [{"voiceId": "a", "displayName": "A", "source": "IVC", "langCode": "VI_VN"},
                                                   {"voiceId": "b", "displayName": "B", "source": "SYSTEM"}]})])
        vs = iw.list_voices()
        assert vs[0]["kind"] == "Của tôi" and vs[0]["language"] == "vi-VN" and vs[1]["kind"] == "Hệ thống"
        ok += 1

        # --- merge + MP4 (real ffmpeg)
        merged = td / "merged.mp3"
        merge_audio_files([str(out2), str(out2)], str(merged))
        assert 1.8 < probe_duration(str(merged)) < 2.4
        img = td / "bg.png"
        subprocess.run([find_ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=640x480",
                        "-frames:v", "1", str(img)], check=True)
        prog = []
        for size, image in (((1280, 720), str(img)), ((1080, 1920), "")):
            mp4 = td / f"v{size[0]}.mp4"
            make_video(str(merged), str(mp4), image_path=image, size=size, bg_color="#123456", progress=prog.append)
            info = subprocess.run([find_ffmpeg(), "-hide_banner", "-i", str(mp4)], capture_output=True, text=True).stderr
            assert f"{size[0]}x{size[1]}" in info and "h264" in info and "aac" in info, info
            dd = probe_duration(str(mp4)); assert 1.8 < dd < 2.6, (size, dd)
        assert prog and prog[-1] == 1.0
        ok += 1

        # --- misc helpers
        assert safe_filename("1.0") == "1" and safe_filename('a/b:c*') == "a_b_c_"
        wav = td / "short.wav"
        subprocess.run([find_ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=3", str(wav)], check=True)
        assert not validate_voice_sample(str(wav), "Inworld")[0]
        wav12 = td / "ok.wav"
        subprocess.run([find_ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=12", str(wav12)], check=True)
        assert validate_voice_sample(str(wav12), "Inworld")[0]
        ok3, msg3 = validate_voice_sample(str(wav), "OmniVoice")           # 3 s: the ideal OmniVoice sample
        ok12, msg12 = validate_voice_sample(str(wav12), "OmniVoice")       # 12 s: fine
        assert ok3 and msg3.startswith("✔") and ok12 and msg12.startswith("✔"), (msg3, msg12)
        wav20 = td / "long.wav"
        subprocess.run([find_ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=20", str(wav20)], check=True)
        okl, msgl = validate_voice_sample(str(wav20), "OmniVoice")         # long: allowed, with a warning
        assert okl and msgl.startswith("⚠"), msgl
        ok += 1

    print(f"Self-test passed: {ok} groups OK.")


if __name__ == "__main__":
    run()
