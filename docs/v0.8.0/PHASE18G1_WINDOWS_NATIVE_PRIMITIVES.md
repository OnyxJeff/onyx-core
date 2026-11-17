# ONYX CORE v0.8.0 — Phase 18G1: Windows native identity and exclusion primitives

**DEVELOPMENT ONLY. v0.8.0 release HOLD. No live runtime enrollment.**

Parent checkpoint: `60df17aceceb6cfdb6e3f21f290fcfb779940848` on `feature/v0.8.0-continuous-monitoring`.

## New isolated module

`windows/monitoring/v080/OnyxWindowsNativeAdmission.py` implements two *unwired* Windows-native primitives. It does not modify M1–M5 or call the Phase 18C fixture supervisor.

1. `current_process_sid()` reads the user SID from the process access token using `OpenProcessToken`, `GetTokenInformation(TokenUser)` and `ConvertSidToStringSidW`, never `whoami`, a subprocess, environment claims or Python usernames. It is only called by an explicitly invoking caller.
2. `_secure_global_mutex()` uses `Global\OnyxCoreV080ReleaseIncidentRecorder`, a protected DACL with SYSTEM and the approved user SID, non-inheritable handle, `CreateMutexW` initial ownership, strict rejection of `ERROR_ALREADY_EXISTS`, and release on exit. It performs no filesystem writes and is never called by the command line or existing runtime.
3. `verified_sid_mutex(expected_sid)` compares the process SID with a supplied expected SID **and refuses to proceed if they differ**, then acquires exclusion. **The expected SID must eventually come from a separately verified trusted enrollment source.** Passing the current SID as `expected_sid` without a trusted source is *not* authorization.

The only CLI operation is `--check-inert`; it does not invoke token inspection or the mutex. No production task or live process is created.

## Limitations and no-go criteria

- An in-memory identity comparison **does not validate a signed enrollment grant**, ACL provenance, source tree integrity, executable hashes, revocation, or the currently active logon session. No M1 development restriction is changed.
- `Global\` namespace spans logon sessions but is not by itself a proof of cross-session exclusion on the target host. A controlled same-user second-session integration test is still required before release. A malicious pre-created object can deny startup; no attempt is made to bypass this fail-closed condition.
- Windows API behavior is **not tested in this Linux review environment**. Unit tests use injected synthetic token and mutex adapters. Windows SQUALL smoke testing may be separately authorized; no live probes are necessary for the identity/lock smoke test.
- No live M1/M2/M3 integration, no process-tree supervision, no task registration, no notification watcher, no release-profile incident storage creation, no changes to production v0.7.0.
- Future phases must obtain an authoritative expected SID and source/grant provenance, revalidate revocation every cycle, attest process/worker identity and source, verify actual global mutex behavior, protect state ACLs and implement auditable lifecycle startup/rollback.

## Offline acceptance

Run `python -B -m unittest discover -s tests/monitoring/v080 -p test_phase18g_windows_native.py -v` against the development worktree. Existing v0.8.0 regression coverage must also pass before staging/commit; tests must not launch live monitoring.

Microsoft reference: [CreateMutexW](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-createmutexw) and [ConvertStringSecurityDescriptorToSecurityDescriptorW](https://learn.microsoft.com/en-us/windows/win32/api/sddl/nf-sddl-convertstringsecuritydescriptortosecuritydescriptorw).
