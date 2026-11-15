"""RC3: isolate release monitoring dashboard on 127.0.0.1:18768.

Offline: mocked monitor reader, no Pi, no persistent storage and no native service.
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path
import importlib.util
import http.server
import threading
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[3]
GATEWAY = ROOT / 'windows' / 'gateway' / 'OnyxGateway.py'
DASHBOARD = ROOT / 'windows' / 'gateway' / 'gateway-dashboard.html'

class ReleaseDashboardContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gateway_source = GATEWAY.read_text(encoding='utf-8')
        cls.dashboard_source = DASHBOARD.read_text(encoding='utf-8')

    def cli(self, *args, profile=None):
        env = dict(os.environ)
        env.pop('ONYXCORE_V080_STORAGE_PROFILE', None)
        if profile is not None:
            env['ONYXCORE_V080_STORAGE_PROFILE'] = profile
        return subprocess.run([sys.executable, '-I', '-B', str(GATEWAY),
                               '--dashboard',str(DASHBOARD),*args],
                              env=env, input='', text=True, capture_output=True,
                              timeout=5)

    def test_production_monitor_remains_denied(self):
        r=self.cli('--port','18766','--v080-monitor-view',profile='release')
        self.assertNotEqual(r.returncode,0)
        self.assertIn('protected production port 18766',r.stderr)

    def test_release_port_requires_explicit_opt_in(self):
        r=self.cli('--port','18768',profile='release')
        self.assertNotEqual(r.returncode,0)
        self.assertIn('requires explicit --v080-monitor-view',r.stderr)

    def test_release_port_requires_release_profile(self):
        for profile in (None,'development','Release',''):
            with self.subTest(profile=profile):
                r=self.cli('--port','18768','--v080-monitor-view',profile=profile)
                self.assertNotEqual(r.returncode,0)
                self.assertIn('requires the release storage profile',r.stderr)

    def test_release_port_accepts_profile_then_requires_credential(self):
        # Invalid dummy credential intentionally exits before opening a listener.
        r=self.cli('--port','18768','--v080-monitor-view',profile='release')
        self.assertNotEqual(r.returncode,0)
        self.assertIn('invalid protected credential',r.stderr)
        self.assertNotIn('requires the release storage profile',r.stderr)

    def test_development_port_not_restricted_by_release_guard(self):
        r=self.cli('--port','18767','--v080-monitor-view',profile='development')
        self.assertIn('invalid protected credential',r.stderr)
        self.assertNotIn('release storage profile',r.stderr)

    def test_browser_gate_both_ports_but_not_production(self):
        self.assertIn("'http://127.0.0.1:18766','http://127.0.0.1:18767','http://127.0.0.1:18768'", self.dashboard_source)
        self.assertIn("const monitorView=gatewayMode&&['18767','18768'].includes(location.port);", self.dashboard_source)
        self.assertIn('body.monitor-enabled #monitor-panel{display:block}',self.dashboard_source)
        self.assertIn("document.body.classList.add('monitor-enabled');",self.dashboard_source)
        self.assertIn("fetch('/api/v1/monitor/summary'",self.dashboard_source)
        self.assertNotIn('v0.8 DEVELOPMENT',self.dashboard_source)

    def test_monitor_api_read_only_and_no_upstream(self):
        spec=importlib.util.spec_from_file_location('gateway_rc3_test',GATEWAY)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        class NeverPi:
            def open(self,*args,**kwargs):
                raise AssertionError('Pi upstream must not be contacted by monitoring summary')
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),module.Gateway)
        server.daemon_threads=True
        server.dashboard=b'ONYX CORE gatewayMode'
        server.overlay=b''
        server.overlay_portrait=b''
        server.token='dummy-not-a-real-token'
        server.opener=NeverPi()
        server.upstream='http://127.0.0.1:8765'
        server.v080_monitor_view=True
        server.monitor_reader=lambda: {'schema_version':1,'source':'OnyxV080MonitoringView','read_only':True,'recorded_checks':2,'state':'Stale'}
        t=threading.Thread(target=server.serve_forever,daemon=True)
        t.start()
        try:
            port=server.server_port
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open('http://127.0.0.1:%s/api/v1/monitor/summary'%port,timeout=3) as r:
                self.assertEqual(r.status,200)
                self.assertIn(b'"recorded_checks":2',r.read())
            req=urllib.request.Request('http://127.0.0.1:%s/api/v1/monitor/summary'%port,method='POST')
            with self.assertRaises(urllib.error.HTTPError) as cm:
                opener.open(req,timeout=3)
            self.assertEqual(cm.exception.code,405)
        finally:
            server.shutdown()
            server.server_close()
            t.join(timeout=3)

if __name__ == '__main__':
    unittest.main()
