"""v0.8 native gateway address evidence: offline mock-only regression.

All native calls are injected Python fakes; no Windows API, network, SSH, store,
PowerShell, job, consent, task, or notification interactions occur.
"""
from __future__ import annotations
import ctypes
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[3] / 'windows' / 'monitoring' / 'v080' / 'OnyxNativeGatewayAddress.py'
SPEC = importlib.util.spec_from_file_location('onyx_gateway_address_offline', SOURCE)
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)

GW = '192.168.137.1'
PI = '192.168.137.167'


class FakeGetEntry:
    def __init__(self, *, status=0, **changes):
        self.status, self.changes = status, changes
        self.calls = []
        self.argtypes = None
        self.restype = None

    def __call__(self, ptr):
        row = ctypes.cast(ptr, ctypes.POINTER(m.MIB_UNICASTIPADDRESS_ROW)).contents
        self.calls.append((int(row.InterfaceIndex), bytes(row.Address.Ipv4.sin_addr),
                           int(row.Address.Ipv4.sin_family), int(row.InterfaceLuid)))
        if self.status:
            return self.status
        row.InterfaceLuid = 0x12345678
        row.OnLinkPrefixLength = 24
        row.DadState = m.IP_DAD_STATE_PREFERRED
        row.SkipAsSource = 0
        row.ValidLifetime = 0xFFFFFFFF
        row.PreferredLifetime = 0xFFFFFFFF
        for name, value in self.changes.items():
            if name == 'address':
                row.Address.Ipv4.sin_addr[:] = bytes(value)
            elif name == 'family':
                row.Address.si_family = value
            else:
                setattr(row, name, value)
        return 0


class FakeDll:
    def __init__(self, api):
        self.GetUnicastIpAddressEntry = api


