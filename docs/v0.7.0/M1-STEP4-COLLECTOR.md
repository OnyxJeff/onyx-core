# ONYX CORE v0.7.0 — Milestone 1 Step 4: Collector Refactor

**Status:** Development source only. No deployed monitor or scheduled task.

## Scope

- Adapt `windows/networking/Collect-OnyxRecoveryEvidence.ps1` to run **only** from `feature/v0.7.0-monitoring` / `onyx-core-v070` with an explicit `-LiveReadOnly` switch.
- Require the reviewed development configuration from `windows/monitoring/monitoring.development.example.json` and validate it via `OnyxMonitorConfig.py` before probing.
- Read Windows adapter, Pi host, restricted key path, Python/SSH runtimes, timeout and development history path settings from the validated config.
- Preserve existing SSH restrictions, wall-clock bounding, 12-observation / five-minute history policy, atomic updates, corruption handling and `repair_action = None`.
- Use a distinct v0.7.0 mutex and development state directory. No v0.6.0 history is migrated.

## Running tests — safe offline mode

Run `C:\Python313\python.exe -m unittest discover -s tests\monitoring -p 'test_*.py' -v` from the development root, then `powershell.exe -NoProfile -NonInteractive -File tests\monitoring\Test-OnyxCollectorM1Step4.ps1`. These commands do not execute live probes or install anything.

Existing read-only policy self-tests can be run directly: `C:\Python313\python.exe windows\networking\Evaluate-OnyxRecovery.py --self-test` and `C:\Python313\python.exe pi\scripts\Test-OnyxUsbForwarding.py --self-test`.

## Manually invoking live read-only diagnostic — separate deliberate step

The collector refuses to run without `-LiveReadOnly`. If approved and after offline checks, invoke manually with `powershell.exe -NoProfile -NonInteractive -File windows\networking\Collect-OnyxRecoveryEvidence.ps1 -LiveReadOnly` from the development worktree. This writes **only** the development observation history under `%LOCALAPPDATA%\OnyxCore-v070-Development\Monitoring` and performs existing network and restricted SSH probes. It is not a background task and never attempts network repairs.

## Known limitations / future milestones

- This step does not add incident state or scheduling. Reboot/sleep handling, stale monitor freshness, incident deduplication and production config will be designed and tested in subsequent milestones.
- The validated example configuration is deliberately the only accepted configuration path; production profile and arbitrary state locations are rejected.
- The bootstrap Python path is currently specific to SQUALL (`C:\Python313\python.exe`) and requires a reviewed strategy for portable installation later.
- Historical v0.6.0 test runners remain tied to their original old baseline/worktree, so this milestone adds branch-independent tests rather than executing those old runners.
- Local GitHub `main` and the protected production backup must remain untouched. Commit, push, merge and deployment require independent checks/approval.
