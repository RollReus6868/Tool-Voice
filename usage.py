"""Inworld plan, balance & usage history (no Qt here — unit-testable).

Inworld has no public API for plan, balance or usage (only the web pages
platform.inworld.ai/billing and /usage), so the app keeps its own history and
lets the user *sync* it with the numbers shown on those pages:

* every successful synthesis adds the characters Inworld reports
  (usage.processedCharactersCount) to an hourly bucket (UTC, like Inworld);
* "Đồng bộ với Inworld" stores the balance from Billing and the characters per
  model from Usage for a window (24 h / 7 / 30 days). The difference between
  Inworld's figure and what the app recorded in that window becomes a *sync
  adjustment* (reads made outside the app, other API keys, older versions…),
  so the app's totals equal Inworld's at the moment of syncing and then grow
  with every read made in the app;
* Inworld refreshes its dashboard about hourly, so reads from the current and
  the previous hour are assumed to be not yet included in the synced numbers.

Prices: inworld.ai/pricing (09/2026), USD per 1M characters.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

# (code, label, monthly fee in USD, credits included in USD)
PLANS = [
    ("on_demand", "On-Demand (trả theo dùng)", 0.0, 0.0),
    ("creator", "Creator — $25/tháng", 25.0, 25.0),
    ("builder", "Builder — $100/tháng", 100.0, 100.0),
    ("developer", "Developer — $300/tháng", 300.0, 300.0),
    ("growth", "Growth — $1.500/tháng", 1500.0, 1500.0),
]
PLAN_LABEL = {code: lbl for code, lbl, _fee, _cr in PLANS}
PLAN_CREDITS = {code: cr for code, _lbl, _fee, cr in PLANS}

# USD per 1,000,000 characters, by model and plan
RATES = {
    "inworld-tts-2": {"on_demand": 25.0, "creator": 20.0, "builder": 17.5, "developer": 15.0, "growth": 12.5},
    "inworld-tts-2-flash": {"on_demand": 15.0, "creator": 10.0, "builder": 9.0, "developer": 8.0, "growth": 7.0},
}
# models not on the current price list: priced like the model they are closest to
RATE_FALLBACK = {"inworld-tts-1.5-max": "inworld-tts-2", "inworld-tts-1.5-mini": "inworld-tts-2-flash"}
DEFAULT_MODEL = "inworld-tts-2-flash"
# models offered in the sync dialog, in Inworld's order, with the colours Inworld's charts use
SYNC_MODELS = ["inworld-tts-2-flash", "inworld-tts-2", "inworld-tts-1.5-max", "inworld-tts-1.5-mini"]
MODEL_COLORS = {"inworld-tts-2-flash": "#8b5cf6", "inworld-tts-2": "#2ec4cc",
                "inworld-tts-1.5-max": "#f59e0b", "inworld-tts-1.5-mini": "#ec4899"}
EXTRA_COLORS = ["#3b82f6", "#10b981", "#f97316", "#94a3b8"]

BILLING_URL = "https://platform.inworld.ai/billing"
USAGE_URL = "https://platform.inworld.ai/usage"

# windows offered on the usage page and in the sync dialog (key, label, days)
VIEWS = [("24h", "24 giờ", 1), ("7d", "7 ngày", 7), ("30d", "30 ngày", 30), ("90d", "90 ngày", 90)]
VIEW_DAYS = {k: d for k, _l, d in VIEWS}
KEEP_DAYS = 100          # hourly buckets older than this are dropped
LAG_HOURS = 1            # Inworld's dashboard is "Updated ~hourly"


# ---------------------------------------------------------------- prices
def rate_per_million(model: str, plan: str) -> float:
    model = model if model in RATES else RATE_FALLBACK.get(model, DEFAULT_MODEL)
    table = RATES.get(model, RATES[DEFAULT_MODEL])
    return table.get(plan, table["on_demand"])


def cost_of(chars: int, model: str, plan: str) -> float:
    return max(0, int(chars)) * rate_per_million(model, plan) / 1_000_000


def model_color(model: str, order: list[str] | None = None) -> str:
    if model in MODEL_COLORS:
        return MODEL_COLORS[model]
    others = [m for m in (order or []) if m not in MODEL_COLORS]
    i = others.index(model) if model in others else abs(hash(model))
    return EXTRA_COLORS[i % len(EXTRA_COLORS)]


# ---------------------------------------------------------------- time helpers (UTC hour buckets)
def _now(now: float | None) -> float:
    return time.time() if now is None else float(now)


def hour_key(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y%m%d%H")


def hour_start(key: str) -> float:
    return datetime.strptime(key, "%Y%m%d%H").replace(tzinfo=timezone.utc).timestamp()


def _floor_hour(ts: float) -> float:
    return ts - ts % 3600


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def _parse_ts(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return datetime.fromisoformat(str(v)).timestamp()
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- data
def new_period(plan: str = "on_demand", budget: float | None = None, now: float | None = None) -> dict:
    """Fresh tracker. `budget` = the credit that counts as 100 % (default: the plan's monthly credit)."""
    plan = plan if plan in PLAN_LABEL else "on_demand"
    return {
        "plan": plan,
        "budget": float(PLAN_CREDITS.get(plan, 0.0) if budget is None else budget),
        "since": _iso(_now(now)),    # anchor for "remaining" when no balance was synced
        "hours": {},                 # "YYYYMMDDHH" (UTC) -> {model: characters read in the app}
        "sync": None,                # last sync with Inworld's Billing/Usage pages
        "requests": 0,
        "rev": 2,
    }


def normalize(data: dict | None) -> dict:
    base = new_period()
    if not isinstance(data, dict):
        return base
    for k in ("plan", "budget", "since", "requests"):
        if k in data:
            base[k] = data[k]
    if base["plan"] not in PLAN_LABEL:
        base["plan"] = "on_demand"
    try:
        base["budget"] = max(0.0, float(base.get("budget") or 0))
    except (TypeError, ValueError):
        base["budget"] = 0.0
    try:
        base["requests"] = max(0, int(base.get("requests") or 0))
    except (TypeError, ValueError):
        base["requests"] = 0
    since = _parse_ts(base.get("since"))
    base["since"] = _iso(since if since is not None else time.time())
    hours = {}
    for key, per in dict(data.get("hours") or {}).items():
        if not (isinstance(key, str) and re.fullmatch(r"\d{10}", key) and isinstance(per, dict)):
            continue
        clean = {}
        for m, n in per.items():
            try:
                n = int(n)
            except (TypeError, ValueError):
                continue
            if n > 0:
                clean[str(m)] = n
        if clean:
            hours[key] = clean
    # 2.2 kept one running tally per model since `since` — move it into that hour's bucket
    if "hours" not in data and isinstance(data.get("chars"), dict):
        key = hour_key(since if since is not None else time.time())
        for m, n in data["chars"].items():
            try:
                n = int(n)
            except (TypeError, ValueError):
                continue
            if n > 0:
                hours.setdefault(key, {})[str(m)] = hours.get(key, {}).get(str(m), 0) + n
    base["hours"] = hours
    base["sync"] = _normalize_sync(data.get("sync"))
    return base


def _normalize_sync(s) -> dict | None:
    if not isinstance(s, dict):
        return None
    at = _parse_ts(s.get("at"))
    if at is None:
        return None
    out = {"at": at, "cutoff": _parse_ts(s.get("cutoff")) or _floor_hour(at) - LAG_HOURS * 3600,
           "days": s.get("days") if s.get("days") in (1, 7, 30, 90) else 30,
           "balance": None, "chars": {}, "adj": {}}
    out["bal_at"] = _parse_ts(s.get("bal_at")) or at
    out["bal_cutoff"] = _parse_ts(s.get("bal_cutoff")) or out["cutoff"]
    try:
        out["balance"] = None if s.get("balance") is None else max(0.0, float(s["balance"]))
    except (TypeError, ValueError):
        out["balance"] = None
    for k in ("chars", "adj"):
        for m, n in dict(s.get(k) or {}).items():
            try:
                n = int(n)
            except (TypeError, ValueError):
                continue
            if n >= 0:
                out[k][str(m)] = n
    return out


def prune(d: dict, now: float | None = None) -> dict:
    limit = hour_key(_now(now) - KEEP_DAYS * 86400)
    d["hours"] = {k: v for k, v in d["hours"].items() if k >= limit}
    return d


def record(data: dict | None, model: str, chars: int, now: float | None = None) -> dict:
    """Return a new tracker with one synthesis added to the current UTC hour."""
    d = normalize(data)
    chars = max(0, int(chars))
    if not chars:
        return d
    model = model or DEFAULT_MODEL
    bucket = d["hours"].setdefault(hour_key(_now(now)), {})
    bucket[model] = bucket.get(model, 0) + chars
    d["requests"] += 1
    return prune(d, now)


def set_plan(data: dict | None, plan: str, budget: float | None = None, now: float | None = None) -> dict:
    """Change plan / 100 % credit. Changing the credit restarts the no-sync anchor."""
    d = normalize(data)
    plan = plan if plan in PLAN_LABEL else "on_demand"
    new_budget = float(PLAN_CREDITS.get(plan, 0.0) if budget is None else max(0.0, budget))
    if abs(new_budget - d["budget"]) > 1e-9:
        d["since"] = _iso(_now(now))
    d["plan"], d["budget"] = plan, new_budget
    return d


def _app_between(d: dict, start: float, end: float | None = None) -> dict:
    """Characters read in the app in hour buckets that start in [start, end)."""
    out: dict[str, int] = {}
    for key, per in d["hours"].items():
        h = hour_start(key)
        if h >= start and (end is None or h < end):
            for m, n in per.items():
                out[m] = out.get(m, 0) + n
    return out


def parse_count(text) -> int | None:
    """'2,755' / '2.755' / '2.5K' / '1,2M' / '270' → int; '' → None; garbage → ValueError."""
    if text is None:
        return None
    s = str(text).strip().lower().replace(" ", "").replace(" ", "")
    for word in ("characters", "character", "ký tự", "kýtự", "chars"):
        s = s.replace(word, "")
    if not s:
        return None
    mult = 1
    if s[-1] in "km":
        mult = 1000 if s[-1] == "k" else 1_000_000
        s = s[:-1]
        s = s.replace(",", ".")
        if s.count(".") > 1 or not re.fullmatch(r"\d+(\.\d+)?", s):
            raise ValueError(text)
        return int(round(float(s) * mult))
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s) or re.fullmatch(r"\d+", s):
        return int(re.sub(r"[.,]", "", s))
    raise ValueError(text)


