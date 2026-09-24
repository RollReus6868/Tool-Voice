"""Inworld plan & spending tracker (no Qt here — unit-testable).

Inworld has no public API for plan, balance or usage, so the app keeps its own
tally: every successful synthesis adds the characters Inworld reports
(usage.processedCharactersCount) and their price for the model and plan.
The user types the credit balance shown on the Billing page once per period;
the app then shows spent / remaining / percent. Prices: inworld.ai/pricing (09/2026).
"""
from __future__ import annotations

from datetime import datetime

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

BILLING_URL = "https://platform.inworld.ai/billing"
USAGE_URL = "https://platform.inworld.ai/usage"


def rate_per_million(model: str, plan: str) -> float:
    model = model if model in RATES else RATE_FALLBACK.get(model, DEFAULT_MODEL)
    table = RATES.get(model, RATES[DEFAULT_MODEL])
    return table.get(plan, table["on_demand"])


def cost_of(chars: int, model: str, plan: str) -> float:
    return max(0, int(chars)) * rate_per_million(model, plan) / 1_000_000


def new_period(plan: str = "on_demand", budget: float | None = None) -> dict:
    return {
        "plan": plan if plan in PLAN_LABEL else "on_demand",
        "budget": float(PLAN_CREDITS.get(plan, 0.0) if budget is None else budget),
        "since": datetime.now().isoformat(timespec="seconds"),
        "chars": {},     # model -> characters
        "cost": {},      # model -> USD
        "requests": 0,
    }


def normalize(data: dict | None) -> dict:
    base = new_period()
    if isinstance(data, dict):
        for k in base:
            if k in data:
                base[k] = data[k]
    base["chars"] = {str(k): int(v) for k, v in dict(base.get("chars") or {}).items() if v}
    base["cost"] = {str(k): float(v) for k, v in dict(base.get("cost") or {}).items() if v}
    try:
        base["budget"] = max(0.0, float(base.get("budget") or 0))
    except (TypeError, ValueError):
        base["budget"] = 0.0
    if base["plan"] not in PLAN_LABEL:
        base["plan"] = "on_demand"
    return base


def record(data: dict | None, model: str, chars: int) -> dict:
    """Return a new tally with one synthesis added (priced with the current plan)."""
    d = normalize(data)
    chars = max(0, int(chars))
    if not chars:
        return d
    model = model or DEFAULT_MODEL
    d["chars"][model] = d["chars"].get(model, 0) + chars
    d["cost"][model] = round(d["cost"].get(model, 0.0) + cost_of(chars, model, d["plan"]), 6)
    d["requests"] = int(d.get("requests") or 0) + 1
    return d


def summary(data: dict | None, model: str = DEFAULT_MODEL) -> dict:
    d = normalize(data)
    chars = sum(d["chars"].values())
    spent = sum(d["cost"].values())
    budget = d["budget"]
    remaining = max(0.0, budget - spent)
    rate = rate_per_million(model, d["plan"])
    return {
        "plan": d["plan"],
        "plan_label": PLAN_LABEL[d["plan"]],
        "since": d["since"],
        "chars": chars,
        "spent": spent,
        "budget": budget,
        "remaining": remaining,
        "used_pct": (min(100.0, spent / budget * 100) if budget > 0 else None),
        "left_pct": (max(0.0, 100 - spent / budget * 100) if budget > 0 else None),
        "chars_left": int(remaining / rate * 1_000_000) if rate > 0 and budget > 0 else None,
        "rate": rate,
        "model": model,
        "by_model": sorted(((m, d["chars"][m], d["cost"].get(m, 0.0)) for m in d["chars"]),
                           key=lambda x: -x[1]),
        "requests": int(d.get("requests") or 0),
    }


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
