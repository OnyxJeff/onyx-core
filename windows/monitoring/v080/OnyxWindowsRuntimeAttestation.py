#!/usr/bin/env python3
"""ONYX CORE v0.8 K1: user-scoped Windows identity/source attestation.

Only callable APIs; CLI inert. The explicit source digest manifest must be pinned by
an independently reviewed launcher, not read from user-modifiable credentials.
This module is NOT sufficient by itself for production startup or SEC closure.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Callable, Mapping

import OnyxWindowsNativeAdmission as native
import OnyxWindowsUserConsent as consent

SHA256_RE = re.compile(r'[0-9a-f]{64}\Z')
COMMIT_RE = re.compile(r'[0-9a-f]{40}\Z')
REQUIRED_FILES = (
    'windows/monitoring/v080/OnyxLiveConnectivity.py',
    'windows/monitoring/v080/OnyxContinuousMonitor.py',
    'windows/monitoring/v080/OnyxLiveIncidentHistory.py',
    'windows/monitoring/v080/OnyxGuardedRuntimeBridge.py',
    'windows/monitoring/v080/OnyxWindowsNativeAdmission.py',
    'windows/monitoring/v080/OnyxWindowsUserConsent.py',
    'windows/monitoring/v080/OnyxWindowsRuntimeAttestation.py',
    # R3 protected-launch runtime transitive imports and actual diagnostic scripts.
    # A missing/modified entry must deny the next consent recheck, including
    # before each probe, record and interval wake-up.
    'windows/monitoring/v080/OnyxV080ReleaseBinding.py',
    'windows/monitoring/v080/OnyxV080ReleaseProfile.py',
    'windows/monitoring/v080/OnyxWindowsJobRunner.py',
    'windows/monitoring/v080/OnyxV080ProtectedLaunch.py',
    'windows/monitoring/OnyxMonitorConfig.py',
    'windows/monitoring/v080/Invoke-OnyxV080WindowsReadiness.ps1',
    'windows/networking/Test-OnyxUsbIcsReadiness.ps1',
    # RC operational controls: installed source/ACL verification and foreground CLI.
    'windows/monitoring/v080/OnyxWindowsProtectedInstallTrust.py',
    'windows/monitoring/v080/OnyxV080ReleaseOperator.py',
    # R6: source-attested foreground-only supervision composition.
    'windows/monitoring/v080/OnyxV080SessionSupervisor.py',
    'windows/monitoring/v080/OnyxV080SessionIntegration.py',
    # R6.2B2B: pinned standalone low-integrity one-shot diagnostic child.
    'windows/monitoring/v080/OnyxV080ContainedProbe.py',
)
MAX_BYTES = 512 * 1024
INVALID_SESSION = 0xFFFFFFFF


class AttestationRefused(RuntimeError):
    """OS identity or content provenance cannot be demonstrated."""


@dataclass(frozen=True)
class ReleaseManifest:
    """Audited source digests must come from trusted launcher/release metadata."""
    source_commit: str
    file_sha256: Mapping[str, str]
    config_sha256: str

    def __post_init__(self):
        if type(self.source_commit) is not str or not COMMIT_RE.fullmatch(self.source_commit):
            raise AttestationRefused('invalid pinned release commit')
        if type(self.config_sha256) is not str or not SHA256_RE.fullmatch(self.config_sha256):
            raise AttestationRefused('invalid pinned config digest')
        if type(self.file_sha256) is not dict or set(self.file_sha256) != set(REQUIRED_FILES):
            raise AttestationRefused('source manifest inventory mismatch')
        if any(type(v) is not str or not SHA256_RE.fullmatch(v) for v in self.file_sha256.values()):
            raise AttestationRefused('invalid source hash in manifest')


def _native_active_console() -> bool:
    """Read the real process session, requiring locally logged-on console user.

    Conservative v0.8 scope: RDP or detached/unknown sessions are denied. This
    does not claim to verify arbitrary remote/secondary sessions or user intent.
    """
    if os.name != 'nt':
        raise AttestationRefused('Windows required')
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcessId.argtypes = []
    kernel.GetCurrentProcessId.restype = wintypes.DWORD
    kernel.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel.ProcessIdToSessionId.restype = wintypes.BOOL
    kernel.WTSGetActiveConsoleSessionId.argtypes = []
    kernel.WTSGetActiveConsoleSessionId.restype = wintypes.DWORD
    session = wintypes.DWORD(INVALID_SESSION)
    if not kernel.ProcessIdToSessionId(kernel.GetCurrentProcessId(), ctypes.byref(session)):
        raise AttestationRefused('Windows process session unavailable')
    active = int(kernel.WTSGetActiveConsoleSessionId())
    return session.value != 0 and active != INVALID_SESSION and session.value == active


def _safe_regular_file(root: Path, relative: str) -> Path:
    """Reject reparse components and files outside the caller-pinned tree.

    This is read-only path screening, not full NTFS ACL or TOCTOU attestation.
    Such attestation is separately required before unattended startup.
    """
    path = root
    if not root.is_absolute() or root.is_symlink() or (hasattr(root, 'is_junction') and root.is_junction()):
        raise AttestationRefused('untrusted source root')
    for item in Path(relative).parts:
        if item in ('', '.', '..') or '/' in item or '\\' in item:
            raise AttestationRefused('unsafe source path')
        path = path / item
        try:
            mode = path.lstat().st_mode
        except OSError as exc:
            raise AttestationRefused('source component unavailable') from exc
        if stat.S_ISLNK(mode) or (hasattr(path, 'is_junction') and path.is_junction()):
            raise AttestationRefused('redirected source component')
    if not path.is_file():
        raise AttestationRefused('source file missing')
    if root.resolve() not in path.resolve().parents:
        raise AttestationRefused('source escaped root')
    return path


def _digest(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_BYTES:
            raise AttestationRefused('source file oversized')
        with path.open('rb') as handle:
            content = handle.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise AttestationRefused('source file oversized')
    except OSError as exc:
        raise AttestationRefused('unable to read source') from exc
    return hashlib.sha256(content).hexdigest()


def attest_source(*, root: Path, manifest: ReleaseManifest, config: Path,
                  digest: Callable[[Path], str] = _digest) -> None:
    """Check explicit manifest contents. Never load manifest from grant or env."""
    if not isinstance(root, Path) or not isinstance(config, Path) or not isinstance(manifest, ReleaseManifest):
        raise AttestationRefused('missing release source policy')
    if not callable(digest):
        raise AttestationRefused('missing digest implementation')
    for relative in REQUIRED_FILES:
        actual = digest(_safe_regular_file(root, relative))
        if actual != manifest.file_sha256[relative]:
            raise AttestationRefused('source digest mismatch')
    # Require config to be an immediate descendant of the pinned monitoring directory.
    expected_parent = (root / 'windows' / 'monitoring').resolve()
    if config.parent.resolve() != expected_parent or config.suffix.lower() != '.json':
        raise AttestationRefused('config outside approved directory')
    relative_config = str(config.relative_to(root)).replace('\\', '/')
    if digest(_safe_regular_file(root, relative_config)) != manifest.config_sha256:
        raise AttestationRefused('config digest mismatch')


def verified_consent_context(*, root: Path, manifest: ReleaseManifest, config: Path,
                             expected_sid: str,
                             sid_provider: Callable[[], str] = native.current_process_sid,
                             console_provider: Callable[[], bool] = _native_active_console,
                             source_checker: Callable = attest_source) -> consent.VerifiedContext:
    """Acquire fresh identity/session/source evidence for a consent evaluation.

    MUST be called again before each probe/write. A caller-supplied manifest or
    callback is NOT independently trustworthy; pin it in reviewed launcher code.
    """
    if not all(callable(x) for x in (sid_provider, console_provider, source_checker)):
        raise AttestationRefused('missing Windows/source attestation adapter')
    approved = native.validate_sid(expected_sid)
    observed = sid_provider()
    if observed != approved:
        raise AttestationRefused('process SID mismatch')
    if console_provider() is not True:
        raise AttestationRefused('not in active local console session')
    source_checker(root=root, manifest=manifest, config=config)
    return consent.VerifiedContext(
        process_sid=observed,
        source_commit=manifest.source_commit,
        config_sha256=manifest.config_sha256,
        source_trusted=True,
        active_user_session=True,
    )


def build_rechecking_authorizer(*, root: Path, manifest: ReleaseManifest,
                                 config: Path, approved_sid: str,
                                 read: Callable[[], bytes] = consent.read_windows_grant,
                                 sid_provider: Callable[[], str] = native.current_process_sid,
                                 console_provider: Callable[[], bool] = _native_active_console,
                                 source_checker: Callable = attest_source,
                                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
    """Bind J1 user consent to fresh session/source checks on *every* call.

    No runnable entrypoint consumes this callback. Not an independent signer;
    source/ACL protections and runtime containment still need host acceptance.
    """
    if not all(callable(x) for x in (read, sid_provider, console_provider, source_checker, now)):
        raise AttestationRefused('missing authorization dependency')
    def authorized():
        context = verified_consent_context(
            root=root, manifest=manifest, config=config, expected_sid=approved_sid,
            sid_provider=sid_provider, console_provider=console_provider,
            source_checker=source_checker,
        )
        return consent.evaluate_grant(read(), context=context, now=now())
    return authorized


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-inert', required=True, action='store_true')
    parser.parse_args(argv)
    print(json.dumps({
        'phase': '18K1', 'runtime_live_enabled': False, 'source_manifest_pinned': False,
        'consent_binding_present': True, 'native_session_checker_present': True,
        'fully_handle_attested_ntfs_acl': False, 'production_enrollment_enabled': False,
        'scheduled_task_created': False, 'release_status': 'HOLD',
    }, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
