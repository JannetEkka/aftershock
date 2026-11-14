"""Claims: the fixed forms a model may write, the recomputation of each figure, and the keep-or-remove rule.

The model describes, the code decides. A claim is KEPT only if
  1. its form is valid (allowed kind, measure, period, window),
  2. every event id it cites exists,
  3. its figure matches our recomputation from the snapshot within 1%, and
  4. the Examiner (a model from the other family) says the wording is supported.
"""
import calendar
import re

from . import eventtest

MEASURES = ["price", "txns", "active_accounts", "new_accounts", "dex_volume", "intents_volume", "tvl", "stablecoins", "fees_usd"]
KINDS = {
    "event_change": "percent change of a measure from the 28 days before an event to the N days after it",
    "events_moved": "how many news events moved a measure (or got a stamp) in the event test",
    "chance_rate": "percent of ORDINARY days that get a stamp under the same rule",
    "period_mean": "average daily value of a measure over a year (YYYY) or a month (YYYY-MM)",
    "period_change": "percent change of a measure's average from one period to another",
}
STAMPS = ["moved_usage", "price_only", "nothing"]
TOLERANCE = 0.01       # figure must be within 1% of the recomputation
ROUNDING = 0.005       # ... or differ only by rounding at two decimals
PERIOD = re.compile(r"^(\d{4})(?:-(\d{2}))?$")


class Context:
    """Everything the recomputation needs: the daily table, the events and the event-test results."""

    def __init__(self, dates, cols, events, tests):
        self.dates, self.cols, self.events, self.tests = dates, cols, events, tests
        self.event_ids = {e["id"] for e in events}
        self.index = {d: i for i, d in enumerate(dates)}

    def period_mean(self, measure, period):
        """Mean over the days of a period that are in the snapshot. None unless 80% of those days have a value."""
        m = PERIOD.match(period or "")
        if not m:
            return None
        y, mo = int(m.group(1)), m.group(2)
        if mo:
            if not 1 <= int(mo) <= 12:
                return None
            lo, hi = f"{y}-{mo}-01", f"{y}-{mo}-{calendar.monthrange(y, int(mo))[1]:02d}"
        else:
            lo, hi = f"{y}-01-01", f"{y}-12-31"
        idx = [i for i, d in enumerate(self.dates) if lo <= d <= hi]
        vals = [self.cols[measure][i] for i in idx if self.cols[measure][i] is not None]
        if not idx or len(vals) < 0.8 * len(idx):
            return None
        return sum(vals) / len(vals)


def validate_form(c, ctx):
    """Return an error string, or None if the claim's form is valid."""
    if not isinstance(c, dict):
        return "claim is not an object"
    kind = c.get("kind")
    if kind not in KINDS:
        return f"kind must be one of {sorted(KINDS)}"
    if not isinstance(c.get("text"), str) or not 10 <= len(c["text"]) <= 400:
        return "text must be a sentence of 10 to 400 characters"
    if isinstance(c.get("figure"), bool) or not isinstance(c.get("figure"), (int, float)):
        return "figure must be a number"
    ids = c.get("event_ids", [])
    if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
        return "event_ids must be a list of event ids"
    after = c.get("after_days", 7)
    if kind in ("event_change", "events_moved", "chance_rate") and after not in eventtest.SENSITIVITY:
        return f"after_days must be one of {list(eventtest.SENSITIVITY)}"
    if kind == "event_change":
        if c.get("measure") not in eventtest.MEASURES:
            return f"measure must be one of {eventtest.MEASURES}"
        if not isinstance(c.get("event_id"), str):
            return "event_id is required"
    elif kind == "events_moved":
        if c.get("measure") not in eventtest.MEASURES + STAMPS:
            return f"measure must be one of {eventtest.MEASURES + STAMPS}"
    elif kind == "chance_rate":
        if c.get("measure") not in STAMPS:
            return f"measure must be one of {STAMPS}"
    else:
        if c.get("measure") not in MEASURES:
            return f"measure must be one of {MEASURES}"
        periods = [c.get("period")] + ([c.get("period_b")] if kind == "period_change" else [])
        if not all(isinstance(p, str) and PERIOD.match(p) for p in periods):
            return "period (and period_b for period_change) must look like YYYY or YYYY-MM"
    return None


def cited_events(c):
    ids = list(c.get("event_ids", []))
    if c.get("kind") == "event_change" and c.get("event_id") not in ids:
        ids.insert(0, c.get("event_id"))
    return ids


