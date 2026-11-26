"""M1-S5: synthetic offline acceptance for interface-scoped USB subnet selection."""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'tools' / 'installation' / 'pi' / 'onyx_v100_usb_binding.py'
spec = importlib.util.spec_from_file_location('onyx_v100_usb_binding', SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def ip_json(*addresses, interface='usb0'):
    return json.dumps([{'ifname': interface, 'addr_info': [
        {'family': 'inet', 'local': ip} for ip in addresses
    ]}])


class UsbBindingTests(unittest.TestCase):
    def test_native_dual_address_selects_only_configured_subnet(self):
        raw = ip_json('192.168.137.167', '10.12.194.1')
        self.assertEqual(module.selected_ipv4_from_json(raw, 'usb0', '192.168.137.0/24'),
                         '192.168.137.167')
        self.assertEqual(module.selected_ipv4_from_json(raw, 'usb0', '10.12.194.0/28'),
                         '10.12.194.1')

    def test_address_selection_does_not_depend_on_ip_order(self):
        raw = ip_json('10.12.194.1', '192.168.137.167')
        self.assertEqual(module.selected_ipv4_from_json(raw, 'usb0', '192.168.137.0/24'),
                         '192.168.137.167')

    def test_extra_address_in_same_subnet_refused(self):
        with self.assertRaises(module.UsbBindRefused):
            module.selected_ipv4_from_json(ip_json('192.168.137.167', '192.168.137.168'),
                                           'usb0', '192.168.137.0/24')

    def test_duplicate_same_address_does_not_create_ambiguity(self):
        self.assertEqual(module.selected_ipv4_from_json(ip_json('192.168.137.167', '192.168.137.167'),
                         'usb0', '192.168.137.0/24'), '192.168.137.167')

    def test_missing_address_refused(self):
        with self.assertRaises(module.UsbBindRefused):
            module.selected_ipv4_from_json(ip_json('10.12.194.1'), 'usb0', '192.168.137.0/24')

    def test_other_interface_not_used(self):
        with self.assertRaises(module.UsbBindRefused):
            module.selected_ipv4_from_json(ip_json('192.168.137.167', interface='eth0'),
                                           'usb0', '192.168.137.0/24')

    def test_duplicate_interface_inventory_refused(self):
        raw = json.dumps([{'ifname': 'usb0', 'addr_info': []},
                          {'ifname': 'usb0', 'addr_info': []}])
        with self.assertRaises(module.UsbBindRefused):
            module.selected_ipv4_from_json(raw, 'usb0', '192.168.137.0/24')

    def test_other_private_subnet_accepted(self):
        self.assertEqual(module.selected_ipv4_from_json(ip_json('172.20.7.14'),
                         'usb0', '172.20.7.0/24'), '172.20.7.14')

    def test_public_or_oversized_subnet_refused(self):
        for subnet in ('8.8.8.0/24', '127.0.0.0/24', '0.0.0.0/0',
                       '192.168.137.167/24', '192.168.137.0/31',
                       '192.168.137.0/32', '192.168.137.0/15', '192.0.0.0/24'):
            with self.subTest(subnet=subnet), self.assertRaises(module.UsbBindRefused):
                module.selected_ipv4_from_json(ip_json('192.168.137.167'), 'usb0', subnet)

    def test_reject_network_and_broadcast(self):
        for address in ('192.168.137.0', '192.168.137.255'):
            with self.subTest(address=address), self.assertRaises(module.UsbBindRefused):
                module.selected_ipv4_from_json(ip_json(address), 'usb0', '192.168.137.0/24')

    def test_wrong_type_or_invalid_json_refused(self):
        for bad in ('{}', '{oops', 'null', 1, None, '', b'\xff'):
            with self.subTest(bad=bad), self.assertRaises(module.UsbBindRefused):
                module.selected_ipv4_from_json(bad, 'usb0', '192.168.137.0/24')

    def test_malformed_address_refused_even_if_another_address_good(self):
        with self.assertRaises(module.UsbBindRefused):
            module.selected_ipv4_from_json(ip_json('192.168.137.167', 'BROKEN'),
                                           'usb0', '192.168.137.0/24')

    def test_json_with_inet6_records_ignored(self):
        raw = json.dumps([{'ifname': 'usb0', 'addr_info': [
            {'family': 'inet6', 'local': 'fe80::1'},
            {'family': 'inet', 'local': '192.168.137.167'}]}])
        self.assertEqual(module.selected_ipv4_from_json(raw, 'usb0', '192.168.137.0/24'),
                         '192.168.137.167')

    def test_selector_has_no_runtime_side_effects(self):
        source = SOURCE.read_text(encoding='utf-8')
        for forbidden in ('subprocess', 'os.system', 'systemctl', 'socket.',
                          'requests.', 'urllib.request', 'open(', '.write_'):
            self.assertNotIn(forbidden, source)


if __name__ == '__main__':
    unittest.main(verbosity=2)
