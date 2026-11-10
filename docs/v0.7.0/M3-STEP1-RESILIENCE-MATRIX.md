# ONYX CORE v0.7.0 — Milestone 3 / Step 1
## Offline cross-component resilience and failure simulation

Status: **development-only, tests-only, not committed by the installer**.
Baseline: Checkpoint G `062b564354389b8160c9807e45c12b87f095416e`.

## Purpose

Verify that the already-built **live bridge → incident reducer → atomic incident store**
continues to fail closed under simulated faults and contradictory evidence. This step
adds **no production implementation changes** and does not change the M1 diagnostics.

## New test module

`tests/monitoring/test_m3_resilience.py` adds 33 `unittest` cases. Every case
uses an isolated `tempfile.TemporaryDirectory`, synthesizes the M1 cycle JSON
contract, and invokes existing functions directly. No real SSH, USB, ICS,
PowerShell collector, network probe, service, task, or persistent development
incident directory is accessed.

## Failure simulation matrix

| Group | Scenarios | Required behavior |
|---|---|---|
| Windows/Pi classification | Adapter missing, ICS service stopped, DNS-only failure | Suspected incident; no false confirmed ICS root cause |
| Evidence uncertainty | Initial, repeated, restored, and interrupted evidence | Unknown display during missing evidence; deduplicate transition events |
| Outage persistence | Active outage with evidence gap or new failure | Incident remains open; pending recovery confirmation resets |
| Recovery timing | Two healthy samples too close, properly spaced, or too far apart | Active incident recovers only with qualified independent healthy samples |
| Incident lifecycle | Repeated suspect; escalation; recovery; later new failure | No duplicate opening/escalation; distinct incident identity for separate outage |
| Replay protection | Exact replay; changed same-timestamp payload; backdated cycle | Exact replay is no-op; conflicting/out-of-order cycles reject without writes |
| Unsupported evidence | False corroboration, false health, unauthorized source/repair | Reject invalid cycle; preserve previous record bytes |
| Missing/corrupt files | State missing; marker missing or malformed; corrupted JSON | Refuse the cycle before collection, never reset or repair stored data |
| Process failure | Collector exception; invalid collector payload; atomic replacement failure | Do not alter existing state; failed temp write cleaned up |
| Overlap | Second cycle while cycle lock is held | Refuse without running the collector |
| Information hygiene | Private decision reason in synthetic cycle | Never store raw sensitive diagnostic reason |

## Explicit limitations

- These tests are **offline simulations**, not proof that Windows ICS, USB gadget,
  the Pi, or the network would behave a certain way under a real outage.
- The test module does not run the live CLI or the existing PowerShell diagnostics.
- State persistence is exercised **only in throwaway test directories**.
- The protected existing development incident store must stay at generation 2,
  with its marker and original recovery observations byte-for-byte unchanged.
- No automatic repair is authorized. `repair_action` remains `None`.
- A `PossibleIcsFailure` decision indicates corroborated symptoms, not proven
  root cause of Windows ICS.

## Expected local results

- New module: 33 / 33 tests.
- On SQUALL (assuming Checkpoint G's 117 monitoring tests): **150 / 150**.
- Existing PowerShell offline collector and cycle-runner suites: both pass.
- Production `main` remains at baseline `68e719b8463c597d9ddac8a8892039c3192ed869`.
- Dev worktree contains exactly two untracked files; Checkpoint G is unmodified.
- No scheduling, Git push, commit, live probe, or deployment.

## Next gate

After local Windows validation, review test coverage and commit the two approved
files as a development checkpoint. Follow with targeted network and subprocess
failure injection using mocks only; real fault injection is not required.
