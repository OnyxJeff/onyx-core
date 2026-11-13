#!/usr/bin/env python3
"""ONYX CORE v0.8: source-checked release component wiring; CLI inert.

Explicit Python-only boundary for an eventual independently approved launcher.
No CLI exposes start, enrollment, live probes, incidents or notifications.
The binding is NOT itself a trusted launcher: the manifest is supplied by its
caller, and neither native handle ACL attestation nor worker Job containment
has been established. Do NOT invoke run from production without these gates.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable

import OnyxGuardedRuntimeBridge as bridge
import OnyxLiveConnectivity as m1
import OnyxLiveIncidentHistory as m3
import OnyxV080ReleaseProfile as profile
import OnyxWindowsRuntimeAttestation as att


class ReleaseBindingRefused(RuntimeError):
    """Missing or contradictory explicit release integration configuration."""


@dataclass(frozen=True)
class ReleaseWiring:
    source_root: Path
    config_path: Path
    manifest: att.ReleaseManifest
    approved_sid: str
    cycles: int = 1

    def __post_init__(self):
        if not isinstance(self.source_root, Path) or not self.source_root.is_absolute():
            raise ReleaseBindingRefused('absolute release source root required')
        expected = self.source_root / 'windows' / 'monitoring' / profile.RELEASE_CONFIG_NAME
        if not isinstance(self.config_path, Path) or self.config_path != expected:
            raise ReleaseBindingRefused('config path must be pinned to source root')
        if not isinstance(self.manifest, att.ReleaseManifest):
            raise ReleaseBindingRefused('externally pinned source manifest required')
        # Enforce SID format; matching the OS SID occurs in the fresh authorizer.
        import OnyxWindowsNativeAdmission as native
        native.validate_sid(self.approved_sid)
        bridge.BoundedRuntimePolicy(cycles=self.cycles, interval_seconds=120)


def read_reviewed_release_config(wiring: ReleaseWiring) -> dict:
    if not isinstance(wiring, ReleaseWiring):
        raise ReleaseBindingRefused('invalid release wiring')
    return profile.load_release_config(wiring.config_path)


def make_release_authorizer(wiring: ReleaseWiring,
                            *, build_authorizer: Callable = att.build_rechecking_authorizer):
    """Build a *fresh-checking* consent/attestation provider, never mint grant."""
    if not isinstance(wiring, ReleaseWiring) or not callable(build_authorizer):
        raise ReleaseBindingRefused('missing source or authorizer builder')
    return build_authorizer(root=wiring.source_root, manifest=wiring.manifest,
                            config=wiring.config_path, approved_sid=wiring.approved_sid)


def require_release_storage_profile() -> str:
    """Select ONLY the release profile; development/default may not be used."""
    selected = m3.storage_profile()
    if selected != 'release':
        raise ReleaseBindingRefused('explicit v0.8 release storage profile required')
    return selected


def release_history_path() -> Path:
    """Constrain M3's resolver to the distinct v0.8 release tree."""
    require_release_storage_profile()
    path = m3.history_path()
    if (not isinstance(path, Path) or path.name != 'incident-history.sqlite3'
            or path.parent.name != 'Monitoring'
            or path.parent.parent.name != 'OnyxCore-v080-Release'):
        raise ReleaseBindingRefused('unexpected v0.8 release history location')
    return path


def run_explicitly_approved_api(wiring: ReleaseWiring, *,
                                build_authorizer: Callable = att.build_rechecking_authorizer,
                                run_bridge: Callable = bridge.run_authorized_cycles):
    """Prepare M1→M2→M3 bindings; NOT APPROVED for real host invocation.

    This Python API is intentionally not a CLI. It must only be invoked by a
    later security-reviewed launcher enforcing independent manifest origin,
    Windows ACLs, process containment, explicit enrollment and live consent.
    The default bridge takes the real native locks and runs live probes.
    All current tests replace run_bridge with an inert recorder.
    """
    if not callable(run_bridge):
        raise ReleaseBindingRefused('missing bounded monitoring bridge')
    config = read_reviewed_release_config(wiring)
    policy = bridge.BoundedRuntimePolicy(
        cycles=wiring.cycles,
        interval_seconds=config['monitoring_interval_seconds'],
    )
    authorize = make_release_authorizer(wiring, build_authorizer=build_authorizer)
    # The supplied config is *never* passed through M1.verify_local_context,
    # which intentionally rejects production. The source attestor is instead
    # called by the real consent authorizer before each probe and record.
    def verify_config(value):
        if value != config:
            raise ReleaseBindingRefused('release configuration changed')
        profile.validate_release_config(value)
    return run_bridge(
        policy, approved_sid=wiring.approved_sid, authorize_cycle=authorize,
        storage_profile=require_release_storage_profile, history_path=release_history_path,
        load_config=lambda: profile.load_release_config(wiring.config_path),
        verify_context=verify_config, probe=m1.run_once,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-inert', required=True, action='store_true')
    parser.parse_args(argv)
    print(json.dumps({'phase': 'release-binding', 'live_cli_enabled': False,
                      'user_enrollment_issued': False, 'manifest_pinned': False,
                      'handle_acl_attestation': False, 'job_containment': False,
                      'release_status': 'HOLD'}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
