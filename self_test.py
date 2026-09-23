"""Offline self-test: mocks HTTP, exercises providers, chunking, merging and MP4.
Run:  python self_test.py"""
from __future__ import annotations

import base64
import subprocess
import tempfile
from pathlib import Path

import providers
from media import find_ffmpeg, make_video, merge_audio_files, probe_duration
from providers import InworldProvider, MiniMaxProvider, ProviderError
from utils import safe_filename, slug_voice_id, split_text, validate_voice_sample


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

        # --- MiniMax clone + TTS (hex), with one rate-limit retry
        mm = MiniMaxProvider("key")
        mm.session = FakeSession([
            Resp({"file": {"file_id": 123}, "base_resp": {"status_code": 0}}),
            Resp({"base_resp": {"status_code": 1002, "status_msg": "rate limit"}}),
            Resp({"base_resp": {"status_code": 0}}),
        ])
        sample = td / "s.wav"
        sample.write_bytes(b"RIFF0000")
        vid = mm.clone_voice(str(sample), "Giọng Đức Anh", "Vietnamese")
        assert vid.startswith("Giong_Duc_Anh_") and len(vid) >= 8, vid
        body = mm.session.calls[-1][2]["json"]
        assert body["language_boost"] == "Vietnamese" and body["file_id"] == 123
        ok += 1

        mm2 = MiniMaxProvider("key")
        mm2.session = FakeSession([Resp({"data": {"audio": mp3.hex()}, "base_resp": {"status_code": 0}})] * 3)
        out = td / "mm.mp3"
        mm2.synthesize("Xin chào " * 1200, "Voice_1234", str(out), model="speech-2.8-hd", speed=1.3, language="Vietnamese")
        assert len(mm2.session.calls) == 3  # 10.8k chars -> 3 chunks of <=5000
        req = mm2.session.calls[0][2]["json"]
        assert req["voice_setting"]["speed"] == 1.3 and req["language_boost"] == "Vietnamese"
        d = probe_duration(str(out))
        assert d and 2.5 < d < 3.6, d
        ok += 1

        # --- MiniMax auth error is NOT retried and is readable
        mm3 = MiniMaxProvider("bad")
        mm3.session = FakeSession([Resp({"base_resp": {"status_code": 1004, "status_msg": "auth failed"}})])
        try:
            mm3.synthesize("hi", "v", str(td / "x.mp3"), model="speech-2.8-hd")
            raise AssertionError("should fail")
        except ProviderError as e:
            assert "1004" in str(e) and "API key" in str(e)
        assert len(mm3.session.calls) == 1
        ok += 1

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
        mm.session = FakeSession([Resp({"voice_cloning": [{"voice_id": "X_123456", "description": []}],
                                        "system_voice": [{"voice_id": "S1", "voice_name": "Sys"}],
                                        "base_resp": {"status_code": 0}})])
        assert [v["kind"] for v in mm.list_voices()] == ["Của tôi", "Hệ thống"]
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
        assert slug_voice_id("123").startswith("Voice_")
        wav = td / "short.wav"
        subprocess.run([find_ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=3", str(wav)], check=True)
        assert not validate_voice_sample(str(wav), "Inworld")[0]
        wav12 = td / "ok.wav"
        subprocess.run([find_ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=12", str(wav12)], check=True)
        assert validate_voice_sample(str(wav12), "Inworld")[0] and validate_voice_sample(str(wav12), "MiniMax")[0]
        ok += 1

    print(f"Self-test passed: {ok} groups OK.")


if __name__ == "__main__":
    run()