def parse_money(text) -> float | None:
    """'$22.10' / '22,10' / '1,234.50' / '$1.500' (VN) → float; '' → None; garbage → ValueError."""
    if text is None:
        return None
    s = str(text).strip().replace("$", "").replace("USD", "").replace("usd", "").replace(" ", "")
    s = s.replace("\u00a0", "")
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", s) else s.replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3}){2,}", s):
        s = s.replace(".", "")
    if not re.fullmatch(r"\d+(\.\d+)?", s):
        raise ValueError(text)
    return float(s)


def reconcile(total: int | None, chars: dict) -> dict:
    """Inworld's table rounds (2.5K) but the headline total is exact (2,755):
    make the biggest model absorb the difference so the models add up to the total."""
    chars = {m: int(n) for m, n in chars.items() if n is not None and int(n) >= 0}
    if total is None:
        return chars
    if not chars:
        return {DEFAULT_MODEL: int(total)} if total > 0 else {}
    big = max(chars, key=lambda m: chars[m])
    rest = sum(n for m, n in chars.items() if m != big)
    if total >= rest:
        chars[big] = int(total) - rest
    return chars


def sync(data: dict | None, balance: float | None, chars: dict | None, days: int = 30,
         now: float | None = None) -> dict:
    """Store numbers read from Inworld's Billing (balance) and Usage (characters per model, last `days`)."""
    d = normalize(data)
    now = _now(now)
    cutoff = _floor_hour(now) - LAG_HOURS * 3600
    days = days if days in (1, 7, 30, 90) else 30
    chars = {m: int(n) for m, n in (chars or {}).items() if n is not None and int(n) >= 0}
    prev = d.get("sync")
    if not chars and prev and prev.get("chars"):
        # only the balance was typed: keep the characters (and their place in time) from the last sync
        new = dict(prev, balance=None if balance is None else max(0.0, float(balance)),
                   bal_at=now, bal_cutoff=cutoff)
        d["sync"] = new
        return d
    app = _app_between(d, now - days * 86400, cutoff)
    adj = {m: max(0, n - app.get(m, 0)) for m, n in chars.items()}
    d["sync"] = {"at": now, "cutoff": cutoff, "days": days,
                 "balance": None if balance is None else max(0.0, float(balance)),
                 "bal_at": now, "bal_cutoff": cutoff,
                 "chars": chars, "adj": {m: n for m, n in adj.items() if n > 0}}
    return d