class GatewayEvidenceOfflineTests(unittest.TestCase):
    def probe(self, api=None, **kwargs):
        api = api or FakeGetEntry()
        result = m.verify_gateway_address(GW, PI, 7, api=api, **kwargs)
        return result, api

    def test_struct_sizes_and_offsets(self):
        m._check_abi()
        self.assertEqual(ctypes.sizeof(m.SOCKADDR_IN), 16)
        self.assertEqual(ctypes.sizeof(m.SOCKADDR_IN6), 28)
        self.assertEqual(ctypes.sizeof(m.SOCKADDR_INET), 28)
        self.assertEqual(ctypes.sizeof(m.MIB_UNICASTIPADDRESS_ROW), 80)
        self.assertEqual(m.MIB_UNICASTIPADDRESS_ROW.InterfaceIndex.offset, 40)
        self.assertEqual(m.MIB_UNICASTIPADDRESS_ROW.DadState.offset, 64)
        self.assertEqual(m.MIB_UNICASTIPADDRESS_ROW.CreationTimeStamp.offset, 72)

    def test_ipv4_input_bytes_and_index(self):
        result, api = self.probe()
        self.assertEqual(result.classification, 'Preferred')
        self.assertEqual(api.calls, [(7, bytes([192, 168, 137, 1]), 2, 0)])
        self.assertEqual(api.argtypes, (ctypes.POINTER(m.MIB_UNICASTIPADDRESS_ROW),))
        self.assertEqual(api.restype, ctypes.c_uint32)

    def test_preferred_ipv4_and_covering_prefix(self):
        result, _ = self.probe()
        self.assertEqual(result.classification, 'Preferred')
        self.assertEqual(result.interface_index, 7)
        self.assertEqual(result.reason, 'GatewayIpv4Preferred')

    def test_fresh_interface_index_per_query(self):
        one, _ = self.probe()
        api = FakeGetEntry()
        two = m.verify_gateway_address(GW, PI, 99, api=api)
        self.assertEqual((one.interface_index, two.interface_index), (7, 99))
        self.assertEqual(api.calls[0][0], 99)

    def test_get_entry_status_error_is_unavailable(self):
        evidence, _ = self.probe(FakeGetEntry(status=1168))
        self.assertEqual(evidence.classification, 'Unavailable')
        self.assertIsNone(evidence.interface_index)

    def test_loader_denial_is_unavailable_no_raw_error(self):
        def denied(_):
            raise PermissionError('SENSITIVE PATH')
        evidence = m.verify_gateway_address(GW, PI, 7, loader=denied)
        self.assertEqual(evidence.classification, 'Unavailable')
        self.assertNotIn('SENSITIVE', str(evidence))

    def test_injected_loader_uses_expected_dll(self):
        names = []
        api = FakeGetEntry()
        def loader(name):
            names.append(name)
            return FakeDll(api)
        evidence = m.verify_gateway_address(GW, PI, 7, loader=loader)
        self.assertEqual(evidence.classification, 'Preferred')
        self.assertEqual(names, ['iphlpapi.dll'])

    def test_missing_native_api_is_unavailable(self):
        evidence = m.verify_gateway_address(GW, PI, 7, loader=lambda _: object())
        self.assertEqual(evidence.classification, 'Unavailable')

    def test_wrong_returned_gateway_unavailable(self):
        evidence, _ = self.probe(FakeGetEntry(address=(192, 168, 137, 9)))
        self.assertEqual(evidence.classification, 'Unavailable')

    def test_wrong_returned_interface_unavailable(self):
        evidence, _ = self.probe(FakeGetEntry(InterfaceIndex=9))
        self.assertEqual(evidence.classification, 'Unavailable')

    def test_missing_returned_luid_unavailable(self):
        evidence, _ = self.probe(FakeGetEntry(InterfaceLuid=0))
        self.assertEqual(evidence.classification, 'Unavailable')

    def test_wrong_family_unavailable(self):
        evidence, _ = self.probe(FakeGetEntry(family=23))
        self.assertEqual(evidence.classification, 'Unavailable')

    def test_nonpreferred_dad_tentative(self):
        evidence, _ = self.probe(FakeGetEntry(DadState=1))
        self.assertEqual(evidence.classification, 'NotPreferred')
        self.assertIsNone(evidence.interface_index)

    def test_nonpreferred_dad_deprecated(self):
        evidence, _ = self.probe(FakeGetEntry(DadState=3))
        self.assertEqual(evidence.classification, 'NotPreferred')

    def test_nonpreferred_skip_as_source(self):
        evidence, _ = self.probe(FakeGetEntry(SkipAsSource=1))
        self.assertEqual(evidence.classification, 'NotPreferred')

    def test_invalid_dad_state_unavailable(self):
        evidence, _ = self.probe(FakeGetEntry(DadState=99))
        self.assertEqual(evidence.classification, 'Unavailable')

    def test_invalid_skip_as_source_unavailable(self):
        evidence, _ = self.probe(FakeGetEntry(SkipAsSource=2))
        self.assertEqual(evidence.classification, 'Unavailable')

    def test_prefix_does_not_cover_receiver(self):
        evidence, _ = self.probe(FakeGetEntry(OnLinkPrefixLength=25))
        self.assertEqual(evidence.classification, 'Unavailable')

    def test_prefix_32_does_not_cover_receiver(self):
        evidence, _ = self.probe(FakeGetEntry(OnLinkPrefixLength=32))
        self.assertEqual(evidence.classification, 'Unavailable')

    def test_invalid_prefix(self):
        for prefix in (0, 33, 255):
            with self.subTest(prefix=prefix):
                evidence, _ = self.probe(FakeGetEntry(OnLinkPrefixLength=prefix))
                self.assertEqual(evidence.classification, 'Unavailable')

    def test_expired_valid_lifetime(self):
        evidence, _ = self.probe(FakeGetEntry(ValidLifetime=0))
        self.assertEqual(evidence.classification, 'Unavailable')

    def test_expired_preferred_lifetime(self):
        evidence, _ = self.probe(FakeGetEntry(PreferredLifetime=0))
        self.assertEqual(evidence.classification, 'Unavailable')

    def test_inconsistent_lifetimes(self):
        evidence, _ = self.probe(FakeGetEntry(PreferredLifetime=100, ValidLifetime=50))
        self.assertEqual(evidence.classification, 'Unavailable')

    def test_bad_input_refuses_before_native_load(self):
        inputs = [(GW, PI, 0), (GW, PI, True), (GW, PI, -1),
                  (GW, PI, 0xFFFFFFFF), (GW, GW, 7),
                  ('not-an-address', PI, 7), ('224.0.0.1', PI, 7),
                  ('0.0.0.0', PI, 7), ('127.0.0.1', PI, 7)]
        def refuse(_):
            raise AssertionError('must not load native DLL')
        for gateway, receiver, index in inputs:
            with self.subTest(gateway=gateway, receiver=receiver, index=index):
                result = m.verify_gateway_address(gateway, receiver, index, loader=refuse)
                self.assertEqual(result.classification, 'Unavailable')

    def test_output_is_only_minimal_evidence(self):
        result, _ = self.probe()
        self.assertEqual(set(vars(result)), {'classification', 'reason', 'interface_index'})
        self.assertNotIn('SENSITIVE', str(result))

    def test_no_live_cli(self):
        with self.assertRaises(SystemExit):
            m.main(['--live-read-only'])

    def test_import_and_inert_cli_do_not_load_dll(self):
        with patch.object(m, '_lookup_gateway', side_effect=AssertionError('unexpected native call')):
            self.assertEqual(m.main(['--check-inert']), 0)
        p = subprocess.run([sys.executable, '-I', '-B', str(SOURCE), '--check-inert'],
                           capture_output=True, text=True, timeout=10, check=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(json.loads(p.stdout)['native_api_invoked'])

    def test_class_invariants(self):
        with self.assertRaises(ValueError):
            m.GatewayAddressEvidence('Preferred', 'ok', None)
        with self.assertRaises(ValueError):
            m.GatewayAddressEvidence('Unavailable', 'ok', 7)
        with self.assertRaises(ValueError):
            m.GatewayAddressEvidence('wrong', 'ok')


if __name__ == '__main__':
    unittest.main()
