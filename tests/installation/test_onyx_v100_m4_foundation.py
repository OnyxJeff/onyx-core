"""M4 v100-only health and read-only history integration, disposable fixtures."""
from datetime import datetime, timedelta, timezone
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / p) for p in ('windows/gateway', 'tests/monitoring/v080',
                                      'tools/installation/windows')]
from pi.services.receiver.health import evaluate_health
from pi.services.receiver.integrated_store_v100 import IntegratedStore
import OnyxV100MonitoringView as view
import OnyxGateway_v100 as gateway
import onyx_v100_make_windows_runtime as make
import onyx_v100_make_dashboard as dashboard
from test_live_incident_history import sample
import OnyxLiveIncidentHistory as journal

NOW = datetime(2026, 11, 25, 17, 0, tzinfo=timezone.utc)


def stamp(seconds):
    return (NOW + timedelta(seconds=seconds)).isoformat().replace('+00:00', 'Z')


class HealthTests(unittest.TestCase):
    def test_legacy_future_remains_unknown(self):
        self.assertEqual(evaluate_health(stamp(1), now=NOW)['status'], 'unknown')

    def test_v100_boundaries(self):
        for offset, status, age in [(0, 'healthy', 0), (0.001, 'healthy', 0),
                                    (5, 'healthy', 0), (5.001, 'unknown', None),
                                    (-90, 'healthy', 90), (-90.001, 'warning', 90),
                                    (-180, 'warning', 180), (-180.001, 'critical', 180)]:
            with self.subTest(offset=offset):
                result = evaluate_health(stamp(offset), now=NOW, future_tolerance_seconds=5)
                self.assertEqual((result['status'], result['age_seconds']), (status, age))
                if 0 < offset <= 5:
                    self.assertEqual(result['reason'], 'telemetry_fresh_clock_skew')

    def test_reject_invalid_tolerance(self):
        for tolerance in (-1, 6, True, 1.5, '5'):
            with self.subTest(tolerance=tolerance), self.assertRaises(ValueError):
                evaluate_health(stamp(1), now=NOW, future_tolerance_seconds=tolerance)

    def test_real_v100_store_health(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            store = IntegratedStore(root/'telemetry.db', root/'latest.json', snapshot_validator=lambda _: None)
            try:
                payload = {'schema_version': 1, 'source': 'Fixture', 'session_id': '12345678-1234-4234-8234-123456789abc',
                           'sequence': 1, 'timestamp_utc': stamp(3),
                           'metrics': {'cpu_percent': 12, 'memory_used_percent': 40, 'uptime_seconds': 3}}
                self.assertTrue(store.accept(payload))
                self.assertEqual(store.health(now=NOW)['reason'], 'telemetry_fresh_clock_skew')
                self.assertEqual(store.health(now=NOW-timedelta(seconds=3))['status'], 'unknown')
                self.assertEqual(store.recent(1)[0]['timestamp_utc'], stamp(3))
            finally:
                store.close()


class ViewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        env = patch.dict(os.environ, {'LOCALAPPDATA': str(self.root), 'ONYXCORE_V080_STORAGE_PROFILE': 'release'})
        env.start(); self.addCleanup(env.stop)
        self.old = self.root/'OnyxCore-v080-Release'/'Monitoring'/'incident-history.sqlite3'
        self.new = self.root/'OnyxCore-v100'/'Monitoring'/'incident-history.sqlite3'
        journal.record_cycle(self.old, sample(timestamp=NOW.isoformat()))
        self.before = self.old.read_bytes()

    def tearDown(self):
        self.assertEqual(self.old.read_bytes(), self.before)

    def test_no_legacy_fallback_or_creation(self):
        self.assertEqual(view.snapshot(now=NOW)['state'], 'NoData')
        self.assertFalse(self.new.parent.exists())

    def test_existing_v100_history(self):
        journal.record_cycle(self.new, sample(timestamp=NOW.isoformat()))
        before = self.new.read_bytes()
        result = view.snapshot(now=NOW)
        self.assertEqual(result['source'], 'OnyxV100MonitoringView')
        self.assertEqual(result['state'], 'Healthy')
        self.assertEqual(view.snapshot(now=NOW+timedelta(seconds=301))['state'], 'Stale')
        self.assertEqual(self.new.read_bytes(), before)

    def test_refuse_linked_database(self):
        self.new.parent.mkdir(parents=True)
        try:
            os.link(self.old, self.new)
        except OSError as e:
            self.skipTest('hard links unavailable: '+str(e))
        with self.assertRaises(ValueError):
            view.snapshot(now=NOW)

    def test_refuse_redirected_parent(self):
        try:
            (self.root/'OnyxCore-v100').symlink_to(self.old.parent.parent, target_is_directory=True)
        except OSError as e:
            self.skipTest('symlinks unavailable: '+str(e))
        with self.assertRaises(ValueError):
            view.snapshot(now=NOW)

    def test_gateway_route_opt_in_and_host_guard(self):
        srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), gateway.Gateway)
        srv.daemon_threads = True
        srv.v100_monitor_view = True
        srv.monitor_reader = view.snapshot
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            url = f'http://127.0.0.1:{srv.server_port}/api/v1/monitor/summary'
            with opener.open(url, timeout=3) as resp:
                self.assertEqual(json.load(resp)['state'], 'NoData')
            for headers, suffix, code in [({'Host': 'bad.example'}, '', 403), ({}, '?x=1', 400)]:
                with self.assertRaises(urllib.error.HTTPError) as err:
                    opener.open(urllib.request.Request(url+suffix, headers=headers), timeout=3)
                self.assertEqual(err.exception.code, code)
            srv.v100_monitor_view = False
            with self.assertRaises(urllib.error.HTTPError) as err:
                opener.open(url, timeout=3)
            self.assertEqual(err.exception.code, 404)
        finally:
            srv.shutdown(); srv.server_close(); thread.join(3)


class GeneratorTests(unittest.TestCase):
    def test_gateway_generated_bytes(self):
        old = (ROOT/'windows/gateway/OnyxGateway.py').read_text(encoding='utf-8')
        result = make.transform_gateway_monitoring(make.transform_gateway(old))
        self.assertEqual(result, (ROOT/'windows/gateway/OnyxGateway_v100.py').read_text(encoding='utf-8'))
        self.assertIn('OnyxV100MonitoringView import snapshot', result)
        self.assertNotIn('--v080-monitor-view', result)

    def test_dashboard_generated_and_opt_in(self):
        result = dashboard.transform((ROOT/'windows/gateway/gateway-dashboard.html').read_bytes())
        self.assertEqual(result, dashboard.normalize((ROOT/'windows/gateway/gateway-dashboard-v100.html').read_bytes()))
        self.assertIn(b'if(response.status===404)', result)
        self.assertIn(b'const monitorView=gatewayMode;', result)

    def test_legacy_cli_rejected_and_reserved_ports(self):
        for args in [('--v080-monitor-view',), ('--v100-monitor-view', '--port', '18767'), ('--port', '18768')]:
            result = subprocess.run([sys.executable, '-B', str(ROOT/'windows/gateway/OnyxGateway_v100.py'),
                '--dashboard', 'unused', '--receiver', '127.0.0.1', '--receiver-port', '8765', *args],
                capture_output=True, input=b'', timeout=5)
            self.assertEqual(result.returncode, 2)


if __name__ == '__main__':
    unittest.main()
