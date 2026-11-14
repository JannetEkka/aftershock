"""Event finder (code, not a model): which days had a spike of news about NEAR?

Rule, fixed before any result was seen:
  a day is a spike when its news count is above the 95th percentile of the previous 90 days
  and at least MIN_COUNT articles; spikes within 3 days of each other merge into one event.
"""
import math
from datetime import date

LOOKBACK = 90
PCT = 95
MERGE_GAP = 3
MIN_COUNT = 3


def percentile(values, p):
    """Linear-interpolation percentile of a non-empty list."""
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p / 100.0
    lo = math.floor(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def spike_days(counts):
    out = []
    for i in range(LOOKBACK, len(counts)):
        c = counts[i]
        prev = [x for x in counts[i - LOOKBACK:i] if x is not None]
        if c is None or len(prev) < LOOKBACK or c < MIN_COUNT:
            continue
        if c > percentile(prev, PCT):
            out.append(i)
    return out


def find_events(dates, counts):
    """Return events as dicts: id, start, end (ISO days), index (row of the first day), peak, articles."""
    groups = []
    for i in spike_days(counts):
        if groups and i - groups[-1][-1] <= MERGE_GAP:
            groups[-1].append(i)
        else:
            groups.append([i])
    events = []
    for n, g in enumerate(groups, 1):
        span = range(g[0], g[-1] + 1)
        events.append({
            "id": f"E{n:03d}", "start": dates[g[0]], "end": dates[g[-1]], "index": g[0],
            "days": (date.fromisoformat(dates[g[-1]]) - date.fromisoformat(dates[g[0]])).days + 1,
            "peak": max(counts[i] or 0 for i in span), "articles": sum(counts[i] or 0 for i in span),
        })
    return events
