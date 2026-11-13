"""`make live`: download the three public sources into data/raw. No keys needed.

Usage: python -m aftershock.fetch sources     (NearBlocks, DefiLlama, GDELT daily counts)
       python -m aftershock.fetch headlines   (GDELT headlines for each event found)
Set AFTERSHOCK_REUSE=nearblocks to keep an existing NearBlocks file (its free limit is a few calls).
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

from . import snapshot

UA = {"User-Agent": "aftershock-research/1.0"}
GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"
QUERY = '"NEAR Protocol"'
GDELT_GAP = 6.0  # GDELT asks for at most one request per 5 seconds
_last_gdelt = [0.0]

SOURCES = {
    "nearblocks": "https://api.nearblocks.io/v1/charts",
    "tvl": "https://api.llama.fi/v2/historicalChainTvl/Near",
    "dex": "https://api.llama.fi/overview/dexs/Near?excludeTotalDataChart=false&excludeTotalDataChartBreakdown=true",
    "stablecoins": "https://stablecoins.llama.fi/stablecoincharts/Near",
    "intents": "https://api.llama.fi/summary/dexs/near-intents",
}


class FetchError(Exception):
    pass


def get_json(name, url, tries=3):
    err = None
    for i in range(tries):
        if "gdeltproject" in url:
            wait = GDELT_GAP - (time.time() - _last_gdelt[0])
            if wait > 0:
                time.sleep(wait)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                body = r.read()
            _last_gdelt[0] = time.time()
            return json.loads(body)
        except Exception as e:  # network error, HTTP error, or a non-JSON body
            _last_gdelt[0] = time.time()
            err = e
            time.sleep((20 if 'gdeltproject' in url else 5) * (i + 1))
    raise FetchError(f"source '{name}' failed after {tries} tries: {err!r}\n  url: {url}")


def save(fname, obj):
    with open(os.path.join(snapshot.RAW, fname), "w") as f:
        json.dump(obj, f, separators=(",", ":"), sort_keys=True)


def gdelt_url(mode, start, end, **extra):
    q = {"query": QUERY, "mode": mode, "format": "json",
         "startdatetime": start.strftime("%Y%m%d") + "000000", "enddatetime": end.strftime("%Y%m%d") + "235959"}
    q.update(extra)
    return GDELT + "?" + urllib.parse.urlencode(q)


def fetch_sources():
    os.makedirs(snapshot.RAW, exist_ok=True)
    reuse = set(os.environ.get("AFTERSHOCK_REUSE", "").split(","))
    today = datetime.now(timezone.utc).date()
    for name, url in SOURCES.items():
        path = os.path.join(snapshot.RAW, snapshot.RAW_FILES[name])
        if name in reuse and os.path.exists(path):
            print(f"  {name}: kept existing file")
            continue
        save(snapshot.RAW_FILES[name], get_json(name, url))
        print(f"  {name}: fetched")
    save(snapshot.RAW_FILES["news"], get_json("news", gdelt_url("timelinevolraw", date(2020, 7, 1), today)))
    print("  news: fetched")
    # The day of the download and the day before can be incomplete, so the snapshot stops two days back.
    cutoff = (today - timedelta(days=2)).isoformat()
    n = snapshot.build(cutoff)
    m = snapshot.write_manifest(cutoff, fetched_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    print(f"snapshot: {n} days through {cutoff}, fingerprint {m['fingerprint']}")


def fetch_headlines():
    """Headlines for each event window. Depends on the event finder, so it runs after `sources`."""
    from . import events
    dates, cols = snapshot.load_daily()
    evs = events.find_events(dates, cols["news_count"])
    path = os.path.join(snapshot.RAW, "gdelt_headlines.json")
    out = {}
    if os.path.exists(path) and "headlines" in os.environ.get("AFTERSHOCK_REUSE", ""):
        with open(path) as f:
            out = json.load(f)
    for i, ev in enumerate(evs):
        key = ev["start"] + "_" + ev["end"]
        if key in out:
            continue
        url = gdelt_url("artlist", date.fromisoformat(ev["start"]), date.fromisoformat(ev["end"]),
                        maxrecords="40", sort="hybridrel")
        arts = get_json("news headlines", url).get("articles", [])
        out[key] = [{"title": a.get("title", "").strip(), "domain": a.get("domain", ""), "url": a.get("url", ""),
                     "seen": a.get("seendate", ""), "lang": a.get("language", "")} for a in arts]
        print(f"  {i + 1}/{len(evs)} {key}: {len(out[key])} headlines", flush=True)
        save("gdelt_headlines.json", out)
    save("gdelt_headlines.json", {k: out[k] for k in sorted(out) if k in {e['start'] + '_' + e['end'] for e in evs}})
    with open(os.path.join(snapshot.DATA, "manifest.json")) as f:
        m = json.load(f)
    m = snapshot.write_manifest(m["cutoff"])
    print(f"snapshot fingerprint with headlines: {m['fingerprint']}")


if __name__ == "__main__":
    try:
        {"sources": fetch_sources, "headlines": fetch_headlines}[sys.argv[1]]()
    except (FetchError, snapshot.SnapshotError) as e:
        sys.exit(f"STOPPED, nothing published: {e}")
