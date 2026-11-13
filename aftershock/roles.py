"""The model roles: what each is asked, and how each reply is validated (required fields, allowed values)."""
from . import claims, eventtest
from .eventtest import NAMES

EVENT_TYPES = ["upgrade", "partnership", "listing", "security", "people", "market-wide", "other"]
FORECAST_MEASURES = ["price", "txns", "active_accounts", "new_accounts", "dex_volume", "intents_volume", "tvl", "stablecoins"]
HORIZONS = [7, 30, 90]
JSON_ONLY = "Reply with one JSON object only: no prose before or after it, no markdown fences."

# ---------- Labeller ----------
LABEL_SYS = ("You label a news event about NEAR Protocol from its headlines. " + JSON_ONLY +
             ' Form: {"type": one of ' + " | ".join(EVENT_TYPES) + ', "summary": one plain sentence of at most 140 characters '
             "saying what the news was}. Use only what the headlines say. If the headlines are mostly generic price commentary "
             'or about the whole crypto market, the type is "market-wide".')


def label_user(ev, headlines):
    lines = "\n".join(f"- {h['title']} ({h['domain']})" for h in headlines[:20])
    return f"News spike from {ev['start']} to {ev['end']} ({int(ev['articles'])} articles).\nHeadlines:\n{lines}"


def label_valid(o):
    if o.get("type") not in EVENT_TYPES:
        return f"type must be one of {EVENT_TYPES}"
    if not isinstance(o.get("summary"), str) or not 5 <= len(o["summary"]) <= 200:
        return "summary must be one sentence of 5 to 200 characters"
    return None


# ---------- The data brief shown to Bull, Bear and nobody else ----------
def fmt(v):
    if v is None:
        return "n/a"
    a = abs(v)
    return f"{v:.4f}" if a < 10 else (f"{v:.2f}" if a < 1000 else f"{v:.0f}")


def data_brief(ctx, labels, cutoff):
    L = [f"SNAPSHOT of NEAR's public daily records, through {cutoff}.",
         "Measures: " + ", ".join(f"{m} ({NAMES[m]})" for m in claims.MEASURES) + ".",
         "", "EVENT TEST. A news event is a day when news about NEAR spiked. For each event and measure: change from the 28 days",
         "before to the N days after. An event 'moved' a measure only if that change is outside the middle 95% of the same",
         "change on ordinary days, so about 5% would pass by chance. Stamps: moved_usage (any of txns, active_accounts,",
         "new_accounts, dex_volume, intents_volume moved), price_only (price moved, no usage measure did), nothing."]
    for a in ("7", "3", "14"):
        r = ctx.tests[a]
        s = r["summary"]
        L.append(f"\nWindow N={a} days: {s['events']} events.")
        for m in eventtest.MEASURES:
            x = r["measures"][m]
            L.append(f"  {m}: tested {x['tested']}, moved {x['moved']} (up {x['up']}, down {x['down']}), expected by chance {x['expected_by_chance']}")
        L.append(f"  stamps: moved_usage {s['moved_usage']}, price_only {s['price_only']}, nothing {s['nothing']}")
        L.append(f"  chance_rate (percent of ORDINARY days given each stamp by the same rule): moved_usage {100 * s['chance_moved_usage']:.2f}, "
                 f"price_only {100 * s['chance_price_only']:.2f}, nothing {100 * (1 - s['chance_moved_usage'] - s['chance_price_only']):.2f}")
    L.append("\nEVENTS (N=7 window; percent change, then verdict: up/down = outside the ordinary band, inside = within it, n/t = not tested):")
    by_id = {e["id"]: e for e in ctx.tests["7"]["events"]}
    for ev in ctx.events:
        lab = labels[ev["id"]]
        r = by_id[ev["id"]]
        parts = []
        for m in eventtest.MEASURES:
            x = r["measures"][m]
            parts.append(f"{m} n/t" if x["change"] is None else f"{m} {100 * x['change']:+.2f}% {x['verdict']}")
        L.append(f"{ev['id']} {ev['start']} [{lab['type']}] {lab['summary']} | stamp {r['stamp']} | " + "; ".join(parts))
    years = sorted({d[:4] for d in ctx.dates})
    L.append("\nYEARLY MEANS of each daily measure (the first and last years are partial):")
    for m in claims.MEASURES:
        L.append(f"  {m}: " + ", ".join(f"{y} {fmt(ctx.period_mean(m, y))}" for y in years))
    months = sorted({d[:7] for d in ctx.dates})[-19:-1]
    L.append("\nMONTHLY MEANS, last 18 complete months:")
    for m in claims.MEASURES:
        L.append(f"  {m}: " + ", ".join(f"{mo} {fmt(ctx.period_mean(m, mo))}" for mo in months))
    return "\n".join(L)


