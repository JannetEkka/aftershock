"""The whole run: snapshot -> events -> labels -> event test -> Bull/Bear -> recompute -> Examiner -> decision
-> Judge -> final check -> AI-alone baseline -> forecasts -> results.json, THESIS.md and the page's data file.

`make replay` runs this with recorded model replies (no key, no network). `make live` records new ones.
"""
import json
import os
import sys
from datetime import date, timedelta

from . import claims, events, eventtest, llm, roles, snapshot
from .snapshot import ROOT

BULL, BEAR = "glm", "nemotron"      # the two families; each side's claims are examined by the other family
FAMILY = {"bull": BULL, "bear": BEAR}
LABELLER, JUDGE = "nemotron", "glm"
BASELINE_RIGHT = 0.10                   # AI alone, from memory: "right" = within 10% of our data (1% also reported)


def load_headlines():
    path = os.path.join(snapshot.RAW, "gdelt_headlines.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def label_events(evs, headlines):
    labels = {}
    for ev in evs:
        hs = [h for h in headlines.get(ev["start"] + "_" + ev["end"], []) if h.get("title")]
        o = llm.ask_json("labeller", LABELLER, roles.LABEL_SYS, roles.label_user(ev, hs), roles.label_valid) if hs else None
        labels[ev["id"]] = ({"type": o["type"], "summary": o["summary"].strip()} if o else
                            {"type": "unlabelled", "summary": "No usable headlines were returned for this spike." if not hs
                             else "The labeller gave no valid label."})
    return labels


def write_claims(side, role, system, user, lo, hi, start):
    o = llm.ask_json(role, FAMILY[side], system, user, roles.claims_valid(lo, hi))
    out = []
    for i, c in enumerate((o or {}).get("claims", []), start):
        c = dict(c) if isinstance(c, dict) else {"text": str(c)}
        c["id"], c["side"] = f"{side.upper()}{i}", side
        out.append(c)
    return out


def check_claim(c, ctx, labels, headlines):
    code = claims.code_checks(c, ctx)
    exam = None
    if code["status"] == "pass":
        exam = llm.ask_json("examiner", llm.OTHER[FAMILY[c["side"]]], roles.EXAM_SYS,
                            roles.exam_user(c, code, ctx, labels, headlines), roles.exam_valid)
    status, reason = claims.decide(code, exam)
    extra = []
    if code["status"] == "pass" and c["kind"] == "events_moved":
        r = ctx.tests[str(c.get("after_days", 7))]
        extra = [float(r["summary"]["events"])] + ([float(r["measures"][c["measure"]]["tested"])] if c["measure"] in r["measures"] else [])
    return {**{k: c.get(k) for k in ("id", "side", "kind", "measure", "event_id", "after_days", "period", "period_b", "figure", "text", "rebuts")},
            "event_ids": claims.cited_events(c) if isinstance(c.get("event_ids", []), list) else [],
            "recomputed": code["recomputed"], "how": code["how"], "code_check": code["status"],
            "examiner": exam, "examiner_model": llm.MODELS[llm.OTHER[FAMILY[c["side"]]]] if exam else None,
            "writer_model": llm.MODELS[FAMILY[c["side"]]], "status": status, "reason": reason, "context_numbers": extra}


def score_baseline(ctx):
    out = []
    for fam in (BULL, BEAR):
        o = llm.ask_json("ai_alone", fam, roles.BASE_SYS, roles.BASE_USER, roles.base_valid)
        for c in (o or {}).get("claims", []):
            row = {"model": llm.MODELS[fam], "text": c.get("text"), "kind": c.get("kind"), "measure": c.get("measure"),
                   "period": c.get("period"), "period_b": c.get("period_b"), "figure": c.get("figure"), "actual": None}
            form = {**c, "event_ids": [], "text": c.get("text") if 10 <= len(str(c.get("text"))) <= 400 else "x" * 10}
            if c.get("kind") not in ("period_mean", "period_change") or claims.validate_form(form, ctx):
                row.update(score="uncheckable", why="not a figure our dataset holds")
            else:
                value, how = claims.recompute(form, ctx)
                if value is None:
                    row.update(score="uncheckable", why=how)
                else:
                    err = abs(c["figure"] - value) / abs(value) if value else float("inf")
                    row.update(actual=value, score="right" if err <= BASELINE_RIGHT else "wrong", within_1pct=err <= claims.TOLERANCE,
                               why=f"off by {100 * err:.1f}%" if err != float("inf") else "actual is zero")
            out.append(row)
        if o is None:
            out.append({"model": llm.MODELS[fam], "text": None, "score": "no_valid_reply", "why": "the model gave no valid reply twice"})
    return out


def make_forecasts(ctx, kept, cutoff):
    latest = {}
    for m in roles.FORECAST_MEASURES:
        v = ctx.cols[m][-7:]
        latest[m] = None if any(x is None for x in v) else sum(v) / 7
    out = []
    for side in ("bull", "bear"):
        mine = [c for c in kept if c["side"] == side]
        o = llm.ask_json("forecaster", FAMILY[side], roles.forecast_sys(side), roles.forecast_user(latest, cutoff, mine), roles.forecasts_valid)
        for f in (o or {}).get("forecasts", []):
            err = roles.forecast_ok(f, latest)
            if err:
                out.append({"side": side, "status": "rejected", "reason": err, "raw": f})
                continue
            due = (date.fromisoformat(cutoff) + timedelta(days=f["horizon_days"])).isoformat()
            out.append({"side": side, "status": "accepted", "measure": f["measure"], "direction": f["direction"],
                        "threshold": float(f["threshold"]), "due": due, "latest": latest[f["measure"]], "why": str(f.get("why", ""))[:300],
                        "statement": f"Mean daily {eventtest.NAMES[f['measure']]} over the 7 days ending {due} will be {f['direction']} {roles.fmt(float(f['threshold']))}."})
    for i, f in enumerate([x for x in out if x["status"] == "accepted"], 1):
        f["id"] = f"F{i}"
    return out, latest


def thin(series, digits=4):
    return [None if v is None else float(f"{v:.{digits}g}") for v in series]


def main():
    try:
        manifest = snapshot.verify()
    except snapshot.SnapshotError as e:
        sys.exit(f"STOPPED, nothing published: {e}")
    cutoff = manifest["cutoff"]
    dates, cols = snapshot.load_daily()
    evs = events.find_events(dates, cols["news_count"])
    tests = eventtest.run_all(cols, evs)
    ctx = claims.Context(dates, cols, evs, tests)
    eventtest.print_report(tests)
    try:
        headlines = load_headlines()
        labels = label_events(evs, headlines)
        brief = roles.data_brief(ctx, labels, cutoff)
        user = "DATA:\n" + brief
        raw = {s: write_claims(s, s, roles.side_sys(s), user, 6, 8, 1) for s in ("bull", "bear")}
        show = lambda cl: "\n".join(f"{c['id']}: {c.get('text')} [figure {c.get('figure')}]" for c in cl)
        for s, other in (("bull", "bear"), ("bear", "bull")):
            raw[s] = raw[s] + write_claims(s, s + "_rebuttal", roles.rebut_sys(s),
                                           f"THE OTHER SIDE'S CLAIMS:\n{show(raw[other][:8])}\n\n{user}", 1, 3, len(raw[s]) + 1)
        checked = [check_claim(c, ctx, labels, headlines) for s in ("bull", "bear") for c in raw[s]]
        kept = [c for c in checked if c["status"] == "kept"]
        kept_by_id = {c["id"]: c for c in kept}
        thesis = {"title": None, "sections": {s: [] for s in roles.SECTIONS}, "note": None}
        if kept:
            j = llm.ask_json("judge", JUDGE, roles.JUDGE_SYS, roles.judge_user(kept), roles.judge_valid)
            if j:
                thesis["title"] = j["title"].strip()
                thesis["sections"] = {s: claims.final_check(j[s], kept_by_id) for s in roles.SECTIONS}
            else:
                thesis["note"] = "The Judge gave no valid reply twice, so no thesis text is published."
        else:
            thesis["note"] = "No claim survived the checks, so there is nothing to write a thesis from."
        baseline = score_baseline(ctx)
        forecasts, latest = make_forecasts(ctx, kept, cutoff)
    except llm.ReplayMissing as e:
        sys.exit(f"STOPPED: {e}")
    if llm.mode() == "live":
        llm.prune()

    t7 = tests["7"]
    by_id = {e["id"]: e for e in t7["events"]}
    sents = [s for sec in thesis["sections"].values() for s in sec]
    base_scored = [b for b in baseline if b["score"] in ("right", "wrong", "uncheckable")]
    counts = {
        "events": len(evs), "moved_usage": t7["summary"]["moved_usage"], "price_only": t7["summary"]["price_only"],
        "nothing": t7["summary"]["nothing"], "moved_price": t7["summary"]["moved_price"],
        "claims_written": len(checked), "claims_kept": len(kept), "claims_removed": len(checked) - len(kept),
        "removed_by_code": sum(c["code_check"] != "pass" for c in checked),
        "removed_by_examiner": sum(c["code_check"] == "pass" and c["status"] != "kept" for c in checked),
        "thesis_sentences_kept": sum(s["status"] == "kept" for s in sents), "thesis_sentences_cut": sum(s["status"] == "cut" for s in sents),
        "ai_alone_right": sum(b["score"] == "right" for b in base_scored), "ai_alone_wrong": sum(b["score"] == "wrong" for b in base_scored),
        "ai_alone_uncheckable": sum(b["score"] == "uncheckable" for b in base_scored),
        "ai_alone_within_1pct": sum(bool(b.get("within_1pct")) for b in base_scored),
        "model_calls": len(llm.calls), "model_replies_invalid": sum(not c["valid"] for c in llm.calls),
    }
    results = {
        "snapshot": {"cutoff": cutoff, "fetched_at": manifest.get("fetched_at"), "fingerprint": manifest["fingerprint"],
                     "files": manifest["files"], "days": len(dates), "first_day": dates[0]},
        "rule": {"event": f"news count above the {events.PCT}th percentile of the previous {events.LOOKBACK} days and at least "
                          f"{events.MIN_COUNT} articles; spikes within {events.MERGE_GAP} days merge",
                 "test": f"change from the {eventtest.BEFORE} days before to the N days after; moved = outside the middle 95% of ordinary days",
                 "keep": "figure within 1% of the recomputation, cited events exist, Examiner (other model family) says supported",
                 "ai_alone_right": f"within {int(100 * BASELINE_RIGHT)}% of the recomputed figure"},
        "models": {"bull": llm.MODELS[BULL], "bear": llm.MODELS[BEAR], "labeller": llm.MODELS[LABELLER], "judge": llm.MODELS[JUDGE],
                   "examiner": "the other family from the claim's writer"},
        "counts": counts,
        "tests": {a: {"summary": r["summary"], "measures": r["measures"]} for a, r in tests.items()},
        "events": [{**{k: ev[k] for k in ("id", "start", "end", "days", "peak", "articles")}, **labels[ev["id"]],
                    "stamp": by_id[ev["id"]]["stamp"], "measures": by_id[ev["id"]]["measures"],
                    "stamps_by_window": {a: next(e["stamp"] for e in tests[a]["events"] if e["id"] == ev["id"]) for a in tests},
                    "headlines": [{"title": h["title"], "url": h["url"], "domain": h["domain"]}
                                  for h in headlines.get(ev["start"] + "_" + ev["end"], [])[:5]]} for ev in evs],
        "claims": checked, "thesis": thesis, "ai_alone": baseline, "forecasts": forecasts,
        "model_calls": llm.calls,
    }
    chain_path = os.path.join(ROOT, "chain", "onchain.json")
    if os.path.exists(chain_path):
        with open(chain_path) as f:
            results["chain"] = json.load(f)
    with open(os.path.join(ROOT, "results.json"), "w") as f:
        json.dump(results, f, indent=1, sort_keys=True)
        f.write("\n")
    page = dict(results)
    page.pop("model_calls")
    page["series"] = {"dates": [dates[0], dates[-1]], "price": thin(cols["price"]), "active_accounts": thin(cols["active_accounts"]),
                      "news": thin(cols["news_count"])}
    os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
    with open(os.path.join(ROOT, "docs", "data.js"), "w") as f:
        f.write("window.AFTERSHOCK = " + json.dumps(page, sort_keys=True, separators=(",", ":")) + ";\n")
    from . import thesis_md
    thesis_md.write(results)
    c = counts
    print(f"\nRESULT  {c['events']} news events: {c['moved_price']} moved the price, {c['moved_usage']} moved usage "
          f"(the same rule stamps {100 * t7['summary']['chance_moved_usage']:.1f}% of ordinary days 'moved usage').")
    print(f"CLAIMS  {c['claims_written']} written, {c['claims_kept']} kept, {c['claims_removed']} removed "
          f"({c['removed_by_code']} by code, {c['removed_by_examiner']} by the Examiner). Thesis: {c['thesis_sentences_kept']} sentences kept, {c['thesis_sentences_cut']} cut.")
    print(f"AI ALONE  {c['ai_alone_right']} right, {c['ai_alone_wrong']} wrong, {c['ai_alone_uncheckable']} uncheckable "
          f"(right = within 10%; within 1%: {c['ai_alone_within_1pct']}).")
    print(f"snapshot fingerprint {manifest['fingerprint']}\nwrote results.json, THESIS.md, docs/data.js")


if __name__ == "__main__":
    main()
