# ONYX CORE v0.8.0 — Release integration consolidation (R1)

**Based on the committed source archive:** `8a870e95abcfdbdc4fb15be49e28730bc6235b59` (SHA256 `F2FF94D2DB3D0A21784F5472771AEC35C7BBF03D75704FCF5F7A206D4C4F5FA2`).

**Disposition: DEVELOPMENT-ONLY. v0.8.0 release remains HOLD.** This patch adds source-level integration, not production permission. No new Scheduled Task, Credential Manager grant, live probe, incident store, notification, or deployment is created.

## Verified code-level integration gap

- M1 `OnyxLiveConnectivity.verify_local_context()` intentionally requires `D:/github_repos/onyx-core-v080`, development branch and M1 development config. Do **not** remove this guard or reinterpret its return value as a production attestation.
- M1's imported `OnyxMonitorConfig.validate_config()` requires `profile=development` and the v0.7.0 development state directory. The legacy `monitoring.release.example.json` is a **v0.7** release profile and points at a **v0.7** store.
- Phase 18I1 `OnyxGuardedRuntimeBridge.run_authorized_cycles()` requires an explicit `release` storage profile and per-cycle authorization, but by default loads M1's development config and invokes M1's development-context guard. This prevents release operation rather than making it safe.
- M3 `history_path()` already chooses distinct v0.8 development/release stores when `ONYXCORE_V080_STORAGE_PROFILE` is explicit; M4 and M5 consume that history. A release-profile selection alone is not authority to start monitoring.

## What this patch provides

1. `OnyxV080ReleaseProfile.py`: strict v0.8-specific release config parser. It reuses existing shared schema validation using a *temporary deep copy* with exactly the two profile-only values substituted, then returns the original validated release dict. It does not touch M1 or weaken the development CLI guard.
2. `monitoring.v080.release.example.json`: explicit `OnyxCore-v080-Release` state, 120-second cadence, no repair. The file is a **non-secret candidate example**, not an enrolled config or a trusted release manifest.
3. `OnyxV080ReleaseBinding.py`: one reviewed Python-only seam that wires the strict release config, K1 per-cycle source/session/consent authorizer, M1 read-only diagnostic, the I1 guarded M2/M3 bridge, and the strictly release-only M3 history resolver. Its command-line interface accepts only `--check-inert`.
4. `test_release_profile_binding.py`: 19 purely offline tests, including validation refusal cases and an integration test that asserts actual M1/M2/M3 functions are bound **without calling** a live runner.

**A Python caller can invoke the underlying runtime API directly**. This patch deliberately does not provide a live CLI, task, operator enrollment flow or trustworthy release launcher. The Python API cannot stand in for an independent security boundary. The default runtime bridge is capable of real diagnostics/writes if invoked from unreviewed code; **do not call it on SQUALL yet**.

## Release blockers that remain: do not waive silently

- **Trusted launch / consent / source:** Pin the manifest *outside user-editable runtime inputs*, verify included source/config/launcher/diagnostic dependencies and their ancestry/ACLs with stable handle-based attestation, defend reparse/TOCTOU changes; accept the user-scoped Credential Manager trust model explicitly or add an independent authority. The current K1 required-source list does not yet cover the new release binding, configuration validator, PowerShell diagnostic dependencies, or startup launcher.
- **Isolation and containment:** Bound actual external Windows/SSH worker process trees using an independently reviewed Windows Job Object or equivalent; ensure cleanup on timeout, shutdown and revoked grant. M1's subprocess timeouts alone do not establish descendant containment.
- **Runtime and storage:** Pin the production source root/commit, validate `ONYXCORE_V080_STORAGE_PROFILE=release`, confirm source and identity in the active console session; protect the new release journal with reviewed user-specific ACLs; don't write to the v0.7 or development stores.
- **Notifications:** M5 remains opt-in and needs real delivery, retry/deduplication and privacy acceptance. The J1 grant explicitly disallows notifications; treat alert delivery as a **separate approval**.
- **Acceptance/rollback:** Explicitly approved bounded on-host cycles, real incident open/recover, dashboard staleness, verified loopback bindings, actual collector/overlay behavior, supervised stop/revoke, safe deployment and exercised rollback. Existing M6 readiness/rollback files are *drafts* with unclosed production gates.
- **Cross-session:** G5B has not passed. A logged-on-console-only policy can narrow deployment scope, but must not be documented as proven global cross-session exclusion. SEC-01..SEC-10 register from the source archive has no recorded closure, and must be reviewed against final scope.

## Release decision path

1. Integrate/fix **trust and worker containment** against this canonical binding. Provide Windows-native test evidence before enabling a live CLI.
2. Separate explicit decisions for a bounded read-only operational test, alert activation, persistent background enrollment and production cutover. Each is **denied by default**.
3. Use temporary isolated storage for functional tests first. Verify production gateway at `127.0.0.1:18766`, collector, overlays and the historical backup survive.
4. Prepare exact authorized deployment/rollback commands and rehearse reversible cutover. Only after PASS and operator approval should v0.8.0 be merged, tagged or published.

**No automatic network repair. Pi-native browser authentication is deferred to v0.9.0.**
