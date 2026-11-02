"""Dashboard health wiring checks. Full browser behavior tested separately."""
import unittest
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parents[2] / "pi" / "services" / "receiver" / "dashboard.html"


class DashboardHealthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = DASHBOARD.read_text(encoding="utf-8")

    def test_health_endpoint_and_authorization(self):
        self.assertIn("fetch('/api/v1/health',options)", self.html)
        self.assertIn("Authorization:'Bearer '+token", self.html)
        self.assertIn("cache:'no-store'", self.html)

    def test_explicit_stale_unreachable_and_recovery(self):
        for state in ("healthy", "warning", "critical", "no_data",
                      "unknown", "degraded", "receiver_unreachable"):
            with self.subTest(state=state):
                self.assertIn(state, self.html)
        self.assertIn("Recovered: fresh telemetry received.", self.html)
        self.assertIn("previousHealth!==state", self.html)

    def test_recovery_only_after_an_incident(self):
        self.assertIn("const wasIncident=['warning','critical','degraded','receiver_unreachable']", self.html)
        self.assertIn("state==='healthy'&&wasIncident", self.html)
        self.assertIn("Fresh telemetry received.", self.html)

    def test_single_sample_marker(self):
        self.assertIn("if(samples.length===1)", self.html)
        self.assertIn("document.createElementNS(ns,'circle')", self.html)

    def test_unreachable_identifies_cached_readings(self):
        self.assertIn("last known, not live", self.html)
        self.assertIn("displaying last known readings", self.html)

    def test_no_persistent_token_storage(self):
        self.assertNotIn("localStorage", self.html)
        self.assertNotIn("sessionStorage", self.html)
        self.assertNotIn("document.cookie", self.html)


if __name__ == "__main__":
    unittest.main()
