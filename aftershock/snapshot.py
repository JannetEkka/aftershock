"""Snapshot: turn the raw downloads into one daily table and fingerprint everything.

A fingerprint is the SHA-256 hash of a file. Change one digit in the file and the
fingerprint changes, so a fingerprint stored on NEAR shows the data was not edited later.
"""
import csv
import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RAW = os.path.join(DATA, "raw")

RAW_FILES = {
    "nearblocks": "nearblocks_charts.json",
    "tvl": "defillama_tvl.json",
    "dex": "defillama_dex.json",
    "stablecoins": "defillama_stablecoins.json",
    "intents": "defillama_intents.json",
    "news": "gdelt_timeline.json",
}
COLUMNS = ["date", "price", "txns", "active_accounts", "new_accounts", "fees_usd", "tvl",
           "dex_volume", "intents_volume", "stablecoins", "news_count", "news_norm"]
# Fewer days than this from a source means the download is broken: stop, publish nothing.
MIN_DAYS = {"nearblocks": 2000, "tvl": 1500, "dex": 1500, "stablecoins": 1000, "intents": 300, "news": 2000}


class SnapshotError(Exception):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _day(ts):
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat()


def _load(name):
    path = os.path.join(RAW, RAW_FILES[name])
    if not os.path.exists(path):
        raise SnapshotError(f"source '{name}': file {RAW_FILES[name]} is missing")
    try:
        with open(path) as f:
            return json.load(f)
    except ValueError as e:
        raise SnapshotError(f"source '{name}': not valid JSON ({e})")


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def parse_sources():
    """Return {source: {day: {column: value}}}. Raises SnapshotError naming a broken source."""
    out = {}
    try:
        nb = {}
        for r in _load("nearblocks")["charts"]:
            d = r["date"][:10]
            price = _num(r.get("near_price"))
            nb[d] = {
                "price": price if price else None,  # 0 before the token traded = no price
                "txns": _num(r.get("txns")),
                "active_accounts": _num(r.get("active_accounts")),
                "new_accounts": _num(r.get("new_accounts")),
                "fees_usd": _num(r.get("txn_fee_usd")) if price else None,
            }
        out["nearblocks"] = nb
        out["tvl"] = {_day(r["date"]): {"tvl": _num(r["tvl"])} for r in _load("tvl")}
        out["dex"] = {_day(t): {"dex_volume": _num(v)} for t, v in _load("dex")["totalDataChart"]}
        out["intents"] = {_day(t): {"intents_volume": _num(v)} for t, v in _load("intents")["totalDataChart"]}
        out["stablecoins"] = {_day(r["date"]): {"stablecoins": _num(r["totalCirculatingUSD"]["peggedUSD"])}
                              for r in _load("stablecoins")}
        news = {}
        for r in _load("news")["timeline"][0]["data"]:
            d = r["date"]
            news[f"{d[:4]}-{d[4:6]}-{d[6:8]}"] = {"news_count": _num(r["value"]), "news_norm": _num(r.get("norm"))}
        out["news"] = news
    except (KeyError, IndexError, TypeError) as e:
        raise SnapshotError(f"a source has an unexpected shape: {e!r}")
    for name, need in MIN_DAYS.items():
        if len(out[name]) < need:
            raise SnapshotError(f"source '{name}': only {len(out[name])} days, expected at least {need}")
    return out


def build(cutoff):
    """Write data/daily.csv (through `cutoff`, the last complete day) and data/manifest.json."""
    src = parse_sources()
    start = date.fromisoformat(min(src["nearblocks"]))
    end = date.fromisoformat(cutoff)
    for name, days in src.items():
        if max(days) < cutoff and name != "stablecoins":
            raise SnapshotError(f"source '{name}': last day {max(days)} is before the cutoff {cutoff}")
    rows = []
    d = start
    while d <= end:
        k = d.isoformat()
        row = {"date": k}
        for days in src.values():
            row.update(days.get(k, {}))
        rows.append(row)
        d += timedelta(days=1)
    path = os.path.join(DATA, "daily.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow([r["date"]] + [("" if r.get(c) is None else repr(float(r[c]))) for c in COLUMNS[1:]])
    write_manifest(cutoff)
    return len(rows)


def manifest_files():
    names = ["daily.csv"] + sorted("raw/" + f for f in os.listdir(RAW) if f.endswith(".json"))
    return {n: sha256_file(os.path.join(DATA, n)) for n in names}


def fingerprint_of(files):
    """One fingerprint for the whole snapshot: the hash of the sorted 'name hash' lines."""
    text = "".join(f"{n} {h}\n" for n, h in sorted(files.items()))
    return hashlib.sha256(text.encode()).hexdigest()


def write_manifest(cutoff, fetched_at=None):
    path = os.path.join(DATA, "manifest.json")
    old = {}
    if os.path.exists(path):
        with open(path) as f:
            old = json.load(f)
    files = manifest_files()
    m = {"cutoff": cutoff, "fetched_at": fetched_at or old.get("fetched_at"),
         "files": files, "fingerprint": fingerprint_of(files)}
    with open(path, "w") as f:
        json.dump(m, f, indent=1, sort_keys=True)
        f.write("\n")
    return m


def verify():
    """Check every file still matches the manifest. Returns the manifest."""
    with open(os.path.join(DATA, "manifest.json")) as f:
        m = json.load(f)
    now = manifest_files()
    bad = sorted(n for n in set(now) | set(m["files"]) if now.get(n) != m["files"].get(n))
    if bad:
        raise SnapshotError("snapshot does not match its fingerprints: " + ", ".join(bad))
    return m


def load_daily():
    """Return (dates, {column: [float or None]})."""
    with open(os.path.join(DATA, "daily.csv")) as f:
        rows = list(csv.DictReader(f))
    dates = [r["date"] for r in rows]
    cols = {c: [float(r[c]) if r[c] != "" else None for r in rows] for c in COLUMNS[1:]}
    return dates, cols
