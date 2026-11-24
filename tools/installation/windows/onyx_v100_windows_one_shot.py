#!/usr/bin/env python3
"""M2-S5E: source-pinned, one-shot *contract* for an inactive Windows install.

PUBLIC CLI IS PREVIEW ONLY. This module cannot be invoked via CLI to publish a
user-profile installation. A separately reviewed, explicitly authorized caller
is required for the private one-shot operation. Nothing here enrolls secrets,
activates runtime, changes tasks/services, or performs network probes.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

S5D_SHA256 = 'ff990bcbe17723c700dde8bf33aae6ff0f90e9e9a239119726e56fe0fae5614b'
M2_HEAD = '00c6ba630a18b054308bb7119b610602790e44be'
PLAN_SHA256 = '77426cdc3207fe96404f04dd410d7c8d00b0d7f36dd46c855fbfe719102a5bd4'
TARGET_NAME = 'OnyxCore-v100-Inactive-Stable100'
TARGET_SCOPE = 'inactive Windows user profile only'
SETTINGS = {'receiver_host': 'svr-onyxcore.local', 'receiver_port': 8765,
            'source': 'SQUALL', 'network_adapter': 'Ethernet',
            'usb_adapter': 'Ethernet 3', 'gateway_port': 18976, 'interval': 30}


class OneShotRefused(ValueError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(doc: dict) -> bytes:
    return (json.dumps(doc, sort_keys=True, ensure_ascii=True,
                       separators=(',', ':')) + '\n').encode('ascii')


def reviewed_s5d():
    source = Path(__file__).with_name('onyx_v100_windows_user_preflight.py')
    if not source.is_file() or source.is_symlink() or sha(source.read_bytes()) != S5D_SHA256:
        raise OneShotRefused('approved M2-S5D preflight source SHA256 mismatch')
    spec = importlib.util.spec_from_file_location('onyx_v100_s5e_pinned_s5d', source)
    if spec is None or spec.loader is None:
        raise OneShotRefused('cannot import approved S5D source')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if (module.M2_HEAD != M2_HEAD or module.TARGET_NAME != TARGET_NAME or
            module.FILE_COUNT != 17):
        raise OneShotRefused('S5D frozen identity mismatch')
    # The imported S5D verifies S5C and its three upstream dependencies as
    # well as the accepted DACL-only helper. No helper is executed here.
    module.reviewed_s5c()
    return module


def validate_plan(plan: dict, expected: dict, cfg: dict, *, root: Path, user) -> Path:
    """Fail closed before publication on any different path, content or plan.

    This function deliberately performs no writes, service calls or network
    calls. It is re-run immediately before future user-scope publication.
    """
    if not isinstance(plan, dict):
        raise OneShotRefused('preflight report must be an object')
    proposed = dict(plan)
    digest = proposed.pop('plan_sha256', None)
    if (digest != PLAN_SHA256 or sha(canonical(proposed)) != PLAN_SHA256):
        raise OneShotRefused('one-shot plan fingerprint mismatch')
    target = root / TARGET_NAME
    if (plan.get('target') != str(target) or target.name != TARGET_NAME):
        raise OneShotRefused('one-shot target mismatch')
    user.validate_target(target, root=root)  # refuses existing, redirected, etc.
    if (plan.get('operation') != 'M2_S5D_USER_INSTALL_PREFLIGHT_ONLY' or
            plan.get('m2_commit') != M2_HEAD or
            plan.get('file_count_if_installed') != 17 or
            len(plan.get('files', [])) != 16 or
            plan.get('collector_source') != 'SQUALL' or
            plan.get('receiver_host') != 'svr-onyxcore.local' or
            plan.get('gateway_port') != 18976 or
            cfg['collector']['source'] != 'SQUALL' or
            cfg['receiver']['host'] != 'svr-onyxcore.local' or
            cfg['gateway']['port'] != 18976):
        raise OneShotRefused('one-shot host configuration or inventory mismatch')
    if (plan.get('publication_performed') is not False or
            plan.get('credential_enrolled') is not False or
            plan.get('credentials_read') is not False or
            plan.get('persistent_installation_authorized') is not False or
            plan.get('requires_separate_one_shot_authorization') is not True or
            plan.get('native_acl_changed') is not False):
        raise OneShotRefused('S5D plan claims unexpected authorization or writes')
    verified = [{'path': rel, 'size': len(data), 'sha256': sha(data)}
                for rel, data in sorted(expected.items())]
    if len(expected) != 16 or plan.get('files') != verified:
        raise OneShotRefused('one-shot payload hash inventory mismatch')
    return target


def prepare(bundle: Path, dashboard: Path):
    """Native, read-only preparation. Never invokes publication."""
    s5d = reviewed_s5d()
    s5c = s5d.reviewed_s5c()
    s5c.native_guard()
    s4c, r3, _ = s5c.reviewed()
    user = s4c.reviewed_modules()[2]
    root = user.native_user_root()
    expected, cfg = s5c.expected_install(bundle, dashboard, SETTINGS, s4c=s4c)
    plan = s5d.target_report(root, expected, cfg, user=user)
    target = validate_plan(plan, expected, cfg, root=root, user=user)
    return s5d, s5c, s4c, r3, user, root, target, expected, cfg, plan


def preview(bundle: Path, dashboard: Path) -> dict:
    *_, target, expected, cfg, plan = prepare(bundle, dashboard)
    return {
        'schema_version': 1,
        'operation': 'M2_S5E_USER_ONE_SHOT_PREVIEW_ONLY',
        'm2_commit': M2_HEAD,
        's5d_plan_sha256': PLAN_SHA256,
        'target': str(target),
        'file_count_if_installed': 17,
        'payload_file_count': len(expected),
        'receiver_host': cfg['receiver']['host'],
        'collector_source': cfg['collector']['source'],
        'gateway_port': cfg['gateway']['port'],
        'persistent_installation_performed': False,
        'user_profile_modified': False,
        'credentials_read': False,
        'credentials_enrolled': False,
        'tasks_or_services_modified': False,
        'activation_performed': False,
        'awaiting_separate_execution_authorization': True,
    }


def _authorization_allowed(record: dict | None, *, target: Path) -> None:
    """Explicit caller contract, NOT proof that the human authorized a write.

    A future, separately reviewed one-shot runner must only construct this
    record after the user explicitly authorizes the precise write. S5E does
    NOT ship a runner or public install mode.
    """
    if (not isinstance(record, dict) or
            set(record) != {'operation', 'plan_sha256', 'target',
                            'approve_persistent', 'approve_inactive', 'approve_no_replace'} or
            record.get('operation') != 'M2_S5E_SEPARATELY_AUTHORIZED_ONE_SHOT' or
            record.get('plan_sha256') != PLAN_SHA256 or
            record.get('target') != str(target) or
            record.get('approve_persistent') is not True or
            record.get('approve_inactive') is not True or
            record.get('approve_no_replace') is not True):
        raise OneShotRefused('separate exact-target one-shot authorization required')


def execute_only_from_future_authorized_runner(bundle: Path, dashboard: Path, *,
                                               authorization: dict | None = None) -> dict:
    """Internal one-shot writer. Not reachable from any S5E public CLI action.

    No automatic cleanup or retry. If hardening or publish fails, S5C retains
    evidence and reports INCOMPLETE. Do not call without separate authorization.
    """
    # Reject missing approval before inspecting inputs. The target string here
    # is only an authorization *declaration*, not trusted filesystem location.
    declared_target = authorization.get('target') if isinstance(authorization, dict) else None
    if not isinstance(declared_target, str) or not declared_target.endswith('\\' + TARGET_NAME):
        raise OneShotRefused('separate exact-target one-shot authorization required')
    # Full validation is performed again using the Windows Known Folder API.
    s5d, s5c, s4c, r3, user, root, target, expected, cfg, plan = prepare(bundle, dashboard)
    _authorization_allowed(authorization, target=target)
    # Second pre-publication revalidation detects target appearance and
    # protects against changing bundle/dashboard inputs.
    expected2, cfg2 = s5c.expected_install(bundle, dashboard, SETTINGS, s4c=s4c)
    plan2 = s5d.target_report(root, expected2, cfg2, user=user)
    validate_plan(plan2, expected2, cfg2, root=root, user=user)
    if expected2 != expected or plan2 != plan:
        raise OneShotRefused('plan or runtime changed before publication')
    result = s5c.install_core(expected2, root=root, target=target, scope='User',
                              s4c=s4c, r3=r3, approve_persistent=True,
                              approve_inactive=True, approve_no_replace=True)
    if (result.get('target') != str(target) or result.get('file_count') != 17 or
            result.get('credentials_enrolled') is not False or
            result.get('activation_performed') is not False):
        raise OneShotRefused('INCOMPLETE: unexpected native publisher result; evidence retained')
    verified = user.verify_inactive(target, expected2, root=root)
    if verified.get('file_count') != 17:
        raise OneShotRefused('INCOMPLETE: installed receipt failed verification')
    # S5C already audited the DACLs *after* publication.
    receipt_bytes = (target / user.RECEIPT_NAME).read_bytes()
    return {'schema_version': 1, 'operation': 'M2_S5E_INACTIVE_USER_INSTALLED',
            'target': str(target), 's5d_plan_sha256': PLAN_SHA256,
            'receipt_sha256': sha(receipt_bytes), 'installed_file_count': 17,
            'credentials_enrolled': False, 'tasks_or_services_modified': False,
            'activation_performed': False}


def cli(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--dashboard', type=Path, required=True)
    parser.add_argument('--mode', choices=('preview',), default='preview')
    args = parser.parse_args(argv)
    try:
        if args.mode != 'preview':
            raise OneShotRefused('only read-only preview is permitted')
        print(canonical(preview(args.bundle, args.dashboard)).decode('ascii').strip())
        return 0
    except (OneShotRefused, OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print('STOP: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(cli())
