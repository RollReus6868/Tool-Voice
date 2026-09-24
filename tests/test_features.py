"""2.2 features without Qt: Inworld options, usage tally, row selection, voice list, settings migration."""
from __future__ import annotations

import base64
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import providers  # noqa: E402
import usage  # noqa: E402
from providers import MODELS, InworldProvider, MiniMaxProvider  # noqa: E402
from storage import migrate  # noqa: E402
from utils import parse_row_selection  # noqa: E402


class Resp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status
        self.text = str(data)

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kw):
        self.calls.append((method, url, copy.deepcopy(kw)))
        return self.responses.pop(0)


AUDIO = base64.b64encode(b"ID3fake").decode()


class InworldOptionsTests(unittest.TestCase):
    def payload(self, model, options):
        p = InworldProvider("k")
        p.session = FakeSession([Resp({"audioContent": AUDIO, "usage": {"processedCharactersCount": 7}})])
        p.synth_chunk("xin chào", "v1", model=model, speed=1.0, language="", options=options)
        return p, p.session.calls[0][2]["json"]

    def test_default_model_is_flash(self):
        self.assertEqual(MODELS["Inworld"][0], "inworld-tts-2-flash")
        self.assertEqual(usage.DEFAULT_MODEL, "inworld-tts-2-flash")

    def test_balanced_sends_nothing_extra(self):
        _, body = self.payload("inworld-tts-2-flash", {"delivery": "BALANCED"})
        for k in ("deliveryMode", "temperature", "enhanceGeneration", "instruction"):
            self.assertNotIn(k, body)

    def test_tts2_uses_delivery_mode_and_instruction(self):
        _, body = self.payload("inworld-tts-2", {"delivery": "CREATIVE", "enhance": True, "instruction": "đọc chậm"})
        self.assertEqual(body["deliveryMode"], "CREATIVE")
        self.assertNotIn("temperature", body)
        self.assertTrue(body["enhanceGeneration"])
        self.assertEqual(body["instruction"], "đọc chậm")

    def test_flash_uses_temperature_and_drops_instruction(self):
        _, body = self.payload("inworld-tts-2-flash", {"delivery": "STABLE", "instruction": "x"})
        self.assertEqual(body["temperature"], 0.7)
        self.assertNotIn("deliveryMode", body)
        self.assertNotIn("instruction", body)

    def test_rejected_option_falls_back_to_plain_request(self):
        p = InworldProvider("k")
        p.session = FakeSession([Resp({"error": "unknown field temperature"}, status=400),
                                 Resp({"audioContent": AUDIO})])
        logs = []
        p.log = logs.append
        p.synth_chunk("abc", "v1", model="inworld-tts-2-flash", speed=1.0, language="",
                      options={"delivery": "CREATIVE", "enhance": True})
        first, second = (c[2]["json"] for c in p.session.calls)
        self.assertIn("temperature", first)
        self.assertNotIn("temperature", second)
        self.assertNotIn("enhanceGeneration", second)
        self.assertTrue(any("không nhận" in m for m in logs))

    def test_other_400_is_not_retried(self):
        p = InworldProvider("k")
        p.session = FakeSession([Resp({"error": "bad voice"}, status=400)])
        with self.assertRaises(providers.ProviderError):
            p.synth_chunk("abc", "v1", model="inworld-tts-2-flash", speed=1.0, language="", options=None)

    def test_counts_reported_characters(self):
        p, _ = self.payload("inworld-tts-2-flash", None)
        self.assertEqual(p.chars_used, 7)

    def test_counts_text_when_not_reported(self):
        p = InworldProvider("k")
        p.session = FakeSession([Resp({"audioContent": AUDIO})])
        p.synth_chunk("abcde", "v1", model="", speed=1.0, language="")
        self.assertEqual(p.chars_used, 5)

    def test_list_voices_paginates_and_classifies(self):
        p = InworldProvider("k")
        p.session = FakeSession([
            Resp({"voices": [{"voiceId": "sys1", "displayName": "Sarah", "source": "SYSTEM", "gender": "female",
                              "languageCode": "en-US", "tags": ["warm"], "description": "Calm"}],
                  "nextPageToken": "t2"}),
            Resp({"voices": [{"voiceId": "ws__me", "displayName": "Tôi", "source": "IVC", "owned": True,
                              "languageCode": "vi-VN"}]}),
        ])
        voices = p.list_voices()
        self.assertEqual([v["voice_id"] for v in voices], ["sys1", "ws__me"])
        self.assertEqual([v["kind"] for v in voices], ["Hệ thống", "Của tôi"])
        self.assertEqual(voices[0]["gender"], "Nữ")
        self.assertEqual(p.session.calls[1][2]["params"]["pageToken"], "t2")

    def test_minimax_ignores_options(self):
        p = MiniMaxProvider("k")
        p.session = FakeSession([Resp({"base_resp": {"status_code": 0}, "data": {"audio": "4944"},
                                       "extra_info": {"usage_characters": 3}})])
        p.synth_chunk("abc", "v", model="speech-2.8-hd", speed=1, language="auto", options={"delivery": "CREATIVE"})
        self.assertEqual(p.chars_used, 3)


