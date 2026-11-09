# ONYX CORE v0.7.0 — M2 Step 3: Synthetic incident integration

**Scope:** Development worktree only. This step adds a glue adapter for already-tested M1 cycle summaries, the pure M2 reducer, and the atomic M2 incident store. **No live probes, scheduled task, ICS changes, Pi changes, or production incident-state writes.**

## Files

- `windows/monitoring/OnyxIncidentAdapter.py` — a strict synthetic-only entry point and an importable `apply_cycle_to_store` helper.
- `tests/monitoring/test_incident_adapter.py` — in-process synthetic incident integration and replay/corruption tests.
- `docs/v0.7.0/M2-STEP3-INCIDENT-INTEGRATION.md` — this document.
- `tests/monitoring/fixtures/m2_incident_sequence.json` — reproducible synthetic suspected → active → recovered → replay sequence.

## Integration contract

The adapter hands an already normalized M1 cycle **unchanged** to `OnyxIncidentStore.advance_store()`. That store invokes `OnyxIncidentState.apply_cycle()` under its OS lock and commits the resulting state **and** transition events together in one checksummed `incident-state.json`.

The adapter emits only a bounded, sanitized status: phase, display state, evidence completeness, incident ID, current generation, bounded journal counts, new transition event IDs/types, `replayed`, and `repair_action: None`. Raw networking evidence, collector paths, `decision_reason`, SSH keys and credentials are never copied into the incident status or journal.

An incomplete cycle causes the display to be **Unknown**, preserving the underlying active incident. Only corroborated `PossibleIcsFailure` can activate an incident; it is **not** proof that ICS caused the outage. An active incident requires two complete healthy cycles 30–300 seconds apart to recover. Replaying the most recent cycle after a crash is a no-op; same-timestamp conflicts, out-of-order events, invalid input and corrupt stores fail closed.

## Explicit synthetic-only CLI

The sole entry point is `--simulate SEQUENCE_JSON`. It validates it is running on Windows from `D:\github_repos\onyx-core-v070` on branch `feature/v0.7.0-monitoring` with Checkpoint E in its history, and validates the existing development configuration. It **always creates a new temporary OS directory** for the incident file. The temporary store is destroyed after the simulation, including when the process errors; it does not read or write `%LOCALAPPDATA%\OnyxCore-v070-Development\Monitoring\incident-state.json`.

The input is a bounded 256-KiB JSON document with exactly `schema_version: 1` and `cycles` (1..64 normalized M1-style objects). For example:

```json
{"schema_version":1,"cycles":[{"schema_version":1,"source":"LiveRestrictedDiagnostic","cycle_started_utc":"2026-11-09T11:00:00Z","cycle_finished_utc":"2026-11-09T11:00:04Z","duration_ms":4000,"cycle_status":"Complete","connectivity_decision":"Healthy","decision_reason":"synthetic","windows_classification":"WindowsPathReady","pi_classification":"PiInternetVerified","observation_count":1,"consecutive_suspected":0,"history_error_present":false,"windows_error_present":false,"pi_error_present":false,"repair_action":"None"}]}
```

Run with:

```powershell
& 'C:\Python313\python.exe' 'D:\github_repos\onyx-core-v070\windows\monitoring\OnyxIncidentAdapter.py' --simulate 'C:\path\to\synthetic-cycles.json'
```

The returned JSON will have `source: SyntheticIncidentIntegration`. The input's `LiveRestrictedDiagnostic` is merely the validated contract consumed by the reducer; the adapter **does not conduct live diagnostics**.

## Tests and boundaries

```powershell
& 'C:\Python313\python.exe' -m unittest discover -s tests\monitoring -p 'test_*.py' -v
```

The tests use temporary folders and simulate healthy → suspected → active → recovered, a crash/restart with replay, missing evidence, corruption, rejected input and event deduplication. Because the adapter never uses the real development state, this step is safe to run without a live Pi connection.

**Next:** After validating and committing this package, design a separate explicitly opt-in *live read-only* PowerShell orchestrator, with pinned development incident-state directory, an initialization marker/deletion policy, an existing-state backup/rollback plan and real cycle validation. No scheduler or repair automation is authorized by this step.

### Reproducible command-line scenario

The package includes a ready-to-run synthetic fixture; from the development worktree:

```powershell
& 'C:\Python313\python.exe' windows\monitoring\OnyxIncidentAdapter.py --simulate tests\monitoring\fixtures\m2_incident_sequence.json
```

Expected values: `cycles_committed: 4`, `cycles_replayed: 1`, `transition_events_emitted: 3`, `final.phase: Recovered`, `repair_action: None`. The fifth fixture cycle deliberately repeats the previous cycle to prove idempotence. All incident storage is temporary and discarded after the process ends.
