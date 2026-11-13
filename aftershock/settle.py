"""`make settle`, step 1: recompute every posted forecast whose due date the snapshot covers, and write settle.json.
Step 2 (chain/chain.mjs settle) sends the results to the contract, which refuses any forecast that is not yet due."""
import json
import os
import sys

from . import snapshot
from .snapshot import ROOT


def outcome(cols, dates, f):
    """(True/False, observed mean) for a forecast, or None if the 7 days ending on its due date are not all in the snapshot."""
    if f["due"] not in dates:
        return None
    i = dates.index(f["due"])
    vals = cols[f["measure"]][max(0, i - 6):i + 1]
    if len(vals) < 7 or any(v is None for v in vals):
        return None
    mean = sum(vals) / 7
    return (mean > f["threshold"]) if f["direction"] == "above" else (mean < f["threshold"]), mean


def main():
    path = os.path.join(ROOT, "chain", "onchain.json")
    if not os.path.exists(path):
        sys.exit("STOPPED: chain/onchain.json not found; nothing has been posted to the contract.")
    with open(path) as f:
        on = json.load(f)
    try:
        m = snapshot.verify()
    except snapshot.SnapshotError as e:
        sys.exit(f"STOPPED: {e}")
    dates, cols = snapshot.load_daily()
    plan = {"fingerprint": m["fingerprint"], "cutoff": m["cutoff"], "settlements": [], "not_due": []}
    for fc in on["forecasts"]:
        r = outcome(cols, dates, fc)
        if r is None:
            plan["not_due"].append({"id": fc["id"], "due": fc["due"]})
            print(f"forecast {fc['id']}: due {fc['due']}, after this snapshot's last day ({m['cutoff']}). Run `make live` after the due date, then `make settle`.")
        else:
            plan["settlements"].append({"id": fc["id"], "outcome": r[0], "observed": float(f"{r[1]:.6g}")})
            print(f"forecast {fc['id']}: \"{fc['statement']}\" -> observed {r[1]:.6g}, so {'TRUE' if r[0] else 'FALSE'}")
    with open(os.path.join(ROOT, "settle.json"), "w") as f:
        json.dump(plan, f, indent=1)
        f.write("\n")


if __name__ == "__main__":
    main()
