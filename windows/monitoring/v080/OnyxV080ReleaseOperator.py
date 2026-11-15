#!/usr/bin/env python3
"""ONYX CORE v0.8.0: explicit, foreground-only release operator commands.

Requires an administrator-pinned, read-only installed source tree and an
independent admin-owned approval digest. No services/tasks, auto repairs,
background monitor, notifications or privileged changes. Default CLI inert.

Use only from C:\\Program Files\\OnyxCore\\v0.8.0 with C:\\Python313\\python.exe
in isolated -I -B mode after separately reviewed protected installation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import ntpath
import os
from pathlib import Path
import sys
import time
import uuid

INSTALL_ROOT = Path(r'C:\Program Files\OnyxCore\v0.8.0')
INSTALL_ANCHOR = Path(r'C:\Program Files\OnyxCore\v0.8.0-release.sha256')
APPROVAL = INSTALL_ROOT / 'release-approval.json'
PYTHON = Path(r'C:\Python313\python.exe')
STORAGE_PROFILE_ENV = 'ONYXCORE_V080_STORAGE_PROFILE'
MAX_ENROLL_MINUTES = 1440
MAX_CYCLES = 20
MAX_SESSION_MINUTES = 60


class OperatorRefused(RuntimeError):
    pass


def canonical_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def make_read_only_grant(*, sid: str, commit: str, config_digest: str,
                         now: datetime, minutes: int) -> bytes:
    """Pure bounded user-consent request. No Windows writes here."""
    if (type(minutes) is not int or not 1 <= minutes <= MAX_ENROLL_MINUTES
            or not isinstance(now, datetime) or now.tzinfo is None):
        raise OperatorRefused('invalid bounded enrollment')
    start = now.astimezone(timezone.utc).replace(microsecond=0)
    end = start + timedelta(minutes=minutes)
    doc = dict(
        schema_version=1, grant_id=uuid.uuid4().hex, sid=sid,
        source_commit=commit, config_sha256=config_digest,
        scope='periodic_read_only_usb_ics', issued_utc=start.strftime('%Y-%m-%dT%H:%M:%SZ'),
        expires_utc=end.strftime('%Y-%m-%dT%H:%M:%SZ'), read_only=True,
        repair_action='None', storage_profile='release',
        session_policy='LoggedOnUserOnly', notifications_enabled=False,
    )
    return canonical_json(doc)


def require_installed_interpreter(module_file: Path, executable: str, *, isolated: bool, no_bytecode: bool):
    """No user-controlled install root, interpreter, or execution environment."""
    try:
        root = module_file.absolute().parents[3]
    except IndexError as exc:
        raise OperatorRefused('operator must execute from protected release tree') from exc
    if ntpath.normcase(str(root)) != ntpath.normcase(str(INSTALL_ROOT)):
        raise OperatorRefused('operator must execute from protected release tree')
    if ntpath.normcase(ntpath.normpath(executable)) != ntpath.normcase(str(PYTHON)):
        raise OperatorRefused('unapproved Python interpreter')
    if isolated is not True or no_bytecode is not True:
        raise OperatorRefused('isolated Python -I -B required')
    return root


def read_admin_pinned_digest(anchor: Path) -> str:
    """Anchor is safe ONLY after native protected-filesystem ACL verification."""
    try:
        raw = anchor.read_bytes()
    except OSError as exc:
        raise OperatorRefused('administrator-pinned approval digest unavailable') from exc
    if len(raw) != 65 or raw[-1:] != b'\n' or any(x not in b'0123456789abcdef' for x in raw[:64]):
        raise OperatorRefused('invalid protected approval digest anchor')
    return raw[:64].decode('ascii')


def _bootstrap():
    """Imports happen only after checking the fixed installed script location."""
    root = require_installed_interpreter(Path(__file__), sys.executable,
                                         isolated=bool(sys.flags.isolated),
                                         no_bytecode=bool(sys.dont_write_bytecode))
    runtime = root / 'windows' / 'monitoring' / 'v080'
    sys.path.insert(0, str(runtime))
    import OnyxWindowsProtectedInstallTrust as trust
    import OnyxWindowsRuntimeAttestation as att
    import OnyxV080ProtectedLaunch as launch
    import OnyxWindowsNativeAdmission as native
    import OnyxWindowsUserConsent as consent
    import OnyxV080ReleaseBinding as binding
    # The Win32 checker uses opened handles to inspect reparse/owner/DACL.
    trust.assert_trusted_install(root, att.REQUIRED_FILES)
    pinned_digest = read_admin_pinned_digest(INSTALL_ANCHOR)
    try:
        raw = APPROVAL.read_bytes()
    except OSError as exc:
        raise OperatorRefused('protected approved policy unavailable') from exc

    def checked_source(*, root, manifest, config):
        trust.assert_trusted_install(root, att.REQUIRED_FILES)
        att.attest_source(root=root, manifest=manifest, config=config)

    reviewed = launch.prepare_reviewed_install(root, raw,
                                               pinned_sha256=pinned_digest,
                                               attest_source=checked_source)
    context = att.verified_consent_context(
        root=root, manifest=reviewed.wiring.manifest,
        config=reviewed.wiring.config_path, expected_sid=reviewed.wiring.approved_sid,
        source_checker=checked_source,
    )
    return reviewed, context, att, consent, binding, checked_source


def _run_protected_session(*, reviewed, context, att, binding, checker,
                           cycles: int, duration_minutes: int,
                           integration=None, supervision=None,
                           clock=time.monotonic, sleep=time.sleep):
    """R6 foreground supervision behind the existing protected operator gate.

    Inputs from the real CLI come solely from _bootstrap's independently
    pinned installation, SID and native handle-backed source admission. Tests
    inject fakes; these injected entrypoints are NOT independent authority.
    """
    if (type(cycles) is not int or not 1 <= cycles <= MAX_CYCLES):
        raise OperatorRefused('invalid bounded foreground session cycle count')
    if (type(duration_minutes) is not int or not 1 <= duration_minutes <= MAX_SESSION_MINUTES):
        raise OperatorRefused('invalid bounded foreground session duration')
    if integration is None:
        import OnyxV080SessionIntegration as integration
    if supervision is None:
        import OnyxV080SessionSupervisor as supervision
    wiring = type(reviewed.wiring)(
        reviewed.wiring.source_root, reviewed.wiring.config_path,
        reviewed.wiring.manifest, reviewed.wiring.approved_sid, cycles=1)
    config = binding.read_reviewed_release_config(wiring)
    policy = supervision.SessionPolicy(
        maximum_cycles=cycles,
        maximum_duration_seconds=duration_minutes * 60,
        interval_seconds=config['monitoring_interval_seconds'])
    # Each call checks the real, unexpired Windows Generic Credential, fresh
    # process SID, active-console identity and pinned source via the same native
    # checker required by the existing one-cycle release operator.
    def fresh_consent():
        return att.build_rechecking_authorizer(
            root=wiring.source_root, manifest=wiring.manifest,
            config=wiring.config_path, approved_sid=wiring.approved_sid,
            source_checker=checker)() is True
    def fresh_session():
        return att._native_active_console() is True
    def fresh_source():
        checker(root=wiring.source_root, manifest=wiring.manifest,
                config=wiring.config_path)
        return True
    def one_cycle(one):
        def real_authorizer(**kwargs):
            return att.build_rechecking_authorizer(**kwargs, source_checker=checker)
        return binding.run_explicitly_approved_api(
            one, build_authorizer=real_authorizer)
    outcome = integration.run_reviewed_session(
        wiring=wiring, policy=policy,
        authorize=fresh_consent, active_console=fresh_session,
        attest_source=fresh_source, run_release_cycle=one_cycle,
        clock=clock, sleep=sleep)
    if outcome.state not in ('Completed', 'Expired'):
        raise OperatorRefused('foreground session terminated unexpectedly')
    return {'result': 'PASS' if outcome.state == 'Completed' else 'EXPIRED',
            'mode': 'bounded-foreground-session',
            'session_state': outcome.state, 'attempts': outcome.attempts,
            'cycles': outcome.completed_cycles,
            'persisted_cycles': outcome.persisted_cycles,
            'notifications_sent': False, 'repairs_invoked': False,
            'tasks_created': False}


def _operator_action(args, *, loader=_bootstrap):
    """No OS side effect until the protected-source gate passes."""
    if args.audit_installed:
        reviewed, ctx, *_rest = loader()
        return {'result':'PASS','mode':'audit-only', 'verified_sources':reviewed.file_count,
                'source_commit':reviewed.wiring.manifest.source_commit,
                'operator_session': 'active-local-console'}

    if args.revoke_read_only:
        if not args.approve_revocation:
            raise OperatorRefused('explicit revocation approval required')
        _reviewed, _ctx, _att, consent, _binding, _checker = loader()
        consent.delete_windows_grant()
        return {'result': 'PASS', 'mode':'revoked', 'live_monitor_started':False}

    if args.enroll_read_only and not args.approve_enrollment:
        raise OperatorRefused('explicit enrollment approval required')
    if args.run_count is not None and not args.approve_live_read_only:
        raise OperatorRefused('explicit live read-only approval required')
    session_count = getattr(args, 'run_session_count', None)
    if session_count is not None and not getattr(args, 'approve_session_read_only', False):
        raise OperatorRefused('explicit foreground session approval required')
    reviewed, context, att, consent, binding, checker = loader()
    if args.enroll_read_only:
        grant = make_read_only_grant(
            sid=context.process_sid, commit=context.source_commit,
            config_digest=context.config_sha256, now=datetime.now(timezone.utc),
            minutes=args.expires_minutes)
        # Validate exact J1 contract before writing any credential.
        if consent.evaluate_grant(grant, context=context,
                                  now=datetime.now(timezone.utc)) is not True:
            raise OperatorRefused('read-only enrollment failed validation')
        consent.write_windows_grant(grant)
        try:
            if consent.evaluate_grant(consent.read_windows_grant(), context=context,
                                      now=datetime.now(timezone.utc)) is not True:
                raise OperatorRefused('credential readback verification refused')
        except Exception:
            consent.delete_windows_grant()
            raise
        return {'result':'PASS', 'mode':'enrolled',
                'expires_minutes':args.expires_minutes, 'notifications_enabled':False}

    if session_count is not None:
        previous = os.environ.get(STORAGE_PROFILE_ENV)
        if previous is not None and previous != 'release':
            raise OperatorRefused('existing nonrelease storage selection refused')
        os.environ[STORAGE_PROFILE_ENV] = 'release'
        try:
            return _run_protected_session(
                reviewed=reviewed, context=context, att=att,
                binding=binding, checker=checker, cycles=session_count,
                duration_minutes=getattr(args, 'session_duration_minutes', 15))
        finally:
            if previous is None:
                os.environ.pop(STORAGE_PROFILE_ENV, None)
            else:
                os.environ[STORAGE_PROFILE_ENV] = previous

    if args.run_count is not None:
        if not args.approve_live_read_only:
            raise OperatorRefused('explicit live read-only approval required')
        if not 1 <= args.run_count <= MAX_CYCLES:
            raise OperatorRefused('invalid bounded cycle count')
        previous = os.environ.get(STORAGE_PROFILE_ENV)
        if previous is not None and previous != 'release':
            raise OperatorRefused('existing nonrelease storage selection refused')
        # The new process is configured for the isolated v0.8 release journal.
        os.environ[STORAGE_PROFILE_ENV] = 'release'
        try:
            wiring = type(reviewed.wiring)(
                reviewed.wiring.source_root, reviewed.wiring.config_path,
                reviewed.wiring.manifest, reviewed.wiring.approved_sid,
                cycles=args.run_count)
            def real_authorizer(**kwargs):
                return att.build_rechecking_authorizer(**kwargs, source_checker=checker)
            outcome = binding.run_explicitly_approved_api(
                wiring, build_authorizer=real_authorizer)
            return {'result':'PASS', 'mode':'bounded-live-read-only',
                    'cycles':outcome.cycles, 'persisted_cycles':outcome.persisted_cycles,
                    'notifications_sent':outcome.notifications_sent,
                    'repairs_invoked':outcome.repairs_invoked}
        finally:
            if previous is None:
                os.environ.pop(STORAGE_PROFILE_ENV, None)
    raise OperatorRefused('no operator action selected')


def _parser():
    p = argparse.ArgumentParser(description='ONYX CORE v0.8.0 protected foreground operator')
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--audit-installed', action='store_true')
    group.add_argument('--enroll-read-only', action='store_true')
    group.add_argument('--run-count', type=int)
    group.add_argument('--run-session-count', type=int)
    group.add_argument('--revoke-read-only', action='store_true')
    p.add_argument('--approve-enrollment', action='store_true')
    p.add_argument('--expires-minutes', type=int, default=60)
    p.add_argument('--approve-live-read-only', action='store_true')
    p.add_argument('--approve-session-read-only', action='store_true')
    p.add_argument('--session-duration-minutes', type=int, default=15)
    p.add_argument('--approve-revocation', action='store_true')
    return p


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        if args.enroll_read_only is False and (args.approve_enrollment or args.expires_minutes != 60):
            raise OperatorRefused('enrollment options only valid for enrollment')
        if args.run_count is None and args.approve_live_read_only:
            raise OperatorRefused('live approval requires --run-count')
        if args.run_session_count is None and (args.approve_session_read_only or
                                               args.session_duration_minutes != 15):
            raise OperatorRefused('session options require --run-session-count')
        if args.revoke_read_only is False and args.approve_revocation:
            raise OperatorRefused('revoke approval requires --revoke-read-only')
        print(json.dumps(_operator_action(args), sort_keys=True))
        return 0
    except KeyboardInterrupt:
        print('ONYX CORE release foreground operation stopped by operator', file=sys.stderr)
        return 130
    except Exception as exc:
        print('ONYX CORE RELEASE REFUSED: ' + type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
