# ONYX CORE v0.8.0 — R1 Offline Windows Identity, ACL and Source-Trust Contract

**Scope:** SEC-01 (operator consent/revocation), SEC-02 (Windows token, NTFS ACL, final-path/source attestation), SEC-09 (symlink/junction security gap).  
**Development parent:** `8673a5cd3e67a966fa88baf28dccc778db54c6c5` on `feature/v0.8.0-continuous-monitoring`.  
**Release status:** **NO-GO for live unattended monitoring.** No live implementation, enrollment, tasks, probes, notifications or repair are provided by R1.

## Purpose and integration

The existing M1 `OnyxUnattendedPolicy.py` and M2B `OnyxOfflineAuthorization.py` verify *synthetic JSON consistency*, **not** Windows identity or operator intent. R1 adds a stricter **pure, offline** proposal for a future OS-attested trust boundary. Its sibling module `OnyxOfflineWindowsTrustContract.py` has no Windows API, network, disk, process, scheduler or enrollment interface. It accepts only three **caller-provided synthetic byte strings**: hypothetical approval, pre-operation snapshot, post-operation snapshot. All can be forged by a caller, so even a valid result **never** grants runtime authority. The CLI only accepts `--check-inert` and returns a constant denial.

### Future OS-attestor interface (design only; **NOT implemented**)

A separately authorized Windows component would have to acquire **independent**, OS-backed and handle-bound evidence for: (1) interactive user token/session and SID; (2) full DACL ownership, effective rights and inherited ACEs for each ancestor and target, including possible write/rename/delete/reparse rights; (3) resolved final paths and file/volume identities on opened handles; (4) source/config hash and clean-tree identity on the actually executed bytes; (5) independently recorded grant, consent and generation-monotonic revocation. It must revalidate after the bounded check and **before** any operation. R1 merely models some of those fields and a change/refusal policy, without asserting that the claimed evidence is authentic or sufficient for Windows privilege decisions.

No application is allowed to treat `assess_synthetic_trust()` as a live authorization provider. There is **no** `authorize`, `enable`, `run`, `enroll`, `repair`, `probe`, `publish`, `schedule` or credential-writing path. Avoid shortcuts based on a JSON `authenticated` or `approved` value, a matching Git SHA, an accessible SSH key, or a scheduled-task name.

## Data-only contract

- Grant: schema v1, `simulation_only=true`, `approval_method=SyntheticOnly`, bounded synthetic ID, account and SID; fixed-branch commit, expected tree/config SHA-256, monotonic revocation floor, UTC expiry, exact seven M2B-aligned resource roles.
- Resource roles: `worktree`, `config`, `enrollment`, `revocation`, `state`, `python`, `ssh`. Synthetic source is constrained to `D:\github_repos\onyx-core-v080`; Python is `C:\Python313\python.exe`; hypothetical enrollment/state is under a v0.8-only path. No actual v0.8 state directory is created.
- Snapshots: mock provider only, ordered sequences `1` and `2`, canonical UTC timestamps spaced more than zero and at most 90 seconds, unchanged token/source/consent/revocation/path structures. A full before/after equality check refuses a simulated race.
- Paths: reject UNC/device/drive-relative references, `..` or `.`, environment expansion, alternative data streams, ambiguous components, v0.7 state and production-source paths. Compare exact expected lexical/final paths, synthetic volume/file identities, reparse tags and a complete synthetic ancestor chain. Reject missing/unverified DACLs, foreign owners, untrusted or duplicate writers, and claims of inherited-untrusted write permission.
- Trust claims: explicit `windows_authenticated=false`, `authoritative=false`, `approved_by_windows=false` are required; claims of live status or forged extra keys are rejected. Success reports `runtime_enabled=false`, `live_probe_authorized=false`, `enrollment_authorized=false`, `task_creation_authorized=false`, `store_modified=false` and `repair_action=None`.
- Strict input: bounded UTF-8 JSON, duplicate-key rejection, no non-finite numbers, exact schema with no unknown fields, bool-vs-int guards; tests cover expired/revoked/stale/mutating hypothetical consent and source.

**Important limits:** A fixture can claim `reparse_tag=0`, safe DACLs and correct handles without consulting Windows. Neither the path string model nor its SHA-256s authenticate the operating system, underlying files, identity, permissions, or revocation. Effective NTFS rights in particular require a real Windows security descriptor/access check that accounts for all applicable groups, deny/allow order, inherited ACEs, rights to replace ancestors, and handle lifetime. Pure mocks **cannot** close SEC-01/02/09 for a live release.

