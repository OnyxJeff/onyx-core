# ONYX CORE v0.7.0 — Offline Gate and Post-Merge Acceptance Record

**Evidence period:** 2026-11-09 to 2026-11-10. **Final feature:** Checkpoint P `ef255f4fb7e5892a501ab19a01c8f8c18a3999ff`, 16 commits beyond the v0.6.0 baseline.\
**Decision:** **OFFLINE AND FIRST-RUN RUNTIME ACCEPTANCE PASS; PR #16 MERGED AND SOURCE SYNCHRONIZED. RELEASE NOT YET TAGGED OR PUBLISHED.**

## Evidence table

| Gate | Assessment | Operator evidence |
|---|---|---|
| Merged ancestry/source scope | PASS | 16 feature commits; 54 changed files (53 additions, 1 modification); no unexpected changes; `git diff --check` clean |
| Local syntax and selected secret-pattern screening | PASS (bounded) | 7 `.ps1` files parsed; no matches for tested PEM/PAT/AWS/Bearer patterns; not exhaustive manual review |
| v0.7.0 monitoring tests | PASS (separate runs) | 363 passed / 7 skipped unelevated; the same 7 symlink tests separately passed elevated; 370 distinct cases covered, not one 370-pass run |
| PowerShell offline monitoring | PASS | Three suites, no live probes or scheduled tasks |
| Existing receiver | PASS | 52 tests |
| Gateway / OBS loopback routes | PASS | 25 checks; localhost HTTP listeners only |
| CPU-temperature integration | PASS | 7 offline checks |
| v0.6.0 recovery evaluator | PASS | 23 decision checks |
| Adversarial recovery evaluation | PASS | 35 offline cases, repair action `None` |
| Pi USB forwarding | PASS | 7 classifications + 4 TCP outcomes |
| Windows USB/ICS classification | PASS | 7 classifications |
| Existing baseline application source | PASS (selected scope) | Six selected legacy application components unchanged from v0.6.0 |
| Production and incident integrity | PASS | `main` at merge `98606451f19071f7d7f6fe7b8d498ee4a449a890`; protected backup and four development incident files unchanged; five separate release files preserved |
| Passive SQUALL network prerequisites | PASS (local only) | `Ethernet 3` Up, `192.168.137.1/24`, ICS Running/Automatic, correct upstream adapter, Pi neighbor-cache `.167` Reachable |
| First release-mode USB/ICS and Pi diagnostic | PASS (point-in-time) | Exactly one authorized run at `2026-11-10T04:01:38.970124Z`: `Healthy` / `Complete`; no current-continuous guarantee |
| Release state initialization | PASS | Separately authorized first run completed: generation 1, one stored cycle; all five release artifacts preserved |
| Runtime key/host prerequisites | ACCEPTED FOR ONE-SHOT; independent ACL audit not recorded | Dedicated key and known-host entry present; one bounded production diagnostic completed; no broad ACL review claimed |
| Documentation package | FINALIZATION IN PROGRESS | Four candidate docs were merged in PR #16; these post-merge corrections require separate review |
| PR, merge, source sync, tag, publication | PARTIAL | PR #16 merged; local source synchronized; one first-run diagnostic accepted; tag and publication pending separate approval |

## Interpretation

- Source/syntax/test/scope review supported PR #16, subsequently merged and synchronized after separate approvals; production one-shot acceptance is now recorded. No tag/publication approval is implied.
- The seven symlink tests were **not** counted as passing in the unelevated run; each was subsequently run and passed under elevation, without claiming an all-pass single run.
- A successful historical `Healthy` report is **not** proof of current connectivity. ONYX CORE v0.7.0 is manual-only and never repairs ICS.
- Live network diagnostics legitimately write release observation and incident state when the operator explicitly invokes a cycle. They are not “read only” in the sense of zero filesystem writes.
- The legacy `10.12.194.9/24` address and the functioning ICS adapter configuration should be left untouched during RC preparation and post-merge acceptance.

## Approval ledger (pre-publication acceptance)

| Action | Status | Authorized by / date / artifact |
|---|---|---|
| Review and approve RC documentation | PR #16 merged; post-merge corrections in review | See four release documents |
| Close seven Windows symlink skips | CLOSED | Seven separate elevated tests passed; unelevated skips remain accurately recorded |
| Open/push v0.7.0 PR | COMPLETED | PR #16, merged |
| Merge PR into `main` | COMPLETED | Merge commit `98606451f19071f7d7f6fe7b8d498ee4a449a890` |
| Update production working checkout | COMPLETED | SQUALL fast-forwarded to `98606451f19071f7d7f6fe7b8d498ee4a449a890` |
| Perform first release-state initialization | COMPLETED | One authorized run; generation 1, five preserved files |
| Run first live release diagnostic | COMPLETED | `2026-11-10T04:01:38.970124Z` `Healthy` / `Complete`, `repair_action=None` |
| Tag/publish GitHub v0.7.0 | NOT AUTHORIZED | — |

## Source preservation

- Development: `D:\github_repos\onyx-core-v070`, `feature/v0.7.0-monitoring`, Checkpoint P `ef255f4fb7e5892a501ab19a01c8f8c18a3999ff`, clean.
- Production: `D:\github_repos\onyx-core`, `main`, HEAD `98606451f19071f7d7f6fe7b8d498ee4a449a890`.
- Untracked protected backup: `windows\collector\Send-OnyxTelemetry.pre-v050.bak`; SHA-256 `59E1EE7205EFBEDB79BA3D0DCB4C9FD0D8EBD3DFA4D5D9313BBD8325976830EB`.
- Never rewrite or initialize the protected development files in `%LOCALAPPDATA%\OnyxCore-v070-Development\Monitoring`.
- Release store is separate at `%LOCALAPPDATA%\OnyxCore-v070-Release\Monitoring` and was initialized only by the one approved live diagnostic; never reset or delete its five artifacts during documentation work.

## Recommended next decision

Review the post-merge documentation diff in the isolated documentation worktree. Commit and push only after approval, merge a documentation-only PR, verify local source synchronization and release history, then separately authorize the `v0.7.0` tag and GitHub Release publication. **No additional live diagnostic is required or authorized by this document.**

## Post-merge acceptance

- One authorized production cycle completed at `2026-11-10T04:01:38.970124Z`, `Healthy`, evidence `Complete`, generation 1, one processed cycle, zero transitions, no repair.
- Release status and age-aware reporting validated stored history without another probe; at inspection, freshness was `Recent` (205 seconds). Future reports may legitimately become `Stale`.
- Four development incident files and the original collector backup retained their validated SHA-256 hashes; all five separate release store artifacts were unchanged during historical reporting.
- The Pi-hosted dashboard is `192.168.137.167:8765/dashboard`; Windows testing port `18766` is not required for release monitoring.
- Pending: review/merge these documentation corrections, finalize tag/release contents, obtain publication authorization. No new probe or ICS change is implied.
