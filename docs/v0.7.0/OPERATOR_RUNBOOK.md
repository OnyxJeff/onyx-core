# ONYX CORE v0.7.0 — Release Operator Runbook (Candidate)

**Status:** REVIEW ONLY. The commands below that target `main` are **future-use procedures**, not permission to run them now. Production currently remains v0.6.0.\
**Operator platform:** Windows 11 SQUALL, Windows PowerShell 5.1.\
**Reviewed candidate:** `9a98172b15463b661c462d810a0b812245cdcf3f`.

## 1. What the commands do

| Entry point | Effect | Consent |
|---|---|---|
| `OnyxReleasePolicy.py --check` | Offline validation of tracked release config | No probes or writes |
| `OnyxReleaseCyclePreflight.py --plan-one-shot --intended-live-read-only` | Offline inspection of proposed one-shot state | No probes or writes |
| `OnyxReleaseReadOnly.py --status` | Reads an **already initialized** historical incident store | No probes or writes |
| `OnyxReleaseReadOnly.py --report` | Reads historical incidents and evaluates age/staleness | No probes or writes |
| `OnyxReleaseLiveIncident.py --live-read-only` | **One real** bounded Windows/Pi diagnostic plus release history write | Explicit separate live authorization |
| `OnyxReleaseLiveIncident.py --live-read-only --initialize-new` | Same, plus first-time release state initialization | Separate live **and** first-run initialization authorizations |

`Invoke-OnyxReleaseCycle.ps1` and `Collect-OnyxReleaseEvidence.ps1` are supervised child components. **Do not launch them directly.** The development commands are separately guarded and must not be used to operate release history.

## 2. Required installation and host checks

Perform these checks after an **approved merge and deliberate checkout update**, not from the development worktree:

- Repository at exactly `D:\github_repos\onyx-core`, checked out to `main`, with all required release runtime source files tracked and no modified tracked files or untracked monitoring source.
- Python at `C:\Python313\python.exe`; SSH at `C:\Windows\System32\OpenSSH\ssh.exe`; restricted identity at `%USERPROFILE%\.ssh\onyxcore_monitor_ed25519`, with established strict host-key checking and forced-command access.
- Tracked config at `windows\monitoring\monitoring.release.example.json`, with `profile=release`, `read_only=true`, `repair_action=None`; the runtime rejects arbitrary config paths and a dirty tracked checkout.
- Windows USB device `Ethernet 3` is the Raspberry Pi RNDIS interface, with ICS gateway `192.168.137.1/24`; upstream is `Ethernet`; configured Pi receiver is `192.168.137.167:8765`. Revalidate at time of actual use: those are historical November 9 observations.
- ICS `SharedAccess` and established existing ONYX CORE services/tasks remain operational. Neither the operator nor the release command changes network configuration.
- Release store is derived from `%LOCALAPPDATA%\OnyxCore-v070-Release\Monitoring` **for the Windows user running the CLI**. Use the intended operator account consistently; a different Windows user sees a different store.
- Before first use, review the release-store directory, all ancestor junction/reparse points, access permissions, and any prior marker, store, lock, observations, or unknown files. The development incident store is unrelated and must not be reset or imported.

**SQUALL passive observations (2026-11-09):** `Ethernet 3` was Up, ICS `SharedAccess` Running/Automatic, `192.168.137.1/24` present, receiver neighbor cache listed `192.168.137.167` as Reachable, and legacy `10.12.194.9/24` was also present. None of this proves live SSH, receiver health, or current Internet connectivity.

## 3. Offline setup validation — only after merge and local deployment approval

```powershell
$Prod = 'D:\github_repos\onyx-core'
$Py = 'C:\Python313\python.exe'

# Offline only: validates the fixed, tracked release config.
& $Py (Join-Path $Prod 'windows\monitoring\OnyxReleasePolicy.py') `
    --check (Join-Path $Prod 'windows\monitoring\monitoring.release.example.json')
