# ONYX CORE v0.7.0 — M5 Step 4B1: Offline Release Cycle Preflight

**Status:** development-only candidate. **No production one-shot diagnostic is enabled.**

**Baseline:** Checkpoint M `f4d7483906674010881a53e7257dbb0759b9c761` (13 development commits beyond the unchanged v0.6.0 production baseline). This patch adds **three files only**; the existing collector, PowerShell runner, development live bridge, and release view CLI are untouched.

## Purpose

The v0.7.0 release policy permits a future manually authorized `one-shot-cycle`, but the actual release-mode PowerShell collector and incident writer are **not yet integrated**. This offline preflight (`windows/monitoring/OnyxReleaseCyclePreflight.py`) is the first gate for that later integration. It validates intent and inspects the presence and integrity of **release-only** incident history without performing a live USB/ICS probe, invoking SSH, creating any directory, acquiring or creating any lock, scheduling, repairing, or changing stored data.

The output always includes `runtime_enabled=false`, `probe_performed=false`, `store_modified=false`, `repair_action=None`, and `future_live_consent_required=true`. A successful planning result is **not** permission to run a later diagnostic.

## Fixed production-only context

It reuses `OnyxReleaseReadOnly.approved_release_view(operation='status', require_store=False)` for the exact release root `D:\github_repos\onyx-core`, committed `main`, tracked clean release source, approved Python runtime, strict release JSON configuration, and `%LOCALAPPDATA%\OnyxCore-v070-Release\Monitoring` with redirect checks. The existing development-only guard and store are never bypassed.

The preflight revalidates the one-shot intent via the pure `OnyxReleasePolicy.validate_release_intent()` contract and requires an **explicit intended-read-only** flag. This does **not** stand in for the runtime `--live-read-only` consent that the future executable must independently require.

### Decision matrix

| Store condition | Preflight behavior |
|---|---|
| Both marker and checksum-validated incident store exist, at least one completed observation, **without** `--initialize-new` | `ExistingValidated` (offline plan only) |
| Both marker and store absent, release directory absent or truly empty, **with** `--initialize-new` | `NewStoreCandidate` (offline plan only; requires separate future first-run approval) |
| Both absent, no `--initialize-new` | Refused (no implicit initialization) |
| Only marker or only store exists | Refused; manual recovery required |
| Marker malformed, store corrupt, store has no completed cycles | Refused; no reset, rewrite or deletion |
| Existing store plus `--initialize-new` | Refused; never reinitialize existing history |
| Redirects, directories substituted for expected files, or unknown artifacts | Refused |

The store's normal writer lock `incident-state.json.lock` is expected **only with a valid initialized store**. Other known files are `incident-cycle.lock` and `recovery-observations.json`. For a genuinely new store, even one leftover lock/history file blocks initialization candidacy. The preflight checks existence and integrity, **not whether any current lock is held**; the future live runner must recheck everything under its exclusive cycle lock immediately before probing and writing.

## CLI (only following a separately approved future merge)

The preflight requires **both** flags even for an offline plan. A new store must also be explicitly selected:

```powershell
& 'C:\Python313\python.exe' `
  'D:\github_repos\onyx-core\windows\monitoring\OnyxReleaseCyclePreflight.py' `
  --plan-one-shot --intended-live-read-only --initialize-new --json
```

Without `--initialize-new`, it checks a previously initialized store. No flags exist to run network probes, schedule, repair, or override the release configuration. Do not invoke this release-only command from the development worktree; the release context gate intentionally refuses it.

## Test boundary and safety

`tests/monitoring/test_release_cycle_preflight.py` uses disposable files and mocked release installation checks; all its storage writes happen **only within temporary test directories**. Tests cover new/existing/partially initialized states; checksum/marker corruption; unexpected artifacts, writer lock behavior and symbolic links; refusal to reset history; explicit intent, negative operations, CLI errors, and repeated byte-for-byte read-only plans.

On SQUALL, install the exact ZIP (3 new files, no overwrites), execute the new tests and all monitoring regressions, run both existing offline PowerShell suites, and verify the four protected **development** incident artifacts' SHA-256 before/after. Expected: 39 new preflight cases, 338 total Python monitoring cases; some symlink tests may be skipped if Windows symlink creation is unavailable. Observe actual results; skipped tests are not passing coverage.

## Still blocking any release-mode live cycle

- Wire a separate, fail-closed release runtime from Python into an explicitly release-aware PowerShell runner and collector. The existing PowerShell scripts are **development-only** and cannot be reused unmodified in release mode.
- Independently revalidate release Git/source context, state marker, lock, config, approved runtimes and restricted SSH identity immediately before **any** probe, and again before persistent writes.
- Review SQUALL-specific path redirects, Windows filesystem permissions/ACLs, network/USB adapter identity, receiver address, forced-command SSH key and host-key pinning.
- Document first initialization, backup/restore, interrupted initialization, retention and rollback; never delete existing incident history as recovery.
- Obtain explicit operator approval for the live cycle and a **separate** first-run approval when no valid release store exists.
- Preserve development data and v0.6.0 runtime, prohibit scheduled execution and ICS repair, and run release-context negative-path tests in disposable fixtures.

**NO-GO** for production merge or live release diagnostics until those gates are satisfied.
