# ONYX CORE v0.8.0 — M2B Offline Authorization Boundary

**Scope:** Development-only, synthetic operator identity and authorization facts.
**Baseline:** `6fb4001a9b270a0631be129aa1310335c36f7970` (`feature/v0.8.0-continuous-monitoring`).
**Status:** Sandbox and SQUALL offline tests passed; staged review pending. **NOT a production authorization mechanism.**

## Nonnegotiable execution boundary

- `windows/monitoring/v080/OnyxOfflineAuthorization.py` is an **offline policy and temporary-fixture reader only**. Its one CLI action, `--check-inert`, prints fixed capability-denial JSON. It **cannot** enroll, revoke, probe, schedule, launch a worker, execute PowerShell/SSH, change ICS, create an incident store, or write a user authorization file.
- This module is intentionally **not imported by a live supervisor**. It is **not** an independent trusted Windows attestor. Its inputs can be fabricated by the caller; a successful evaluation **never** conveys an execution capability.
- The existing v0.7.0 manual read-only runner, collector, release/development histories, and running scheduled tasks are not touched. The original telemetry collector backup is not touched.
- M1's `operator_approved: true` JSON property is **not authentication**. M2B's `operator_consent_observed` assertion is also **not authentication**. An operator-owned or attacker-written file must never become the basis for live permission by asserting these booleans.

## M2B inputs and checks

`assess_simulated_preflight(config_bytes, enrollment_bytes, revocation_bytes, facts_bytes)` is pure and applies the reviewed M1 schema plus M2B simulation gates:

| Input | Offline-only rule | Real-world proof remaining |
|---|---|---|
| Config | Exact M1 unattended config schema, test-only enabled copy, SHA-256 bound to grant and consent assertion | Approved deployed config path, restricted owner/DACL, immutable digest at launch |
| Enrollment | M1 data fields, account and commit match, SHA-256 bound to independent simulated consent and revocation | Operator approval captured via a separate trusted enrollment workflow, protected file location, authentic principal |
| Identity | Simulated interactive account `DOMAIN\\user` and SID, strict boolean flags | Verified Windows token SID, logon/session type, Task Scheduler principal, process integrity and access token |
| Source | Simulated expected branch, commit SHA, clean source, matching approved/observed component SHA-256 | Hash of **actual executable bytes** and imported modules, pinned installed source, trusted path/ACL, no worktree races |
| ACLs | Seven role snapshots: `worktree`, `config`, `enrollment`, `revocation`, `state`, `python`, `ssh`; no reparse claim, DACL checked flag, owner/write SIDs limited to operator/SYSTEM/Admin | Inspect real NTFS DACLs, *all parent directories*, inherited ACEs, owner, deny/allow semantics, junctions and race-safe handles |
| Revocation | Separate simulated JSON record bound to exact grant digest, monotonic generation floor, `revoked=false` | Trusted write-protected revocation authority, authentic tamper-evident checkpoint, rollback prevention across restarts |
| Paths | Canonical drive-absolute simulated Windows paths, no UNC/ADS/traversal/v0.7.0 history references | Handle-based canonicalization and final-path verification on Windows, robust reparse-point rejection |

`assess_temporary_fixture(Path(...))` reads **exactly four** bounded documents (`config.json`, `enrollment.json`, `revocation.json`, `facts.json`) from a test-specific, direct child of the OS temporary directory with prefix `onyx-v080-m2b-`. It rejects missing/extra entries, symlinks/junctions at the fixture directory and files, and invalid schemas. Fixture files are **created only by the tests** and removed by their temporary-directory context. The module performs **no writes** and never reads `%LOCALAPPDATA%\\OnyxCore-v080\\Authorization` or protected v0.7.0 locations.

### Data-only result

Even a fully matching synthetic fixture returns:

```json
{
  "simulated_preflight": "EligibleDataOnly",
  "simulation_only": true,
  "identity_authenticated_in_windows": false,
  "windows_acls_verified": false,
  "revocation_authoritative": false,
  "runtime_enabled": false,
  "live_probe_authorized": false,
  "task_creation_authorized": false,
  "store_modified": false,
  "repair_action": "None"
}
```

