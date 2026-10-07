"""On GitHub Actions, repeat every test failure as an ::error:: annotation.

Annotations can be read from the run's summary page (and the API) without opening
the full job log, which is what whoever fixes a red build usually has at hand."""
from __future__ import annotations

import os
import unittest

ON_CI = bool(os.getenv("GITHUB_ACTIONS"))


def annotate(title: str, text: str) -> None:
    if ON_CI:
        body = text.strip()[-1400:].replace("%", "%25").replace("\r", "").replace("\n", "%0A")
        print(f"::error title={title[:80]}::{body}", flush=True)


def install() -> None:
    """Make unittest's text runner annotate failures and errors (idempotent)."""
    cls = unittest.TextTestResult
    if not ON_CI or getattr(cls, "_tts_annotated", False):
        return
    cls._tts_annotated = True
    for name in ("addFailure", "addError"):
        original = getattr(cls, name)

        def wrapper(self, test, err, _original=original):
            _original(self, test, err)
            try:
                annotate(str(test), self._exc_info_to_string(err, test))
            except Exception:  # noqa: BLE001 - never let reporting break the run
                pass

        setattr(cls, name, wrapper)
