import random
import unittest
import unittest.mock

from aftershock import events, eventtest


def synthetic(n=1200, seed=7):
    rng = random.Random(seed)
    return [100 + rng.gauss(0, 3) for _ in range(n)]


class TestEvents(unittest.TestCase):
    def test_percentile(self):
        self.assertEqual(events.percentile([1, 2, 3, 4, 5], 50), 3)
        self.assertAlmostEqual(events.percentile(list(range(101)), 95), 95)

    def test_spike_found_and_merged(self):
        counts = [1.0] * 400
        counts[200] = 9
        counts[202] = 8   # within 3 days: same event
        counts[300] = 7   # separate event
        counts[350] = 2   # above the percentile but below MIN_COUNT: not an event
        dates = [f"d{i}" for i in range(400)]
        with unittest.mock.patch.object(events, "date") as d:
            d.fromisoformat.side_effect = lambda s: __import__("datetime").date.fromordinal(730000 + int(s[1:]))
            evs = events.find_events(dates, counts)
        self.assertEqual([(e["index"], e["days"]) for e in evs], [(200, 3), (300, 1)])
        self.assertEqual(evs[0]["articles"], 18)

    def test_no_event_without_full_lookback(self):
        counts = [1.0] * 50 + [20.0] + [1.0] * 50
        self.assertEqual(events.spike_days(counts), [])


class TestEventTest(unittest.TestCase):
    def setUp(self):
        self.n = 1200
        base = synthetic(self.n)
        # pick two days where the noise itself is unremarkable in every window, so only the planted jump stands out
        calm = lambda lo, hi: min(range(lo, hi), key=lambda i: max(abs(eventtest.change(base, i, a)) for a in eventtest.SENSITIVITY))
        self.jump_at, self.quiet_at = calm(550, 650), calm(850, 950)
        jumped = list(base)
        for i in range(self.jump_at, self.jump_at + 14):
            jumped[i] *= 1.5   # the known jump: +50% for two weeks
        self.cols = {m: list(base) for m in eventtest.MEASURES}
        self.cols["active_accounts"] = jumped
        self.events = [{"id": "E001", "index": self.jump_at, "days": 1}, {"id": "E002", "index": self.quiet_at, "days": 1}]

    def test_change_value(self):
        s = [10.0] * 28 + [15.0] * 7
        self.assertAlmostEqual(eventtest.change(s, 28), 0.5)

    def test_known_jump_is_moved_and_quiet_event_is_not(self):
        for after in eventtest.SENSITIVITY:
            r = eventtest.run(self.cols, self.events, after)
            e1, e2 = r["events"]
            self.assertEqual(e1["measures"]["active_accounts"]["verdict"], "up")
            self.assertAlmostEqual(e1["measures"]["active_accounts"]["change"], 0.5, delta=0.05)
            self.assertEqual(e1["stamp"], "moved_usage")
            self.assertEqual(e1["measures"]["price"]["verdict"], "inside")
            self.assertEqual(e2["stamp"], "nothing")
            self.assertEqual(r["measures"]["active_accounts"]["moved"], 1)
            self.assertEqual(r["measures"]["active_accounts"]["tested"], 2)

    def test_price_only_stamp(self):
        self.cols["active_accounts"] = list(self.cols["txns"])
        p = list(self.cols["price"])
        for i in range(self.jump_at, self.jump_at + 14):
            p[i] *= 0.5
        self.cols["price"] = p
        r = eventtest.run(self.cols, self.events)
        self.assertEqual(r["events"][0]["stamp"], "price_only")
        self.assertEqual(r["events"][0]["measures"]["price"]["verdict"], "down")

    def test_missing_days_are_not_tested_not_nothing(self):
        self.cols["active_accounts"][self.jump_at + 2] = None
        r = eventtest.run(self.cols, self.events)
        self.assertEqual(r["events"][0]["measures"]["active_accounts"]["verdict"], "not_tested")
        self.cols2 = {m: [None] * self.n for m in eventtest.MEASURES}
        r2 = eventtest.run(self.cols2, self.events)
        self.assertEqual(r2["events"][0]["stamp"], "not_tested")

    def test_chance_rate_near_five_percent_on_noise(self):
        cols = {m: synthetic(3000, seed=k) for k, m in enumerate(eventtest.MEASURES)}
        r = eventtest.run(cols, [])
        ordinary = eventtest.ordinary_indices(3000, [])
        b = eventtest.band(cols["price"], ordinary)
        outside = sum(1 for i in ordinary if eventtest.verdict(eventtest.change(cols["price"], i), b) in ("up", "down"))
        tested = sum(1 for i in ordinary if eventtest.change(cols["price"], i) is not None)
        self.assertAlmostEqual(outside / tested, 0.05, delta=0.005)
        self.assertGreater(r["summary"]["chance_moved_usage"], 0.05)  # several measures: more than 5% by chance

    def test_ordinary_days_exclude_event_windows(self):
        o = eventtest.ordinary_indices(100, [{"id": "E1", "index": 50, "days": 2}], after=7)
        self.assertNotIn(44, o); self.assertNotIn(51, o); self.assertIn(43, o); self.assertIn(52, o)

    def test_binom_tail(self):
        self.assertAlmostEqual(eventtest.binom_tail(0, 10, 0.05), 1.0)
        self.assertAlmostEqual(eventtest.binom_tail(1, 1, 0.05), 0.05)


if __name__ == "__main__":
    import unittest.mock
    unittest.main()
