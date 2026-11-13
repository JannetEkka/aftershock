import json
import os
import tempfile
import unittest
from unittest import mock

from aftershock import fetch, snapshot


class TestBadInput(unittest.TestCase):
    def test_missing_source_is_named(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(snapshot, "RAW", d):
            with self.assertRaises(snapshot.SnapshotError) as e:
                snapshot.parse_sources()
            self.assertIn("nearblocks", str(e.exception))

    def test_too_few_days_stops(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(snapshot, "RAW", d):
            with open(os.path.join(d, snapshot.RAW_FILES["nearblocks"]), "w") as f:
                json.dump({"charts": [{"date": "2024-01-01T00:00:00.000Z", "near_price": "1", "txns": "5"}]}, f)
            for k in ("tvl", "stablecoins"):
                with open(os.path.join(d, snapshot.RAW_FILES[k]), "w") as f:
                    json.dump([], f)
            for k in ("dex", "intents"):
                with open(os.path.join(d, snapshot.RAW_FILES[k]), "w") as f:
                    json.dump({"totalDataChart": []}, f)
            with open(os.path.join(d, snapshot.RAW_FILES["news"]), "w") as f:
                json.dump({"timeline": [{"data": []}]}, f)
            with self.assertRaises(snapshot.SnapshotError) as e:
                snapshot.parse_sources()
            self.assertIn("only 1 days", str(e.exception))

    def test_damaged_file_is_named(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(snapshot, "RAW", d):
            with open(os.path.join(d, snapshot.RAW_FILES["nearblocks"]), "w") as f:
                f.write("{not json")
            with self.assertRaises(snapshot.SnapshotError) as e:
                snapshot.parse_sources()
            self.assertIn("not valid JSON", str(e.exception))

    def test_edited_snapshot_fails_verification(self):
        with tempfile.TemporaryDirectory() as d:
            os.mkdir(os.path.join(d, "raw"))
            with open(os.path.join(d, "daily.csv"), "w") as f:
                f.write("date,price\n2024-01-01,1.0\n")
            with mock.patch.object(snapshot, "DATA", d), mock.patch.object(snapshot, "RAW", os.path.join(d, "raw")):
                snapshot.write_manifest("2024-01-01")
                snapshot.verify()
                with open(os.path.join(d, "daily.csv"), "w") as f:
                    f.write("date,price\n2024-01-01,1.1\n")
                with self.assertRaises(snapshot.SnapshotError):
                    snapshot.verify()

    def test_failed_download_names_the_source(self):
        with mock.patch.object(fetch.urllib.request, "urlopen", side_effect=OSError("down")), mock.patch.object(fetch.time, "sleep"):
            with self.assertRaises(fetch.FetchError) as e:
                fetch.get_json("tvl", "https://example.invalid/x", tries=2)
            self.assertIn("source 'tvl' failed", str(e.exception))


if __name__ == "__main__":
    unittest.main()
