# ONYX CORE v0.8.0 — Phase 18C: Offline supervision foundation

**Status: DEVELOPMENT-ONLY, INERT. Release: HOLD.**

Baseline: `98e5eb0a5108e7805d1d5b3806195cf01082e109` on `feature/v0.8.0-continuous-monitoring`.

This is a small, verifiable **simulation-only** step toward production supervision. It does not replace the existing R1–R6 contracts or pretend to close their documented SEC-01–SEC-10 findings.

## Added interfaces

- `OnyxOfflineProductionSupervisor.py`: strongly typed, bounded loop with caller-injected synthetic admission, mock work, monotonic clock, sleep, and exclusive-adapter hooks. Admission is re-evaluated before **every** simulated cycle. Invalid admission, backward clocks, missing hooks, and lock refusal fail closed. Cycle overruns do not create catch-up work.
- `test_phase18_supervision.py`: offline regression tests for negative admission, simulated revocation, overlap refusal, invalid intervals, no catch-up, and failure propagation.

The command-line surface is **only** `--check-inert`. It creates no state and cannot run actual monitoring. The default exclusive hook is deliberately inert and **must not** be used for production exclusion.

## Not implemented and not authorized

1. Genuine Windows identity/session authentication, trusted source/ACL handle checks, authoritative enrollment and revocation, signed grant issuance.
2. Cross-session locking, process-tree containment, start-suspended worker launch, shutdown and crash recovery.
3. Any integration with M1/M2/M3 live execution, scheduled tasks, actual Pi/USB probes or protected v0.7 histories.
4. Production dashboard cutover, release-profile history creation, notification watch, enrollment or repair.

The next Phase 18 step is a separately reviewed Windows-native trust and cross-session exclusion adapter. Until verified, **live production monitoring is NO-GO**.