CLAIM_FORM = """Each claim is an object:
{"kind": ..., "measure": ..., "figure": number, "text": one sentence, "event_ids": [ids of events the sentence refers to, may be empty], plus the fields its kind needs}
Kinds and their extra fields:
- "event_change": needs "event_id" and "after_days" (3, 7 or 14); measure is one of price, txns, active_accounts, new_accounts, dex_volume, intents_volume. figure = the percent change for that event.
- "events_moved": needs "after_days"; measure is one of those six measures or a stamp (moved_usage, price_only, nothing). figure = the count of events.
- "chance_rate": needs "after_days"; measure is a stamp. figure = percent of ordinary days given that stamp.
- "period_mean": needs "period" ("YYYY" or "YYYY-MM"); any measure. figure = the mean daily value.
- "period_change": needs "period" and "period_b"; any measure. figure = percent change of the mean from period to period_b.
Code recomputes every figure from the snapshot and removes the claim if it is off by more than 1%, so copy figures exactly or compute them carefully.
A second model then reads only your sentence and the evidence, and removes the claim if the sentence says more than the figure and the events show.
Say what happened AFTER an event, never that the event caused it. Do not use facts that are not in the data below."""


def side_sys(side):
    stance = ("the BULL: argue the strongest honest case that NEAR is worth holding for years"
              if side == "bull" else "the BEAR: argue the strongest honest case against holding NEAR for years")
    return (f"You are {stance}, using only the data you are given. " + JSON_ONLY +
            ' Form: {"claims": [6 to 8 claims]}.\n' + CLAIM_FORM)


def rebut_sys(side):
    return (f"You are the {'BULL' if side == 'bull' else 'BEAR'} in a debate about holding NEAR for years. You are shown the other side's claims. "
            "Answer them with 1 to 3 new claims from the same data that weaken their case. " + JSON_ONLY +
            ' Form: {"claims": [1 to 3 claims, each also with "rebuts": the id of the claim it answers]}.\n' + CLAIM_FORM)


def claims_valid(lo, hi):
    def v(o):
        cl = o.get("claims")
        if not isinstance(cl, list) or not lo <= len(cl) <= hi:
            return f'"claims" must be a list of {lo} to {hi} claims'
        for i, c in enumerate(cl):
            if not isinstance(c, dict) or c.get("kind") not in claims.KINDS or not isinstance(c.get("text"), str):
                return f"claim {i + 1} needs a kind from {sorted(claims.KINDS)} and a text"
        return None
    return v


# ---------- Examiner ----------
EXAM_SYS = ("You are the EXAMINER. You see one sentence from an analyst, the figure our code recomputed for it, and the evidence. "
            "You do not see the analyst's reasoning. Decide whether the sentence is supported. It is supported only if: "
            "the direction and size words fit the figure (a 2% change is not a surge); it does not say or imply that a news "
            "event CAUSED a change (saying a change came 'after' an event is fine); it does not present a change that is inside "
            "the ordinary band as a real effect of the event; and it states no fact that is missing from the evidence. "
            + JSON_ONLY + ' Form: {"verdict": "supported" or "not_supported", "reason": one short sentence}.')


def exam_user(c, code, ctx, labels, headlines):
    L = [f'Sentence: "{c["text"]}"', f"What the figure means: {code['how']}", f"Recomputed figure: {round(code['recomputed'], 4)}"]
    after = str(c.get("after_days", 7))
    if c["kind"] in ("events_moved", "chance_rate"):
        r = ctx.tests[after]
        s = r["summary"]
        L.append(f"Event test, {after}-day window: {s['events']} events; stamped moved_usage {s['moved_usage']}, price_only {s['price_only']}, nothing {s['nothing']}.")
        L.append(f"The same rule stamps {100 * s['chance_moved_usage']:.2f}% of ordinary days moved_usage and {100 * s['chance_price_only']:.2f}% price_only.")
        if c["measure"] in r["measures"]:
            x = r["measures"][c["measure"]]
            L.append(f"{c['measure']}: tested {x['tested']}, moved {x['moved']} (up {x['up']}, down {x['down']}), expected by chance {x['expected_by_chance']}.")
    by_id = {e["id"]: e for e in ctx.tests[after]["events"]}
    for eid in claims.cited_events(c):
        ev = next(e for e in ctx.events if e["id"] == eid)
        r = by_id[eid]
        L.append(f"\nEvent {eid}, {ev['start']} to {ev['end']}, type {labels[eid]['type']}: {labels[eid]['summary']}")
        for h in headlines.get(ev["start"] + "_" + ev["end"], [])[:6]:
            L.append(f"  headline: {h['title']}")
        L.append(f"  {after}-day test: " + "; ".join(
            f"{m} n/t" if x["change"] is None else f"{m} {100 * x['change']:+.2f}% ({'outside the ordinary band, ' + x['verdict'] if x['verdict'] in ('up', 'down') else 'inside the ordinary band'})"
            for m, x in r["measures"].items()) + f". Stamp: {r['stamp']}.")
    return "\n".join(L)


def exam_valid(o):
    if o.get("verdict") not in ("supported", "not_supported"):
        return 'verdict must be "supported" or "not_supported"'
    if not isinstance(o.get("reason"), str) or not o["reason"].strip():
        return "reason must be a short sentence"
    return None


