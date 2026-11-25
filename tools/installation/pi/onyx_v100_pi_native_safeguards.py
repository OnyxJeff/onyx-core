#!/usr/bin/env python3
"""M2-S7B: offline-only ARMv6 installation contract review (never publish)."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
import sys

# Explicit, reviewed modules from frozen M2 source. No native install/prepare
# entry points are called from this module.
HERE = Path(__file__).resolve().parent
for folder in (HERE, HERE.parent / 'common'):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
from onyx_v100_pi_code_publish import (  # noqa: E402
    expected_files, receipt_bytes, digest, UNIT_CANDIDATE, RECEIPT,
    RELEASE_NAME, PARENT,
)
from onyx_v100_pi_config_state import proposed as proposed_config  # noqa: E402
from onyx_v100_pi_system_plan import (  # noqa: E402
    RELEASE_ROOT, CONFIG_PATH, CREDENTIAL_PATH, ACTIVATION_MARKER, UNIT_PATH,
    LEGACY_STATE, LEGACY_UNIT,
)

BUNDLE_HASH = 'b4e3c350e47d087bd06c4249aa163d96abe07b792109fc4e9b1032705e2c263d'
EXPECTED_HOST = 'svr-onyxcore'
EXPECTED_RELEASE_FILES = 15
EXPECTED_SERVICE_USER = (999, 985)
EXPECTED_SOURCE = 'SQUALL'
EXPECTED_USB = '192.168.137.167/24'
EXPECTED_TARGETS = {
    'release_target', 'configuration_target', 'v1_state_target',
    'v1_unit_target', 'v1_activation_marker',
}


class SafeguardsRefused(ValueError):
    pass


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snapshot_review(bundle: Path, config: Path, observations: dict) -> dict:
    """Pure review of pinned bundle, canonical config and supplied past evidence.

    The supplied observations are user-reported S7A evidence, not newly
    authenticated Pi measurements. Never claim native acceptance from them.
    """
    if bundle.is_symlink() or not bundle.is_file() or _sha(bundle.read_bytes()) != BUNDLE_HASH:
        raise SafeguardsRefused('M2-S1 bundle SHA256 is not the frozen accepted bundle')
    if config.is_symlink() or not config.is_file():
        raise SafeguardsRefused('configuration must be a regular, local, non-symlink file')
    if type(observations) is not dict:
        raise SafeguardsRefused('S7A evidence must be a JSON object')
    files, cfg = expected_files(bundle, config)
    config_data, config_receipt, cfg2, selected = proposed_config(bundle, config)
    if cfg != cfg2 or files != selected or len(files) != 14:
        raise SafeguardsRefused('S3C/S3D payload disagreement')
    if cfg['receiver'] != {'interface':'usb0', 'port':8765,
                           'ipv4_subnet':'192.168.137.0/24', 'source':EXPECTED_SOURCE}:
        raise SafeguardsRefused('Pi configuration must match SQUALL/USB reviewed contract')
    if cfg['storage']['state_dir'] != '/var/lib/onyxcore-v100':
        raise SafeguardsRefused('legacy state must not be used for v1')
    unit = files[UNIT_CANDIDATE].decode('utf-8')
    needed = ('ConditionPathExists=' + ACTIVATION_MARKER, 'RefuseManualStart=yes',
              'EnvironmentFile=' + CREDENTIAL_PATH, 'User=onyxcore',
              'Group=onyxcore', 'ReadWritePaths=/var/lib/onyxcore-v100',
              'ProtectSystem=strict', 'NoNewPrivileges=true')
    if any(field not in unit.splitlines() for field in needed):
        raise SafeguardsRefused('inactive unit candidate has lost a mandatory guard')
    if not (RELEASE_ROOT == '/opt/onyxcore/v1.0.0' and (PARENT / RELEASE_NAME).as_posix() == RELEASE_ROOT
            and CONFIG_PATH == '/etc/onyxcore/v1.0.0/pi-armv6.config.json'
            and LEGACY_STATE == '/var/lib/onyxcore'
            and LEGACY_UNIT == '/etc/systemd/system/onyxcore-receiver.service'
            and UNIT_PATH == '/etc/systemd/system/onyxcore-v100-receiver.service'):
        raise SafeguardsRefused('reviewed fixed paths changed')
    if len(files) + 1 != EXPECTED_RELEASE_FILES or RECEIPT in files:
        raise SafeguardsRefused('unexpected release inventory')
    release_receipt = receipt_bytes(files)
    receipt = json.loads(release_receipt)
    if (len(receipt['files']) != 14 or
        {x['path'] for x in receipt['files']} != set(files) or
        any(x['sha256'] != _sha(files[x['path']]) or
            x['size'] != len(files[x['path']]) for x in receipt['files'])):
        raise SafeguardsRefused('release receipt inventory mismatch')
    config_row = json.loads(config_receipt)
    if config_row['config_sha256'] != _sha(config_data):
        raise SafeguardsRefused('config receipt hash mismatch')

    blockers, pending = [], []
    if (observations.get('hostname') != EXPECTED_HOST or
        observations.get('architecture') != 'armv6l' or
        not str(observations.get('python_version','')).startswith('3.13.') or
        observations.get('os_codename') != 'trixie' or
        EXPECTED_USB not in observations.get('usb0_ipv4', [])):
        blockers.append('s7a_host_arch_python_os_or_usb_not_verified')
    if (observations.get('service_uid'), observations.get('service_gid')) != EXPECTED_SERVICE_USER:
        blockers.append('unexpected_service_identity')
    paths = observations.get('paths')
    if type(paths) is not dict or set(paths) != EXPECTED_TARGETS | {'release_parent','configuration_parent','legacy_state'}:
        raise SafeguardsRefused('S7A path evidence inventory incomplete')
    for name in sorted(EXPECTED_TARGETS):
        value = paths[name]
        if value != 'absent':
            blockers.append('v1_target_not_proven_absent_' + name)
    release_parent = paths['release_parent']
    if (not isinstance(release_parent, dict) or
            (release_parent.get('uid'), release_parent.get('gid'),release_parent.get('mode'),release_parent.get('kind'))
            != (0,0,'0755','dir')):
        blockers.append('release_parent_permissions_require_review')
    config_parent = paths['configuration_parent']
    if not isinstance(config_parent, dict) or config_parent.get('kind') != 'dir':
        blockers.append('configuration_parent_metadata_unknown')
    else:
        try:
            p_mode = int(config_parent.get('mode','?'),8)
        except ValueError:
            blockers.append('configuration_parent_mode_unknown')
            p_mode = -1
        if config_parent.get('uid') != 0 or p_mode & 0o022:
            blockers.append('configuration_parent_unsafe')
        # Mirrors S3D._service_can_traverse. Distinguish deliberate root 0700
        # from a vulnerability: do not alter it in this milestone.
        if p_mode >= 0 and not (p_mode & stat.S_IXOTH or
                                (config_parent.get('gid') == EXPECTED_SERVICE_USER[1]
                                 and p_mode & stat.S_IXGRP)):
            blockers.append('s3d_service_cannot_traverse_protected_config_parent')
    if paths['legacy_state'] != {'kind':'dir','uid':999,'gid':985,'mode':'0750'}:
        blockers.append('legacy_state_metadata_changed')
    if observations.get('legacy_receiver_state') != 'active' or 8765 not in observations.get('legacy_listen_ports', []):
        pending.append('verify_legacy_receiver_runtime_state_before_future_install')
    else:
        pending.append('legacy_receiver_occupies_port_8765_future_activation_requires_handover')
    pending.extend(('pi_native_renameat2_filesystem_acceptance_not_performed',
                    'two_directory_nonatomic_publication_requires_incomplete_state_review',
                    'config_parent_traverse_design_requires_separate_review',
                    'actual_pi_installation_not_authorized',
                    'native_pi_source_and_usb_connectivity_not_proven_by_offline_snapshot'))
    report = {
        'schema_version':1, 'operation':'M2_S7B_OFFLINE_PI_INSTALL_SAFEGUARDS_REVIEW',
        'development_commit':'cf682b0729c8d03a0ba7c882dbdb811e752bd6a2',
        'native_readiness':'BLOCKED' if blockers else 'REVIEW_ONLY',
        'blockers':sorted(set(blockers)), 'pending':sorted(set(pending)),
        'source_identity':EXPECTED_SOURCE, 'bundle_sha256':BUNDLE_HASH,
        'release_target':RELEASE_ROOT, 'release_file_count':15,
        'release_receipt_sha256':_sha(release_receipt),
        'config_target':CONFIG_PATH, 'config_sha256':_sha(config_data),
        'config_receipt_sha256':_sha(config_receipt),
        'state_target':'/var/lib/onyxcore-v100',
        'unit_candidate_sha256':_sha(files[UNIT_CANDIDATE]),
        'legacy_receiver_port_observed':8765,
        'no_replace_required':True,
        'rollback_policy':'stop_preserve_partial_state_manual_reconciliation',
        'evidence_source':'operator_reported_M2_S7A_plus_root_metadata_check',
        'evidence_not_live_reattested':True,
        'writes_to_pi':False, 'service_changes':False,
        'credential_read_or_enrollment':False, 'activation':False,
        'filesystem_publication':False, 'installer_invoked':False,
    }
    return report


def main(argv=None) -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bundle', type=Path, required=True)
    ap.add_argument('--config', type=Path, required=True)
    ap.add_argument('--evidence', type=Path, required=True)
    args=ap.parse_args(argv)
    try:
        if args.evidence.is_symlink() or not args.evidence.is_file() or args.evidence.stat().st_size > 16000:
            raise SafeguardsRefused('evidence must be a small regular local JSON file')
        observations=json.loads(args.evidence.read_text(encoding='utf-8'))
        report=snapshot_review(args.bundle,args.config,observations)
        print(json.dumps(report,sort_keys=True,separators=(',',':')))
        # A BLOCKED result is an expected inspection finding, not an offline test failure.
        return 0
    except (ValueError, KeyError, TypeError, OSError, UnicodeError) as exc:
        print('STOP: '+type(exc).__name__+': '+str(exc),file=sys.stderr)
        return 2

if __name__=='__main__':
    raise SystemExit(main())
