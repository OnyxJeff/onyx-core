# ONYX CORE v0.7.0 — Controlled Deployment and Rollback Record

**Status: HISTORICAL PROCEDURE AND POST-MERGE RECORD.** PR merge, source sync, one initial store creation, and one live diagnostic completed under individual approvals. No authorization to repeat a diagnostic, restart services, repair ICS, tag or publish.\
**Current production:** `D:\github_repos\onyx-core` on `main` at `98606451f19071f7d7f6fe7b8d498ee4a449a890` (prior v0.6.0 baseline `68e719b8463c597d9ddac8a8892039c3192ed869`).\
**Reviewed v0.7.0 candidate:** feature branch `feature/v0.7.0-monitoring` at Checkpoint P `ef255f4fb7e5892a501ab19a01c8f8c18a3999ff`; merged via PR #16.

## 1. Operating assumptions and hard exclusions

- Preserve v0.6.0 telemetry collection, receiver, dashboard, gateway, overlays, and existing scheduled tasks; no authorization to restart or reconfigure them.
- Preserve `windows\collector\Send-OnyxTelemetry.pre-v050.bak` and its SHA-256: `59E1EE7205EFBEDB79BA3D0DCB4C9FD0D8EBD3DFA4D5D9313BBD8325976830EB`.
- Preserve all four persistent files in `%LOCALAPPDATA%\OnyxCore-v070-Development\Monitoring`: `incident-state.json`, `incident-state.initialized.json`, `incident-cycle.lock`, `recovery-observations.json`.
- Release uses a separate state directory under `%LOCALAPPDATA%\OnyxCore-v070-Release\Monitoring`; its first initialization was separately authorized and completed after Git source deployment.
- No `git reset --hard`, force push, deleting/recreating a store, unapproved ICS repair, adapter reset, scheduled release monitoring task, or scripted reboot.

## 2. Historical pre-PR gate (completed)

1. Confirm Checkpoint O / current candidate SHA and clean development worktree; confirm production `main` still matches expected baseline and protected untracked backup hash.
2. Record SQUALL validation transcript: 370 distinct Python monitoring tests (363 passed / 7 skipped unelevated, with all seven skipped tests separately passing elevated); 3 offline PowerShell suites; cross-version receiver 52, gateway 25, CPU temp 7, recovery evaluator 23, adversarial 35, Pi forwarding 11, Windows USB/ICS 7.
3. Confirm source inventory: 16 feature commits, 54 paths (53 added / 1 modified), `git diff --check` clean; 7 changed PowerShell scripts syntax-parse; selected credential-pattern scan clear. Manual diff/secret review still recommended.
4. Review the release-only source, strict host-key and forced-command SSH identity, approved Python/SSH paths, fixed release config, no auto-repair/task installation, and the release history integrity boundaries.
5. Record that all seven Windows symlink/junction skipped tests subsequently passed in an elevated, isolated run; do not present one 370-pass test run.
6. Review this plan, release notes and operator runbook. Agree that opening a PR is **not** merge/deploy authorization.

**Stop conditions:** unexpected new changes, mismatch in a recorded SHA/hash, unexpected untracked monitoring files, unreviewed hardcoded receiver/adapter, active production regression, or any source attempting repair/scheduling.

## 3. PR creation and review — completed for PR #16

Only after operator approval: push the reviewed feature branch without rewriting production history, open a v0.7.0 PR against `main`, and examine actual diff and CI results. If target `main` has moved, stop and perform a fresh compatibility/rebase review before considering merge. Review source and operational docs in the same PR or a separately coordinated documentation PR. **Do not merge merely because CI is green.**

## 4. Merge and production checkout — completed under separate approvals

1. Record current `main` SHA, v0.6.0 tag, existing production services/tasks and configuration. Preserve an independently accessible copy of relevant production data/configuration. Distinguish source checkout changes from running services: updating Git files does not automatically redeploy or reload an existing process.
2. Merge the reviewed PR by the agreed GitHub repository policy. Record PR number, merge SHA, and whether the merge is a merge commit or squash; the rollback method depends on this.
3. Update the production working checkout by an explicitly approved, **non-forced** method after confirming its status and protected untracked backup. Stop on conflicts or unexpected drift. Reconfirm main branch, exact HEAD and clean tracked monitoring source.
4. Run the release configuration checker and offline regressions from the newly deployed checkout. Check that existing collector/gateway/OBS endpoints and tasks have not regressed. Reconfirm the intended Windows operator identity, Python 3.13 and SSH executables, restricted monitoring key, known host key, release config and release state path ACLs.
5. **Historical deployment gate (completed):** Do not start `OnyxReleaseLiveIncident.py` during source synchronization, create a release task, or initialize history as part of Git deployment. The first live diagnostic and release-store initialization were authorized separately afterward.

## 5. First release diagnostic and initialization — completed once

After deployment approval and production integrity review, separately approve **one** bounded live read-only diagnostic. Inventory and hash the release state directory **before** any first-run attempt. If the store is truly new, separately authorize initialization and require a passing first-run offline preflight. Run only the top-level release Python CLI, not the PowerShell children. Preserve sanitized output and any stored-history timestamps. Run the historical reader after successful initialization to verify store readability. No forced rerun on error.

One authorized production one-shot diagnostic completed `2026-11-10T04:01:38.970124Z`: `Healthy` / `Complete`, release generation 1, no repair. The passive neighbor-cache observation alone was not proof of application health, and this one historical cycle does not provide continuous monitoring.

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

Offline and first-run runtime gates passed. PR #16 merge, production source update, first initialization, and one live diagnostic were performed under separate approvals and recorded. The `v0.7.0` tag and GitHub release publication remain unapproved; no rollback was necessary or performed.

## Post-merge acceptance and rollback checkpoint (2026-11-10)

- PR #16 merge: `98606451f19071f7d7f6fe7b8d498ee4a449a890`; production source fast-forwarded to this commit without resetting history.
- Legacy collector, gateway, and LibreHardwareMonitor scheduled tasks remained running during source synchronization; no task or service changes were performed.
- Approved one-shot: one cycle, `Healthy` / `Complete`, generation 1, no open incident, zero transition events, `repair_action=None`; not an automatic monitor.
- Release store: five files (`incident-state.json`, `incident-state.initialized.json`, `incident-cycle.lock`, `incident-state.json.lock`, `recovery-observations.json`); preserve all on future source rollback.
- Historical report returned the recorded result without a new diagnostic and confirmed release-store hashes unchanged.
- Remaining change is documentation-only. Preserve release and development history when merging these docs. Tagging and publication require separate approval.
