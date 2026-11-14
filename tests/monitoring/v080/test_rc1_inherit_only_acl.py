"""RC1 inherit-only native ACE regression: pure, no native Windows operations."""
from __future__ import annotations
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'windows' / 'monitoring' / 'v080'))
import OnyxWindowsProtectedInstallTrust as checker

ADMIN = 'S-1-5-32-544'
SYSTEM = 'S-1-5-18'
CREATOR_OWNER = 'S-1-3-0'
USER = 'S-1-5-32-545'


class InheritOnlyAceTests(unittest.TestCase):
    def owner_acl(self, *rules):
        return checker.reject_ace(ADMIN, tuple(rules))

    def test_creator_owner_inherit_only_generic_all_is_not_effective_here(self):
        self.owner_acl((0, CREATOR_OWNER, 0x10000000, 0x0b),
                       (0, SYSTEM, 0x1f01ff, 0),
                       (0, USER, 0x1200a9, 0x10))

    def test_generic_all_on_user_inherit_only_is_not_effective_here(self):
        self.owner_acl((0, USER, 0x10000000, 0x0b))

    def test_inherited_but_effective_nonprivileged_write_denied(self):
        with self.assertRaisesRegex(checker.InstallTrustRefused, 'write'):
            self.owner_acl((0, USER, 0x10000000, 0x10))

    def test_noninherited_effective_nonprivileged_write_denied(self):
        with self.assertRaisesRegex(checker.InstallTrustRefused, 'write'):
            self.owner_acl((0, USER, 0x2, 0x03))

    def test_no_propagate_inherit_still_effective(self):
        with self.assertRaisesRegex(checker.InstallTrustRefused, 'write'):
            self.owner_acl((0, USER, 0x40000000, 0x07))

    def test_child_ace_gets_its_own_effective_check(self):
        # Inherit-only rule on parent is safe ONLY if children are inspected.
        parent = lambda _path: (ADMIN, ((0, CREATOR_OWNER, 0x10000000, 0x0b),))
        child = lambda _path: (ADMIN, ((0, USER, 0x10000000, 0x10),))
        checker.assert_protected_path(Path(r'C:\parent'), read_acl=parent)
        with self.assertRaisesRegex(checker.InstallTrustRefused, 'write'):
            checker.assert_protected_path(Path(r'C:\parent\child'), read_acl=child)

    def test_trusted_owner_requirement_not_bypassed(self):
        with self.assertRaisesRegex(checker.InstallTrustRefused, 'owner'):
            checker.reject_ace(USER, ((0, CREATOR_OWNER, 0x10000000, 0x0b),))

    def test_unsupported_ace_type_not_ignored(self):
        with self.assertRaises(checker.InstallTrustRefused):
            self.owner_acl((5, CREATOR_OWNER, 0x10000000, 0x0b))

    def test_unknown_flags_not_ignored(self):
        with self.assertRaises(checker.InstallTrustRefused):
            self.owner_acl((0, CREATOR_OWNER, 0x10000000, 0x4b))

    def test_inherit_only_without_inherit_target_rejected(self):
        with self.assertRaises(checker.InstallTrustRefused):
            self.owner_acl((0, CREATOR_OWNER, 0x10000000, 0x08))

    def test_inherit_only_with_object_target_valid(self):
        self.owner_acl((0, CREATOR_OWNER, 0x10000000, 0x09))

    def test_inherit_only_with_container_target_valid(self):
        self.owner_acl((0, CREATOR_OWNER, 0x10000000, 0x0a))

    def test_legacy_three_tuple_is_effective(self):
        with self.assertRaisesRegex(checker.InstallTrustRefused, 'write'):
            self.owner_acl((0, USER, 0x2))

    def test_malformed_ace_lengths_fail_closed(self):
        for rule in ((0, USER), (0, USER, 2, 0, 0), [0, USER, 2, 0]):
            with self.subTest(rule=rule), self.assertRaises(checker.InstallTrustRefused):
                self.owner_acl(rule)

    def test_noninteger_flags_and_mask_fail_closed(self):
        for rule in ((0, USER, 2, '0'), (0, USER, True, 0),
                     (True, USER, 2, 0), (0, USER, 2, True)):
            with self.subTest(rule=rule), self.assertRaises(checker.InstallTrustRefused):
                self.owner_acl(rule)

    def test_unknown_write_mask_still_fails(self):
        for mask in (0x2,0x4,0x10,0x40,0x100,0x10000,0x40000,0x80000,0x40000000,0x10000000):
            with self.subTest(mask=mask), self.assertRaises(checker.InstallTrustRefused):
                self.owner_acl((0, USER, mask, 0))

    def test_native_header_decoder_preserves_inherit_only_flags(self):
        header = bytes((0, 0x0b, 20, 0)) + (0x10000000).to_bytes(4, 'little')
        self.assertEqual(checker._decode_basic_ace_header(header), (0, 0x10000000, 0x0b))

    def test_native_header_decoder_rejects_malformed_records(self):
        for value in (b'', b'\0' * 7, bytes((5, 0x0b, 20, 0)) + b'\0'*4,
                      bytes((0, 0x0b, 4, 0)) + b'\0'*4):
            with self.subTest(value=value), self.assertRaises(checker.InstallTrustRefused):
                checker._decode_basic_ace_header(value)

    def test_empty_acl_still_fails_closed(self):
        with self.assertRaises(checker.InstallTrustRefused):
            checker.reject_ace(ADMIN, ())

    def test_native_reader_is_not_called_during_pure_tests(self):
        with patch.object(checker, '_handle_acl', side_effect=AssertionError('native call')):
            self.owner_acl((0, CREATOR_OWNER, 0x10000000, 0x0b))


if __name__ == '__main__':
    unittest.main()
