"""M4 local gateway+SQLite tests; no real network probe, credential or task."""
from datetime import datetime, timedelta, timezone
import http.server
import json
import os
from pathlib import Path
import sqlite3
from contextlib import closing
import sys
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'windows/gateway'))
sys.path.insert(0, str(ROOT / 'tests/monitoring/v080'))
import OnyxGateway as gateway
import OnyxMonitoringView as m4
from test_live_incident_history import sample


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'incident-history.sqlite3'
        self.now = datetime.now(timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def _record(self, status='Healthy', *, ago=0, windows='WindowsPathReady', pi='PiInternetVerified'):
        at = (self.now - timedelta(seconds=ago)).isoformat()
        m4.m3.record_cycle(self.path, sample(status, timestamp=at, windows=windows, pi=pi))

    def test_missing_history_is_no_data_and_creates_nothing(self):
        report = m4.snapshot(now=self.now, path=self.path)
        self.assertEqual(report['state'], 'NoData')
        self.assertEqual(report['recorded_checks'], 0)
        self.assertEqual(report['incidents'], [])
        self.assertFalse(self.path.exists())
        self.assertTrue(report['read_only'])

    def test_recent_realistic_healthy_remains_healthy(self):
        self._record(ago=80)
        report = m4.snapshot(now=self.now, path=self.path)
        self.assertEqual(report['state'], 'Healthy')
        self.assertEqual(report['latest']['windows_classification'], 'WindowsPathReady')
        self.assertEqual(report['latest']['pi_classification'], 'PiInternetVerified')
        self.assertEqual(report['incident_count'], 0)
        self.assertEqual(report['recorded_checks'], 1)

    def test_stale_healthy_is_not_reported_currently_healthy(self):
        self._record(ago=301)
        report = m4.snapshot(now=self.now, path=self.path)
        self.assertEqual(report['state'], 'Stale')
        self.assertEqual(report['latest']['observed_status'], 'Healthy')

    def test_stale_outage_has_open_incident_but_not_current_proof(self):
        self._record('Degraded', ago=600, windows='AdapterDown')
        report = m4.snapshot(now=self.now, path=self.path)
        self.assertEqual(report['state'], 'Stale')
        self.assertEqual(report['latest']['observed_status'], 'Degraded')
        self.assertEqual(report['open_incident']['last_status'], 'Degraded')
        self.assertEqual(len(report['incidents']), 1)

    def test_fresh_failure_and_recovery_lifecycle(self):
        self._record('Degraded', ago=125, windows='AdapterDown')
        self._record('Healthy', ago=10)
        report = m4.snapshot(now=self.now, path=self.path)
        self.assertEqual(report['state'], 'Healthy')
        self.assertIsNone(report['open_incident'])
        self.assertIsNotNone(report['incidents'][0]['resolved_at_utc'])
        self.assertEqual(report['incident_count'], 1)
        self.assertEqual(report['recorded_checks'], 2)

    def test_future_clock_does_not_claim_healthy(self):
        self._record(ago=-120)
        report = m4.snapshot(now=self.now, path=self.path)
        self.assertEqual(report['state'], 'Unknown')

    def test_snapshot_does_not_mutate_history_database(self):
        self._record(ago=60)
        before = self.path.read_bytes()
        m4.snapshot(now=self.now, path=self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_unsupported_history_version_rejected_not_overwritten(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('PRAGMA user_version=77')
        before = self.path.read_bytes()
        with self.assertRaises(m4.m3.HistoryError):
            m4.snapshot(now=self.now, path=self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_outputs_sanitized_not_raw_probes(self):
        self._record('Degraded', ago=20, windows='AdapterDown')
        body = json.dumps(m4.snapshot(now=self.now, path=self.path))
        for forbidden in ('Authorization', 'ssh_private_key', '192.168.137.167', 'Bearer ', 'raw_output'):
            self.assertNotIn(forbidden, body)


class GatewayRouteTests(unittest.TestCase):
    def setUp(self):
        self.srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), gateway.Gateway)
        self.srv.daemon_threads = True
        self.srv.dashboard = b'ONYX CORE gatewayMode'
        self.srv.overlay = b'ONYX CORE id="hud"'
        self.srv.overlay_portrait = b'ONYX CORE id="hud"'
        self.srv.v080_monitor_view = True
        self.srv.monitor_reader = lambda: {'source': 'OnyxV080MonitoringView', 'state': 'NoData', 'incidents': []}
        self.worker = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.worker.start()
        self.port = self.srv.server_port
        self.base = 'http://127.0.0.1:' + str(self.port)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.worker.join(timeout=2)

    def get(self, endpoint, headers=None, method='GET'):
        req = urllib.request.Request(self.base + endpoint, headers=headers or {}, method=method)
        try:
            with self.opener.open(req, timeout=3) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def test_opt_in_endpoint_serves_sanitized_local_json(self):
        code, data = self.get('/api/v1/monitor/summary')
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(data)['state'], 'NoData')
        self.assertEqual(json.loads(data)['source'], 'OnyxV080MonitoringView')

    def test_disabled_endpoint_not_found(self):
        self.srv.v080_monitor_view = False
        self.assertEqual(self.get('/api/v1/monitor/summary')[0], 404)

    def test_monitor_endpoint_cannot_be_cross_origin_or_dns_rebound(self):
        self.assertEqual(self.get('/api/v1/monitor/summary', {'Host': 'attacker.example'})[0], 403)
        self.assertEqual(self.get('/api/v1/monitor/summary', {'Origin': 'http://bad.test'})[0], 403)
        self.assertEqual(self.get('/api/v1/monitor/summary', {'Sec-Fetch-Site': 'cross-site'})[0], 403)

    def test_monitor_endpoint_is_read_only_no_queries(self):
        self.assertEqual(self.get('/api/v1/monitor/summary?all=true')[0], 400)
        self.assertEqual(self.get('/api/v1/monitor/summary', method='POST')[0], 405)

    def test_history_errors_are_fail_closed(self):
        def failing():
            raise m4.m3.HistoryError('some private disk location should not leak')
        self.srv.monitor_reader = failing
        code, data = self.get('/api/v1/monitor/summary')
        self.assertEqual(code, 503)
        self.assertNotIn(b'private disk location', data)
        self.assertIn(b'monitor_history_unavailable', data)

    def test_existing_telemetry_and_overlay_routes_unchanged(self):
        self.assertEqual(self.get('/dashboard')[0], 200)
        self.assertEqual(self.get('/overlay')[0], 200)
        self.assertEqual(self.get('/overlay-portrait')[0], 200)
        self.assertEqual(self.get('/api/v1/unknown')[0], 404)


if __name__ == '__main__':
    unittest.main()
