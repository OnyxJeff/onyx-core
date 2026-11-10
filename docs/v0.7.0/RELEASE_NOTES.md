# ONYX CORE v0.7.0 — Release Notes (Pre-Publication Finalization)

**Status:** MERGED AND SOURCE-SYNCHRONIZED; production first live cycle accepted; not yet tagged or published.\
**Review and acceptance dates:** 2026-11-09 to 2026-11-10\
**Reviewed feature:** `feature/v0.7.0-monitoring` at `ef255f4fb7e5892a501ab19a01c8f8c18a3999ff` (Checkpoint P); PR #16 merged into `main` at `98606451f19071f7d7f6fe7b8d498ee4a449a890`.\
**Prior baseline:** v0.6.0 `main` at `68e719b8463c597d9ddac8a8892039c3192ed869`. **Current source checkout:** merged v0.7.0 at `98606451f19071f7d7f6fe7b8d498ee4a449a890`.

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
| v0.7.0 Python monitoring suite | 363 passed and 7 symlink tests skipped in unelevated run; all 7 subsequently passed in a separate elevated run (370 distinct tests covered) |
| Offline PowerShell monitoring suites | 3 passed |
| v0.6.0 receiver service regression | 52 passed |
| Gateway / OBS route loopback checks | 25 passed |
| CPU-temperature offline integration | 7 passed |
| v0.6.0 recovery evaluator | 23 passed |
| Adversarial recovery cases | 35 passed; no repair action |
| Pi USB-forwarding classification | 11 passed |
| Windows USB/ICS classification | 7 passed |
| Merged source-scope audit | 16 feature commits; 54 paths (53 added, 1 modified), no whitespace errors |
| Selected credential-pattern scan and PowerShell syntax audit | No selected secret matches; 7 PowerShell files parsed |

The cross-version audit verified that six selected legacy application components match v0.6.0. The gateway tests used localhost listeners. **The listed regression suites were offline.** A separately authorized first production one-shot cycle subsequently completed at `2026-11-10T04:01:38.970124Z` with `Healthy` / `Complete` evidence, generation 1, `repair_action=None`. This is an observation at that time, not ongoing proof of connectivity.

## Operational boundaries

- **No automatic monitoring:** one authorized invocation performs one cycle only.
- **No auto-repair:** all incident decisions carry `repair_action=None`; an ICS suspicion requires manual investigation.
- **No network reconfiguration:** Windows `Ethernet 3`, ICS, and the Raspberry Pi gadget are not changed by these diagnostics.
- **No history migration:** development generation-2 history stays in `%LOCALAPPDATA%\OnyxCore-v070-Development\Monitoring`; release history uses `%LOCALAPPDATA%\OnyxCore-v070-Release\Monitoring` only after separately authorized initialization.
- **No change to existing telemetry pipeline:** existing collector, Pi receiver, gateway/OBS routes, CPU temperature metrics, and scheduled tasks remain production contracts.

## Known limitations and release gates

- Seven symbolic-link tests were skipped in the normal unelevated run; all seven subsequently passed separately under an elevated Windows PowerShell session. Do not report all 370 as passing in a single run.
- Passive Windows inspection confirmed the expected adapter, ICS service, gateway address, and a reachable neighbor-cache entry for `192.168.137.167`. **This passive evidence alone was not an application-level test; the subsequent one-shot diagnostic recorded complete evidence at its observation time.**
- Windows `Ethernet 3` also carries legacy `10.12.194.9/24`; no cleanup is part of v0.7.0.
- The release profile is committed source: configuration edits must be reviewed/committed rather than made silently on `main` (a dirty tracked checkout is rejected by runtime guards).
- Release-root Git/source checks and state checks are defensive controls, **not** a substitute for restricted Windows ACLs, approved merge/deployment, or verified host keys.
- Approval to open a PR, merge, deploy, initialize release incident state, run a live diagnostic, tag, and publish are separate decisions. **PR merge, source synchronization, one first-run initialization, and one live diagnostic have occurred under separate approvals; tag and publication remain pending.**

## Upgrade and rollback

No automatic migration or installer is provided. Follow the reviewed `OPERATOR_RUNBOOK` and `DEPLOYMENT_ROLLBACK_PLAN` documents. Preserve the recorded v0.6.0 source baseline, the current production checkout, untracked collector backup, Pi telemetry and USB/ICS settings. A failed first run must not be handled by deleting a lock, marker, or incident history file.

## Release status

**NOT YET PUBLISHED.** The approved PR was merged, the production source checkout was fast-forwarded, and the first authorized manual diagnostic and historical-reader acceptance passed. Documentation finalization, release tagging, and GitHub publication remain separate gates.

## Post-merge acceptance (2026-11-10)

- PR #16 merged as a two-parent merge commit at `98606451f19071f7d7f6fe7b8d498ee4a449a890` (parents: v0.6.0 baseline `68e719b...` and feature checkpoint P `ef255f4...`).
- SQUALL production `main` synchronized to that exact merge; existing scheduled tasks were left unchanged.
- Exactly one authorized first-run release diagnostic completed at `2026-11-10T04:01:38.970124Z`: `Healthy`, evidence `Complete`, generation 1, one processed cycle, zero incident transitions, no open incident, `repair_action=None`.
- All five release store artifacts were checked. The four protected development incident artifacts and collector backup retained their hashes.
- Stored status and age-aware report passed without another network probe; the historical report was `Recent` at age 205 seconds and is allowed to become `Stale` over time.
- No auto-repair, service restart, unattended monitor, second live cycle, tag, or GitHub Release was authorized.
- The Pi dashboard is `http://192.168.137.167:8765/dashboard`; Windows port `18766` was identified by the operator as a separate testing/gateway endpoint and is not a prerequisite for the v0.7.0 release one-shot diagnostic.
