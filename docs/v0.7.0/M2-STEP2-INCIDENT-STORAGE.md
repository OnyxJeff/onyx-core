# ONYX CORE v0.7.0 — M2 Step 2: Atomic incident state and bounded journal

**Status:** Development-only/offline validation; no production deployment, automatic schedule, live probes, credential handling, or network repair.

## Files

- `windows/monitoring/OnyxIncidentStore.py` — standard-library persistence helper for the M2 incident reducer.
- `tests/monitoring/test_incident_store.py` — synthetic durability, corruption, replay, and concurrency tests using temporary directories.
- `docs/v0.7.0/M2-STEP2-INCIDENT-STORAGE.md` — this contract.

The reducer `OnyxIncidentState.py` remains unchanged. The existing M1 runner and evidence collector remain unchanged. No incident state is written to a real development directory by installing the package or running its tests.

## Persistence contract

Storage is **one atomic JSON transaction**, `incident-state.json`, holding both the complete incident state and a bounded transition-event journal. A *single* `os.replace` publishes both together; no partial scenario exists where a new state is committed while its corresponding event is absent (or the reverse). The JSON includes:

- `schema_version: 1`
- `generation` equal to the reducer's monotonically increasing `processed_cycles`
- `state` — validated reducer state
- `events` — most recent 128 transition events, not one event per poll
- `events_discarded` — count of journal entries intentionally pruned
- `integrity_sha256` — SHA-256 of canonical JSON **for accidental corruption detection, not authentication**

The maximum snapshot size is 128 KiB. Both event count and document size are enforced on read and before replacement. Corrupted, oversized, contradictory, unknown-schema, or duplicate-key records **raise `CorruptIncidentStore` and remain untouched**. Never silently reset a damaged incident. The writer does not back up or quarantine automatically.

Each accepted cycle is reduced under a nonblocking OS file lock (`msvcrt` for Windows and `fcntl` for POSIX). The lock file `incident-state.json.lock` remains as a normal coordination artifact; the OS releases its underlying lock on process termination. The snapshot is written to a uniquely named sibling temporary file, flushed and `fsync`ed before atomic replacement; temporary files are cleaned up on ordinary write failures. On POSIX, directory metadata is also synced where supported. Windows filesystem/power-loss behavior still requires later real-world verification and appropriate backups.

Repeated delivery of the *same last cycle* is an idempotent no-op: no disk write and no duplicate journal event. Conflicting same-timestamp cycles and out-of-order timestamps fail without changing storage. If a process fails after `os.replace` but before acknowledging success, retrying the cycle safely reads the committed state and does not produce a second event. The bounded journal cannot provide indefinite audit retention; long-term export and rotation policy belong to a later milestone.

## Example (synthetic use only)

```python
from pathlib import Path
from OnyxIncidentStore import advance_store, load_store

# In tests, use a temporary absolute path. Later, the separately guarded adapter
# must select the approved %LOCALAPPDATA%/OnyxCore-v070-Development/Monitoring path.
path = Path(r"C:\Users\EXAMPLE\AppData\Local\OnyxCore-v070-Development\Monitoring\incident-state.json")
# outcome = advance_store(path, validated_cycle_dict)
# snapshot = load_store(path)
```

The `advance_store` API is a low-level library: it accepts any absolute path ending in `incident-state.json` to support isolated temp tests. **It is not a production entry point.** The future M2 adapter must validate that the selected directory is the approved v0.7.0 *development-only* path from `OnyxMonitorConfig.py` before calling it; this module itself does not decide which host/repository is authorized.

`load_store()` treats a missing file as a fresh initial state. This is suitable for first setup but **cannot distinguish first boot from external deletion of a previously committed store**. The future supervised adapter must establish a durable initialization/retention policy to avoid silently losing old open incidents after external deletion. Corrupted *existing* stores fail closed now.

## Offline tests

From the v0.7.0 worktree in Windows PowerShell:

```powershell
& 'C:\Python313\python.exe' -m unittest discover -s tests\monitoring -p 'test_*.py' -v
```

Expected count at this checkpoint: **71 monitoring tests** (47 existing + 24 new). These tests simulate write failures before and after atomic replacement, duplicate cycles after crashes, overlapping writers, corruption (including checksum-recomputed structural tampering), journal rotation, missing/invalid files, and incident recovery after reload. They do not contact SQUALL network interfaces or the Pi.

## Next implementation boundary

M2 Step 3 integrates this persistence library with an explicitly controlled one-cycle adapter. A separate validation gate will test the adapter against synthetic cycle summaries first. Live read-only use and scheduling require separate review; automatic ICS repair remains forbidden.
