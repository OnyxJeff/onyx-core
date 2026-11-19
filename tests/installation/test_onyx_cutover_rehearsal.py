#!/usr/bin/env python3
"""Focused offline tests for Pi state transitions and Windows safety contract."""
from __future__ import annotations
from contextlib import ExitStack, redirect_stdout
import importlib.util
import io
import os
import json
from pathlib import Path
import shutil
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]
PI = ROOT / 'tools/installation/pi/onyx_pi_rehearsal.py'
WIN = ROOT / 'tools/installation/windows/Invoke-OnyxV090Rehearsal.ps1'
SHA = 'a' * 40

spec = importlib.util.spec_from_file_location('pi_rehearsal', PI)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class FakeServiceHost:
    def __init__(self):
        self.legacy_active = True
        self.legacy_enabled = True
        self.candidate_active = False
        self.candidate_enabled = False
        self.block_legacy = True
        self.fail_candidate_start = False
        self.trace = []

    def get(self, unit, key):
        legacy = unit == mod.LEGACY
        if key == 'ActiveState':
            return ('active' if self.legacy_active else 'inactive') if legacy else ('active' if self.candidate_active else 'inactive')
        if key == 'UnitFileState':
            return ('enabled' if self.legacy_enabled else 'disabled') if legacy else ('enabled' if self.candidate_enabled else 'disabled')
        if key == 'LoadState':
            return 'loaded' if legacy or mod.CANDIDATE_FILE.exists() else 'not-found'
        raise ValueError(key)

    def sockets(self):
        if self.candidate_active:
            return ['192.168.137.167:8765']
        if self.legacy_active:
            return ['192.168.137.167:8765']
        return []

    def run(self, *argv, check=True):
        self.trace.append(tuple(argv))
        if argv[0] != 'systemctl':
            raise ValueError('Unexpected process command')
        action = argv[1]
        if action == 'daemon-reload':
            return types.SimpleNamespace(stdout='', returncode=0)
        unit = argv[2]
        legacy = unit == mod.LEGACY
        if action == 'disable':
            if legacy: self.legacy_enabled = False
            else: self.candidate_enabled = False
        elif action == 'enable':
            if legacy: self.legacy_enabled = True
            else: self.candidate_enabled = True
        elif action == 'stop':
            if legacy: self.legacy_active = False
            else: self.candidate_active = False
        elif action == 'start':
            if legacy:
                if not ((mod.DROPIN.is_file() or mod.PERSISTENT_GUARD.is_file()) and self.block_legacy):
                    self.legacy_active = True
            else:
                if self.fail_candidate_start:
                    if check: raise mod.Refused('Synthetic candidate start failed')
                else:
                    self.candidate_active = True
        else:
            raise ValueError(action)
        return types.SimpleNamespace(stdout='', returncode=0)