class UsageTests(unittest.TestCase):
    def test_rates(self):
        self.assertEqual(usage.rate_per_million("inworld-tts-2-flash", "on_demand"), 15.0)
        self.assertEqual(usage.rate_per_million("inworld-tts-2", "creator"), 20.0)
        self.assertEqual(usage.rate_per_million("unknown", "creator"), 10.0)
        self.assertAlmostEqual(usage.cost_of(1_000_000, "inworld-tts-2", "on_demand"), 25.0)

    def test_record_and_summary(self):
        d = usage.new_period("creator", 25.0)
        d = usage.record(d, "inworld-tts-2-flash", 500_000)   # $5
        d = usage.record(d, "inworld-tts-2", 250_000)         # $5
        su = usage.summary(d, "inworld-tts-2-flash")
        self.assertEqual(su["chars"], 750_000)
        self.assertAlmostEqual(su["spent"], 10.0)
        self.assertAlmostEqual(su["remaining"], 15.0)
        self.assertAlmostEqual(su["left_pct"], 60.0)
        self.assertEqual(su["chars_left"], 1_500_000)
        self.assertEqual(su["requests"], 2)

    def test_no_budget_and_overspend(self):
        su = usage.summary(usage.record(None, "inworld-tts-2-flash", 1000))
        self.assertIsNone(su["left_pct"])
        d = usage.record(usage.new_period("on_demand", 0.01), "inworld-tts-2", 1_000_000)
        su = usage.summary(d)
        self.assertEqual(su["remaining"], 0.0)
        self.assertEqual(su["left_pct"], 0.0)

    def test_normalize_garbage(self):
        d = usage.normalize({"plan": "nope", "budget": "x", "chars": {"m": 0}})
        self.assertEqual(d["plan"], "on_demand")
        self.assertEqual(d["budget"], 0.0)
        self.assertEqual(d["chars"], {})


class RowSelectionTests(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(parse_row_selection("", 3), [1, 2, 3])
        self.assertEqual(parse_row_selection("1-3, 5", 10), [1, 2, 3, 5])
        self.assertEqual(parse_row_selection("8-", 10), [8, 9, 10])
        self.assertEqual(parse_row_selection("3–1; 7 7", 10), [1, 2, 3, 7])

    def test_errors(self):
        for bad in ("0", "11", "a", "1-x", "-3", ","):
            with self.assertRaises(ValueError, msg=bad):
                parse_row_selection(bad, 10)


class MigrationTests(unittest.TestCase):
    def test_switches_old_default_once(self):
        ch = migrate({"model_Inworld": "inworld-tts-2", "defaults_rev": 0})
        self.assertEqual(ch["model_Inworld"], "inworld-tts-2-flash")
        self.assertEqual(ch["defaults_rev"], 2)
        self.assertEqual(migrate({"model_Inworld": "inworld-tts-2", "defaults_rev": 2}), {})


if __name__ == "__main__":
    providers.BaseProvider._sleep = lambda self, a, r: None
    unittest.main()
