#!/usr/bin/env python3
"""ONYX CORE v0.8.0 native LOW-integrity acceptance: OFFLINE CONTRACT ONLY.

This is a synthetic policy oracle, NOT a Windows security attestor. It cannot
launch processes, inspect the current access token, query native Windows APIs,
or issue approval. A future, separately reviewed native host harness must
obtain real OS evidence from a trusted parent and an isolated LOW worker.

Never use a simulated receipt to authorize a live probe, release, health
classification, consent change, deployment, monitoring task or notification.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json

LOW_INTEGRITY_RID = 0x1000
_ALLOWED_NATIVE = frozenset({'NativePathVerified', 'RouteMismatch',
                             'GatewayNotPreferred', 'Unavailable'})
_REQUIRED = (
    'source_attested', 'current_consent', 'parent_identity_attested',
    'low_integrity_token_verified', 'job_member_verified', 'job_no_breakaway',
    'job_exit_audited', 'bounded_memory_and_time', 'local_native_only',
    'no_state_writes', 'output_schema_pinned',
)
_REASONS = frozenset({'MissingBoundaryEvidence', 'InvalidBoundaryEvidence',
                      'NativeEvidenceUnavailable', 'SimulatedAcceptancePlanOnly'})


@dataclass(frozen=True)
class OfflineBoundary:
    """Caller-supplied mock facts. Absolutely not evidence about the real host."""
    source_attested: bool
    current_consent: bool
    parent_identity_attested: bool
    low_integrity_token_verified: bool
    job_member_verified: bool
    job_no_breakaway: bool
    job_exit_audited: bool
    bounded_memory_and_time: bool
    local_native_only: bool
    no_state_writes: bool
    output_schema_pinned: bool

    def __post_init__(self):
        for name in _REQUIRED:
            if type(getattr(self, name)) is not bool:
                raise ValueError('mock boundary field must be boolean')


@dataclass(frozen=True)
class OfflineAcceptance:
    """No success state grants actual native execution or establishes health."""
    decision: str
    reason: str
    simulated_native_classification: str
    schema_version: int = 1
    phase: str = 'native-low-integrity-offline-contract'
    simulation_only: bool = True
    release_status: str = 'HOLD'
    live_authorized: bool = False
    native_api_invoked: bool = False
    windows_health_claimed: bool = False

    def __post_init__(self):
        if (self.decision not in ('SimulatedEligible', 'SimulatedHold') or
                self.reason not in _REASONS or
                self.simulated_native_classification not in _ALLOWED_NATIVE or
                type(self.schema_version) is not int or self.schema_version != 1 or
                self.phase != 'native-low-integrity-offline-contract' or
                self.simulation_only is not True or self.release_status != 'HOLD' or
                self.live_authorized is not False or
                self.native_api_invoked is not False or
                self.windows_health_claimed is not False):
            raise ValueError('offline-only output contract violated')

        # A receipt must match a decision path the offline simulator can emit.
        if self.decision == 'SimulatedEligible':
            if (self.reason != 'SimulatedAcceptancePlanOnly' or
                    self.simulated_native_classification == 'Unavailable'):
                raise ValueError('inconsistent offline acceptance receipt')
        elif (self.reason == 'SimulatedAcceptancePlanOnly' or
              (self.reason in ('InvalidBoundaryEvidence', 'NativeEvidenceUnavailable') and
               self.simulated_native_classification != 'Unavailable')):
            raise ValueError('inconsistent offline acceptance receipt')

    def as_dict(self) -> dict:
        """Allow-listed fields only; never return raw callback/output content."""
        return {
            'decision': self.decision,
            'reason': self.reason,
            'simulated_native_classification': self.simulated_native_classification,
            'schema_version': self.schema_version,
            'phase': self.phase,
            'simulation_only': self.simulation_only,
            'release_status': self.release_status,
            'live_authorized': self.live_authorized,
            'native_api_invoked': self.native_api_invoked,
            'windows_health_claimed': self.windows_health_claimed,
        }


def simulate_acceptance(boundary: OfflineBoundary, native_classification: str
                        ) -> OfflineAcceptance:
    """Pure deterministic test oracle: no callbacks, imports, file or host access.

    A positive simulated decision means ONLY that an artificial test fixture
    satisfies the proposed admission invariants. It is NOT observed host state.
    """
    if type(boundary) is not OfflineBoundary:
        return OfflineAcceptance('SimulatedHold', 'InvalidBoundaryEvidence',
                                 'Unavailable')
    if type(native_classification) is not str or native_classification not in _ALLOWED_NATIVE:
        return OfflineAcceptance('SimulatedHold', 'InvalidBoundaryEvidence',
                                 'Unavailable')
    if not all(getattr(boundary, key) is True for key in _REQUIRED):
        return OfflineAcceptance('SimulatedHold', 'MissingBoundaryEvidence',
                                 native_classification)
    if native_classification == 'Unavailable':
        return OfflineAcceptance('SimulatedHold', 'NativeEvidenceUnavailable',
                                 'Unavailable')
    return OfflineAcceptance('SimulatedEligible', 'SimulatedAcceptancePlanOnly',
                             native_classification)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-inert', required=True, action='store_true')
    parser.parse_args(argv)
    # No live modes are implemented. This CLI never touches the OS networking stack.
    result = simulate_acceptance(OfflineBoundary(**dict.fromkeys(_REQUIRED, False)),
                                 'Unavailable')
    print(json.dumps(result.as_dict(), sort_keys=True, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
