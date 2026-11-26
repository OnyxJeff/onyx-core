#!/usr/bin/env python3
"""Offline native-Pi receiver launch integration tests (no sockets/services)."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PI = ROOT/'tools/installation/pi'
if str(PI) not in sys.path:
    sys.path.insert(0, str(PI))
import onyx_v100_make_receiver as maker
import onyx_v100_pi_launch as launcher
from onyx_v100_config import load_config

CONFIG = ROOT/'docs/v1.0.0/examples/pi-armv6.config.example.json'

def ip_inventory(addrs=None):
    if addrs is None: addrs = ['10.12.194.1', '192.168.137.167']
    return json.dumps([{'ifname':'usb0','addr_info':[{'family':'inet','local':x} for x in addrs]}])

class PiRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.receiver = self.root/'pi/services/receiver/receiver_v100.py'
        self.receiver.parent.mkdir(parents=True)
        self.receiver.write_text('# generated v1 receiver synthetic fixture\n', encoding='utf-8')
        self.config = load_config(CONFIG,'pi-armv6')

    def test_dual_ip_selects_configured_subnet(self):
        x = launcher.plan(self.config, ip_inventory(), self.root)
        self.assertEqual(x['bind_address'],'192.168.137.167')
        self.assertEqual(x['receiver_port'],8765)
        self.assertEqual(x['usb_subnet'],'192.168.137.0/24')
        self.assertTrue(x['history_path'].endswith('/var/lib/onyxcore/telemetry.db'))
        self.assertIn('--usb-subnet',x['argv'])
        self.assertEqual(x['argv'][x['argv'].index('--expected-source')+1], 'MyWindowsPC')
        self.assertEqual(x['argv'][x['argv'].index('--bind')+1],'192.168.137.167')
        self.assertFalse(x['activation_performed'])

    def test_configurable_subnet_and_storage_and_port(self):
        v=json.loads(json.dumps(self.config))
        v['receiver']['ipv4_subnet']='10.12.194.0/28'
        v['receiver']['port']=9789
        v['storage']['state_dir']='/srv/onyx-v100'
        v['storage']['history_name']='history.db'
        x=launcher.plan(v, ip_inventory(), self.root)
        self.assertEqual(x['bind_address'],'10.12.194.1')
        self.assertEqual(x['receiver_port'],9789)
        self.assertEqual(x['history_path'],'/srv/onyx-v100/history.db')

    def test_ambiguous_subnet_fails_closed(self):
        with self.assertRaises(ValueError):
            launcher.plan(self.config,ip_inventory(['192.168.137.167','192.168.137.168']),self.root)

    def test_missing_subnet_fails_closed(self):
        with self.assertRaises(ValueError):
            launcher.plan(self.config,ip_inventory(['10.12.194.1']),self.root)

    def test_missing_versioned_receiver_fails_closed(self):
        self.receiver.unlink()
        with self.assertRaises(launcher.LaunchRefused):
            launcher.plan(self.config,ip_inventory(),self.root)

    def test_legacy_receiver_never_modified_by_plan(self):
        orig = self.receiver.read_bytes()
        launcher.plan(self.config,ip_inventory(),self.root)
        self.assertEqual(self.receiver.read_bytes(),orig)

    def test_cli_preview_no_activation(self):
        capture = self.root/'metadata.json'
        capture.write_text(ip_inventory(),encoding='utf-8')
        p=subprocess.run([sys.executable,'-I','-B',str(PI/'onyx_v100_pi_launch.py'),
                          '--config',str(CONFIG),'--installed-root',str(self.root),
                          '--ip-json-file',str(capture)],capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr)
        obj=json.loads(p.stdout)
        self.assertFalse(obj['activation_performed'])
        self.assertEqual(obj['operation'],'RECEIVER_LAUNCH_PREVIEW')
        self.assertNotIn('ONYXCORE_TOKEN',p.stdout)

    def test_cli_cannot_activate_with_captured_metadata(self):
        capture=self.root/'metadata.json'
        capture.write_text(ip_inventory(),encoding='utf-8')
        p=subprocess.run([sys.executable,'-I','-B',str(PI/'onyx_v100_pi_launch.py'),
                          '--config',str(CONFIG),'--installed-root',str(self.root),
                          '--ip-json-file',str(capture),'--run','--approve-execution'],
                         capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,2)
        self.assertIn('STOP:',p.stderr)

    def test_cli_rejects_one_sided_execution_approval(self):
        p=subprocess.run([sys.executable,'-I','-B',str(PI/'onyx_v100_pi_launch.py'),
                          '--config',str(CONFIG),'--installed-root',str(self.root),
                          '--run'],capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,2)

    def test_generator_handles_windows_crlf_checkout(self):
        source = (ROOT/'pi/services/receiver/receiver.py').read_bytes()
        lf_source = source.replace(b'\r\n', b'\n')
        self.assertNotIn(b'\r', lf_source)
        crlf_source = lf_source.replace(b'\n', b'\r\n')
        self.assertEqual(maker.transform(lf_source), maker.transform(crlf_source))
        self.assertEqual(maker.transform(source), maker.transform(lf_source))
        self.assertIn(b'--usb-subnet', maker.transform(source))
        self.assertIn(b'--expected-source', maker.transform(source))

    def test_generator_refuses_mixed_line_endings(self):
        source = (ROOT/'pi/services/receiver/receiver.py').read_bytes()
        lf_source = source.replace(b'\r\n', b'\n')
        self.assertNotIn(b'\r', lf_source)
        mixed = lf_source.replace(b'\n', b'\r\n', 1)
        self.assertIn(b'\r\n', mixed)
        self.assertIn(b'\n', mixed.replace(b'\r\n', b''))
        with self.assertRaisesRegex(maker.PatchRefused, 'Mixed source line endings refused'):
            maker.transform(mixed)

    def test_generator_accepts_frozen_receiver_checkout(self):
        source = ROOT/'pi/services/receiver/receiver.py'
        data = maker.transform(source.read_bytes())
        self.assertIn(b'--expected-source', data)
        self.assertIn(b'expected_source=expected_source', data)
        self.assertIn(b'integrated_store_v100', data)
        self.assertNotIn(b'payload["source"] != "SQUALL"', data)
        self.assertEqual(data, (ROOT/'pi/services/receiver/receiver_v100.py').read_bytes())

    def test_patcher_fails_unreviewed_source(self):
        with self.assertRaises(maker.PatchRefused):
            maker.transform(b'hello world')

    def test_patcher_fails_duplicated_signature(self):
        source = (ROOT/'pi/services/receiver/receiver.py').read_bytes().replace(b'\r\n', b'\n')
        self.assertNotIn(b'\r', source)
        duplicated = source.replace(maker.OLD_ARGUMENT.encode(),
                                    (maker.OLD_ARGUMENT+'\n'+maker.OLD_ARGUMENT).encode())
        self.assertNotEqual(duplicated, source)
        with self.assertRaisesRegex(maker.PatchRefused, 'Pinned legacy receiver Git blob mismatch'):
            maker.transform(duplicated)

    def test_generator_pins_full_source_not_just_signatures(self):
        source = (ROOT/'pi/services/receiver/receiver.py').read_bytes()
        modified = source.replace(b'standard library only.', b'standard library updated.')
        self.assertNotEqual(modified, source)
        with self.assertRaisesRegex(maker.PatchRefused, 'Pinned legacy receiver Git blob mismatch'):
            maker.transform(modified)

    def test_patcher_versioned_behavior(self):
        modified = maker.transform((ROOT/'pi/services/receiver/receiver.py').read_bytes()).decode()
        self.assertIn('parser.add_argument("--usb-subnet", required=True', modified)
        self.assertIn('parser.add_argument("--expected-source", required=True', modified)
        self.assertIn('subnet = ipaddress.IPv4Network(args.usb_subnet, strict=True)', modified)
        self.assertIn('validate(payload, expected_source=expected_source)', modified)
        self.assertNotIn('address not in ipaddress.IPv4Network("192.168.137.0/24")', modified)

    def test_patcher_never_overwrites(self):
        source = self.root/'receiver.py'
        source.write_bytes((ROOT/'pi/services/receiver/receiver.py').read_bytes())
        output = self.root/'receiver_v100.py'
        output.write_text('existing versioned file', encoding='utf-8')
        with self.assertRaises(maker.PatchRefused):
            maker.build(source, output)
        self.assertEqual(output.read_text(encoding='utf-8'), 'existing versioned file')

    def test_module_import_is_not_service_activation(self):
        text=(PI/'onyx_v100_pi_launch.py').read_text(encoding='utf-8')
        self.assertNotIn('systemctl',text)
        self.assertNotIn('service restart',text)
        self.assertNotIn('nmcli con mod',text)

if __name__=='__main__': unittest.main(verbosity=2)
