import unittest

from aftershock import claims, eventtest, llm


def make_ctx():
    dates, vals = [], []
    for y, v in ((2024, 100.0), (2025, 150.0)):
        for m in range(1, 13):
            for d in range(1, 29):
                dates.append(f"{y}-{m:02d}-{d:02d}")
                vals.append(v)
    cols = {m: list(vals) for m in claims.MEASURES}
    cols["intents_volume"] = [None] * len(vals)
    i = dates.index("2025-01-01")
    events = [{"id": "E001", "start": "2025-01-01", "end": "2025-01-01", "index": i, "days": 1}]
    tests = eventtest.run_all(cols, events)
    return claims.Context(dates, cols, events, tests)


def claim(**kw):
    c = {"kind": "period_change", "measure": "txns", "period": "2024", "period_b": "2025", "figure": 50.0,
         "text": "Transactions rose 50% from 2024 to 2025.", "event_ids": []}
    c.update(kw)
    return c


OK = {"verdict": "supported", "reason": "matches"}


class TestDecisionRule(unittest.TestCase):
    def setUp(self):
        self.ctx = make_ctx()

    def test_kept_when_all_three_hold(self):
        code = claims.code_checks(claim(), self.ctx)
        self.assertEqual(code["status"], "pass")
        self.assertAlmostEqual(code["recomputed"], 50.0)
        self.assertEqual(claims.decide(code, OK), ("kept", None))

    def test_figure_within_one_percent(self):
        self.assertEqual(claims.code_checks(claim(figure=50.4), self.ctx)["status"], "pass")
        r = claims.code_checks(claim(figure=51.0), self.ctx)
        self.assertEqual(r["status"], "removed")
        self.assertIn("does not match", r["reason"])
        self.assertEqual(claims.decide(r, OK)[0], "removed")  # the Examiner cannot rescue a wrong figure

    def test_unknown_event_id_removed(self):
        r = claims.code_checks(claim(event_ids=["E999"]), self.ctx)
        self.assertIn("does not exist", r["reason"])
        r = claims.code_checks(claim(kind="event_change", measure="price", event_id="E404", figure=1.0), self.ctx)
        self.assertIn("does not exist", r["reason"])

    def test_examiner_must_say_supported(self):
        code = claims.code_checks(claim(), self.ctx)
        self.assertEqual(claims.decide(code, {"verdict": "not_supported", "reason": "says 'because'"})[0], "removed")
        self.assertEqual(claims.decide(code, None)[0], "removed")

    def test_event_change_recomputed(self):
        r = claims.code_checks(claim(kind="event_change", measure="price", event_id="E001", figure=50.0, after_days=7), self.ctx)
        self.assertEqual(r["status"], "pass")

    def test_uncovered_data_cannot_be_recomputed(self):
        r = claims.code_checks(claim(measure="intents_volume"), self.ctx)
        self.assertIn("cannot be recomputed", r["reason"])
        r = claims.code_checks(claim(period="2019"), self.ctx)
        self.assertIn("cannot be recomputed", r["reason"])

    def test_events_moved_is_exact(self):
        r = claims.code_checks(claim(kind="events_moved", measure="price", figure=1, after_days=7), self.ctx)
        n = self.ctx.tests["7"]["measures"]["price"]["moved"]
        self.assertEqual(r["status"], "pass" if n == 1 else "removed")


class TestValidation(unittest.TestCase):
    def setUp(self):
        self.ctx = make_ctx()

    def test_bad_forms(self):
        for bad in (claim(kind="vibes"), claim(measure="market_cap"), claim(figure="50"), claim(figure=True),
                    claim(period="last year"), claim(text="short"), claim(event_ids="E001"),
                    claim(kind="event_change", measure="price", event_id="E001", after_days=5), "not a dict"):
            r = claims.code_checks(bad, self.ctx)
            self.assertEqual(r["status"], "removed")
            self.assertTrue(r["reason"].startswith("malformed"), r["reason"])

    def test_extract_json(self):
        self.assertEqual(llm.extract_json('Sure!\n```json\n{"a": {"b": "}"}}\n``` done'), {"a": {"b": "}"}})
        self.assertEqual(llm.extract_json("<think>{\"x\":1}</think>{\"y\": 2}"), {"y": 2})
        self.assertIsNone(llm.extract_json("no json here"))
        self.assertIsNone(llm.extract_json('{"broken": '))
        self.assertIsNone(llm.extract_json(None))


class TestFinalCheck(unittest.TestCase):
    def test_sentences(self):
        kept = {"B1": {"figure": 50.0, "recomputed": 50.0, "text": "Transactions rose 50% from 2024 to 2025.",
                       "period": "2024", "period_b": "2025", "kind": "period_change"}}
        out = claims.final_check([
            {"text": "Transactions grew 50% between 2024 and 2025.", "claims": ["B1"]},
            {"text": "NEAR will reach $100.", "claims": ["B1"]},
            {"text": "Usage is strong.", "claims": []},
            {"text": "Usage is strong.", "claims": ["B9"]},
            {"text": "Usage grew.", "claims": ["B1"]},
        ], kept)
        self.assertEqual([s["status"] for s in out], ["kept", "cut", "cut", "cut", "kept"])
        self.assertIn("100", out[1]["reason"])

    def test_numbers(self):
        self.assertEqual(claims.numbers_in("E012 moved price by -12.5% in 2024, $3,000"), [-12.5, 2024.0, 3000.0])
        self.assertTrue(claims.number_supported(12.5, [-12.4871]))
        self.assertTrue(claims.number_supported(12, [-12.4871]))
        self.assertFalse(claims.number_supported(13.5, [-12.4871]))


if __name__ == "__main__":
    unittest.main()
