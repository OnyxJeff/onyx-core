# ONYX CORE v0.7.0 — Controlled Deployment and Rollback Plan (Candidate)

**Status: REVIEW / DO NOT EXECUTE.** This is not approval to open a PR, merge, deploy, initialize a store, start a live diagnostic, tag or publish.\
**Current production:** `D:\github_repos\onyx-core` on `main` at `68e719b8463c597d9ddac8a8892039c3192ed869`.\
**Reviewed v0.7.0 candidate:** feature branch `feature/v0.7.0-monitoring` at `9a98172b15463b661c462d810a0b812245cdcf3f`.

## 1. Operating assumptions and hard exclusions

- Preserve v0.6.0 telemetry collection, receiver, dashboard, gateway, overlays, and existing scheduled tasks; no authorization to restart or reconfigure them.
- Preserve `windows\collector\Send-OnyxTelemetry.pre-v050.bak` and its SHA-256: `59E1EE7205EFBEDB79BA3D0DCB4C9FD0D8EBD3DFA4D5D9313BBD8325976830EB`.
- Preserve all four persistent files in `%LOCALAPPDATA%\OnyxCore-v070-Development\Monitoring`: `incident-state.json`, `incident-state.initialized.json`, `incident-cycle.lock`, `recovery-observations.json`.
- Release uses a separate state directory under `%LOCALAPPDATA%\OnyxCore-v070-Release\Monitoring`; its first initialization is **never** part of Git deployment.
- No `git reset --hard`, force push, deleting/recreating a store, unapproved ICS repair, adapter reset, scheduled release monitoring task, or scripted reboot.

## 2. Pre-PR gate (review only)

1. Confirm Checkpoint O / current candidate SHA and clean development worktree; confirm production `main` still matches expected baseline and protected untracked backup hash.
2. Record SQUALL validation transcript: 370 Python monitoring tests (363 passed, 7 Windows skips); 3 offline PowerShell suites; cross-version receiver 52, gateway 25, CPU temp 7, recovery evaluator 23, adversarial 35, Pi forwarding 11, Windows USB/ICS 7.
3. Confirm source inventory: 15 commits, 50 paths (49 added / 1 modified), `git diff --check` clean; 7 changed PowerShell scripts syntax-parse; selected credential-pattern scan clear. Manual diff/secret review still recommended.
4. Review the release-only source, strict host-key and forced-command SSH identity, approved Python/SSH paths, fixed release config, no auto-repair/task installation, and the release history integrity boundaries.
5. Review the known seven Windows symlink/junction skipped tests and decide explicitly whether to accept that limitation or perform separate tests against disposable paths.
6. Review this plan, release notes and operator runbook. Agree that opening a PR is **not** merge/deploy authorization.

**Stop conditions:** unexpected new changes, mismatch in a recorded SHA/hash, unexpected untracked monitoring files, unreviewed hardcoded receiver/adapter, active production regression, or any source attempting repair/scheduling.

## 3. PR creation and review — distinct authorization

Only after operator approval: push the reviewed feature branch without rewriting production history, open a v0.7.0 PR against `main`, and examine actual diff and CI results. If target `main` has moved, stop and perform a fresh compatibility/rebase review before considering merge. Review source and operational docs in the same PR or a separately coordinated documentation PR. **Do not merge merely because CI is green.**

## 4. Merge and production checkout — separate authorization

1. Record current `main` SHA, v0.6.0 tag, existing production services/tasks and configuration. Preserve an independently accessible copy of relevant production data/configuration. Distinguish source checkout changes from running services: updating Git files does not automatically redeploy or reload an existing process.
2. Merge the reviewed PR by the agreed GitHub repository policy. Record PR number, merge SHA, and whether the merge is a merge commit or squash; the rollback method depends on this.
3. Update the production working checkout by an explicitly approved, **non-forced** method after confirming its status and protected untracked backup. Stop on conflicts or unexpected drift. Reconfirm main branch, exact HEAD and clean tracked monitoring source.
4. Run the release configuration checker and offline regressions from the newly deployed checkout. Check that existing collector/gateway/OBS endpoints and tasks have not regressed. Reconfirm the intended Windows operator identity, Python 3.13 and SSH executables, restricted monitoring key, known host key, release config and release state path ACLs.
5. **Do not start `OnyxReleaseLiveIncident.py` yet**, create any release task, or initialize the release store. Deployment and the first read-only live diagnostic are separate decisions.

## 5. Live smoke test and optional first initialization — separate authorization

After deployment approval and production integrity review, separately approve **one** bounded live read-only diagnostic. Inventory and hash the release state directory **before** any first-run attempt. If the store is truly new, separately authorize initialization and require a passing first-run offline preflight. Run only the top-level release Python CLI, not the PowerShell children. Preserve sanitized output and any stored-history timestamps. Run the historical reader after successful initialization to verify store readability. No forced rerun on error.

No end-to-end release-mode SSH/receiver smoke test has yet been executed; the passive neighbor table on 2026-11-09 was supporting evidence only.

## 6. Rollback decision matrix

| Situation | Required immediate response | What is forbidden |
|---|---|---|
| PR review issue before merge | Stop PR/hold merge; correct in development and rerun tests | Changing production to "test it" |
| Deployment/source regression after merge | Stop release diagnostic usage, preserve logs and current SHAs; prepare reviewed source revert | `reset --hard`, forced rewrites of shared history |
| Running collector/gateway regression | Capture task/service state, isolate source vs running-process version, plan approved restoration and retest | Blind task deletion/restart or assuming a Git revert restarted services |
| Failed or interrupted first initialization | Stop, record state-file names, hashes, timestamps and ACLs; preserve marker/lock/history files | Removing lock/marker or replacing state with blank records |
| Corrupt release observation history | Record checksum/parse errors and copy forensic evidence; investigate read-only | Overwriting, silently dropping observations, "fixing" with deletion |
| USB/ICS or Pi connectivity problem | Document read-only diagnostics, require separate change approval | Restarting ICS/resetting adapter as part of release rollback |

## 7. Source rollback mechanics (plan only; not commands to run now)

- **Merge commit:** an approved `git revert -m 1 <merge-commit-sha>` is a possible non-history-rewriting reversal, subject to verifying the merge parents and reviewing the generated revert diff.
- **Squash merge:** an approved `git revert <squash-commit-sha>` may be appropriate, again subject to review.
- **Fast-forward merge:** evaluate the set of introduced commits and choose a reviewed revert strategy; do not assume `-m 1` applies.
- Before rollback, preserve relevant config, task/service inventory, release history and backup integrity. After rollback, check actual runtime services/tasks and receiver/gateway/OBS behavior. Revert source separately from any approved process restart or deployment reversal.
- Never delete or migrate the release incident store as part of source rollback. A future version can read/convert it only through a separately reviewed migration procedure.

## 8. Final decision gate

A passing offline audit closes the test gate only. **PR approval**, **merge**, **production update**, **first-run initialization**, **live diagnostic**, **tag**, and **GitHub release publication** each require explicit operator decisions. Record actual evidence for each; no release or rollback step in this document has been executed.