def recompute(c, ctx):
    """Recompute a claim's figure from the snapshot. Returns (value, how) or (None, why not)."""
    kind, m = c["kind"], c["measure"]
    after = str(c.get("after_days", 7))
    if kind == "event_change":
        ev = next(e for e in ctx.events if e["id"] == c["event_id"])
        ch = eventtest.change(ctx.cols[m], ev["index"], int(after))
        if ch is None:
            return None, "the snapshot has missing days in this event's window"
        return 100 * ch, f"100 * (mean of {m} over the {after} days from {ev['start']} / mean over the 28 days before - 1)"
    if kind == "events_moved":
        r = ctx.tests[after]
        if m in STAMPS:
            return float(r["summary"][m]), f"events stamped '{m}' in the {after}-day event test"
        return float(r["measures"][m]["moved"]), f"events where {m} left the ordinary-day band in the {after}-day event test"
    if kind == "chance_rate":
        s = ctx.tests[after]["summary"]
        if m == "nothing":
            v = 1 - s["chance_moved_usage"] - s["chance_price_only"]
        else:
            v = s["chance_" + m]
        return 100 * v, f"percent of ordinary days stamped '{m}' by the same rule, {after}-day window"
    a = ctx.period_mean(m, c["period"])
    if a is None:
        return None, f"the snapshot does not cover {m} for {c['period']}"
    if kind == "period_mean":
        return a, f"mean of daily {m} over {c['period']}"
    b = ctx.period_mean(m, c["period_b"])
    if b is None:
        return None, f"the snapshot does not cover {m} for {c['period_b']}"
    if a == 0:
        return None, "the first period's mean is zero"
    return 100 * (b / a - 1), f"100 * (mean of {m} over {c['period_b']} / mean over {c['period']} - 1)"


def figure_matches(figure, value, kind):
    if kind == "events_moved":
        return float(figure) == value
    return abs(figure - value) <= max(TOLERANCE * abs(value), ROUNDING)


def code_checks(c, ctx):
    """Steps 1-3 of the rule. Returns a dict with status 'pass' or 'removed' and the reason."""
    err = validate_form(c, ctx)
    if err:
        return {"status": "removed", "reason": "malformed: " + err, "recomputed": None, "how": None}
    missing = [e for e in cited_events(c) if e not in ctx.event_ids]
    if missing:
        return {"status": "removed", "reason": "cites an event that does not exist: " + ", ".join(missing), "recomputed": None, "how": None}
    value, how = recompute(c, ctx)
    if value is None:
        return {"status": "removed", "reason": "cannot be recomputed: " + how, "recomputed": None, "how": how}
    if not figure_matches(c["figure"], value, c["kind"]):
        return {"status": "removed", "reason": f"figure {c['figure']} does not match the recomputed {round(value, 4)} within 1%",
                "recomputed": value, "how": how}
    return {"status": "pass", "reason": None, "recomputed": value, "how": how}


def decide(code, examiner):
    """The decision rule. `code` is from code_checks; `examiner` is {'verdict','reason'} or None (no valid reply)."""
    if code["status"] != "pass":
        return "removed", code["reason"]
    if examiner is None:
        return "removed", "the Examiner gave no valid verdict"
    if examiner.get("verdict") != "supported":
        return "removed", "Examiner: " + str(examiner.get("reason", "not supported"))
    return "kept", None


NUMBER = re.compile(r"(?<![A-Za-z0-9])[-+]?\$?\d[\d,]*(?:\.\d+)?")


def numbers_in(text):
    """Numbers written in a sentence. Event ids (E012), claim ids (B3) are skipped by the regex's look-behind."""
    out = []
    for tok in NUMBER.findall(text):
        t = tok.replace(",", "").replace("$", "").lstrip("+")
        try:
            out.append(float(t))
        except ValueError:
            pass
    return out


def number_supported(n, allowed):
    """A number in a thesis sentence is fine if it equals an allowed number, sign aside, after rounding to 0-2 decimals."""
    for a in allowed:
        for dec in (0, 1, 2):
            if abs(abs(n) - round(abs(a), dec)) < 1e-9:
                return True
        if a and abs(abs(n) - abs(a)) <= TOLERANCE * abs(a):
            return True
    return False


def allowed_numbers(claim):
    """Numbers a sentence may use when it cites this kept claim: its figure, recomputation, and whatever its own text states."""
    out = [claim["figure"], claim["recomputed"], 28.0, 95.0, 5.0, float(claim.get("after_days") or 7)]
    out += numbers_in(claim["text"])
    for p in (claim.get("period"), claim.get("period_b")):
        if p:
            out += [float(x) for x in p.split("-")]
    out += claim.get("context_numbers", [])
    return out


def final_check(sentences, kept):
    """Final check on the Judge's thesis. A sentence stays only if it cites at least one claim, every cited id
    is a kept claim, and every number in it is backed by a cited claim. Returns the sentences with status."""
    out = []
    for s in sentences:
        ids = s.get("claims") if isinstance(s, dict) else None
        text = s.get("text") if isinstance(s, dict) else None
        if not isinstance(text, str) or not text.strip():
            continue
        reason = None
        if not isinstance(ids, list) or not ids:
            reason, ids = "cites no claim", []
        elif any(i not in kept for i in ids):
            reason = "cites a claim that was not kept: " + ", ".join(str(i) for i in ids if i not in kept)
        else:
            allowed = [n for i in ids for n in allowed_numbers(kept[i])]
            bad = [n for n in numbers_in(text) if not number_supported(n, allowed)]
            if bad:
                reason = "contains a number no cited claim backs: " + ", ".join(f"{b:g}" for b in bad)
        out.append({"text": text.strip(), "claims": ids, "status": "cut" if reason else "kept", "reason": reason})
    return out
