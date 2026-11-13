# ONYX CORE v0.8.0 — Phase 18I1 Guarded Runtime Bridge

**Status:** Development-only integration; release HOLD. **Baseline:** `f8f10d6b4522644ce1d4a77ea096f2132355763c` (Phase 18H1 local commit). **Scope:** Three new files, zero changes to existing source, tasks, profiles, Pi, production or protected stores.

## What is actually integrated

The Python module `windows/monitoring/v080/OnyxGuardedRuntimeBridge.py` connects real M1 → M2 → M3 interfaces behind an explicit *caller-supplied* per-cycle authorization check and the Windows-native global mutex. It also holds the existing M2 local foreground mutex. Each bounded run is 1–20 cycles at 90–3,600 seconds; default interval 120 seconds.

**Invariants:** authorization is rechecked before acquiring locks, after locks, after context verification, before each diagnostic and again before each incident journal write. Any denial, mismatch, runtime failure, invalid count, invalid release profile or journal failure aborts without initiating the next cycle. M2 validates evidence and controls pacing. M3 atomically records sanitized incident state in the explicitly selected v0.8 release history. No catch-up overlap, no repair, tasks or notification send is added. No token or raw SSH output is persisted by the bridge.

## Explicit trust limitation

`authorize_cycle` is an integration seam, **not** a production authentication implementation. Passing a lambda that returns `True` is not evidence of permission. `approved_sid` must eventually originate from a separately verified grant; supplying an arbitrary SID string does not create trusted enrollment. This bridge MUST NOT be wired to an executable entrypoint, scheduler, service or deployment until the independent issuer, pinned verifier, revocation, source/ACL/handle attestation, session evidence and runtime containment requirements are implemented and independently accepted. The CLI accepts only `--check-inert` and cannot run live cycles. The existing M1 development-only guard is not weakened by this patch.

## Offline evidence

The new focused test suite has 21 cases. One case uses the actual M2 monitor loop and M3 SQLite incident lifecycle with a synthetic read-only probe and a temporary test database: verifies `Opened → Recovered`, two persisted checks, no open incident. It never performs Pi SSH/Windows network diagnostics. Negative cases include denied/revoked authorization before probe or write, invalid SID, storage profile, source verifier, native lock, persistence and incomplete execution. Tests use in-memory locks; Phase 18G5A already separately validated real Windows SID/mutex behavior within one session. Cross-session acceptance Phase 18G5B remains deferred and unverified.

## Remaining release blockers

- A real authority for enrollment and revocation (not the Phase 18H simulation-only grant), independently validated source/NTFS path and Windows session attestation.
- Approved production execution posture: signed release/configuration allowlist, process-tree containment and finite worker deadlines. No design shortcut silently closes SEC-01/02/03/09/10.
- Live operator-authorized integration acceptance on SQUALL, opt-in alert delivery, incident durability, startup/stop/rollback and evidence capture. Production v0.7.0 must remain reversible until final approval.
- The release checklist and security register must be updated from actual operator evidence; 1,000+ offline tests alone are not operational acceptance.

**Security note:** A Python caller with local code execution can construct arbitrary callbacks. This module does not claim to enforce an independent trust boundary on its own. Do not declare SEC gates closed by this integration alone.
