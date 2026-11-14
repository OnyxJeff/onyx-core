#!/usr/bin/env python3
"""ONYX CORE v0.8 R3: protected-release approval admission (INERT CLI).

This module validates an independently pinned approval document against the
complete live monitoring source set, then constructs the EXISTING release
binding. It does not issue consent, start monitoring or modify Windows state.

The release approval fingerprint must be baked into a later reviewed installer,
not supplied by a runtime option, environment variable or Credential Manager.
No operational CLI exists until file-handle/NTFS source integrity and the
protected installation are accepted separately on the Windows host.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import ntpath
import os
from pathlib import Path
import re
import stat
import sys
from typing import Callable

import OnyxV080ReleaseBinding as binding
import OnyxV080ReleaseProfile as profile
import OnyxWindowsNativeAdmission as native
import OnyxWindowsRuntimeAttestation as att

INSTALL_ROOT = Path(r'C:\Program Files\OnyxCore\v0.8.0')
APPROVAL_NAME = 'release-approval.json'
RELEASE_CONFIG = Path('windows/monitoring') / profile.RELEASE_CONFIG_NAME
MAX_APPROVAL_BYTES = 16 * 1024
# Explicitly unset until a separate approved, immutable deployment build pins
# the exact release-approval.json SHA256. Never read this value from user input.
APPROVED_RELEASE_DOCUMENT_SHA256 = None
SHA256 = re.compile(r'[0-9a-f]{64}\Z')
REQUIRED_DOCUMENT_KEYS = frozenset({
    'schema_version', 'source_commit', 'approved_sid',
    'config_sha256', 'file_sha256',
})


class ProtectedLaunchRefused(RuntimeError):
    """The protected release has not demonstrated its launch authority."""


@dataclass(frozen=True)
class ReviewedAdmission:
    """Source-verified offline wiring, NOT a grant or authorization to probe."""
    wiring: binding.ReleaseWiring
    file_count: int
    approved_document_sha256: str


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise ProtectedLaunchRefused('duplicate approved policy field')
        result[key] = value
    return result


def _bad_constant(_):
    raise ProtectedLaunchRefused('nonfinite approval value')


def _checked_sha256(value):
    if type(value) is not str or SHA256.fullmatch(value) is None:
        raise ProtectedLaunchRefused('pinned approval SHA256 is missing or invalid')
    return value


def parse_approval_document(raw: bytes, *, pinned_sha256: str) -> tuple[att.ReleaseManifest, str]:
    """Compare the *entire* approval document to an external reviewed digest.

    A checksum inside the same JSON file would be self-authorizing and is
    deliberately not accepted. This function has no filesystem or OS effects.
    """
    pinned_sha256 = _checked_sha256(pinned_sha256)
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_APPROVAL_BYTES:
        raise ProtectedLaunchRefused('missing or oversized approved policy')
    if hashlib.sha256(raw).hexdigest() != pinned_sha256:
        raise ProtectedLaunchRefused('approved release document digest mismatch')
    try:
        value = json.loads(raw.decode('utf-8', 'strict'), object_pairs_hook=_pairs,
                           parse_constant=_bad_constant)
    except (ValueError, UnicodeError, TypeError) as exc:
        raise ProtectedLaunchRefused('approved release document is not valid JSON') from exc
    if type(value) is not dict or set(value) != REQUIRED_DOCUMENT_KEYS:
        raise ProtectedLaunchRefused('approved release document schema mismatch')
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ProtectedLaunchRefused('unsupported approved release schema')
    canonical = json.dumps(value, sort_keys=True, separators=(',', ':'),
                           ensure_ascii=True, allow_nan=False).encode('ascii')
    if canonical != raw:
        raise ProtectedLaunchRefused('release approval is not canonical JSON')
    try:
        sid = native.validate_sid(value['approved_sid'])
        manifest = att.ReleaseManifest(value['source_commit'], value['file_sha256'],
                                        value['config_sha256'])
    except (ValueError, TypeError, native.NativeAdmissionRefused, att.AttestationRefused) as exc:
        raise ProtectedLaunchRefused('invalid approved source identity') from exc
    return manifest, sid


def _no_redirection(path: Path):
    """Reject symlinks/junctions and reparse attributes in existing path parts.

    This *is not* native handle-backed NTFS ACL or TOCTOU attestation; those
    remain a separate mandatory operational blocker.
    """
    path = Path(path)
    current = path
    while True:
        try:
            info = current.lstat()
        except OSError as exc:
            raise ProtectedLaunchRefused('protected install path unavailable') from exc
        if (stat.S_ISLNK(info.st_mode)
            or (getattr(info, 'st_file_attributes', 0) & 0x400)
            or (hasattr(current, 'is_junction') and current.is_junction())):
            raise ProtectedLaunchRefused('redirected protected path component')
        if current == current.parent:
            break
        current = current.parent


def prepare_reviewed_install(root: Path, raw_approval: bytes, *, pinned_sha256: str,
                             cycles: int = 1,
                             attest_source: Callable = att.attest_source) -> ReviewedAdmission:
    """Offline source-to-real-wiring integration; no consent read/probe/DB write.

    The caller must independently prove that both this code and the root's
    manifest came from an authorized protected installation. This is not the
    operational entrypoint, and supplying an arbitrary digest is NOT consent.
    """
    if not isinstance(root, Path) or not root.is_absolute() or not callable(attest_source):
        raise ProtectedLaunchRefused('invalid approved source location or verifier')
    manifest, sid = parse_approval_document(raw_approval, pinned_sha256=pinned_sha256)
    _no_redirection(root)
    config = root / RELEASE_CONFIG
    # attestation covers the new launcher itself, release binding/profile,
    # diagnostic scripts, Job runner, native consent, and all M1/M2/M3 modules.
    attest_source(root=root, manifest=manifest, config=config)
    # Reuse the existing release policy validator; never use M1's dev-only guard.
    profile.load_release_config(config)
    return ReviewedAdmission(
        binding.ReleaseWiring(root, config, manifest, sid, cycles=cycles),
        len(manifest.file_sha256), pinned_sha256)


def _windows_fixed_root() -> Path:
    if os.name != 'nt':
        raise ProtectedLaunchRefused('protected release requires Windows')
    # The script must execute FROM the protected installation, not a Git tree.
    observed = Path(__file__).absolute().parents[3]
    if ntpath.normcase(str(observed)) != ntpath.normcase(str(INSTALL_ROOT)):
        raise ProtectedLaunchRefused('launcher not executed from protected installation')
    return observed


def audit_pinned_install() -> ReviewedAdmission:
    """Fail closed until the approved installer pins this module's digest.

    The user cannot provide source root, approval path, hash or SID through a
    command-line option. No monitor invocation is possible from this function.
    """
    digest = _checked_sha256(APPROVED_RELEASE_DOCUMENT_SHA256)
    root = _windows_fixed_root()
    approval_path = root / APPROVAL_NAME
    _no_redirection(approval_path)
    try:
        with approval_path.open('rb') as handle:
            raw = handle.read(MAX_APPROVAL_BYTES + 1)
    except OSError as exc:
        raise ProtectedLaunchRefused('approved release document unavailable') from exc
    return prepare_reviewed_install(root, raw, pinned_sha256=digest)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-inert', action='store_true', required=True)
    parser.parse_args(argv)
    print(json.dumps({
        'phase': 'R3-protected-release-admission', 'cli_live_enabled': False,
        'enrollment_enabled': False, 'notifications_enabled': False,
        'protected_manifest_pinned': False, 'native_acl_handle_attestation': False,
        'operational_launcher_enabled': False, 'release_status': 'HOLD',
    }, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