The CLI's `--check-inert` output is a smaller fixed denial statement; it does not read any fixture.

## Required denial paths

M2B tests refuse missing consent, enrollment/config changes, nonmatching Windows account, invalid SID, noninteractive/synthetic authentication flags, dirty/wrong-branch/redirected source, altered component digest, untrusted ACL owners or writers (`Everyone`/`Users`), duplicate paths, unchecked/inherited DACL snapshots, v0.7.0 paths, UNC and alternate data streams, revoked grant, stale revocation generation, changed grant digest, unknown/duplicate JSON keys, nonfinite/invalid input, invalid temp directories, and unauthorized CLI options.

The checks are **data-model tests**, not proof that SQUALL's actual ACLs, authentication, Git state, or Windows process lifetime are safe. A malicious caller could forge all four temporary JSON files. A real approval requires separate authenticated attestation and explicit deployment authorization; this code must never be promoted merely by flipping `enabled`.

## Further engineering required before any live diagnostics

1. Author and independently test a Windows-specific identity/ACL attestor with verified SID and token type, real NTFS security descriptors, process image identity, path ancestry/reparse checks, and source digest verification; avoid user-controlled self-attestation.
2. Implement a separate operator enrollment and revocation protocol with auditable consent, protected ACLs, monotonic anti-rollback persistence and **per-cycle** revalidation. Define an explicit cancel/disable action that fails closed.
3. Close time-of-check/time-of-use gaps using trusted open handles or equivalently strong source/config validation. A clean Git worktree alone is insufficient against concurrent modification.
4. Reconcile the eventual production source/branch model: M2B deliberately models the **development branch** and does not claim that this branch is a production deployment identity.
5. Integrate a new v0.8.0-only **read-only** evidence adapter, with isolated state, and implement a safe Windows atomic-start-and-contain mechanism. Do **not** schedule or bypass the v0.7.0 manual release collector, which writes protected history.
6. Keep evidence absence distinct from confirmed ICS faults, use the existing v0.7.0 reducer semantics, and test crash-safe stores and alert deduplication in later milestones. Proposed 120s poll interval / 90s cycle deadline are not operationally validated.
7. Real enrollment, live probes, Task Scheduler changes, Windows/ICS/SSH configuration, production changes, Git push/merge/tag and network repair all require separate operator approvals; none are included in M2B.

## Offline acceptance commands (development only)

```powershell
$Dev = 'D:\github_repos\onyx-core-v080'
$Python = 'C:\Python313\python.exe'
& $Python -B (Join-Path $Dev 'windows\monitoring\v080\OnyxOfflineAuthorization.py') --check-inert
if ($LASTEXITCODE -ne 0) { throw 'M2B inert CLI failed' }
& $Python -B -m unittest discover -s (Join-Path $Dev 'tests\monitoring\v080') -p 'test_*.py' -v
if ($LASTEXITCODE -ne 0) { throw 'Offline monitoring suite failed' }
```

**Local preparation:** 138/138 integrated Python 3.13 tests passed on the development environment. No tests run against real network, identity or ACL state.

**SQUALL offline acceptance (2026-11-10): PASS.** Windows PowerShell 5.1 / Python 3.13 execution reported `Ran 138 tests` and `OK (skipped=1)`: 137 passed, 1 skipped, 0 failed. All 61 new M2B offline authorization tests passed. The only skip was M2A's `test_rejects_symlinked_fixture_directory` because creating a test symlink was not permitted. Both M2A and M2B inert CLIs reported runtime execution and live probing disabled; M2B also reported Windows identity, Windows ACLs and revocation authority unverified. The installer confirmed exactly three new untracked M2B development files, production and original collector backup unchanged, protected v0.7.0 incident histories preserved, and no enrollment, commit, push, merge, scheduling, deployment or repair. This is operator-provided SQUALL evidence, not production authorization.

**Stage gate:** Record this evidence and inspect the three-file staged diff before authorizing any *local* M2B commit. No real authentication, enrollment, live monitoring or scheduling is included.
