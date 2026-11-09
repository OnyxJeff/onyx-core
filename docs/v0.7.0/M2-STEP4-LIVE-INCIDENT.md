# ONYX CORE v0.7.0 — M2 Step 4: guarded live incident integration

**Status:** development-only, manually invoked; **not deployed, no scheduled task or repair automation**.

This step introduces `windows/monitoring/OnyxLiveIncident.py` as a narrow operator boundary between the already validated single-cycle PowerShell runner and the incident reducer/store. It does not modify existing source files, telemetry collector, local gateway, Pi receiver, overlays, or network configuration.

## Operator execution model

1. **Before any probe**, confirm Windows, exact `D:\github_repos\onyx-core-v070` worktree, branch `feature/v0.7.0-monitoring`, Checkpoint F ancestry, untouched production main at the v0.6.0 baseline, protected collector backup SHA-256, and approved read-only config.
2. Pin the incident-state directory to `%LOCALAPPDATA%\OnyxCore-v070-Development\Monitoring`; refuse junctions, symlinks, and redirected store files. An OS lock covers the **entire** probe plus incident commit, preventing overlapping cycles.
3. Require explicit `--live-read-only` for every invocation. Run the existing `Invoke-OnyxMonitoringCycle.ps1 -LiveReadOnly -Json` exactly once, in a noninteractive PowerShell 5.1 process; set UTF-8 stdout; bound runtime to 120 seconds. The original runner/collector handles read-only Windows + restricted SSH Pi probes.
4. Decode and validate bounded, strict JSON against the existing reducer contract; reject incomplete/contradictory/unsafe input rather than constructing a healthy result.
5. Apply the cycle with the existing `OnyxIncidentAdapter.apply_cycle_to_store()` (which calls the reducer and atomic store). Print only sanitized summary fields and transition event IDs/types; no raw `decision_reason`, SSH output, private paths or tokens are persisted.
6. Report `repair_action: None` in all successful responses. No networking configuration changes or automatic ICS repair code is present.

## Explicit initialization and missing-store policy

**No incident file is created by importing the module or running tests.** The first *live* transaction requires two opt-ins: `--live-read-only --initialize-new`. That mode is allowed **only if both** `incident-state.json` and `incident-state.initialized.json` are absent. The marker is exclusively created and synchronized **after validating the actual cycle but before the first store transaction**. If the process crashes after marker creation but before the transaction, subsequent runs fail closed. The operator must investigate that incomplete initialization; **do not delete marker/state files to bypass this gate**.

After a successful initial run, subsequent one-cycle runs use only `--live-read-only`. Both state file and initialization marker must be present, the marker must match its expected bytes, and the store must pass checksum/schema validation **before** launching another probe. Missing or corrupt records refuse execution; they are never silently reset.

The OS-level lock file `incident-cycle.lock` is an ordinary synchronization artifact. It is intentionally left in the development state directory between invocations. It is not an incident state or source artifact. The incident transaction itself is bounded to 128 KiB, retains the last 128 events, uses atomic file replacement and an independent writer lock.

**Limitations:** A marker and store deleted together cannot be distinguished from a first-time machine initialization without external backups or supervisory metadata. This step does not implement archival backups or automated recovery. On Windows, an atomic replace does not guarantee full filesystem durability across catastrophic power loss. These are release-readiness risks for later milestones; do not represent this as production-ready autonomous monitoring.

## Offline validation before any live operation

```powershell
cd D:\github_repos\onyx-core-v070
& 'C:\Python313\python.exe' -m unittest discover -s tests\monitoring -p 'test_*.py' -v
```

The new `tests/monitoring/test_live_incident.py` exercises initialization, marker/store disappearance, corruption, duplicate replay, incident escalation/recovery, invalid JSON, restricted PowerShell invocation, timeout/error refusal and mutex guard using **temporary local directories and mocked subprocesses only**. It never contacts the Pi or writes to `%LOCALAPPDATA%\OnyxCore-v070-Development\Monitoring`.

## Manual live steps (require separate validation gate)

Do not run these until the installer + offline tests have passed on SQUALL and the operator has inspected the state directory to confirm no pre-existing incident files:

```powershell
# First persistent diagnostic only, requires new empty state.
& 'C:\Python313\python.exe' 'D:\github_repos\onyx-core-v070\windows\monitoring\OnyxLiveIncident.py' --live-read-only --initialize-new

# Later: one read-only diagnostic and one atomic incident transaction.
& 'C:\Python313\python.exe' 'D:\github_repos\onyx-core-v070\windows\monitoring\OnyxLiveIncident.py' --live-read-only
```

Do not install scheduling/auto-repair or initialize a previously used incident store with these commands. An `IncidentOpened` or `IncidentEscalated` event describes observed connectivity evidence, **not** a proven ICS root cause. Subsequent M2 work should implement supervised startup policy, backups and rollback checks before unattended trials.
