# ONYX CORE v0.8.0 — Phase 17 Storage Profile Isolation (Development Patch)

**Status:** Implementation proposal for offline validation. **Not authorization for production activation, Scheduled Tasks, live probes, or webhooks.**

## Shared storage selection

M3's `history_path()` is the one source of truth. M4's read-only snapshot and M5's journal and cursor use it, so separate processes **must** be launched under the same Windows account with the same explicitly selected profile. Merely changing a PowerShell session variable does not change the environment of an already-running gateway or Scheduled Task.

Environment variable: `ONYXCORE_V080_STORAGE_PROFILE` (exact case-sensitive values):

| Value | Incident history | Selection |
| --- | --- | --- |
| Variable absent or `development` | `%LOCALAPPDATA%\OnyxCore-v080-Development\Monitoring\incident-history.sqlite3` | Backward-compatible default |
| `release` | `%LOCALAPPDATA%\OnyxCore-v080-Release\Monitoring\incident-history.sqlite3` | Explicit path selection only |
| Any other value, including empty | None | Refuse; never fall back |

M5 cursor follows the same selected directory as `alert-delivery.sqlite3`. The paths of the protected v0.7.0 release and development stores remain unchanged. There is **no automatic migration or copying of old incidents or notification cursors**. A missing journal is read-only `NoData`; a missing M5 cursor remains uninitialized unless the watcher is explicitly enabled, which is *not* authorized by this patch.

`history_path()` itself creates nothing. SQLite writes remain gated behind M3's explicit `--record-live` mode. The existing path/junction checks and M3 source-validation safeguards remain in effect; redirected `LOCALAPPDATA` is additionally refused. M5 now derives cursor and journal from a single selection in each CLI invocation, avoiding cross-profile mismatches if process environment variables are later changed.

## Scope and remaining blockers

- **Storage selection is not production execution authorization.** M1 `OnyxLiveConnectivity.verify_local_context()` still requires the reviewed `D:\github_repos\onyx-core-v080` development worktree, development branch and config. The inherited `OnyxMonitorConfig` validator also requires `profile: development`. These guards must be reviewed in a **separate production-activation milestone**; do not bypass them.
- M2's `Local\\OnyxCoreV080ForegroundConnectivityMonitor` mutex is scoped to a Windows logon session. Cross-session single-instance protection and unattended startup remain unproven.
- Existing gateway rejects opt-in M4 on port 18766; activation topology and rollback must still be reviewed. Do not change either existing production Scheduled Task.
- M5 webhook watcher remains **disabled** and must not be started as part of this patch. A change of storage profile must not silently enable a watcher, nor re-baseline/rewind a notification cursor.
- Production v0.7.0 `main`, tag, DPAPI material, retained pre-v0.5.0 collector backup, and both protected v0.7 monitoring histories must remain unchanged.

## Offline acceptance

1. Confirm exact development `549a4997996ac81e29ed561a234306dbd079880f`, clean worktree, and unchanged production `06ec81582791fc797f74ad294195d68b2023cb66` before applying.
2. Run `python -B -m unittest discover -s tests/monitoring/v080 -p 'test_storage_profiles.py' -v` and existing M3, M4 and M5 tests **without any real probes**.
3. Verify default, explicit release and invalid selection; read-only M4/M5 behavior; journal/cursor co-location and no cross-profile contamination in synthetic temporary directories.
4. No commit, push, PR, merge, tagging, task installation, live checks or production use until separately reviewed and authorized.
