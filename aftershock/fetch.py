"""`make live`: download the three public sources into data/raw. No keys needed.

Usage: python -m aftershock.fetch sources     (NearBlocks, DefiLlama, GDELT daily counts)
       python -m aftershock.fetch headlines   (GDELT top headlines per day)
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
        json.dump(obj, f, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


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
    """Top headlines for every day, in one request (GDELT's timeline-with-articles mode)."""
    today = datetime.now(timezone.utc).date()
    save("gdelt_headlines.json", get_json("news headlines", gdelt_url("timelinevolinfo", date(2020, 7, 1), today)))
    with open(os.path.join(snapshot.DATA, "manifest.json")) as f:
        m = json.load(f)
    m = snapshot.write_manifest(m["cutoff"])
    print(f"  headlines: fetched\nsnapshot fingerprint: {m['fingerprint']}")


if __name__ == "__main__":
    try:
        {"sources": fetch_sources, "headlines": fetch_headlines}[sys.argv[1]]()
    except (FetchError, snapshot.SnapshotError) as e:
        sys.exit(f"STOPPED, nothing published: {e}")
