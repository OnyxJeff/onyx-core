"""ONYX CORE v0.8 native IP Helper evidence: offline tests with injected API only.

Never loads iphlpapi.dll, consults the host route, or touches the Pi/network.
"""
from __future__ import annotations

import ctypes
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'windows' / 'monitoring' / 'v080'))
import OnyxNativeRouteEvidence as m


GOOD = m.NativeRoute('192.168.137.0/24', 7, '0.0.0.0', m.ROUTE_DIRECT)
DEST = '192.168.137.167'
GATEWAY = '192.168.137.1'


class FakeApiFunction:
    """Minimal ctypes-compatible injected GetBestRoute; NEVER calls Windows."""
    def __init__(self, *, network='192.168.137.0/24', if_index=7,
                 next_hop='0.0.0.0', route_type=m.ROUTE_DIRECT, status=0):
        self.network = network
        self.if_index = if_index
        self.next_hop = next_hop
        self.route_type = route_type
        self.status = status
        self.calls = []
        self.argtypes = None
        self.restype = None

    def __call__(self, destination, source, ptr):
        self.calls.append((destination, source))
        if self.status != 0:
            return self.status
        route = ctypes.cast(ptr, ctypes.POINTER(m.MIB_IPFORWARDROW)).contents
        network = m.IPv4Network(self.network)
        route.dwForwardDest = m._ip_to_dword(str(network.network_address))
        route.dwForwardMask = m._ip_to_dword(str(network.netmask))
        route.dwForwardNextHop = m._ip_to_dword(self.next_hop)
        route.dwForwardIfIndex = self.if_index
        route.dwForwardType = self.route_type
        return 0


class FakeDLL:
    def __init__(self, fn):
        self.GetBestRoute = fn


