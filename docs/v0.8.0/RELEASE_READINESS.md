# ONYX CORE v0.8.0 — Pre-merge release readiness

**Status:** CONDITIONAL HOLD — evidence and source review complete; protected install and real operational acceptance remain open.  
**As of:** November 16, 2026.  
**Draft PR:** [#18](https://github.com/OnyxJeff/onyx-core/pull/18).  
**Accepted executable baseline:** `e1b1d596513fd04ef7434b7a587e8f3381b61300`; release-documentation-only commits after this do not change runtime.  
**Production:** `main` / `v0.7.0` = `06ec81582791fc797f74ad294195d68b2023cb66`.

## Scope decision

The proposed `v0.8.0` GitHub release adds opt-in monitoring building blocks and an explicitly authorized, bounded foreground read-only operator. It **does not** install unattended monitoring, a Scheduled Task, automatic notification delivery, or repairs. The optional notification watcher is separate and disabled by default. Do not represent the release as an already-enabled always-on monitoring service.

## Verified pre-merge evidence

| Gate | Result | Scope/qualification |
|---|---|---|
| GitHub PR provenance | PASS | Open draft PR #18; development code at `e1b1d59`, production `main` still v0.7.0 at prior review |
| Offline tests | PASS | 1,410 discovered, 1,400 passed, 10 expected skips, zero errors/failures on SQUALL after final accounting change |
| Windows synthetic native containment | PASS | 5/5: low-IL, timeout, revocation, descendant exit, scratch integrity |
| Actual release-path access | PASS | 8/8 paths, 40 write-capable handle requests denied; fingerprints unchanged |
| Source-evidence collection | PASS WITH SCOPE | 76 pinned R7 files at preceding checkpoint, final two-file accounting amendment separately verified and tested |
| PR review comments/reviews | NONE FOUND | Does not imply independent approval |
| GitHub Actions CI checks | NONE FOUND | Host transcript tests are not GitHub CI |
| Protected installed-source equivalence | **OPEN** | Existing `Program Files` tree previously reported different from candidate |
| Administrator-pinned approval and read-only installed audit | **OPEN** | New 19-file candidate manifest and digest must be reviewed/pinned |
| Real authorized foreground cycle/revocation | **OPEN** | Synthetic tests cannot replace a live Windows/Pi operational run |
| Gateway/overlay/collector preservation and rollback | **OPEN** | Production cutover never evidenced or authorized |
| Final operator review | **OPEN** | Required before merging PR #18 |

## Release go/no-go

**HOLD for merge and publication.** The pre-merge paperwork and GitHub review can finish without mutating the host. SQUALL acceptance needs a protected installation that exactly matches the approved commit and configuration, followed by an explicit user-authorized bounded diagnostic session, monitoring dashboard validation, and rollback/production-preservation observation.

A final release decision must explicitly distinguish the shipped **opt-in foreground** capability from the unimplemented **unattended** capability. If unattended automation is a required feature for v0.8.0, mark it NO-GO rather than silently reducing scope.

## Required next operator actions

Use the exact checklist in [PRE_MERGE_RELEASE_CHECKLIST.md](PRE_MERGE_RELEASE_CHECKLIST.md). Preserve the v0.7.0 production collector backup, task definitions and protected monitoring stores. No unexpected use of `git clean`, `reset --hard`, credentials in logs, task changes, or deployment. The protected installer must preserve a rollback copy and must not reuse the old approval digest.

Once operator evidence is attached and the user approves the final PR, merging and release publication are distinct next actions. This document itself does not grant those permissions.

## Companion docs

- [Release notes](RELEASE_NOTES.md)
- [Deployment and rollback plan](DEPLOYMENT_ROLLBACK_PLAN.md)
- [Operator runbook](OPERATOR_RUNBOOK.md)
- [RC1 protected operational acceptance](RC1_OPERATIONAL_LAUNCH_AND_ACCEPTANCE.md)
