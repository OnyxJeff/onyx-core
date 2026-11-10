# ONYX CORE v0.7.0 — Release Notes (Candidate)

**Status:** RELEASE CANDIDATE DRAFT — not merged, tagged, deployed, or published.\
**Review date:** 2026-11-09\
**Candidate:** `feature/v0.7.0-monitoring` at `9a98172b15463b661c462d810a0b812245cdcf3f` (Checkpoint O).\
**Existing production:** v0.6.0 `main` at `68e719b8463c597d9ddac8a8892039c3192ed869`.

## Overview

ONYX CORE v0.7.0 adds a **manually invoked, read-only USB/Internet Connection Sharing diagnostic and incident-history workflow** for the Windows 11 host and its Raspberry Pi Zero USB-gadget receiver. It helps distinguish missing USB adapters, failed routing or receiver connectivity, incomplete Pi evidence, suspected ICS problems, and recovery, while preserving evidence across manual runs.

**Read-only refers to the monitored network and operating system configuration.** An explicitly approved cycle may create/update local release observation and incident-history files. It does not repair ICS, reset adapters, restart services, install tasks, or run itself on a timer.

## What's new

- **Strict configuration contract.** Separate development and release profiles, fixed approved runtime paths, bounded timeouts, mandatory `repair_action=None`, and refusal of unexpected operations.
- **Evidence collection and classification.** Read-only Windows USB/ICS and restricted forced-command Pi checks, with bounded SSH and network timeouts; incomplete or contradictory evidence is not represented as healthy.
- **Incident lifecycle and durable records.** Validated incident state transitions, checksummed atomic JSON storage, an exclusive one-shot cycle lock, bounded event journal, and replay/idempotency protections.
- **Historical operator views.** Status and age-aware report commands read persisted evidence without launching probes or creating history; stale historical health is explicitly labeled.
- **Guarded release entry points.** Release-only status/report, offline initialization preflight, and manually authorized one-shot diagnostic are separate from development commands and use a distinct release state directory.
- **Fail-closed first-run behavior.** Partial initialization, unexpected files, corrupted state, and stray locks cause refusal. Existing history is never silently reset or recreated.
- **Offline tests.** Resilience, malformed data, SSH failures, lock contention, state corruption, recovery decisions, and safety checks covering forbidden repair/scheduling operations.

## Verified release-candidate evidence

| Evidence | SQUALL result |
|---|---|
| v0.7.0 Python monitoring suite | 370 tests executed; 363 passed, 7 skipped (Windows symlink prerequisites unavailable) |
| Offline PowerShell monitoring suites | 3 passed |
| v0.6.0 receiver service regression | 52 passed |
| Gateway / OBS route loopback checks | 25 passed |
| CPU-temperature offline integration | 7 passed |
| v0.6.0 recovery evaluator | 23 passed |
| Adversarial recovery cases | 35 passed; no repair action |
| Pi USB-forwarding classification | 11 passed |
| Windows USB/ICS classification | 7 passed |
| Candidate source-scope audit | 15 commits; 50 paths (49 added, 1 modified), no whitespace errors |
| Selected credential-pattern scan and PowerShell syntax audit | No selected secret matches; 7 PowerShell files parsed |

The cross-version audit verified that six selected legacy application components match v0.6.0. The gateway tests used localhost listeners. **None of the checks above performed a release-mode live diagnostic or verified current Pi SSH/receiver application reachability.**

## Operational boundaries

- **No automatic monitoring:** one authorized invocation performs one cycle only.
- **No auto-repair:** all incident decisions carry `repair_action=None`; an ICS suspicion requires manual investigation.
- **No network reconfiguration:** Windows `Ethernet 3`, ICS, and the Raspberry Pi gadget are not changed by these diagnostics.
- **No history migration:** development generation-2 history stays in `%LOCALAPPDATA%\OnyxCore-v070-Development\Monitoring`; release history uses `%LOCALAPPDATA%\OnyxCore-v070-Release\Monitoring` only after separately authorized initialization.
- **No change to existing telemetry pipeline:** existing collector, Pi receiver, gateway/OBS routes, CPU temperature metrics, and scheduled tasks remain production contracts.

## Known limitations and release gates

- Seven Windows symbolic-link/junction-oriented tests were skipped because the test environment could not create required symlinks; this coverage remains qualified.
- Passive Windows inspection confirmed the expected adapter, ICS service, gateway address, and a reachable neighbor-cache entry for `192.168.137.167`. **This is not an application-level connectivity test.**
- Windows `Ethernet 3` also carries legacy `10.12.194.9/24`; no cleanup is part of v0.7.0.
- The release profile is committed source: configuration edits must be reviewed/committed rather than made silently on `main` (a dirty tracked checkout is rejected by runtime guards).
- Release-root Git/source checks and state checks are defensive controls, **not** a substitute for restricted Windows ACLs, approved merge/deployment, or verified host keys.
- Approval to open a PR, merge, deploy, initialize release incident state, run a live diagnostic, tag, and publish are separate decisions. **None has occurred under this draft.**

## Upgrade and rollback

No automatic migration or installer is provided. Follow the reviewed `OPERATOR_RUNBOOK` and `DEPLOYMENT_ROLLBACK_PLAN` documents. Preserve the existing v0.6.0 checkout, untracked collector backup, Pi telemetry and USB/ICS settings. A failed first run must not be handled by deleting a lock, marker, or incident history file.

## Release status

**NOT YET PUBLISHED.** Source/security/syntax and cross-version offline gates have passed. Documentation review, deployment/rollback approval, and any requested hardware/live validation remain separate release gates.
