#!/usr/bin/env python3
"""ONYX CORE v0.9.0 Pi receiver rehearsal and separately approved boot promotion.

Read-only Preview is default. Live phases require separate operator approval,
root on ARMv6, a verified inactive installed release, and a private receipt.
The initial rehearsal uses a runtime-only systemd guard. A separate optional
boot-promotion phase persists a legacy-start guard and enables the candidate
only after a successful supervised rehearsal. Live phases require separate
authorization. Rollback never restores database bytes.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import uuid
import os
try:
    import pwd
    import grp
except ImportError:  # Windows CI can import and exercise refusal paths.
    pwd = None
    grp = None
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone

LEGACY = 'onyxcore-receiver.service'
CANDIDATE = 'onyxcore-v090-receiver.service'
LEGACY_FILE = Path('/etc/systemd/system/onyxcore-receiver.service')
DISPATCHER_ROOT = Path('/etc/NetworkManager/dispatcher.d')
CANDIDATE_FILE = Path('/etc/systemd/system/onyxcore-v090-receiver.service')
ROOT = Path('/opt/onyxcore/v0.9.0')
CANDIDATE_SOURCE = ROOT / 'tools/installation/pi/onyxcore-v090-receiver.service'
PLANNER = ROOT / 'tools/installation/common/onyx_runtime_plan.py'
BACKUP_PARENT = Path('/var/backups/onyxcore')
ESCROW = BACKUP_PARENT / 'v090-rehearsal'
JOURNAL = ESCROW / 'state.json'
DROPIN_DIR = Path('/run/systemd/system/onyxcore-receiver.service.d')
DROPIN = DROPIN_DIR / '90-v090-block-legacy.conf'
DROPIN_BYTES = (b'[Unit]\n'
                b'# Temporary v0.9.0 rehearsal guard. Lost on reboot.\n'
                b'ConditionPathExists=/run/onyxcore/v090-legacy-receiver-allow\n')
PERSISTENT_DIR = Path('/etc/systemd/system/onyxcore-receiver.service.d')
PERSISTENT_GUARD = PERSISTENT_DIR / '90-v090-block-legacy.conf'
PERSISTENT_MARKER = Path('/etc/onyxcore/v090-legacy-receiver-allow')
PERSISTENT_BYTES = (b'[Unit]\n'
                    b'# v0.9.0 durable legacy-receiver exclusion (requires explicit rollback).\n'
                    b'ConditionPathExists=/etc/onyxcore/v090-legacy-receiver-allow\n')
COMMIT = re.compile(r'[a-f0-9]{40}\Z')
BIND = re.compile(r'^192\.168\.137\.(?:[2-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-4]):8765$')

class Refused(RuntimeError):
    pass


def read_boot_id():
    value = Path('/proc/sys/kernel/random/boot_id').read_text(encoding='ascii').strip()
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise Refused('Invalid kernel boot ID') from exc


def canonical(doc):
    return (json.dumps(doc, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def no_redirects(path):
    for node in (path, *path.parents):
        if node.is_symlink():
            raise Refused('redirected path refused: ' + str(node))


def run(*argv, check=True):
    r = subprocess.run(argv, text=True, capture_output=True, check=False, timeout=25)
    if check and r.returncode:
        raise Refused(f'command failed ({argv[0]} {argv[1] if len(argv)>1 else ""}), code {r.returncode}')
    return r


def unit_property(name, key):
    return run('systemctl', 'show', name, '--property', key, '--value').stdout.strip()


def state(name):
    return {'active': unit_property(name, 'ActiveState'),
            'enabled': unit_property(name, 'UnitFileState'),
            'load': unit_property(name, 'LoadState')}


def listeners():
    rows = run('ss', '-ltnH').stdout.splitlines()
    found = []
    for row in rows:
        columns = row.split()
        if len(columns) < 4:
            continue
        local = columns[3]
        if local.rsplit(':', 1)[-1] == '8765':
            found.append(local)
    return found


def assert_free():
    if listeners():
        raise Refused('Port 8765 has at least one listener. STOP.')


def assert_candidate_listening():
    found = listeners()
    if len(found) != 1 or not BIND.fullmatch(found[0]):
        raise Refused('Candidate port 8765 is not USB-only or has multiple owners. STOP.')


def assert_legacy_listening():
    found = listeners()
    if len(found) != 1 or not BIND.fullmatch(found[0]):
        raise Refused('Legacy port 8765 ownership/address changed. STOP.')


def verify_install(commit):
    if not COMMIT.fullmatch(commit):
        raise Refused('Exact frozen candidate source commit required')
    for path in (CANDIDATE_SOURCE, PLANNER):
        no_redirects(path)
        if not path.is_file():
            raise Refused('Verified inactive Pi installation missing')
    r = run('/usr/bin/python3', '-I', '-B', str(PLANNER), '--installed-root', str(ROOT),
            '--platform', 'pi-armv6', '--expected-commit', commit)
    doc = json.loads(r.stdout)
    if doc.get('operation') != 'READ_ONLY_ACTIVATION_PLAN' or doc.get('activated') is not False or doc['audit']['source_commit'] != commit:
        raise Refused('Candidate manifest, receipt, or source commit mismatch')


def check_private_parent():
    no_redirects(BACKUP_PARENT)
    if not BACKUP_PARENT.is_dir():
        raise Refused('Private root-owned backup parent must be provisioned separately')
    info = BACKUP_PARENT.stat()
    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700:
        raise Refused('Backup parent must be root-owned and mode 0700')


def get_journal(commit):
    check_private_parent()
    no_redirects(JOURNAL)
    if not JOURNAL.is_file():
        raise Refused('Escrow state missing')
    doc = json.loads(JOURNAL.read_bytes())
    if doc.get('schema') != 1 or doc.get('commit') != commit or doc.get('legacy_unit_sha256') != sha(LEGACY_FILE.read_bytes()):
        raise Refused('Escrow integrity or identity mismatch')
    return doc


def set_phase(doc, phase):
    doc['phase'] = phase
    tmp = ESCROW / 'state.json.pending'
    if tmp.exists() or tmp.is_symlink():
        raise Refused('Existing temporary state. STOP.')
    with tmp.open('xb') as output:
        output.write(canonical(doc))
        output.flush()
        os.fsync(output.fileno())
    os.chmod(tmp, 0o600)
    tmp.replace(JOURNAL)
    # Persist state transition before any next service mutation.
    directory_fd = os.open(str(ESCROW), os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def preview():
    # Neither opens the SQLite DB nor reads credentials.
    report = {'phase': 'PREVIEW_ONLY', 'architecture': platform.machine(),
              'legacy': state(LEGACY), 'candidate': state(CANDIDATE),
              'port_8765_listeners': len(listeners()),
              'legacy_unit_exists': LEGACY_FILE.is_file(),
              'private_escrow_exists': JOURNAL.is_file(), 'writes': False}
    print(canonical(report).decode('ascii').strip())


def escrow(commit):
    check_private_parent()
    if ESCROW.exists() or ESCROW.is_symlink():
        raise Refused('Escrow already exists; do not overwrite')
    no_redirects(LEGACY_FILE)
    if (not LEGACY_FILE.is_file() or CANDIDATE_FILE.exists() or DROPIN.exists()
            or PERSISTENT_GUARD.exists() or PERSISTENT_GUARD.is_symlink()
            or PERSISTENT_MARKER.exists() or PERSISTENT_MARKER.is_symlink()):
        raise Refused('Unexpected legacy/candidate/guard state')
    old = state(LEGACY)
    if old['active'] != 'active' or old['enabled'] != 'enabled':
        raise Refused('Legacy service is not active and enabled')
    assert_legacy_listening()
    # Hash dispatcher scripts; escrow hashes only, never potentially sensitive contents.
    dispatchers = dispatcher_inventory()
    ESCROW.mkdir(mode=0o700)
    (ESCROW / 'legacy-unit.service').write_bytes(LEGACY_FILE.read_bytes())
    os.chmod(ESCROW / 'legacy-unit.service', 0o600)
    doc = {'schema': 1, 'phase': 'escrowed', 'commit': commit,
           'legacy_unit_sha256': sha(LEGACY_FILE.read_bytes()),
           'original_legacy_enabled': True, 'dispatchers': dispatchers,
           'database_restored': False,
           'created_utc': datetime.now(timezone.utc).isoformat()}
    set_phase(doc, 'escrowed')
    print('PASS: original unit privately escrowed, dispatcher hashes recorded; no service changes.')


def check_runtime_prerequisites():
    # All checks are read-only and must pass BEFORE the legacy service stops.
    if pwd is None or grp is None:
        raise Refused('POSIX service identities unavailable')
    try:
        pwd.getpwnam('onyxcore')
        grp.getgrnam('onyxcore')
    except KeyError as exc:
        raise Refused('Candidate onyxcore service user/group not provisioned') from exc
    for path in (Path('/etc/onyxcore/receiver.env'),
                 Path('/var/lib/onyxcore/telemetry.db')):
        no_redirects(path)
        if not path.is_file():
            raise Refused('Required external receiver environment/database missing')
    if Path('/var/lib/onyxcore/telemetry.db').stat().st_size < 100:
        raise Refused('Existing history database suspiciously small')


def dispatcher_inventory():
    entries = []
    root = DISPATCHER_ROOT
    if root.exists():
        no_redirects(root)
        for p in sorted(root.rglob('*')):
            if p.is_file():
                no_redirects(p)
                blob = p.read_bytes()
                if b'onyxcore-receiver' in blob:
                    entries.append({'path': str(p), 'sha256': sha(blob)})
    return entries


def check_dispatchers(doc):
    if dispatcher_inventory() != doc['dispatchers']:
        raise Refused('Legacy dispatcher inventory drifted after escrow')
    # The unit guard rejects systemctl starts from audited dispatchers.
    # A dispatcher invoking receiver.py directly is not supported.


def quiesce(commit):
    doc = get_journal(commit)
    if doc['phase'] != 'escrowed':
        raise Refused('Wrong phase for quiesce')
    check_dispatchers(doc)
    check_runtime_prerequisites()
    if state(CANDIDATE)['active'] == 'active' or CANDIDATE_FILE.exists():
        raise Refused('Candidate already exists or runs')
    if state(LEGACY)['active'] != 'active':
        raise Refused('Legacy service not active')
    assert_legacy_listening()
    if Path('/run/onyxcore/v090-legacy-receiver-allow').exists():
        raise Refused('Legacy startup guard marker unexpectedly present')
    if DROPIN_DIR.exists() and DROPIN_DIR.is_symlink():
        raise Refused('Runtime drop-in directory redirected')
    DROPIN_DIR.mkdir(mode=0o755, parents=True, exist_ok=True)
    if DROPIN.exists() or DROPIN.is_symlink():
        raise Refused('Runtime guard already exists')
    # Durable state records intent BEFORE writing any new unit override.
    set_phase(doc, 'quiescing')
    DROPIN.write_bytes(DROPIN_BYTES)
    os.chmod(DROPIN, 0o644)
    run('systemctl', 'daemon-reload')
    run('systemctl', 'disable', LEGACY)
    run('systemctl', 'stop', LEGACY)
    if state(LEGACY)['active'] != 'inactive':
        raise Refused('Legacy service did not stop')
    assert_free()
    # Exercise the dispatcher-equivalent restart path. Condition must prevent it.
    run('systemctl', 'start', LEGACY, check=False)
    if state(LEGACY)['active'] != 'inactive':
        raise Refused('Temporary systemd guard did not block legacy restart')
    assert_free()
    set_phase(doc, 'legacy-quiesced')
    print('PASS: legacy service stopped, disabled and guarded at runtime; 8765 free.')


def activate(commit):
    doc = get_journal(commit)
    if doc['phase'] != 'legacy-quiesced':
        raise Refused('Wrong phase for candidate activation')
    if DROPIN.read_bytes() != DROPIN_BYTES or Path('/run/onyxcore/v090-legacy-receiver-allow').exists() or state(LEGACY)['active'] != 'inactive':
        raise Refused('Legacy runtime guard missing or service restarted')
    check_dispatchers(doc)
    assert_free()
    if CANDIDATE_FILE.exists() or CANDIDATE_FILE.is_symlink():
        raise Refused('Candidate service already registered')
    shutil.copyfile(CANDIDATE_SOURCE, CANDIDATE_FILE)
    os.chmod(CANDIDATE_FILE, 0o644)
    run('systemctl', 'daemon-reload')
    # Candidate is deliberately NOT enabled (no automatic start after reboot).
    set_phase(doc, 'candidate-unit-registered')
    run('systemctl', 'start', CANDIDATE)
    if state(CANDIDATE)['active'] != 'active' or state(CANDIDATE)['enabled'] != 'disabled':
        raise Refused('Candidate did not start in manual-only mode')
    if state(LEGACY)['active'] != 'inactive':
        raise Refused('Legacy receiver restarted concurrently')
    assert_candidate_listening()
    set_phase(doc, 'candidate-running-rehearsal')
    print('PASS: manual-only candidate receiver active on USB 8765; legacy guarded.')
    print('WARNING: this is a non-reboot-safe REHEARSAL; rollback before reboot.')



def promote_boot(commit):
    """Separate opt-in durable startup configuration; not a reboot acceptance test.

    Transition order is intentionally conservative: persist legacy exclusion
    first, verify it, and only then enable the candidate. An interrupted
    operation has a rollback path, with possible temporary downtime.
    """
    doc = get_journal(commit)
    if doc['phase'] != 'candidate-running-rehearsal':
        raise Refused('Boot promotion requires successful manual rehearsal')
    check_dispatchers(doc)
    if state(LEGACY)['active'] != 'inactive' or state(LEGACY)['enabled'] != 'disabled':
        raise Refused('Legacy is not stopped and disabled')
    if state(CANDIDATE)['active'] != 'active' or state(CANDIDATE)['enabled'] != 'disabled':
        raise Refused('Candidate must be running without boot enablement')
    if not CANDIDATE_FILE.is_file() or CANDIDATE_FILE.is_symlink() or CANDIDATE_FILE.read_bytes() != CANDIDATE_SOURCE.read_bytes():
        raise Refused('Candidate unit diverged from reviewed version')
    if DROPIN.read_bytes() != DROPIN_BYTES:
        raise Refused('Rehearsal guard missing or modified')
    for node in (PERSISTENT_DIR, PERSISTENT_GUARD, PERSISTENT_MARKER):
        no_redirects(node)
    if PERSISTENT_GUARD.exists() or PERSISTENT_MARKER.exists():
        raise Refused('Persistent legacy policy already exists')
    assert_candidate_listening()
    # Intent is journaled before the first persistent configuration mutation.
    set_phase(doc, 'boot-promoting')
    PERSISTENT_DIR.mkdir(mode=0o755, parents=True, exist_ok=True)
    with PERSISTENT_GUARD.open('xb') as stream:
        stream.write(PERSISTENT_BYTES)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(PERSISTENT_GUARD, 0o644)
    run('systemctl', 'daemon-reload')
    run('systemctl', 'start', LEGACY, check=False)
    if state(LEGACY)['active'] != 'inactive' or state(LEGACY)['enabled'] != 'disabled':
        # Abort and attempt to stop an unexpectedly restarted legacy unit.
        # Never proceed to enable candidate startup with an active legacy.
        if state(LEGACY)['active'] == 'active':
            run('systemctl', 'stop', LEGACY, check=False)
        raise Refused('Persistent legacy exclusion did not hold')
    if PERSISTENT_GUARD.read_bytes() != PERSISTENT_BYTES:
        raise Refused('Persistent guard content mismatch')
    run('systemctl', 'enable', CANDIDATE)
    if state(CANDIDATE)['active'] != 'active' or state(CANDIDATE)['enabled'] != 'enabled':
        raise Refused('Candidate not active and boot-enabled')
    if state(LEGACY)['active'] != 'inactive' or state(LEGACY)['enabled'] != 'disabled':
        raise Refused('Legacy unexpectedly active/enabled')
    assert_candidate_listening()
    doc['boot_id_at_promotion'] = read_boot_id()
    set_phase(doc, 'candidate-boot-configured')
    print('PASS: persistent legacy guard installed; candidate boot-enabled (reboot still unverified).')
    print('PENDING: actual reboot, USB renewal, authenticated telemetry, and rollback acceptance.')



def audit_boot(commit):
    # Read-only post-reboot attestation. No secrets/database opened.
    verify_install(commit)
    doc = get_journal(commit)
    if doc['phase'] != 'candidate-boot-configured':
        raise Refused('Not in promoted candidate state')
    check_dispatchers(doc)
    if not PERSISTENT_GUARD.is_file() or PERSISTENT_GUARD.is_symlink() or PERSISTENT_GUARD.read_bytes() != PERSISTENT_BYTES:
        raise Refused('Persistent legacy exclusion not intact')
    if PERSISTENT_MARKER.exists() or PERSISTENT_MARKER.is_symlink():
        raise Refused('Legacy allow marker unexpectedly exists')
    if not CANDIDATE_FILE.is_file() or CANDIDATE_FILE.is_symlink() or CANDIDATE_FILE.read_bytes() != CANDIDATE_SOURCE.read_bytes():
        raise Refused('Running candidate unit no longer matches reviewed source')
    if state(LEGACY)['active'] != 'inactive' or state(LEGACY)['enabled'] != 'disabled':
        raise Refused('Legacy receiver unexpectedly running or enabled')
    if state(CANDIDATE)['active'] != 'active' or state(CANDIDATE)['enabled'] != 'enabled':
        raise Refused('Promoted receiver is not active and boot-enabled')
    assert_candidate_listening()
    current_boot_id = read_boot_id()
    after_reboot = bool(doc.get('boot_id_at_promotion') and doc['boot_id_at_promotion'] != current_boot_id)
    if after_reboot and (DROPIN.exists() or DROPIN.is_symlink()):
        raise Refused('Transient guard unexpectedly persisted across reboot')
    print(canonical({'phase': 'POST_BOOT_READ_ONLY_AUDIT', 'legacy_excluded': True,
                     'candidate_running': True, 'candidate_enabled': True,
                     'reboot_observed': after_reboot, 'writes': False}).decode('ascii').strip())


def rollback(commit):
    doc = get_journal(commit)
    if doc['phase'] not in ('quiescing','legacy-quiesced','candidate-unit-registered','candidate-running-rehearsal','boot-promoting','candidate-boot-configured'):
        raise Refused('Not in a reversible rehearsal phase')
    check_dispatchers(doc)
    if CANDIDATE_FILE.exists():
        no_redirects(CANDIDATE_FILE)
        if CANDIDATE_FILE.read_bytes() != CANDIDATE_SOURCE.read_bytes():
            raise Refused('Candidate unit changed; refuse unsafe stop')
        # Disable startup FIRST, then stop; an interrupted rollback must not
        # reanimate the candidate after a reboot.
        run('systemctl', 'disable', CANDIDATE)
        run('systemctl', 'stop', CANDIDATE)
        if state(CANDIDATE)['active'] != 'inactive' or state(CANDIDATE)['enabled'] != 'disabled':
            raise Refused('Candidate did not fully quiesce')
    if state(LEGACY)['active'] == 'active' and doc['phase'] != 'quiescing':
        raise Refused('Both receivers might be active')
    if state(LEGACY)['active'] != 'active':
        assert_free()
    # Clear only exact known guards, never arbitrary other systemd drop-ins.
    if PERSISTENT_GUARD.exists() or PERSISTENT_GUARD.is_symlink():
        no_redirects(PERSISTENT_GUARD)
        if PERSISTENT_GUARD.read_bytes() != PERSISTENT_BYTES:
            raise Refused('Persistent guard changed; refuse blind removal')
        PERSISTENT_GUARD.unlink()
    if DROPIN.exists() or DROPIN.is_symlink():
        no_redirects(DROPIN)
        if DROPIN.read_bytes() != DROPIN_BYTES:
            raise Refused('Legacy guard modified; refuse blind removal')
        DROPIN.unlink()
    run('systemctl', 'daemon-reload')
    if doc['original_legacy_enabled']:
        run('systemctl', 'enable', LEGACY)
    run('systemctl', 'start', LEGACY)
    if state(LEGACY)['active'] != 'active' or state(CANDIDATE)['active'] == 'active':
        raise Refused('Legacy not fully restored')
    assert_legacy_listening()
    set_phase(doc, 'rolled-back')
    print('PASS: original service restored on 8765; database and snapshot untouched.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('preview','audit-boot','escrow','quiesce','activate','promote-boot','rollback'), default='preview')
    parser.add_argument('--expected-commit', default='')
    parser.add_argument('--approve-live-pi-changes', action='store_true')
    a = parser.parse_args(argv)
    try:
        if a.phase == 'preview':
            if a.approve_live_pi_changes:
                raise Refused('Approval flag invalid in preview')
            preview()
            return 0
        if a.phase == 'audit-boot':
            if a.approve_live_pi_changes or not COMMIT.fullmatch(a.expected_commit):
                raise Refused('Read-only boot audit needs frozen commit, not live approval')
            if getattr(os, 'geteuid', lambda: -1)() != 0 or platform.machine() != 'armv6l':
                raise Refused('Post-boot audit requires root on ARMv6')
            audit_boot(a.expected_commit)
            return 0
        if not a.approve_live_pi_changes:
            raise Refused('Separate operator approval required; STOP')
        if getattr(os, 'geteuid', lambda: -1)() != 0 or platform.machine() != 'armv6l':
            raise Refused('Live operations require root on original ARMv6 Pi')
        verify_install(a.expected_commit)
        fn = {'escrow': escrow, 'quiesce': quiesce, 'activate': activate, 'promote-boot': promote_boot, 'rollback': rollback}[a.phase]
        fn(a.expected_commit)
        return 0
    except (OSError, ValueError, Refused, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        print('STOP: ' + str(exc), file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
