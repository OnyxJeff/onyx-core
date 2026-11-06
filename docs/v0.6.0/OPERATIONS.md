# ONYX CORE v0.6.0 — Manual Reliability Diagnostics

**Operating mode:** Read-only and manually invoked. **Automatic ICS repair is not implemented or enabled.**

## Components and boundaries

- Windows host: `SQUALL` with PowerShell 5.1 and private USB RNDIS interface to the original Pi Zero.
- Development worktree: `D:\github_repos\onyx-core-v060`, `feature/v0.6.0-reliability`.
- Pi monitoring diagnostic (installed separately and owned by root): `/usr/local/libexec/onyxcore-monitor/Test-OnyxUsbForwarding.py`.
- SSH identity on Windows: `%USERPROFILE%\.ssh\onyxcore_monitor_ed25519`.
- SSH is noninteractive, restricted to the forced diagnostic command, and host-key checked; it is **not** a general administrative account.
- History path: `%LOCALAPPDATA%\OnyxCore-v060-Development\recovery-observations.json`. This file is **not** telemetry storage and must not be copied into the production SQLite database.

## Manual evidence collection

In Windows PowerShell 5.1:

```powershell
$Dev = 'D:\github_repos\onyx-core-v060'
$Collector = Join-Path $Dev 'windows\networking\Collect-OnyxRecoveryEvidence.ps1'
$Result = & $Collector

# Review a compact summary before inspecting full details.
$Result | Select-Object mode, observation_count, history_error, windows_error, pi_error, repair_action
$Result.decision | Format-List
$Result.observation | ConvertTo-Json -Depth 8
```

Do not run as a Scheduled Task for this milestone. Do not copy the developer key into the repository, and do not bypass `StrictHostKeyChecking` or `BatchMode` in response to an SSH failure.

## Recovery-policy rules

- **History:** at most 12 observations, at most five minutes old; the history reader bounds input size to 262,144 bytes.
- **SSH:** one restricted command, no password or keyboard-interactive prompts; connection attempt bounded and entire process subject to a wall-clock limit. Oversized or malformed output is treated as inconclusive.
- **Windows:** USB route, receiver TCP reachability, and two upstream TCP destinations (`1.1.1.1:443`, `9.9.9.9:443`) are verified. A Windows upstream failure makes the cause ambiguous.
- **Pi:** gateway reachability, DNS resolution, HTTPS probe and failure of the two external TCP destinations provide corroborating evidence. A single failed target is insufficient.
- **Escalation:** three consecutive, timestamp-ordered, corroborated failures separated by at least 30 seconds in a five-minute window may result in `PossibleIcsFailure`.
- **Fail closed:** corrupt history, missing/unknown startup-grace status, SSH errors, stale evidence, unexpected response content, and unverified upstream results produce non-repair decisions.

The decision output's `repair_action` remains `None` for **all** statuses, including `PossibleIcsFailure`.

## Suggested manual diagnostic workflow

1. Run the collector once and inspect `decision`, `pi_error`, `windows_error`, `history_error`, `observation_count`.
2. If `Healthy`, no intervention is indicated. If the telemetry dashboard still appears broken, check gateway freshness separately.
3. If `WaitAndRetry`, allow for Windows startup/USB initialization; run another manual observation only after enough time has passed. Do not defeat the spacing guard.
4. If `Investigate`, examine evidence for missing routes, failed DNS, failed SSH, or an unavailable Pi. Do not infer ICS failure from one symptom.
5. If `PossibleIcsFailure`, record the evidence and investigate manually. This is **not** permission to restart ICS or change network adapter settings.
6. Confirm read-only status of the existing gateway and both overlays; if applicable, check the existing Windows scheduled tasks without changing them.

## What the diagnostic does **not** do

It does not restart `SharedAccess`, set IP addresses, toggle USB/Ethernet adapters, alter Windows Internet Connection Sharing settings, edit Pi routes, modify production telemetry, reset tokens, or install scheduled tasks. These are deliberately out of scope.

## Troubleshooting safely

**SSH error or timeout:** inspect whether the Pi is reachable on the USB network, whether the dedicated key exists, and whether the forced command is installed. Do not enter a password or run a general-purpose SSH shell with the restricted key. Use a separately authorized administrator login only for manual repair/inspection.

**History error:** the collector fails closed and can rebuild its isolated development history. Do not treat the missing sequence as three separate corroborated failures. Retain a sanitized copy if necessary for debugging; avoid sharing user paths or credentials.

**Pi DNS/HTTPS evidence disagrees:** classify as inconclusive rather than presuming ICS is responsible. The Pi diagnostic and Windows upstream probe can fail for independent reasons.

**Existing gateway returns HTTP 200 but overlays show stale data:** inspect the gateway's `/api/v1/health` behavior and telemetry freshness under existing credentials. Do not embed the bearer token in a URL or browser screenshot.

## Manual regression commands

```powershell
$Dev = 'D:\github_repos\onyx-core-v060'
$Test = Join-Path $Dev 'windows\networking\Test-OnyxRecoveryMilestone6.ps1'
& $Test                  # offline
& $Test -RunBaselineTests # existing v0.5.1 automated suites
& $Test -LiveReadOnly     # explicit live, read-only checks
```

Review both OBS overlays visually, including actual telemetry freshness, before declaring release-ready. Document results and exact Git commit in the release checklist.
