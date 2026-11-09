# ONYX CORE v0.7.0 — M4 Step 1: Read-only operator incident status

**Scope:** development-only. This step adds a manually invoked, human-readable view of *persisted* incident state. It does **not** run a live diagnostic, modify the incident store, contact the Pi, change ICS, create tasks, perform repairs or deploy code. It does not modify any existing application modules.

## What the operator sees

`OnyxOperatorStatus.py` displays the last stored observation timestamp, the incident lifecycle phase, the separately derived **display status**, evidence completeness, an open incident ID and opened timestamp (when any), last recovery time, processed cycle count and store generation, journal count, discarded historical event count, and up to 20 of the most recent journal transitions.

**The displayed state is historical, not a statement about present network health.** No age-based freshness calculation is made. In particular, an `Active` incident with incomplete most-recent evidence is displayed as `Unknown` while the underlying active incident remains open. No raw decision reasons, SSH output, tokens, filesystem paths or configuration secrets appear in its output.

## Safety and storage policy

- CLI always uses `OnyxLiveIncident.approved_context()` to validate the exact SQUALL development worktree, expected branch and baseline, unchanged production and protected backup, approved read-only config, and pinned `%LOCALAPPDATA%\OnyxCore-v070-Development\Monitoring` location. It additionally requires Checkpoint I to be an ancestor of HEAD.
- `read_status()` is a pure *reader* of an explicitly supplied path for testing. It refuses missing, redirected, uninitialized or incorrectly marked stores **before** invoking `OnyxIncidentStore.load_store()`, which otherwise treats a missing file as a blank first-run state. The store loader checks size, checksum, full state and event schemas, and event chronology.
- Reads the state document once. Atomic writer replacement means the reader receives a complete stored document, not an in-progress partial update. The status command does not acquire or create a lock, does not initialize any file, and never calls the monitoring cycle runner.
- No path override or `--initialize-new` option exists on this CLI. The standalone operator script does not create backups or automatically reset damaged history. Operator inspection of corrupt/missing files is required.
- Both text and `--json` output contain only selected, bounded fields. The `--events` parameter accepts only `0..20`, and an existing journal remains limited by its own independent 128-event retention policy.

## Development-only manual commands

Run **after** installing and validating the M4 package:

```powershell
$Py = 'C:\Python313\python.exe'
$Script = 'D:\github_repos\onyx-core-v070\windows\monitoring\OnyxOperatorStatus.py'

# View last stored status and up to 10 recent transitions. No new probe.
& $Py $Script --status

# Optional: structured read-only output, last 5 transitions.
& $Py $Script --status --json --events 5
```

At the currently validated generation-2 baseline, expect: phase `Healthy`, evidence `Complete`, journal count `0` and no open incident. This is a **stored** result from the previous live cycles, not a fresh network check.

## Offline validation

```powershell
cd D:\github_repos\onyx-core-v070
& 'C:\Python313\python.exe' -m unittest discover -s tests\monitoring -p 'test_operator_status.py' -v
& 'C:\Python313\python.exe' -m unittest discover -s tests\monitoring -p 'test_*.py' -q
```

The new tests use isolated temporary incident stores and mock production-context checks. No test reads or modifies the real development incident history, invokes a live runner, or connects to the Pi. Existing PowerShell offline suites remain required for completion.

**Next gate:** verify the two saved healthy cycles remain byte-for-byte intact after running the real operator CLI manually; then commit the three files as the next development checkpoint. No deployment or scheduling is approved by this step.
