# ONYX CORE v0.6.0 — Deployment and Rollback Plan (Not Authorized)

**This is a plan, not an instruction to deploy now.** Milestone 6 writes documents and tests in the development worktree only. No automatic ICS repair is part of v0.6.0.

## Confirmed pre-release baseline

- Production worktree: `D:\github_repos\onyx-core`, `main`, commit `6d1e599` (v0.5.1 documented production).
- Development worktree: `D:\github_repos\onyx-core-v060`, branch `feature/v0.6.0-reliability`, Milestone 5 checkpoint `725ed95`.
- Known pre-existing production-only untracked file: `windows/collector/Send-OnyxTelemetry.pre-v050.bak` (leave untouched).
- Windows gateway: localhost `127.0.0.1:18766`; routes `/dashboard`, `/overlay`, `/overlay-portrait`.
- Pi monitored diagnostic: root-owned at `/usr/local/libexec/onyxcore-monitor/Test-OnyxUsbForwarding.py`; restricted forced-command SSH key already validated.

## Preconditions before proposing a merge

1. Run the Milestone 6 offline suite and capture output with the development HEAD.
2. Run explicit baseline receiver/gateway/CPU-temperature tests. Investigate failures, do not waive silently.
3. Run the optional live read-only diagnostics and check both OBS overlays with recent telemetry.
4. Compare every modified file to the protected v0.5.1 baseline. Only documented diagnostics/tests/docs should change.
5. Verify no passwords, tokens, private keys, history JSON, SQLite databases, or machine-specific paths containing secrets are committed.
6. Confirm production services and scheduled tasks have **not** been modified, stopped, restarted, or rescheduled.
7. Explicitly approve the PR, merge, and deployment as **separate decisions**.

## Proposed safe rollout (future, approval required)

**Phase A — Source integration:** Prepare a PR from the isolated feature branch. Require passing tests and scope review. Merge source only when approved; merging does not itself install or enable a monitor.

**Phase B — Manual diagnostics only:** Confirm the restricted Pi command remains installed and is compatible with the merged source. Invoke diagnostics manually. Retain local-only, bounded history. No new network listeners or scheduled tasks.

**Phase C — Verify production baseline:** Confirm Windows collector telemetry continues arriving at the Pi, authenticated gateway APIs function with the existing DPAPI-protected credential, and both OBS overlays render fresh readings.

No part of these phases authorizes automatic Windows ICS changes, service restarts, Windows adapter resets, or Pi network reconfiguration. If a future release proposes automation, it needs a separately reviewed specification, tests, and explicit permission.

## Backup / evidence preservation before any later deployment

- Record exact production commit and branch, plus `git status --short`, **without cleaning** pre-existing files.
- Preserve current production gateway/collector source and the existing Pi diagnostic file through an approved backup method before changing either of them.
- Preserve the current Task Scheduler action/settings for `ONYX CORE - Local Gateway` and the telemetry collector. Do not export secrets into public archives.
- Capture sanitized prechange screenshots of dashboard and OBS overlays.
- Confirm an approved rollback mechanism exists (PR revert or restoring known-good source); test the previous behavior before considering the update complete.

## Rollback triggers and approach

Trigger review/rollback if telemetry ingestion stops, API authentication fails, gateway dashboard/overlays regress, collector unexpectedly changes state, credentials become exposed, or the new diagnostics produce non-`None` repair actions.

1. **Stop the v0.6.0 rollout** and leave ICS and existing telemetry services running. Gather read-only diagnostics.
2. If only new diagnostics/tests/docs are affected, disable manual use of the new diagnostic entry point and keep serving the existing v0.5.1 applications; do not restart unrelated services.
3. If merged source must be reverted, prepare a reviewed Git revert or restore of the exact known-good files from the recorded baseline. Avoid destructive `git reset --hard` on a repository that may contain user data or untracked backups.
4. If the Pi diagnostic was updated in a separately authorized deployment, restore its backed-up, root-owned known-good version, keeping the restricted authorization boundary. Do not alter the Pi spontaneously during source-only release work.
5. Confirm production collector samples, authenticated gateway APIs, and both OBS scenes again. Document the incident and the restored revision.

## Unverified behavior / follow-up

Windows startup/reboot resilience, automatic LibreHardwareMonitor startup, and recovery after an intentionally interrupted USB link were noted as unverified in v0.5.1 documentation. Milestone 6's safe offline simulations do **not** prove these live behaviors. Schedule manual, supervised tests separately if needed, never by damaging the running connection as a shortcut.

**Release is NOT approved by the existence of this document or by a green automated suite alone.**