if ($LASTEXITCODE -ne 0) { throw 'Release config refused.' }
```

**Do not edit `monitoring.release.example.json` locally to correct an alias/IP.** It is tracked and the runtime requires clean tracked sources. Correct discrepancies in a reviewed change before deployment.

## 4. Release-store preflight — no probe and no initialization

**For an already initialized, valid release store**, after deployment approval:

```powershell
& $Py (Join-Path $Prod 'windows\monitoring\OnyxReleaseCyclePreflight.py') `
    --plan-one-shot --intended-live-read-only --json
if ($LASTEXITCODE -ne 0) { throw 'Existing-store preflight refused.' }
```

**For a confirmed brand-new release store**, only after separately reviewing and approving the initial state:

```powershell
& $Py (Join-Path $Prod 'windows\monitoring\OnyxReleaseCyclePreflight.py') `
    --plan-one-shot --intended-live-read-only --initialize-new --json
if ($LASTEXITCODE -ne 0) { throw 'First-run preflight refused.' }
```

The `--initialize-new` preflight **does not initialize** anything; it only checks if a later first-run request would be eligible. A fresh directory must contain **no leftover lock, observation history, marker, store, or other files**. A partial or corrupt store is a hard refusal. Do not remove artifacts merely to make preflight pass.

## 5. Live diagnostic — requires an additional explicit authorization

**DO NOT RUN as part of an offline audit, documentation review, PR creation, or production checkout update.** These examples may probe the Windows upstream and Pi over restricted SSH and write local release history. Each invocation is a single bounded cycle.

For a previously initialized release store:

```powershell
& $Py (Join-Path $Prod 'windows\monitoring\OnyxReleaseLiveIncident.py') `
    --live-read-only
if ($LASTEXITCODE -ne 0) { throw 'Release diagnostic refused or failed.' }
```

For a genuinely empty store **only after the separate first-run authorization**:

```powershell
& $Py (Join-Path $Prod 'windows\monitoring\OnyxReleaseLiveIncident.py') `
    --live-read-only --initialize-new
if ($LASTEXITCODE -ne 0) { throw 'Release first run refused or failed.' }
```

The Python entry point checks release source and policy, takes an exclusive cycle lock, rechecks history under lock, invokes a bounded PowerShell diagnostic, strictly validates one returned cycle, then updates the release incident store if authorized. **Do not rerun first initialization automatically on failure.** A failed attempt can leave an evidence file or lock that deliberately blocks another fresh start.

## 6. Historical operator views — no new probe

Available only after successful release-store initialization:

```powershell
& $Py (Join-Path $Prod 'windows\monitoring\OnyxReleaseReadOnly.py') `
    --status --events 10

& $Py (Join-Path $Prod 'windows\monitoring\OnyxReleaseReadOnly.py') `
    --report --events 10 --stale-minutes 30
```

Optional `--json` is supported. `--events` accepts 0–20; report staleness threshold accepts 1–1440 minutes. **Status and report are historical.** A stored `Healthy` result from an earlier cycle is not evidence of current connectivity. A stale report must be presented as stale.

## 7. Reading decisions and handling failures

- `Healthy`: evidence supported health **at the last completed diagnostic time**, not forever.
- `WaitAndRetry`: startup grace or insufficient corroboration; no automatic retry is configured.
- `Investigate`: missing, contradictory, corrupt, or incomplete evidence; do not treat as proven ICS failure.
- `PossibleIcsFailure`: corroborated suspicion requiring operator investigation; never an instruction to restart ICS or repair the adapter.
- Every cycle requires `repair_action=None`. No automatic remediation, scheduled task, or background monitor is supplied in v0.7.0.
- Refusal due to corrupt/partial state, unknown files, unexpected locks, or invalid source: **STOP**. Preserve files, capture hashes, and follow the rollback/evidence-preservation document. Do not delete markers, locks or observation files; do not fall back to the development history.

## 8. Explicit approval record

Before any production live use, record the exact approved Git commit, operator Windows account, release config/adapter/receiver, protected state inventory, date/time, and specific approval for: (1) release deployment, (2) one live diagnostic cycle, and (3) release-store initialization **if needed**. These are not implied by an offline test passing.
