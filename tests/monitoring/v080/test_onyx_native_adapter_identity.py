"""ONYX CORE v0.8.0 native adapter identity: fully mocked, offline tests.

No actual Windows API call, network probe, SSH, source, or task changes.
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
import OnyxNativeAdapterIdentity as m


class FakeFunction:
    def __init__(self, impl):
        self.impl = impl
        self.calls = []
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        self.calls.append(args)
        return self.impl(*args)


class FakeDLL:
    def __init__(self, *, alias_status=0, index_status=0, reverse_status=0,
                 luid=67890, index=7, reverse_alias='Ethernet 3'):
        self.alias_status = alias_status
        self.index_status = index_status
        self.reverse_status = reverse_status
        self.luid_value = luid
        self.index_value = index
        self.reverse_alias = reverse_alias
        self.ConvertInterfaceAliasToLuid = FakeFunction(self.alias_to_luid)
        self.ConvertInterfaceLuidToIndex = FakeFunction(self.luid_to_index)
        self.ConvertInterfaceLuidToAlias = FakeFunction(self.luid_to_alias)

    def alias_to_luid(self, alias, pointer):
        if self.alias_status == 0:
            ctypes.cast(pointer, ctypes.POINTER(m.LUID)).contents.value = self.luid_value
        return self.alias_status

    def luid_to_index(self, pointer, index_pointer):
        self._received_luid = ctypes.cast(pointer, ctypes.POINTER(m.LUID)).contents.value
        if self.index_status == 0:
            ctypes.cast(index_pointer, ctypes.POINTER(m.IFINDEX)).contents.value = self.index_value
        return self.index_status

    def luid_to_alias(self, pointer, buffer, length):
        self._reverse_luid = ctypes.cast(pointer, ctypes.POINTER(m.LUID)).contents.value
        if self.reverse_status == 0:
            buffer.value = self.reverse_alias
        return self.reverse_status


class NativeAdapterIdentityTests(unittest.TestCase):
    def test_native_abi_sizes(self):
        self.assertEqual(ctypes.sizeof(m.LUID), 8)
        self.assertEqual(ctypes.sizeof(m.IFINDEX), 4)
        self.assertEqual(ctypes.sizeof(m.NETSTATUS), 4)

    def test_valid_alias_and_index(self):
        fake = FakeDLL()
        names = []
        result = m.resolve_adapter('Ethernet 3', loader=lambda name: (names.append(name), fake)[1])
        self.assertEqual(result.classification, 'Resolved')
        self.assertEqual(result.interface_index, 7)
        self.assertEqual(names, ['iphlpapi.dll'])
        self.assertEqual(fake._received_luid, fake.luid_value)
        self.assertEqual(fake._reverse_luid, fake.luid_value)
        self.assertEqual(fake.ConvertInterfaceAliasToLuid.calls[0][0], 'Ethernet 3')
        self.assertEqual(fake.ConvertInterfaceAliasToLuid.argtypes[0], ctypes.c_wchar_p)
        self.assertEqual(fake.ConvertInterfaceLuidToIndex.argtypes[1]._type_, m.IFINDEX)
        self.assertEqual(fake.ConvertInterfaceLuidToAlias.restype, m.NETSTATUS)

    def test_index_changes_are_fresh_per_call(self):
        values = [7, 15]
        def loader(_):
            return FakeDLL(index=values.pop(0))
        self.assertEqual(m.resolve_adapter('Ethernet 3', loader=loader).interface_index, 7)
        self.assertEqual(m.resolve_adapter('Ethernet 3', loader=loader).interface_index, 15)

    def test_valid_case_insensitive_roundtrip(self):
        result = m.resolve_adapter('Ethernet 3', loader=lambda _: FakeDLL(reverse_alias='ETHERNET 3'))
        self.assertEqual(result.classification, 'Resolved')

    def test_invalid_alias_does_not_load_api(self):
        for alias in ('', ' ', '../Ethernet', 'Ethernet\\3', 'Ethernet\n3', 'x'*65,
                      None, 7, True, 'Ethernet/3'):
            with self.subTest(alias=alias):
                result = m.resolve_adapter(alias, loader=lambda _: self.fail('API must not load'))
                self.assertEqual(result.classification, 'Unavailable')

    def test_alias_conversion_failure(self):
        fake = FakeDLL(alias_status=5)
        result = m.resolve_adapter('Ethernet 3', loader=lambda _: fake)
        self.assertEqual(result.classification, 'Unavailable')
        self.assertFalse(fake.ConvertInterfaceLuidToIndex.calls)

    def test_zero_luid_refused(self):
        self.assertEqual(m.resolve_adapter('Ethernet 3', loader=lambda _: FakeDLL(luid=0)).classification,
                         'Unavailable')

    def test_index_conversion_failure(self):
        fake = FakeDLL(index_status=87)
        self.assertEqual(m.resolve_adapter('Ethernet 3', loader=lambda _: fake).classification,
                         'Unavailable')
        self.assertFalse(fake.ConvertInterfaceLuidToAlias.calls)

    def test_invalid_interface_index(self):
        for index in (0, 0xFFFFFFFF):
            with self.subTest(index=index):
                self.assertEqual(m.resolve_adapter('Ethernet 3', loader=lambda _: FakeDLL(index=index)).classification,
                                 'Unavailable')

    def test_reverse_conversion_failure(self):
        self.assertEqual(m.resolve_adapter('Ethernet 3', loader=lambda _: FakeDLL(reverse_status=5)).classification,
                         'Unavailable')

    def test_wrong_reverse_alias_refused(self):
        self.assertEqual(m.resolve_adapter('Ethernet 3', loader=lambda _: FakeDLL(reverse_alias='Ethernet 2')).classification,
                         'Unavailable')

    def test_loader_denied_is_unavailable_and_no_raw_error(self):
        def denied(_):
            raise PermissionError('raw path /secret/never-reveal')
        report = m.resolve_adapter('Ethernet 3', loader=denied)
        self.assertEqual(report.classification, 'Unavailable')
        self.assertNotIn('secret', str(report))

    def test_missing_native_entrypoint_is_unavailable(self):
        class Missing:
            pass
        self.assertEqual(m.resolve_adapter('Ethernet 3', loader=lambda _: Missing()).classification,
                         'Unavailable')

    def test_output_only_contains_minimal_evidence(self):
        report = m.resolve_adapter('Ethernet 3', loader=lambda _: FakeDLL())
        self.assertEqual(set(vars(report)), {'classification', 'reason', 'interface_index'})
        self.assertEqual(report.reason, 'AdapterAliasIndexVerified')

    def test_class_invariants(self):
        with self.assertRaises(ValueError):
            m.AdapterIdentity('Resolved', 'test', None)
        with self.assertRaises(ValueError):
            m.AdapterIdentity('Unavailable', 'test', 7)
        with self.assertRaises(ValueError):
            m.AdapterIdentity('ExpectedRoute', 'test', 7)

    def test_no_api_on_import_or_inert_cli(self):
        with patch.object(m, '_lookup_alias', side_effect=AssertionError('native call')):
            self.assertEqual(m.main(['--check-inert']), 0)
        cmd = [sys.executable, '-I', '-B',
               str(ROOT / 'windows/monitoring/v080/OnyxNativeAdapterIdentity.py'), '--check-inert']
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(json.loads(p.stdout)['gateway_address_verified'])

    def test_cli_live_refused(self):
        cmd = [sys.executable, '-I', '-B',
               str(ROOT / 'windows/monitoring/v080/OnyxNativeAdapterIdentity.py'), '--live-read-only']
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertNotIn('iphlpapi', p.stdout)

    def test_native_query_on_non_windows_without_injection_refused(self):
        if sys.platform == 'win32':
            self.skipTest('Only a cross-platform non-Windows guard test')
        else:
            self.assertEqual(m.resolve_adapter('Ethernet 3').classification, 'Unavailable')


if __name__ == '__main__':
    unittest.main()
