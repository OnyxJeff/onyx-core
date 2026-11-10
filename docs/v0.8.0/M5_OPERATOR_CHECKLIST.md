# ONYX CORE v0.8.0 — M5 Operator Checklist (Offline Only)

**Operator host:** SQUALL, Windows PowerShell 5.1, `C:\Python313\python.exe`.  
**Development:** `D:\github_repos\onyx-core-v080`, `feature/v0.8.0-continuous-monitoring`, exact HEAD `27071dcdbb41616096107bfa3a7fcc8be337b7ce`.  
**Production to preserve:** `D:\github_repos\onyx-core`, `main` at `06ec81582791fc797f74ad294195d68b2023cb66`.  
**Authorized:** Offline documentation installation and tests. **Not authorized:** Git commit/staging, live probe, task change, enrollment, notification, repair, push/merge/tag/deploy/release.

## A. Before running the installer

- [ ] Save `ONYX_CORE_v0.8.0_M5_Readiness_Docs.zip` and `ONYX_CORE_v0.8.0_M5_Installer.zip` to Downloads; extract the single PowerShell script from the installer ZIP to Downloads.
- [ ] Execute the supplied **checksum-verifying wrapper**, not a modified script. Confirm its PowerShell syntax check passes.
- [ ] Confirm production `main` and development feature HEAD are exactly as above; **no** staged, tracked or untracked development changes exist.
- [ ] Confirm all 19 M1–M4 known source/document/config hashes and genuine v0.7.0 tracked reducer are present.
- [ ] Confirm original collector backup and both **five-file** protected v0.7.0 histories (including `.json.lock`) pass SHA-256 checks.
- [ ] Confirm existing ONYX CORE / LibreHardwareMonitor Scheduled Task definitions are snapshotted read-only, not started, stopped or edited.
- [ ] Confirm no M5 target files exist; the installer refuses overwrite and redirected parent paths.

## B. Offline test acceptance

- [ ] Verify the exact four-member M5 ZIP and every file SHA-256 **before writing**.
- [ ] Confirm **exactly four Markdown files** are installed under `docs/v0.8.0/`, and no other repository content is changed.
- [ ] Confirm `monitoring.unattended.example.json` remains **disabled** with no live entitlement, and every M2A/M2B/M2C/M3/M4 CLI still refuses live/scheduling/repair capability.
- [ ] Discover **301** offline tests: M3 61, M4 64, with the genuine checked-in v0.7.0 reducer compatibility cases present.
- [ ] Confirm `Ran 301 tests`, `OK` (possibly `skipped=1` only for the known M2A symlink creation restriction), zero failures/errors, all M3/M4 tests passed.
- [ ] Recheck production, protected directories, collector backup, pinned sources and read-only scheduled-task XML snapshots **after** tests.
- [ ] Confirm Git shows **exactly four untracked M5 documentation files**, nothing staged, unchanged `27071dc` HEAD.

## C. Stop conditions / reporting

- [ ] On **any** checksum, source, task, test, path, inventory or state mismatch: **STOP**. Do not rerun an installer after partial file creation. Do not use Git reset/clean, remove lock files or alter monitoring history to force a pass.
- [ ] Report the final PowerShell transcript and any failing gate. Record `Ran 301 tests`, skip identity, `git status`, protected-inventory acceptance and task-definition preservation from the script's output.
- [ ] If all pass, review `M5_INTEGRATION_SECURITY_AUDIT.md`, `M5_RELEASE_READINESS.md`, `M5_DEPLOYMENT_ROLLBACK_PLAN.md` and this checklist. Identify whether the **live NO-GO** verdict and ten security findings are reflected accurately.
- [ ] Ask separately before **staging** for review, then separately before **one local commit**. No commit authorization is inferred from M5 development approval.

## D. Subsequent independent gates (do not perform under M5 approval)

- [ ] Close real identity, ACL, source, consent/revocation and process containment blockers.
- [ ] Implement and test new v0.8-only read-only evidence, atomic state and durable deduplication; avoid protected v0.7.0 release collector.
- [ ] Validate notification and timing/restart/rollback behavior in a separately authorized environment.
- [ ] Obtain distinct approvals for any scheduling, live diagnostic, enrollment, notification, deployment, production Git operations, publication and release.

**Completion rule:** M5 host success means **offline documentation and regression validation only**. It cannot turn the v0.8.0 synthetic operator view into a functioning unattended monitor.