# ---------- Judge ----------
SECTIONS = ["claim", "evidence_for", "evidence_against", "change_our_mind"]
JUDGE_SYS = ("You are the JUDGE. You write a long-term investment thesis for NEAR from the checked claims below and from nothing else. "
             "Both the Bull's and the Bear's kept claims must be weighed. Every sentence must list the ids of the claims it rests on. "
             "Code will cut any sentence that cites no kept claim or contains a number that its cited claims do not contain, so reuse "
             "the claims' own numbers and add no others. Plain words, no hype, no advice to buy or sell. " + JSON_ONLY +
             ' Form: {"title": at most 12 words, "claim": [2-3 sentences: the thesis itself], "evidence_for": [2-5 sentences], '
             '"evidence_against": [2-5 sentences], "change_our_mind": [2-3 sentences: what measured result would change this thesis]} '
             'where each sentence is {"text": ..., "claims": [claim ids]}.')


def judge_user(kept):
    return "KEPT CLAIMS:\n" + "\n".join(
        f"{c['id']} ({c['side']}): {c['text']} [figure {round(c['recomputed'], 4)}; {c['how']}]" for c in kept)


def judge_valid(o):
    if not isinstance(o.get("title"), str) or not o["title"].strip():
        return "title is required"
    for s in SECTIONS:
        v = o.get(s)
        if not isinstance(v, list) or not v:
            return f'"{s}" must be a non-empty list of sentences'
        for x in v:
            if not isinstance(x, dict) or not isinstance(x.get("text"), str) or not isinstance(x.get("claims"), list):
                return f'every sentence in "{s}" must be {{"text": ..., "claims": [...]}}'
    return None


# ---------- AI alone (baseline) ----------
BASE_SYS = ("You are a crypto analyst. No data is provided: answer from your own knowledge. Write a long-term investment thesis for "
            "NEAR Protocol as 10 specific numeric claims. " + JSON_ONLY + ' Form: {"claims": [10 claims]}. Each claim: '
            '{"text": one sentence, "kind": "period_mean" | "period_change" | "other", "measure": one of ' + ", ".join(claims.MEASURES) +
            ' or "other", "period": "YYYY" or "YYYY-MM", "period_b": the later period (period_change only), "figure": number}. '
            "period_mean = the average DAILY value over that period (price in USD, txns/active_accounts/new_accounts as daily counts, "
            "dex_volume/intents_volume/fees_usd in USD per day, tvl/stablecoins in USD). period_change = percent change of that "
            'average from period to period_b. Use kind "other" for anything else. Prefer claims of the first two kinds.')
BASE_USER = "Write the thesis claims for NEAR Protocol now."


def base_valid(o):
    cl = o.get("claims")
    if not isinstance(cl, list) or not 5 <= len(cl) <= 12:
        return '"claims" must be a list of 5 to 12 claims'
    for i, c in enumerate(cl):
        if not isinstance(c, dict) or not isinstance(c.get("text"), str):
            return f"claim {i + 1} needs a text"
    return None


# ---------- Forecasts ----------
def forecast_sys(side):
    return (f"You are the {'BULL' if side == 'bull' else 'BEAR'}. Propose exactly 2 forecasts about NEAR that can be checked later against the same public "
            "data. " + JSON_ONLY + ' Form: {"forecasts": [{"measure": one of ' + ", ".join(FORECAST_MEASURES) +
            ', "direction": "above" or "below", "threshold": number, "horizon_days": 7, 30 or 90, "why": one sentence}]}. '
            "Meaning: on the due date (snapshot day + horizon_days), the mean of the measure over the 7 days ending that day will be "
            "above/below the threshold. The threshold must be between 0.2 and 5 times the latest 7-day mean. Use two different measures.")


def forecast_user(latest, cutoff, kept_side):
    return (f"Snapshot day: {cutoff}. Latest 7-day means: " + ", ".join(f"{m} {fmt(v)}" for m, v in latest.items() if v is not None) +
            "\nYour side's kept claims:\n" + "\n".join(f"- {c['text']}" for c in kept_side))


def forecast_ok(f, latest):
    """Form check for one forecast. Returns an error string or None."""
    if not isinstance(f, dict):
        return "not an object"
    if f.get("measure") not in FORECAST_MEASURES or latest.get(f.get("measure")) is None:
        return "measure not on the menu"
    if f.get("direction") not in ("above", "below"):
        return "direction must be above or below"
    if f.get("horizon_days") not in HORIZONS:
        return f"horizon_days must be one of {HORIZONS}"
    t = f.get("threshold")
    if isinstance(t, bool) or not isinstance(t, (int, float)) or t <= 0:
        return "threshold must be a positive number"
    base = latest[f["measure"]]
    if not 0.2 * base <= t <= 5 * base:
        return "threshold is not between 0.2 and 5 times the latest 7-day mean"
    return None


def forecasts_valid(o):
    fs = o.get("forecasts")
    if not isinstance(fs, list) or len(fs) != 2:
        return '"forecasts" must be a list of exactly 2'
    return None