class NativeRouteEvidenceTests(unittest.TestCase):
    def test_api_abi_exactly_56_bytes(self):
        self.assertEqual(ctypes.sizeof(m.MIB_IPFORWARDROW), 56)
        self.assertEqual(len(m.MIB_IPFORWARDROW._fields_), 14)

    def test_byte_order_canonical_ipv4(self):
        self.assertEqual(m._ip_to_dword('192.168.137.167'), 0xA789A8C0)
        self.assertEqual(m._dword_to_ip(0xA789A8C0), '192.168.137.167')
        self.assertEqual(m._ip_to_dword('0.0.0.0'), 0)

    def test_onlink_expected_route(self):
        outcome = m.evaluate_route(GOOD, destination=DEST, expected_gateway=GATEWAY, expected_if_index=7)
        self.assertEqual(outcome.classification, 'ExpectedRoute')
        self.assertEqual(outcome.reason, 'SelectedDirectUsbRoute')

    def test_other_interface_is_confirmed_mismatch(self):
        route = m.NativeRoute('192.168.137.0/24', 9, '0.0.0.0', m.ROUTE_DIRECT)
        self.assertEqual(m.evaluate_route(route, destination=DEST, expected_gateway=GATEWAY,
                                          expected_if_index=7).classification, 'ConfirmedMismatch')

    def test_indirect_hop_is_confirmed_mismatch(self):
        route = m.NativeRoute('192.168.137.167/32', 7, '192.168.137.254', m.ROUTE_INDIRECT)
        self.assertEqual(m.evaluate_route(route, destination=DEST, expected_gateway=GATEWAY,
                                          expected_if_index=7).classification, 'ConfirmedMismatch')

    def test_wrong_interface_and_wrong_hop_mismatch(self):
        route = m.NativeRoute('0.0.0.0/0', 9, '10.100.0.1', m.ROUTE_INDIRECT)
        self.assertEqual(m.evaluate_route(route, destination=DEST, expected_gateway=GATEWAY,
                                          expected_if_index=7).classification, 'ConfirmedMismatch')

    def test_incoherent_direct_next_hop_unavailable(self):
        route = m.NativeRoute('192.168.137.0/24', 7, '192.168.137.254', m.ROUTE_DIRECT)
        self.assertEqual(m.evaluate_route(route, destination=DEST, expected_gateway=GATEWAY,
                                          expected_if_index=7).classification, 'Unavailable')

    def test_incoherent_indirect_zero_hop_unavailable(self):
        route = m.NativeRoute('192.168.137.0/24', 7, '0.0.0.0', m.ROUTE_INDIRECT)
        self.assertEqual(m.evaluate_route(route, destination=DEST, expected_gateway=GATEWAY,
                                          expected_if_index=7).classification, 'Unavailable')

    def test_invalid_route_type_unavailable(self):
        for value in (0, 1, 2, 5, -1):
            with self.subTest(value=value):
                route = m.NativeRoute('192.168.137.0/24', 7, '0.0.0.0', value)
                self.assertEqual(m.evaluate_route(route, destination=DEST, expected_gateway=GATEWAY,
                                                  expected_if_index=7).classification, 'Unavailable')

    def test_wrong_destination_network_unavailable(self):
        route = m.NativeRoute('10.0.0.0/24', 7, '0.0.0.0', m.ROUTE_DIRECT)
        self.assertEqual(m.evaluate_route(route, destination=DEST, expected_gateway=GATEWAY,
                                          expected_if_index=7).classification, 'Unavailable')

    def test_invalid_input_unavailable(self):
        cases = [(GOOD, DEST, True), (GOOD, DEST, 0), (GOOD, DEST, 2**32),
                 (GOOD, 'not ipv4', 7), ('wrong type', DEST, 7),
                 (m.NativeRoute('bad/prefix',7,'0.0.0.0',3), DEST, 7)]
        for route, target, index in cases:
            with self.subTest(target=target,index=index):
                self.assertEqual(m.evaluate_route(route, destination=target, expected_gateway=GATEWAY,
                                                  expected_if_index=index).classification,'Unavailable')

    def test_invalid_interface_index_unavailable(self):
        for index in (0, -2, 2**32, True):
            route = m.NativeRoute('192.168.137.0/24', index, '0.0.0.0', 3)
            self.assertEqual(m.evaluate_route(route, destination=DEST, expected_gateway=GATEWAY,
                                              expected_if_index=7).classification,'Unavailable')

    def test_direct_default_route_cannot_prove_usb_subnet(self):
        route = m.NativeRoute('0.0.0.0/0', 7, '0.0.0.0', m.ROUTE_DIRECT)
        self.assertEqual(m.evaluate_route(route, destination=DEST,
                                          expected_gateway=GATEWAY,
                                          expected_if_index=7).classification, 'Unavailable')

    def test_direct_host_route_without_gateway_cannot_prove_usb_subnet(self):
        route = m.NativeRoute('192.168.137.167/32', 7, '0.0.0.0', m.ROUTE_DIRECT)
        self.assertEqual(m.evaluate_route(route, destination=DEST,
                                          expected_gateway=GATEWAY,
                                          expected_if_index=7).classification, 'Unavailable')

    def test_native_lookup_injected_api_uses_unconstrained_source_zero(self):
        fn = FakeApiFunction()
        names = []
        def loader(name):
            names.append(name)
            return FakeDLL(fn)
        out = m.probe_route(DEST, GATEWAY, 7, loader=loader)
        self.assertEqual(out.classification, 'ExpectedRoute')
        self.assertEqual(names, ['iphlpapi.dll'])
        self.assertEqual(fn.calls, [(m._ip_to_dword(DEST), 0)])
        self.assertEqual(fn.argtypes[:2], (ctypes.c_uint32,ctypes.c_uint32))
        self.assertIs(fn.restype, ctypes.c_uint32)

    def test_native_status_error_is_unavailable_not_degraded(self):
        fn=FakeApiFunction(status=5)
        self.assertEqual(m.probe_route(DEST, GATEWAY, 7, loader=lambda _: FakeDLL(fn)).classification,
                         'Unavailable')

    def test_native_loader_denied_is_unavailable(self):
        def denied(_):
            raise PermissionError('sensitive raw path must not leak')
        outcome=m.probe_route(DEST, GATEWAY, 7, loader=denied)
        self.assertEqual(outcome.classification, 'Unavailable')
        self.assertNotIn('sensitive', str(outcome))

    def test_native_inconsistent_prefix_is_unavailable(self):
        fn=FakeApiFunction(network='192.168.138.0/24')
        self.assertEqual(m.probe_route(DEST,GATEWAY,7,loader=lambda _: FakeDLL(fn)).classification,
                         'Unavailable')

    def test_native_noncontiguous_mask_is_unavailable(self):
        class MaskFn(FakeApiFunction):
            def __call__(self,destination,source,ptr):
                result=super().__call__(destination,source,ptr)
                ctypes.cast(ptr,ctypes.POINTER(m.MIB_IPFORWARDROW)).contents.dwForwardMask = (
                    m._ip_to_dword('255.0.255.0'))
                return result
        fn=MaskFn()
        self.assertEqual(m.probe_route(DEST,GATEWAY,7,loader=lambda _: FakeDLL(fn)).classification,
                         'Unavailable')

    def test_no_host_or_network_probe_on_import_and_inert_cli(self):
        script=ROOT/'windows'/'monitoring'/'v080'/'OnyxNativeRouteEvidence.py'
        r=subprocess.run([sys.executable,'-I','-B',str(script),'--check-inert'],
                         text=True,capture_output=True,timeout=10,check=False)
        self.assertEqual(r.returncode,0,r.stderr)
        doc=json.loads(r.stdout)
        self.assertFalse(doc['native_api_invoked'])
        self.assertFalse(doc['release_integrated'])

    def test_cli_live_refused(self):
        script=ROOT/'windows'/'monitoring'/'v080'/'OnyxNativeRouteEvidence.py'
        r=subprocess.run([sys.executable,'-I','-B',str(script),'--live-read-only'],
                         text=True,capture_output=True,timeout=10,check=False)
        self.assertNotEqual(r.returncode,0)
        self.assertNotIn('iphlpapi',r.stdout)

    def test_prototype_import_does_not_load_native_library(self):
        # Explicitly inject the API in tests. Merely evaluating pure code must
        # not initiate a native DLL load, even on Windows.
        with patch.object(m, '_get_best_route', side_effect=AssertionError('native call')):
            self.assertEqual(m.evaluate_route(GOOD,destination=DEST,expected_gateway=GATEWAY,
                                              expected_if_index=7).classification,'ExpectedRoute')
            self.assertEqual(m.main(['--check-inert']),0)


if __name__ == '__main__':
    unittest.main()
