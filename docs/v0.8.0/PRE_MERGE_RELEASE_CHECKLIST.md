> **November 17, 2026 scope decision:** v0.8.0 is approved for a **code-only GitHub release**, not deployment. The operational HOLD recorded below remains active for protected installation, native host acceptance and unattended runtime. See [CODE_ONLY_RELEASE_DECISION.md](CODE_ONLY_RELEASE_DECISION.md).

# ONYX CORE v0.8.0 — Pre-merge release checklist

**Decision:** HOLD for merge and publication pending protected-install and end-to-end operational acceptance.  
**Review date:** November 16, 2026.  
**Draft PR:** [#18](https://github.com/OnyxJeff/onyx-core/pull/18) into `main`.  
**Last validated executable commit:** `e1b1d596513fd04ef7434b7a587e8f3381b61300` (subsequent release-documentation commits do not change executable code).  
**Protected production baseline:** `v0.7.0` / `06ec81582791fc797f74ad294195d68b2023cb66`.

This document is a pre-merge evidence register, not release authorization. The release is **opt-in foreground read-only monitoring**, *not* an automatically installed monitor, scheduled notification service, or network repair service.

## 1. GitHub and candidate provenance

- [x] Draft PR #18 opened against `main`; no merge.
- [x] Candidate executable commit `e1b1d596513fd04ef7434b7a587e8f3381b61300` pushed to the PR branch.
- [x] Production `main` remained at `06ec8158...` during the GitHub review.
- [x] All 135 PR-changed files enumerated and the PR history reviewed (35 candidate commits before docs-only release preparation).
- [x] Existing published `v0.7.0` release retained; no `v0.8.0` or `v0.8.0-rc.1` tag found.
- [x] Versioned draft release notes updated with the actual candidate scope and validation.
- [ ] Record the *final* merged commit after approval; do not tag or publish before merge.

**CI disclosure:** No GitHub Actions workflow and no GitHub check run were found for the candidate. The host test results below are user-provided SQUALL console evidence, not GitHub CI.

## 2. Completed host verification (evidence-based)

- [x] SQUALL final offline suite after accounting fix: **1,410 discovered, 1,400 passed, 10 expected skips, zero failures/errors**, as reported by the guarded runner.
- [x] Synthetic native worker/Job containment: **5/5** (low integrity, hard timeout, revocation, descendant exit, scratch integrity).
- [x] Native low-integrity exact-path audit: **8/8** locations; **40** write-capable open requests denied; protected file hashes unchanged.
- [x] R7 source-evidence archive: **76/76** collected files verified at the preceding `56ee3d5` candidate checkpoint; final accounting source amendment `e1b1d596513fd04ef7434b7a587e8f3381b61300` separately hashed and tested on SQUALL.
- [x] Production v0.7.0 Git state and protected v0.7/v0.8 histories reported unchanged by the final regression runner.

**Evidence boundary:** Those results establish offline and synthetic acceptance; they do **not** prove that the current administrator-protected installation is source-equivalent to the final candidate or that a real foreground monitoring session passed.

## 3. Blocking pre-merge operator acceptance — SQUALL

- [ ] Freeze the source inventory from the *final candidate commit* and independently review all **19** `OnyxWindowsRuntimeAttestation.REQUIRED_FILES`, release configuration, and exact SHA-256 manifest. The older RC 16/18-file inventories and approval digest must not be reused.
- [ ] Reconcile the administrator-owned `C:\Program Files\OnyxCore\v0.8.0` installation with that reviewed inventory. The prior exact-path audit explicitly reported **installed source differs from development**. Preserve existing release journal, config, approval artifacts until an independently reviewed replacement plan exists; no in-place unguarded overwrite.
- [ ] Independently approve and pin a new canonical `release-approval.json` digest in `C:\Program Files\OnyxCore\v0.8.0-release.sha256`, with protected owner/DACL/integrity and correct source commit/approved SID. Never put the SID, credentials, or mutable approval document into a public PR.
- [ ] SQUALL logged-on-console-user `--audit-installed` passes with the final protected source/config and correct approval anchor. Record only redacted outcomes/hashes.
- [ ] Separately authorize and observe 1–2 bounded **real read-only** Windows/Pi diagnostics using the protected foreground operator, confirm journal isolation and accurate cycle/receipt accounting, verify revocation, and stop the operator. No automatic repair, task, or notification authorization.
- [ ] Check the explicitly launched local monitoring dashboard (release port `127.0.0.1:18768` where applicable) and confirm existing production `127.0.0.1:18766` dashboard, OBS overlays, DPAPI-backed telemetry, and task launchers remain intact; do not alter v0.7 task definitions.
- [ ] Validate a safe stop and rollback rehearsal, preserving both versions' SQLite histories, untracked collector backup, task definitions, and credentials. Document a concise result and abort criteria.
- [ ] Record a final operator **GO/NO-GO** covering the tested *foreground opt-in* scope. If unattended monitoring or automatic outbound alerts are required as launch features, they remain out of scope and require separate acceptance.

These steps require access to SQUALL and deliberate user authorization. **They have not been executed by GitHub or by this checklist.**

## 4. Final review and merge gate

- [ ] All Section 3 blocking items have verified evidence, exceptions, or an explicit release-scope decision.
- [ ] Recheck PR head, `main`, file inventory, comments, and any GitHub checks before merge; preserve a reviewable PR diff.
- [ ] User reviews the checklist, release notes, and any residual risk, then explicitly authorizes **merging PR #18**.

**STOP HERE.** Do not merge, create release tags, publish GitHub releases, or deploy without the final review. After merge, tag the reviewed merge commit `v0.8.0`, publish release notes and link the validated rollback plan; these are distinct, separately authorized post-merge actions.

## Supporting documents

- [Release notes](RELEASE_NOTES.md)
- [Deployment and rollback plan](DEPLOYMENT_ROLLBACK_PLAN.md)
- [Operator runbook](OPERATOR_RUNBOOK.md)
- [Release foreground acceptance contract](RC1_OPERATIONAL_LAUNCH_AND_ACCEPTANCE.md)
- [R6.2B2B process containment](R62B2B_WORKER_CONTAINMENT.md)
- [R6.2B2E durable receipts](R62B2E_DURABLE_CYCLE_RECEIPTS.md)
