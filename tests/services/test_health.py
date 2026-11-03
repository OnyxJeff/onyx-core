"""Deterministic, dependency-free health evaluator tests."""
import unittest
from datetime import datetime, timedelta, timezone

from pi.services.receiver.health import evaluate_health


NOW = datetime(2026, 11, 2, 5, 0, 0, tzinfo=timezone.utc)


def stamp(seconds_ago):
    return (NOW - timedelta(seconds=seconds_ago)).isoformat().replace("+00:00", "Z")


class HealthEvaluatorTests(unittest.TestCase):
    def test_boundaries(self):
        for age, expected in [(0, "healthy"), (90, "healthy"),
                              (91, "warning"), (180, "warning"),
                              (181, "critical")]:
            with self.subTest(age=age):
                result = evaluate_health(stamp(age), now=NOW)
                self.assertEqual(result["status"], expected)
                self.assertEqual(result["age_seconds"], age)

    def test_no_data(self):
        result = evaluate_health(None, now=NOW)
        self.assertEqual(result["status"], "no_data")
        self.assertEqual(result["reason"], "no_accepted_samples")
        self.assertIsNone(result["age_seconds"])

    def test_future_clock_skew_is_unknown(self):
        result = evaluate_health(stamp(-1), now=NOW)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["reason"], "sample_in_future")
        self.assertIsNone(result["age_seconds"])

    def test_malformed_timestamp_is_unknown(self):
        for timestamp in ("not-a-time", "2026-11-02T05:00:00+00:00", "", 3):
            with self.subTest(timestamp=timestamp):
                self.assertEqual(
                    evaluate_health(timestamp, now=NOW)["status"], "unknown"
                )

    def test_recovery_transition(self):
        stale = evaluate_health(stamp(181), now=NOW)
        fresh = evaluate_health(stamp(3), now=NOW)
        self.assertEqual((stale["status"], fresh["status"]),
                         ("critical", "healthy"))

    def test_now_must_be_aware(self):
        with self.assertRaises(ValueError):
            evaluate_health(stamp(0), now=datetime(2026, 11, 2, 5, 0, 0))

    def test_fractional_threshold(self):
        self.assertEqual(
            evaluate_health(stamp(90), now=NOW + timedelta(milliseconds=1))["status"],
            "warning"
        )


if __name__ == "__main__":
    unittest.main()