## Test and review contract

- R1 ships **85 synthetic-only adversarial Python tests**. Tests use in-memory snapshots, a fixed module import, and a bounded subprocess only to check the inert CLI. No test creates symbolic links, launches a diagnostic, changes tasks, reads host security data, or accesses production or the v0.7 stores.
- SQUALL integrated gate: exactly **386** tests = **301** pre-existing M1–M4 tests + **85** new R1 tests. Require all 61 M3, all 64 M4, 85 R1 and both real-reducer compatibility tests, zero failures/errors, no skips other than the known M2A symlink-permission skip. This host gate is acceptance of **offline development**, not of live NTFS behavior.
- SEC-09 remains **OPEN**: actual reparse-point/junction/symlink attacks under Windows require separately authorized testing with appropriate privileges, without modifying production tasks or monitoring history.
- A later implementation will require independent Windows API implementation and genuine hostile-environment tests before SEC-01, SEC-02 or SEC-09 can be closed. The future live attestor must not reuse these mock objects as authentic evidence.

## Required preservation

- Production `D:\github_repos\onyx-core` `main` at `06ec81582791fc797f74ad294195d68b2023cb66`, original collector backup SHA-256 `59E1EE7205EFBEDB79BA3D0DCB4C9FD0D8EBD3DFA4D5D9313BBD8325976830EB`.
- Both `%LOCALAPPDATA%\OnyxCore-v070-{Release,Development}\Monitoring` retain their exact five existing files and audited hashes, including `incident-state.json.lock`; do not create, rewrite or delete anything there.
- Existing SQUALL root Scheduled Tasks `LibreHardwareMonitor`, `ONYX CORE - Local Gateway`, `ONYX CORE - Telemetry Collector`: exported definitions read-only and compared pre/post. Task state is not a definition.
- R1 installer writes **exactly three new files** in the isolated development worktree, with no overwrite, staging or commit. It executes only the Python synthetic suite and inert CLI checks. No production changes, Git remote action, live probe, task action, enrollment, notification, or repair.

## SQUALL R1 host acceptance — 2026-11-10

**Checkpoint:** PASS for *offline synthetic development only*; verified against local development parent `8673a5cd3e67a966fa88baf28dccc778db54c6c5` on `feature/v0.8.0-continuous-monitoring`.

- Package integrity and Windows PowerShell 5.1 parsing verified before execution; exact three-file ZIP validated by names, sizes, and SHA-256.
- Exactly three R1 files installed without overwrite: this contract, `test_offline_windows_trust_contract.py`, and `OnyxOfflineWindowsTrustContract.py`.
- SQUALL integrated suite: **386 tests run, 385 passed, 1 skipped, 0 failures/errors**. The 85 R1 adversarial tests passed; 61 M3, 64 M4, and both genuine reducer-compatibility tests also passed.
- Sole skip: `test_offline_supervisor.SyntheticSupervisorTests.test_rejects_symlinked_fixture_directory` — `symlink creation not permitted`; this does **not** constitute a successful real Windows symlink test.
- Disabled M1 example and M2A–M4/R1 inert CLI checks passed. R1 reported `runtime_enabled=false`, `identity_authenticated_in_windows=false`, `windows_acls_verified=false`, `revocation_authoritative=false`, `enrollment_authorized=false`, and `live_probe_authorized=false`.
- Installer's final checks reported unchanged production and original collector backup, both exact five-file protected v0.7 monitoring histories, and the three existing Scheduled Task definitions.
- Git remains at pinned M5 commit with **exactly three untracked R1 additions; none staged or committed**. No push, merge, tag, release, deployment, live probe, elevation, enrollment, notification, repair, or task modification occurred in the checkpoint.

**Security disposition:** SEC-01, SEC-02 and SEC-09 are **still OPEN**. Synthetic acceptance is not real Windows identity, NTFS ACL, filesystem handle, operator consent or revocation attestation. **Live unattended monitoring remains NO-GO.** Staging requires separate operator approval; committing requires an additional approval.

## Decision and subsequent approvals

**R1 offline acceptance PASS** (only after SQUALL validates) means the source contract and mocks meet this defined set of tests. **SEC-01, SEC-02 and SEC-09 still BLOCK live deployment.** A separate documentation/code review and staging approval, then a **separate local commit approval**, are required. Any controlled real-Windows security assessment, elevation, enrollment, or runtime test also needs its own explicit authorization.