# ---------------------------------------------------------------- views
def summary(data: dict | None, model: str = DEFAULT_MODEL, now: float | None = None) -> dict:
    """Balance view: what is left, in USD, percent and characters for `model`."""
    d = normalize(data)
    now = _now(now)
    plan = d["plan"]
    s = d["sync"]
    if s and s.get("balance") is not None:
        base, anchor, source = s["balance"], s["bal_cutoff"], "sync"
    else:
        base, anchor, source = d["budget"], _floor_hour(_parse_ts(d["since"]) or now), "budget"
    after = _app_between(d, anchor)
    spent_after = sum(cost_of(n, m, plan) for m, n in after.items())
    remaining = max(0.0, base - spent_after)
    ref = max(d["budget"], base)
    rate = rate_per_million(model, plan)
    all_app = _app_between(d, 0)
    adj = (s or {}).get("adj") or {}
    by_model = {}
    for m in set(all_app) | set(adj):
        by_model[m] = all_app.get(m, 0) + adj.get(m, 0)
    return {
        "plan": plan,
        "plan_label": PLAN_LABEL[plan],
        "since": d["since"],
        "source": source,                     # "sync" = balance from Billing, "budget" = plan credit
        "base": base,
        "anchor": anchor,
        "chars": sum(by_model.values()),      # everything known (app history + last sync adjustment)
        "chars_after": sum(after.values()),   # read in the app since the anchor
        "spent": max(0.0, ref - remaining) if ref > 0 else spent_after,
        "spent_after": spent_after,
        "budget": ref,
        "remaining": remaining,
        "used_pct": (min(100.0, (ref - remaining) / ref * 100) if ref > 0 else None),
        "left_pct": (max(0.0, remaining / ref * 100) if ref > 0 else None),
        "chars_left": int(remaining / rate * 1_000_000) if rate > 0 and ref > 0 else None,
        "rate": rate,
        "model": model,
        "by_model": sorted(((m, n, cost_of(n, m, plan)) for m, n in by_model.items()), key=lambda x: -x[1]),
        "requests": d["requests"],
        "sync": s,
    }