@unittest.skipUnless(os.name == 'posix', 'Pi synthetic POSIX filesystem behavior tested on Linux CI')
class PiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        sandbox = base / 'root'
        backup = sandbox / 'backups'
        backup.mkdir(parents=True)
        dispatcher = sandbox / 'dispatcher'
        dispatcher.mkdir()
        (dispatcher / '99-old-onyx').write_bytes(b'#!/bin/sh\nsystemctl restart onyxcore-receiver.service\n')
        legacy = sandbox / 'units/onyxcore-receiver.service'
        legacy.parent.mkdir()
        legacy.write_bytes(b'[Service]\nExecStart=/opt/onyxcore/launch-receiver.sh\n')
        candidate = sandbox / 'units/onyxcore-v090-receiver.service'
        source = sandbox / 'versioned/onyxcore-v090-receiver.service'
        source.parent.mkdir()
        source.write_bytes(b'[Service]\nExecStart=/opt/onyxcore/v0.9.0/launch.sh\n')
        root = sandbox / 'versioned'
        planner = root / 'onyx_runtime_plan.py'
        planner.write_text('pass')
        guard = sandbox / 'runtime/onyxcore-receiver.service.d/90-v090-block-legacy.conf'
        persistent = sandbox / 'persistent/onyxcore-receiver.service.d/90-v090-block-legacy.conf'
        marker = sandbox / 'persistent/v090-legacy-receiver-allow'
        self.host = FakeServiceHost()
        self.boot_id = 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa'
        patches = [
            patch.object(mod, 'LEGACY_FILE', legacy),
            patch.object(mod, 'CANDIDATE_FILE', candidate),
            patch.object(mod, 'ROOT', root),
            patch.object(mod, 'CANDIDATE_SOURCE', source),
            patch.object(mod, 'PLANNER', planner),
            patch.object(mod, 'DISPATCHER_ROOT', dispatcher),
            patch.object(mod, 'BACKUP_PARENT', backup),
            patch.object(mod, 'ESCROW', backup / 'v090-rehearsal'),
            patch.object(mod, 'JOURNAL', backup / 'v090-rehearsal/state.json'),
            patch.object(mod, 'DROPIN_DIR', guard.parent),
            patch.object(mod, 'DROPIN', guard),
            patch.object(mod, 'PERSISTENT_DIR', persistent.parent),
            patch.object(mod, 'PERSISTENT_GUARD', persistent),
            patch.object(mod, 'PERSISTENT_MARKER', marker),
            patch.object(mod, 'unit_property', self.host.get),
            patch.object(mod, 'listeners', self.host.sockets),
            patch.object(mod, 'run', self.host.run),
            patch.object(mod, 'check_private_parent', lambda: None),
            patch.object(mod, 'check_runtime_prerequisites', lambda: None),
            patch.object(mod, 'verify_install', lambda commit: None),
            patch.object(mod, 'read_boot_id', lambda: self.boot_id),
            patch.object(mod.platform, 'machine', lambda: 'armv6l'),
            patch.object(mod.os, 'geteuid', lambda: 0),
        ]
        self.stack = ExitStack()
        for p in patches: self.stack.enter_context(p)
        self.addCleanup(self.stack.close)
        # A real SQLite path is never accessed by the orchestration module.
        self.telemetry = sandbox / 'telemetry.db'
        self.telemetry.write_bytes(b'PRESERVE EXISTING TELEMETRY BYTES')
        self.snapshot = sandbox / 'latest-snapshot.json'
        self.snapshot.write_bytes(b'{"telemetry":"existing"}')
        self.dispatcher_root = dispatcher

    def advance(self):
        with redirect_stdout(io.StringIO()):
            mod.escrow(SHA)
            mod.quiesce(SHA)
            mod.activate(SHA)

    def test_reversible_non_autostart_and_data_preserving(self):
        before = self.telemetry.read_bytes(), self.snapshot.read_bytes()
        self.advance()
        self.assertFalse(self.host.legacy_active)
        self.assertTrue(self.host.candidate_active)
        self.assertFalse(self.host.candidate_enabled)
        self.assertEqual(json.loads(mod.JOURNAL.read_bytes())['phase'], 'candidate-running-rehearsal')
        with redirect_stdout(io.StringIO()):
            mod.rollback(SHA)
        self.assertTrue(self.host.legacy_active)
        self.assertTrue(self.host.legacy_enabled)
        self.assertFalse(self.host.candidate_active)
        self.assertEqual(before, (self.telemetry.read_bytes(), self.snapshot.read_bytes()))
        self.assertEqual(json.loads(mod.JOURNAL.read_bytes())['phase'], 'rolled-back')
        self.assertFalse(mod.DROPIN.exists())
        self.assertFalse(any(cmd[1] == 'enable' and cmd[2] == mod.CANDIDATE for cmd in self.host.trace))

    def test_refuses_restart_guard_failure_before_candidate_start(self):
        with redirect_stdout(io.StringIO()):
            mod.escrow(SHA)
        self.host.block_legacy = False
        with self.assertRaisesRegex(mod.Refused, 'did not block legacy restart'):
            mod.quiesce(SHA)
        self.assertFalse(self.host.candidate_active)
        self.assertFalse(mod.CANDIDATE_FILE.exists())

    def test_refuses_second_escrow_and_wrong_order(self):
        with self.assertRaisesRegex(mod.Refused, 'Escrow state missing'):
            mod.activate(SHA)
        with redirect_stdout(io.StringIO()):
            mod.escrow(SHA)
        with self.assertRaisesRegex(mod.Refused, 'already exists'):
            mod.escrow(SHA)

    def test_activation_failure_allows_rollback_without_database_restore(self):
        with redirect_stdout(io.StringIO()):
            mod.escrow(SHA)
            mod.quiesce(SHA)
        self.host.fail_candidate_start = True
        with self.assertRaisesRegex(mod.Refused, 'Synthetic candidate start failed'):
            mod.activate(SHA)
        self.assertEqual(json.loads(mod.JOURNAL.read_bytes())['phase'], 'candidate-unit-registered')
        with redirect_stdout(io.StringIO()):
            mod.rollback(SHA)
        self.assertTrue(self.host.legacy_active)
        self.assertFalse(self.host.candidate_active)

    def test_boot_promotion_is_persistent_and_rollback_preserves_history(self):
        before = self.telemetry.read_bytes(), self.snapshot.read_bytes()
        self.advance()
        with redirect_stdout(io.StringIO()):
            mod.promote_boot(SHA)
        self.assertEqual(mod.PERSISTENT_GUARD.read_bytes(), mod.PERSISTENT_BYTES)
        self.assertFalse(self.host.legacy_enabled)
        self.assertTrue(self.host.candidate_enabled)
        self.assertEqual(json.loads(mod.JOURNAL.read_bytes())['phase'], 'candidate-boot-configured')
        # Simulate a reboot: /run transient condition disappears, persisted one remains.
        mod.DROPIN.unlink()
        self.host.candidate_active = False
        self.host.legacy_active = False
        self.host.run('systemctl', 'start', mod.LEGACY, check=False)
        self.assertFalse(self.host.legacy_active)
        self.host.run('systemctl', 'start', mod.CANDIDATE)
        self.boot_id = 'bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb'
        with redirect_stdout(io.StringIO()) as out:
            mod.audit_boot(SHA)
        self.assertTrue(json.loads(out.getvalue())['reboot_observed'])
        self.assertTrue(self.host.candidate_active)
        self.assertFalse(self.host.legacy_active)
        with redirect_stdout(io.StringIO()):
            mod.rollback(SHA)
        self.assertTrue(self.host.legacy_active)
        self.assertTrue(self.host.legacy_enabled)
        self.assertFalse(self.host.candidate_active)
        self.assertFalse(self.host.candidate_enabled)
        self.assertFalse(mod.PERSISTENT_GUARD.exists())
        self.assertEqual(before, (self.telemetry.read_bytes(), self.snapshot.read_bytes()))

    def test_postboot_audit_reports_pending_before_reboot(self):
        self.advance()
        with redirect_stdout(io.StringIO()):
            mod.promote_boot(SHA)
        with redirect_stdout(io.StringIO()) as out:
            mod.audit_boot(SHA)
        self.assertFalse(json.loads(out.getvalue())['reboot_observed'])
        self.assertFalse(json.loads(out.getvalue())['writes'])

    def test_promotion_refuses_guard_failure_and_rollback_still_available(self):
        self.advance()
        self.host.block_legacy = False
        with self.assertRaisesRegex(mod.Refused, 'Persistent legacy exclusion did not hold'):
            mod.promote_boot(SHA)
        self.assertEqual(json.loads(mod.JOURNAL.read_bytes())['phase'], 'boot-promoting')
        self.assertFalse(self.host.candidate_enabled)
        # Restore guarded behavior and rollback; no DB restore.
        self.host.block_legacy = True
        with redirect_stdout(io.StringIO()):
            mod.rollback(SHA)
        self.assertTrue(self.host.legacy_active)
        self.assertFalse(self.host.candidate_active)

    def test_persistent_guard_tamper_refuses_rollback(self):
        self.advance()
        with redirect_stdout(io.StringIO()):
            mod.promote_boot(SHA)
        mod.PERSISTENT_GUARD.write_bytes(b'[Unit]\nOtherPolicy=bad\n')
        with self.assertRaisesRegex(mod.Refused, 'Persistent guard changed'):
            mod.rollback(SHA)
        self.assertFalse(self.host.legacy_active)
        self.assertFalse(self.host.candidate_enabled)

    def test_new_dispatcher_entry_after_escrow_refused(self):
        with redirect_stdout(io.StringIO()):
            mod.escrow(SHA)
        (self.dispatcher_root / '99-rogue').write_bytes(b'systemctl restart onyxcore-receiver.service\n')
        with self.assertRaisesRegex(mod.Refused, 'dispatcher inventory drifted'):
            mod.quiesce(SHA)
        self.assertTrue(self.host.legacy_active)

    def test_preview_rejects_live_approval(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(mod.main(['--phase','preview']), 0)
        with patch('sys.stderr', io.StringIO()):
            self.assertEqual(mod.main(['--phase','quiesce','--expected-commit',SHA]), 2)
            self.assertEqual(mod.main(['--phase','preview','--approve-live-pi-changes']), 2)
        self.assertTrue(self.host.legacy_active)
        self.assertFalse(mod.ESCROW.exists())


class WindowsSourceTest(unittest.TestCase):
    def test_windows_trigger_collections_filter_null_across_all_gates(self):
        source = WIN.read_text(encoding='utf-8')
        self.assertIn('function Get-ActualTaskTriggers', source)
        self.assertIn('$Task.Triggers | Where-Object { $null -ne $_ }', source)
        self.assertNotIn('@($task.Triggers)', source)
        self.assertEqual(5, source.count('Get-ActualTaskTriggers $task'))

    def test_windows_hard_guards_in_source(self):
        source = WIN.read_text(encoding='utf-8')
        for literal in ('ApproveLiveWindowsChanges', 'ConfirmCandidatePiActive',
                        'ConfirmLegacyPiRestored','Export-ScheduledTask',
                        'Get-CimInstance Win32_Process', '127.0.0.1',
                        'Stop-Process -Id', 'Disable-ScheduledTask',
                        'No logon triggers', 'Start-ScheduledTask',
                        'PromoteBoot', 'PreviewBoot', 'New-ScheduledTaskTrigger -AtLogOn', 'candidate-boot-configured', 'reboot_observed'):
            self.assertIn(literal.lower(), source.lower())
        self.assertNotIn('Unregister-ScheduledTask', source)


if __name__ == '__main__':
    unittest.main(verbosity=2)
