"""Event test (code, not a model): did a measure change more after a news event than it does on ordinary days?

For a day i and a measure:  change = mean(the AFTER days starting on day i) / mean(the 28 days before day i) - 1.
We compute that for every event and for every ordinary day. An event "moved" the measure only if its change
falls outside the middle 95% of the ordinary-day changes. By chance alone about 5% of events would pass.
"""
from .events import percentile

BEFORE = 28
AFTER = 7
SENSITIVITY = (3, 7, 14)
MEASURES = ["price", "txns", "active_accounts", "new_accounts", "dex_volume", "intents_volume"]
USAGE = ["txns", "active_accounts", "new_accounts", "dex_volume", "intents_volume"]
NAMES = {"price": "price", "txns": "transactions", "active_accounts": "active accounts",
         "new_accounts": "new accounts", "dex_volume": "DEX volume", "intents_volume": "Intents volume",
         "tvl": "value locked (TVL)", "stablecoins": "stablecoins on NEAR", "fees_usd": "fees (USD)"}
MIN_ORDINARY = 200  # fewer ordinary days than this and the measure is "not tested"


def change(series, i, after=AFTER, before=BEFORE):
    """Fractional change from the `before` days ending the day before i to the `after` days starting on i.
    None if any day in either window is missing (then the measure is 'not tested', never 'nothing')."""
    if i - before < 0 or i + after > len(series):
        return None
    b = series[i - before:i]
    a = series[i:i + after]
    if any(v is None for v in b) or any(v is None for v in a):
        return None
    mb = sum(b) / before
    if mb <= 0:
        return None
    return (sum(a) / after) / mb - 1.0


def event_day_mask(n, events):
    mask = [False] * n
    for ev in events:
        for i in range(ev["index"], ev["index"] + ev["days"]):
            if 0 <= i < n:
                mask[i] = True
    return mask


def ordinary_indices(n, events, after=AFTER):
    """Ordinary day: no news-event day anywhere in its own AFTER window."""
    mask = event_day_mask(n, events)
    return [i for i in range(n) if not any(mask[i:i + after])]


def band(series, ordinary, after=AFTER):
    """(low, high, how many ordinary days) = the middle 95% of ordinary-day changes."""
    ch = [c for c in (change(series, i, after) for i in ordinary) if c is not None]
    if len(ch) < MIN_ORDINARY:
        return None
    return percentile(ch, 2.5), percentile(ch, 97.5), len(ch)


def verdict(c, bnd):
    if c is None or bnd is None:
        return "not_tested"
    if c > bnd[1]:
        return "up"
    if c < bnd[0]:
        return "down"
    return "inside"


def stamp(verdicts):
    """One stamp per event from its per-measure verdicts."""
    tested = [m for m, v in verdicts.items() if v != "not_tested"]
    if not tested:
        return "not_tested"
    if any(verdicts[m] in ("up", "down") for m in USAGE if m in verdicts):
        return "moved_usage"
    if verdicts.get("price") in ("up", "down"):
        return "price_only"
    return "nothing"


def binom_tail(k, n, p):
    """P(X >= k) for X ~ Binomial(n, p)."""
    if n == 0:
        return 1.0
    from math import comb
    return sum(comb(n, j) * p ** j * (1 - p) ** (n - j) for j in range(k, n + 1))


def run(cols, events, after=AFTER):
    """Run the test for one AFTER window. Returns per-event results, per-measure summary and stamp summary."""
    n = len(cols["price"])
    ordinary = ordinary_indices(n, events, after)
    bands = {m: band(cols[m], ordinary, after) for m in MEASURES}
    per_event = []
    for ev in events:
        res = {}
        for m in MEASURES:
            c = change(cols[m], ev["index"], after)
            res[m] = {"change": c, "verdict": verdict(c, bands[m])}
        per_event.append({"id": ev["id"], "measures": res, "stamp": stamp({m: r["verdict"] for m, r in res.items()})})
    measures = {}
    for m in MEASURES:
        vs = [e["measures"][m]["verdict"] for e in per_event]
        tested = sum(v != "not_tested" for v in vs)
        moved = sum(v in ("up", "down") for v in vs)
        measures[m] = {"tested": tested, "moved": moved, "up": vs.count("up"), "down": vs.count("down"),
                       "not_tested": vs.count("not_tested"), "expected_by_chance": round(0.05 * tested, 2),
                       "p_value": binom_tail(moved, tested, 0.05),
                       "band": None if bands[m] is None else {"low": bands[m][0], "high": bands[m][1], "ordinary_days": bands[m][2]}}
    # The stamp looks at several measures at once, so its chance rate is not 5%. Measure it: stamp every ordinary day.
    ord_stamps = []
    for i in ordinary:
        v = {m: verdict(change(cols[m], i, after), bands[m]) for m in MEASURES}
        s = stamp(v)
        if s != "not_tested":
            ord_stamps.append((s, v["price"]))
    stamps = [e["stamp"] for e in per_event]
    tested = sum(s != "not_tested" for s in stamps)
    n_ord = len(ord_stamps)
    price_tested = measures["price"]["tested"]
    summary = {
        "after_days": after, "before_days": BEFORE, "events": len(events), "events_tested": tested,
        "ordinary_days": n_ord,
        "moved_usage": stamps.count("moved_usage"), "price_only": stamps.count("price_only"),
        "nothing": stamps.count("nothing"), "not_tested": stamps.count("not_tested"),
        "moved_price": measures["price"]["moved"], "price_tested": price_tested,
        "chance_moved_usage": sum(s == "moved_usage" for s, _ in ord_stamps) / n_ord if n_ord else None,
        "chance_price_only": sum(s == "price_only" for s, _ in ord_stamps) / n_ord if n_ord else None,
        "chance_moved_price": sum(p in ("up", "down") for _, p in ord_stamps) / max(1, sum(p != "not_tested" for _, p in ord_stamps)),
    }
    if n_ord:
        summary["p_moved_usage"] = binom_tail(summary["moved_usage"], tested, summary["chance_moved_usage"])
        summary["p_moved_price"] = binom_tail(summary["moved_price"], price_tested, summary["chance_moved_price"])
    return {"events": per_event, "measures": measures, "summary": summary}


def run_all(cols, events):
    return {str(a): run(cols, events, a) for a in SENSITIVITY}


def print_report(results):
    for a, r in results.items():
        s = r["summary"]
        print(f"\nAFTER window = {a} days (before = {BEFORE} days). {s['events']} news events, {s['ordinary_days']} ordinary days.")
        print(f"  {'measure':<17}{'tested':>7}{'moved':>7}{'up':>5}{'down':>6}{'not tested':>12}{'chance (5%)':>13}")
        for m in MEASURES:
            x = r["measures"][m]
            print(f"  {NAMES[m]:<17}{x['tested']:>7}{x['moved']:>7}{x['up']:>5}{x['down']:>6}{x['not_tested']:>12}{x['expected_by_chance']:>13}")
        print(f"  stamps: moved usage {s['moved_usage']}, price only {s['price_only']}, nothing {s['nothing']}, not tested {s['not_tested']}")
        print(f"  the same rule stamps {100 * s['chance_moved_usage']:.1f}% of ordinary days 'moved usage' "
              f"(events: {100 * s['moved_usage'] / max(1, s['events_tested']):.1f}%)")