def series(data: dict | None, view: str = "30d", now: float | None = None) -> dict:
    """Bars (hourly for 24 h, daily UTC otherwise), per-model totals and cost for one window."""
    d = normalize(data)
    now = _now(now)
    days = VIEW_DAYS.get(view, 30)
    if days == 1:
        last = _floor_hour(now)
        starts = [last - 3600 * i for i in range(23, -1, -1)]
        step = 3600
        labels = [datetime.fromtimestamp(t).strftime("%H:%M") for t in starts]
    else:
        today = datetime.fromtimestamp(now, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        days_list = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
        starts = [t.timestamp() for t in days_list]
        step = 86400
        labels = [f"{t.month}/{t.day}" for t in days_list]
    begin, end = starts[0], starts[-1] + step
    n = len(starts)
    app: dict[str, list[int]] = {}
    for key, per in d["hours"].items():
        h = hour_start(key)
        if begin <= h < end:
            i = min(n - 1, int((h - begin) // step))
            for m, c in per.items():
                app.setdefault(m, [0] * n)[i] += c
    synced: dict[str, list[int]] = {}
    s = d["sync"]
    note = None
    included = False
    if s and s.get("adj"):
        if days >= s["days"] and begin <= s["at"] < end:
            included = True
            i = min(n - 1, int((s["at"] - begin) // step))
            for m, c in s["adj"].items():
                synced.setdefault(m, [0] * n)[i] += c
        elif days < s["days"]:
            note = (f"Số đồng bộ từ Inworld là của {s['days']} ngày nên không chia được vào khung "
                    f"{dict((k, l) for k, l, _d in VIEWS)[view]} — xem khung ≥ {s['days']} ngày để thấy đủ.")
    models = sorted(set(app) | set(synced), key=lambda m: (SYNC_MODELS.index(m) if m in SYNC_MODELS else 99, m))
    totals = {}
    for m in models:
        a = sum(app.get(m, [])) if m in app else 0
        sy = sum(synced.get(m, [])) if m in synced else 0
        totals[m] = {"app": a, "sync": sy, "chars": a + sy, "cost": cost_of(a + sy, m, d["plan"])}
    return {
        "view": view, "days": days, "labels": labels, "starts": starts, "step": step,
        "models": models, "app": app, "sync": synced, "totals": totals,
        "chars": sum(t["chars"] for t in totals.values()),
        "cost": sum(t["cost"] for t in totals.values()),
        "sync_included": included, "note": note, "plan": d["plan"],
    }


# ---------------------------------------------------------------- formatting
def fmt_usd(v: float) -> str:
    if v >= 100:
        return f"${v:,.0f}".replace(",", ".")
    if v >= 1:
        return f"${v:,.2f}"
    if v >= 0.001:
        return f"${v:.3f}"
    return "<$0.001" if v > 0 else "$0"


def fmt_int(n: int) -> str:
    return f"{int(n):,}".replace(",", ".")


def fmt_short(n: float) -> str:
    """2755 → 2.8K like Inworld's charts."""
    n = float(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1000:
        return f"{n / 1000:.1f}K".replace(".0K", "K")
    return str(int(n))


def fmt_ago(ts: float | None, now: float | None = None) -> str:
    if ts is None:
        return "chưa đồng bộ"
    sec = max(0, _now(now) - ts)
    if sec < 90:
        return "vừa xong"
    if sec < 3600:
        return f"{int(sec // 60)} phút trước"
    if sec < 86400:
        return f"{int(sec // 3600)} giờ trước"
    return f"{int(sec // 86400)} ngày trước"
