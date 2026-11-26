#!/usr/bin/env python3
"""M2-S7C offline-only isolated Pi candidate contract; no publication API."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import onyx_v100_pi_native_safeguards as s7b
import onyx_v100_pi_code_publish as s3c
import onyx_v100_pi_config_state as s3d

CONFIG_ROOT = '/etc/onyxcore-v100'
CONFIG = CONFIG_ROOT + '/pi-armv6.config.json'
CREDENTIAL = CONFIG_ROOT + '/receiver.env'
MARKER = CONFIG_ROOT + '/activation-approved'
STATE = '/var/lib/onyxcore-v100'
IDENTITY = 'onyxcore-v100'
RELEASE = '/opt/onyxcore/v1.0.0'
UNIT = '/etc/systemd/system/onyxcore-v100-receiver.service'
OLD_HASHES = {
    'release_receipt_sha256': '98b9e0ebdffe240388d953dbaa7e9b442d6271df3285bef7024ae65c78bf71ab',
    'config_receipt_sha256': '30d91f44f6e75e7bc777dfaaad03d2f5a67f4b53865d8c0166cd8ce2a657f6b2',
    'unit_candidate_sha256': '76d2ee56a6da61f591c173675019bef971632ee911e6ba87617acd401eae7712',
}
class ContractRefused(ValueError):
    pass

def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()

def revised_unit(old: bytes) -> bytes:
    if sha(old) != OLD_HASHES['unit_candidate_sha256']:
        raise ContractRefused('original unit fingerprint differs from S7B acceptance')
    text = old.decode('ascii')
    replacements = {
        'User=onyxcore\n': 'User=onyxcore-v100\n',
        'Group=onyxcore\n': 'Group=onyxcore-v100\n',
        '/etc/onyxcore/v1.0.0/': CONFIG_ROOT + '/',
        'ReadWritePaths=/var/lib/onyxcore-v100\n': (
            'ReadWritePaths=/var/lib/onyxcore-v100\n'
            'InaccessiblePaths=/etc/onyxcore /var/lib/onyxcore\n'),
        '[Install]\nWantedBy=multi-user.target\n': '',
    }
    for original, replacement in replacements.items():
        count = 3 if original == '/etc/onyxcore/v1.0.0/' else 1
        if text.count(original) != count:
            raise ContractRefused('unexpected original unit structure')
        text = text.replace(original, replacement)
    # The candidate is static, manually unstartable, and requires a root-created marker.
    required = ('ConditionPathExists=' + MARKER, 'RefuseManualStart=yes',
                'User=' + IDENTITY, 'Group=' + IDENTITY,
                'EnvironmentFile=' + CREDENTIAL, 'ReadWritePaths=' + STATE,
                'InaccessiblePaths=/etc/onyxcore /var/lib/onyxcore',
                'ProtectSystem=strict', 'NoNewPrivileges=true', 'UMask=0077')
    if any(x not in text.splitlines() for x in required) or '[Install]' in text:
        raise ContractRefused('revised unit isolation guard missing')
    if '--config ' + CONFIG + ' --installed-root ' + RELEASE not in text:
        raise ContractRefused('revised launcher configuration mismatch')
    return text.encode('ascii')

def build_candidates(bundle: Path, config: Path, evidence: dict) -> tuple[dict[str, bytes], dict[str, bytes], dict]:
    old = s7b.snapshot_review(bundle, config, evidence)
    if old['blockers'] != ['s3d_service_cannot_traverse_protected_config_parent']:
        raise ContractRefused('S7B evidence differs from accepted single blocker')
    if any(old[k] != v for k, v in OLD_HASHES.items()):
        raise ContractRefused('S7B fingerprints differ from accepted SQUALL values')
    original, cfg = s3c.expected_files(bundle, config)
    config_bytes, _, cfg2, same = s3d.proposed(bundle, config)
    if cfg != cfg2 or original != same or len(original) != 14:
        raise ContractRefused('frozen release inputs disagree')
    if PurePosixPath(CONFIG_ROOT).parent != PurePosixPath('/etc') or CONFIG_ROOT == '/etc/onyxcore':
        raise ContractRefused('configuration must be independent of legacy parent')
    files = dict(original)
    files[s3c.UNIT_CANDIDATE] = revised_unit(original[s3c.UNIT_CANDIDATE])
    # Receipts are prospective, not evidence of a completed installation.
    release_receipt = json.loads(s3c.receipt_bytes(files))
    release_receipt.update(operation='PI_V100_ISOLATED_CODE_CANDIDATE',
                           contract_revision='M2-S7C', service_identity=IDENTITY,
                           config_target=CONFIG, native_publication_verified=False)
    files[s3c.RECEIPT] = s3c.canonical_json(release_receipt)
    config_receipt = s3c.canonical_json({
        'schema_version': 1, 'operation': 'PI_V100_ISOLATED_CONFIG_CANDIDATE',
        'contract_revision': 'M2-S7C', 'source_commit': s3c.SOURCE_COMMIT,
        'bundle_sha256': s3c.BUNDLE_SHA256, 'config_sha256': sha(config_bytes),
        'config_target': CONFIG, 'state_target': STATE, 'service_identity': IDENTITY,
        'credential_enrolled': False, 'unit_registered': False,
        'activation_performed': False, 'native_publication_verified': False,
        'existing_history_migrated': False,
    })
    external = {'pi-armv6.config.json': config_bytes, 'config-receipt.json': config_receipt}
    report = {
        'schema_version': 1, 'operation': 'M2_S7C_OFFLINE_ISOLATION_CONTRACT',
        'status': 'DESIGN_READY_NATIVE_PREPARATION_REQUIRED',
        'old_installer_blocker': old['blockers'][0],
        'old_fingerprints': dict(OLD_HASHES),
        'release_target': RELEASE, 'config_root': CONFIG_ROOT, 'config_target': CONFIG,
        'credential_target': CREDENTIAL, 'activation_marker': MARKER,
        'state_target': STATE, 'unit_target': UNIT,
        'service_identity': IDENTITY, 'numeric_uid_gid_assigned': False,
        'legacy_config_policy': 'preserve_root_root_0700',
        'permission_plan': {
            'release_directory': ['root', IDENTITY, '0750'],
            'release_file': ['root', IDENTITY, '0640'],
            'config_directory': ['root', IDENTITY, '0750'],
            'config_file': ['root', IDENTITY, '0640'],
            'future_credential_file': ['root', 'root', '0600'],
            'future_activation_marker': ['root', 'root', '0600'],
            'state_directory': [IDENTITY, IDENTITY, '0700'],
            'future_unit_file': ['root', 'root', '0644'],
        },
        'release_file_count': len(files), 'external_config_file_count': len(external),
        'release_receipt_sha256': sha(files[s3c.RECEIPT]),
        'config_receipt_sha256': sha(config_receipt),
        'unit_candidate_sha256': sha(files[s3c.UNIT_CANDIDATE]),
        'config_sha256': sha(config_bytes),
        'new_path_absence_verified': False, 'new_service_identity_verified': False,
        'native_publication_verified': False, 'installation_authorized': False,
        'writes_to_pi': False, 'service_changes': False, 'credential_read_or_enrollment': False,
        'activation': False, 'installer_invoked': False,
        'pending': ['native_readonly_new_paths_and_identity_check',
                    'dedicated_account_no_legacy_group_memberships',
                    'adapt_and_validate_native_publishers_for_new_contract',
                    'native_no_replace_and_permission_fixture_acceptance',
                    'explicit_install_authorization', 'legacy_port_8765_handover_review'],
    }
    return files, external, report

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle', required=True, type=Path)
    p.add_argument('--config', required=True, type=Path)
    p.add_argument('--evidence', required=True, type=Path)
    a = p.parse_args(argv)
    try:
        evidence = json.loads(s3c.read_regular(a.evidence, 16000).decode('utf-8'))
        _, _, report = build_candidates(a.bundle, a.config, evidence)
        print(json.dumps(report, sort_keys=True, separators=(',', ':')))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print('STOP: ' + str(exc), file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
