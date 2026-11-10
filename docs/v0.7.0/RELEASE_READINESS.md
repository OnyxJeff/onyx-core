# ONYX CORE v0.7.0 — Milestone 5 Final Offline Readiness Gate

**Evidence date:** 2026-11-09. **Candidate:** `9a98172b15463b661c462d810a0b812245cdcf3f` (Checkpoint O), 15 commits beyond existing production.\
**Decision:** **OFFLINE RC GATES PASS; PR/DOCUMENTATION REVIEW PENDING. NOT DEPLOYED OR PUBLISHED.**

## Evidence table

| Gate | Assessment | Operator evidence |
|---|---|---|
| Candidate ancestry/source scope | PASS | 15 commits; 50 changed files (49 additions, 1 modification); no unexpected changes; `git diff --check` clean |
| Local syntax and selected secret-pattern screening | PASS (bounded) | 7 `.ps1` files parsed; no matches for tested PEM/PAT/AWS/Bearer patterns; not exhaustive manual review |
| v0.7.0 monitoring offline tests | PASS with qualified skips | 370 executed; 363 passed; 7 skipped for symlink setup unavailable on Windows |
| PowerShell offline monitoring | PASS | Three suites, no live probes or scheduled tasks |
| Existing receiver | PASS | 52 tests |
| Gateway / OBS loopback routes | PASS | 25 checks; localhost HTTP listeners only |
| CPU-temperature integration | PASS | 7 offline checks |
| v0.6.0 recovery evaluator | PASS | 23 decision checks |
| Adversarial recovery evaluation | PASS | 35 offline cases, repair action `None` |
| Pi USB forwarding | PASS | 7 classifications + 4 TCP outcomes |
| Windows USB/ICS classification | PASS | 7 classifications |
| Existing baseline application source | PASS (selected scope) | Six selected legacy application components unchanged from v0.6.0 |
| Production and incident integrity | PASS | Existing `main` at `68e719b8463c597d9ddac8a8892039c3192ed869`; protected backup, four development incident files unchanged |
| Passive SQUALL network prerequisites | PASS (local only) | `Ethernet 3` Up, `192.168.137.1/24`, ICS Running/Automatic, correct upstream adapter, Pi neighbor-cache `.167` Reachable |
| Current Pi/receiver application connectivity | NOT VERIFIED | No live SSH, receiver TCP/API, or one-shot release diagnostic |
| Release state initialization | NOT AUTHORIZED | New separate release directory must be inspected before any first-run approval |
| ACLs, ownership, strict SSH host-key validity | OPERATIONAL REVIEW NEEDED | Binary/key presence checked; runtime authentication/path-ACLs not end-to-end exercised |
| Documentation package | DRAFT FOR REVIEW | Release notes, operator runbook, rollback plan, this gate record; not yet committed |
| PR, merge, deployment, tag, publication | NOT AUTHORIZED | Each requires separate explicit approval |

## Interpretation

- Source/syntax/test/scope review supports **preparing a reviewed PR once documentation and residual-risk acceptance are approved**, but not merging or deploying immediately.
- The seven skipped symlink tests are **not** treated as passing coverage; decide whether to accept them as a documented limitation or run targeted disposable-path validation.
- A successful historical `Healthy` report is **not** proof of current connectivity. ONYX CORE v0.7.0 is manual-only and never repairs ICS.
- Live network diagnostics legitimately write release observation and incident state when the operator explicitly invokes a cycle. They are not “read only” in the sense of zero filesystem writes.
- The legacy `10.12.194.9/24` address and the functioning ICS adapter configuration should be left untouched during RC preparation.

## Approval ledger (blank intentionally)

| Action | Status | Authorized by / date / artifact |
|---|---|---|
| Review and approve RC documentation | PENDING | — |
| Accept or close seven Windows symlink skips | PENDING | — |
| Open/push v0.7.0 PR | PENDING | — |
| Merge PR into `main` | NOT AUTHORIZED | — |
| Update production working checkout | NOT AUTHORIZED | — |
| Perform first release-state initialization | NOT AUTHORIZED | — |
| Run first live release diagnostic | NOT AUTHORIZED | — |
| Tag/publish GitHub v0.7.0 | NOT AUTHORIZED | — |

## Source preservation

- Development: `D:\github_repos\onyx-core-v070`, `feature/v0.7.0-monitoring`, Checkpoint O `9a98172b15463b661c462d810a0b812245cdcf3f`, clean.
- Production: `D:\github_repos\onyx-core`, `main`, HEAD `68e719b8463c597d9ddac8a8892039c3192ed869`.
- Untracked protected backup: `windows\collector\Send-OnyxTelemetry.pre-v050.bak`; SHA-256 `59E1EE7205EFBEDB79BA3D0DCB4C9FD0D8EBD3DFA4D5D9313BBD8325976830EB`.
- Never rewrite or initialize the protected development files in `%LOCALAPPDATA%\OnyxCore-v070-Development\Monitoring`.
- Release store is a distinct `%LOCALAPPDATA%\OnyxCore-v070-Release\Monitoring` path and must not be created by a documentation/PR step.

## Recommended next decision

Review these documents, then explicitly approve incorporation into the development branch and whether the seven Windows symlink test skips are acceptable for PR review. After that, do a final exact candidate-and-documentation regression check, establish the next clean checkpoint, and only then seek authorization to push/open a PR. **Do not run a live release diagnostic to close an offline documentation gate.**
