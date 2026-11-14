# ONYX CORE v0.8.0 — RC1 Operational Launcher / Acceptance Contract

**Scope:** logged-on-console-user foreground operation on SQUALL; USB/ICS diagnostics only. **Status: RC implementation under test; no production authorization and no live acceptance yet.**

## Functionality wired

- A reviewed, admin-installed source tree is required at `C:\Program Files\OnyxCore\v0.8.0`. The Python executable is pinned to `C:\Python313\python.exe`, and CLI execution requires isolated `-I -B` mode.
- An independently administrator-pinned `C:\Program Files\OnyxCore\v0.8.0-release.sha256` anchors the canonical `release-approval.json` document (which identifies an approved Windows SID, source commit, strict v0.8 release config, and **16** source files). The RC builder's output in Downloads is **not** itself an approved trust anchor. The digest must be independently reviewed and installed by a separate explicitly elevated operation.
- Win32 handle-backed inspection rejects redirected filesystem entries, unprivileged write ACEs, nonprivileged file owners, and unsupported ACL ACE types on the code and approved metadata. SHA256 checks protect the release runtime source and config; reauthorization repeats checks before probes/records and during each wait.
- Explicit user-scoped consent issues a bounded Windows Generic Credential; both stored source/config binding and a local console session are checked. The grant is revocable. **Windows Generic Credentials can be modified by the same Windows user:** this is a known accepted-or-mitigated release threat-model decision, *not* evidence of independent signing.
- `--run-count N --approve-live-read-only` (N=1..20) invokes the existing M1→M2→M3 runtime in the foreground only, setting the release history-store environment. A Job Object contains PowerShell and SSH subprocess trees; the two-second intercycle consent checks stop a revoked run before the next cycle. An active worker can continue until its bounded timeout.
- There is **no** unattended task, auto-repair, automatic notifications, background service, auto-enrollment, elevated launcher, or production deployment in this source patch.

## CLI shape — documentation only; do NOT run before the approved protected install

```powershell
$Python = 'C:\Python313\python.exe'
$Operator = 'C:\Program Files\OnyxCore\v0.8.0\windows\monitoring\v080\OnyxV080ReleaseOperator.py'
& $Python -I -B $Operator --audit-installed
& $Python -I -B $Operator --enroll-read-only --approve-enrollment --expires-minutes 60
& $Python -I -B $Operator --run-count 2 --approve-live-read-only
& $Python -I -B $Operator --revoke-read-only --approve-revocation
```

## Acceptance gates: all must pass before v0.8.0 release

1. Full offline regression and exact five-file local commit; production v0.7.0 and all four monitoring stores/tasks unchanged.
2. Git-archive RC source + canonical approval/manifest built from that committed HEAD. Independently verify archive, approval digest, approved SID, all file hashes and identities.
3. Explicit administrator-approved *inactive* installation with controlled NTFS owner/DACL and an independently pinned approval anchor; verify native handle-backed checks on SQUALL. No v0.7.0 modifications.
4. Logged-on-user read-only `--audit-installed`; then separately approve bounded consent enrollment, 1–2 real diagnostic/incident cycles, revocation and stop; demonstrate release journal isolation and no repairs or notifications.
5. Dashboard and optional notification behavior evaluated separately. **No opt-in notifications are enabled by this launcher**; if notifications are required to satisfy the v0.8.0 release scope, they remain an open feature/acceptance gate.
6. Rehearse safe uninstall/rollback of inactive/active v0.8 code while preserving histories; ensure v0.7.0 still runs. Review exceptions and give separate authorization for merge/tag/production cutover and GitHub publication.

## Known limitations

- Native Windows security APIs and Job Object behavior need SQUALL-specific acceptance; synthetic unit tests are not sufficient.
- Absolute protection against malware running as a local administrator, arbitrary same-user Credential Manager tampering, arbitrary executable/DLL injection by administrators, and multiple interactive Windows sessions is out of scope. Cross-session smoke G5B is deferred.
- The read-only source attestor hashes files by path after a handle-backed ACL check. It is not a guarantee of atomic file-content snapshots against a malicious administrator racing the checks.
- This RC source patch adds no delivery integration between the notification watcher and the operational launcher; notifications remain explicitly disabled.
- No customer-visible 'ready for release' or v1.0.0 claim until live and rollback evidence exists.
