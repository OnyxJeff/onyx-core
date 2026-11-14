# ONYX CORE v0.8.0 — R3 Revocation-Aware Foreground Monitoring

**Development checkpoint:** `f14807909890dfe203eb4d88f4c19edbc77cd1ac`  
**Release disposition:** HOLD; not yet a production startup/consent issuer or deployment authorization.

## Changed operational integration

The existing `OnyxV080ReleaseBinding.py` now passes a concrete M2 monitor-loop adapter to `OnyxGuardedRuntimeBridge.run_authorized_cycles`. It calls **the real `OnyxContinuousMonitor.run_monitor`** with a checked sleeper rather than constructing another scheduler. During the wait between cycles, the adapter invokes the already existing per-cycle authorizer **before and after each at-most-two-second sleep slice**. A denied grant or failed native attestation raises and exits the runtime bridge, releasing its locks. `KeyboardInterrupt` is not swallowed.

Existing bridge checks still occur before the first probe, before every probe, and before every SQLite journal write. No notifications, repairs, enrollment issuance, scheduled task registration, or automatic startup are introduced. M1's Windows Job Object runner remains the only release-mode subprocess runner. The original development CLI is unchanged.

## Important limits

* This code only improves **intercycle wait-time revocation**, not immediate cancellation of an already-running Windows or SSH diagnostic. A child process remains bounded by M1's existing worker timeout and its tested Windows Job Object behavior.
* The callback checks grant and source evidence only when called. Its caller still must establish a real user session, protected installation, pinned trusted manifest and independently approved enrollment. The current CLI is inert.
* This is not a Windows native acceptance test of revocation or startup. Windows behavior must be evaluated in a separately authorized, bounded operational acceptance.
* Synthetic test callbacks must never be used as production authorization.
* A same-account Windows Generic Credential is writable by processes of that user; the release threat model must explicitly accept or mitigate this before production approval.

## Validation

Review environment: 12 new revocation tests, 19 release binding tests, 21 guarded bridge tests, and 15 R2 job containment tests passed (**67 total, one skipped**). Run the full regression on SQUALL **before commit**. Production v0.7.0, source backup, four protected monitoring histories and Scheduled Tasks must remain unchanged.

## Release gates not closed

Protected binary/config/manifest installation and native filesystem trust, approved consent/enrollment/revocation commands, the actual Windows foreground launcher and shutdown, sustained operational acceptance, notifications opt-in and recovery, rollback/cutover, PR/merge/tag/deploy/publish. None are implicitly authorized by installation of this development patch.
