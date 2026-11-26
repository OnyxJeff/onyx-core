# ONYX CORE v1.0.0 — M2-S4A Windows runtime isolation

**Scope:** deterministic, OFFLINE generation and verification of isolated Windows
runtime assets from the approved M2-S1 source archive. SQUALL acceptance does not
install, enroll credentials, launch collectors or gateways, register tasks, or
change production.

## Why this is required

The M1-pinned runtime bundle still contains inherited v0.x paths for the Windows
collector (`%LOCALAPPDATA%\OnyxCore`), DPAPI credential, and collector mutex
(`Local\OnyxCoreCollector`). Those names can collide with the working installation.

## Derived assets

- `windows/collector/Send-OnyxTelemetry-v100.ps1`: use `OnyxCore-v100`
  user data directory and `Local\OnyxCoreV100Collector` mutex.
- `windows/gateway/Get-OnyxGatewayToken.ps1`: look only in
  `%LOCALAPPDATA%\OnyxCore-v100\collector-token.dpapi`.
- `tools/installation/windows/Invoke-OnyxV100WindowsRuntime.ps1`: require the
  same versioned credential path for runtime readiness.

The generator requires a SHA256-perfect original M2-S1 runtime ZIP and pinned
individual source assets. It performs exact-one substitutions and records the
derived file hashes in a deterministic manifest. The gateway Python code already
loads the helper beside its script, so it is intentionally unchanged.

## Demonstration only

Preview (read-only):

```text
python -I -B tools/installation/windows/onyx_v100_windows_isolation.py --bundle <approved-runtime-zip>
```

Synthetic build into a *new empty target name* under OS Temp:

```text
python -I -B tools/installation/windows/onyx_v100_windows_isolation.py --bundle <approved-runtime-zip> --output <new-temp-dir> --approve-build
```

Verification:

```text
python -I -B tools/installation/windows/onyx_v100_windows_isolation.py --bundle <approved-runtime-zip> --verify-directory <new-temp-dir>
```

The derived assets are **not automatically included** by M2-S2B or M2-S2C.
**Follow-up M2-S4B must integrate the exact derived assets into the permanent
Windows installer**, revise the installed-file manifest, verify Windows PS 5.1
parsing, ensure port/adapter/endpoint isolation, and perform native acceptance.

The new versioned credential location **does not yet have an ACL enrollment
contract**, and nothing in this phase writes a credential. Do not enable live
runtime or tasks based on this phase alone. The Pi env credential file also
requires a distinct, separately authorized enrollment step.

## Review boundary

M2-S4A commits: **none**. Development M1 HEAD and production HEAD remain pinned.
Tests run entirely on SQUALL with a disposable synthetic directory. Legacy
monitoring histories, token DPAPI stores, and Pi telemetry database remain intact.
