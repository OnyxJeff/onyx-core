# ONYX CORE v1.0.0 — M1-S6B Windows runtime integration

**Status:** offline development candidate; not installed or activated.

This step adds `Invoke-OnyxV100WindowsRuntime.ps1`, an entry point consuming the
strict Windows JSON config validated by `onyx_v100_config.py`. It also introduces
a SHA-pinned offline generator for **separate** versioned collector/gateway source:

- `windows/collector/Send-OnyxTelemetry-v100.ps1`
- `windows/gateway/OnyxGateway_v100.py`

The generator requires frozen v0.9.0 Git blob fingerprints, canonicalizes an
otherwise byte-identical LF/CRLF checkout, refuses mixed line endings, refuses
changed transformation signatures and never overwrites an existing output.
The legacy sources remain unchanged. Both original source blobs are in Git at
commit `a323962a53c7eeb5bab8cc523e2b731ddef64916`.

## Configured runtime behavior

- The collector uses configured `receiver.host`, `receiver.port`,
  `collector.source`, `collector.network_adapter`, and `interval_seconds`.
- CPU temperature is opt-in; the configured endpoint and sensor path replace
  SQUALL-specific values. A disabled sensor never triggers an HTTP request.
- The gateway gets `--receiver-port` and retains localhost-only binding,
  localhost dashboard, existing OBS overlay handling, and DPAPI CurrentUser
  credential boundaries. Local monitoring remains unrequested/disabled.
- Credential files are **not** included in JSON configuration and are never
  read in a preview. Existing user-scoped `%LOCALAPPDATA%\OnyxCore` DPAPI
  credential handling is retained; M2 must provision it on a new host.

## Native preview (safe on SQUALL after package acceptance)

```powershell
$Dev = 'D:\github_repos\onyx-core-v100'
$Launcher = Join-Path $Dev 'tools\installation\windows\Invoke-OnyxV100WindowsRuntime.ps1'
$Config = Join-Path $Dev 'docs\v1.0.0\examples\windows.config.example.json'
foreach ($Component in @('Collector','Gateway')) {
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
        -File $Launcher -ConfigPath $Config -InstalledRoot $Dev `
        -PythonPath 'C:\Python313\python.exe' -Component $Component
}
```

The example configuration is **illustrative**, not an approved SQUALL config.
Preview validates config and prints a sanitized JSON plan. It does not call
collectors, start gateways, read DPAPI secrets, or change Scheduled Tasks.

Execution requires **both** `-Run` and `-ApproveExecution`; the default is
preview. The optional `-DryRun` is collector-only and runs one no-HTTP,
no-credential collection when separately approved. Live execution refuses
existing protected ONYX CORE Scheduled Tasks, including disabled v0.9
candidate tasks, so SQUALL cannot accidentally run competing workloads. Any
production upgrade must use an independently authorized coordinated cutover.

## Not yet accepted

- No M1-S6B runtime has been started. No production task changed.
- Native PowerShell parser and preview acceptance require SQUALL.
- Actual Windows collector no-network dry-run requires a separate explicit
  local execution step; live HTTP and gateway/OBS are not tested here.
- Cross-platform test suite is synthetic. Do not confuse it with an installed
  or reboot-persistent runtime.
- Windows USB adapter/network scope and Pi credential pairing must be checked
  before M2 service activation; validated JSON is not proof of an accessible
  private endpoint.
- Installer manifest, deterministic artifacts, dependencies, task enrollment,
  backup/rollback, reboot/ICS recovery, and end-to-end telemetry still belong
  to M2–M6.
