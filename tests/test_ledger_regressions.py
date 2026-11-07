import unittest
from datetime import date, datetime
from unittest.mock import Mock, patch

import numpy as np

from ipo import ledger, model
from web import render


def at(time):
    return datetime.fromisoformat(f"2026-11-06T{time}:00+05:30")


class LoggingTests(unittest.TestCase):
    def run_log(self, times, previous=(), force=False):
        ipo = dict(slug="example", name="Example", listing="2026-11-06", status="Open")
        with patch.object(ledger, "datetime", wraps=datetime) as clock, \
                patch.object(ledger, "entries", return_value=list(previous)), \
                patch.object(ledger.pipeline, "all_ipos", return_value=[ipo]), \
                patch.object(ledger.pipeline, "analyze", return_value={}) as analyze, \
                patch.object(ledger, "record", return_value={}) as record, \
                patch.object(ledger, "_append") as append:
            clock.now.side_effect = [at(t) for t in times]
            written = ledger.log_live(progress=lambda _: None, force=force)
        return written, analyze, record, append

    def test_timestamp_is_analysis_completion(self):
        written, _, record, append = self.run_log(["08:30", "08:45"])
        self.assertEqual(written, 1)
        self.assertEqual(record.call_args.args[1], at("08:45"))
        append.assert_called_once()

    def test_analysis_crossing_cutoff_is_not_appended(self):
        for finished in ("09:00", "09:01"):
            with self.subTest(finished=finished):
                written, _, record, append = self.run_log(["08:59", finished], force=True)
                self.assertEqual(written, 0)
                record.assert_not_called()
                append.assert_not_called()

    def test_late_run_is_skipped_even_with_force(self):
        written, analyze, _, append = self.run_log(["15:13"], force=True)
        self.assertEqual(written, 0)
        analyze.assert_not_called()
        append.assert_not_called()

    def test_force_bypasses_recent_entry(self):
        previous = [dict(slug="example", logged_at=at("08:00").isoformat())]
        written, _, _, _ = self.run_log(["08:30", "08:40"], previous, force=True)
        self.assertEqual(written, 1)
        written, analyze, _, _ = self.run_log(["08:30"], previous)
        self.assertEqual(written, 0)
        analyze.assert_not_called()

    def test_cutoff_is_strict(self):
        for time, expected in (("08:59", True), ("09:00", False), ("15:13", False)):
            with self.subTest(time=time):
                self.assertEqual(ledger._before_listing(at(time).isoformat(), date(2026, 11, 6)), expected)


class PredictionTests(unittest.TestCase):
    def test_missing_gmp_has_no_listing_prediction_but_zero_is_valid(self):
        estimator = model.IPOModel()
        estimator.p_beat = None
        estimator.miss_low, estimator.miss_high = -2, 2
        estimator.p_pos = Mock()
        estimator.p_pos.predict_proba.return_value = np.array([[0.4, 0.6]])
        for gmp in (None, 0, 12):
            with self.subTest(gmp=gmp):
                features = model.feature_row(dict(gmp_pct=gmp), None, None)
                prediction = estimator.predict([features])[0]
                self.assertEqual(prediction["gain_mid"], gmp)
                for key in ("gain_low", "gain_high", "p_positive"):
                    self.assertEqual(prediction[key] is None, gmp is None)

    def test_sentiment_waits_for_ten_eligible_observations(self):
        rows = [dict(state="scored", gmp_pct=0, actual=i, sentiment=dict(overall=i / 10))
                for i in range(10)]
        for n in (3, 9):
            self.assertEqual(ledger.sentiment_test(rows[:n]), dict(n=n, rho=None, min_n=10))
        self.assertAlmostEqual(ledger.sentiment_test(rows)["rho"], 1)
        rows += [dict(state="waiting for listing", gmp_pct=0, actual=None, sentiment=dict(overall=1)),
                 dict(state="scored", gmp_pct=None, actual=0, sentiment=dict(overall=1))]
        self.assertEqual(ledger.sentiment_test(rows)["n"], 10)

    def test_no_gmp_home_keeps_rating_without_gain(self):
        ipo = dict(slug="example", name="Example", status="Open", open=None, close=None,
                   listing=None, prediction=dict(gain_mid=None),
                   verdict=dict(listing=dict(label="Moderate", score=55), long_term=dict(label="Risky")))
        html = render.home(dict(ipos=[ipo]), {}, None)
        self.assertIn("no GMP yet", html)
        self.assertIn("Moderate", html)
        self.assertIn("Risky", html)
        self.assertNotIn("+0.0%", html)


if __name__ == "__main__":
    unittest.main()
