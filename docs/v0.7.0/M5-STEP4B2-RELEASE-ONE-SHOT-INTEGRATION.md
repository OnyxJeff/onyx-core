# ONYX CORE v0.7.0 — M5 Step 4B2: Release-only manual diagnostic integration

**Candidate state:** Source/testing only. **Not released, merged or installed.** The current SQUALL production repository must remain on v0.6.0 until explicit approval. No live release probe is authorized by installing or testing this package.

## Scope

- `OnyxReleaseLiveIncident.py` is a separate release **entry point** for exactly one explicit `--live-read-only` cycle. A genuinely new release incident store additionally requires `--initialize-new`. No scheduling or repair flags exist.
- `Invoke-OnyxReleaseCycle.ps1` and `Collect-OnyxReleaseEvidence.ps1` are dedicated release counterparts to the development scripts. They keep the existing read-only Windows/SSH/decision logic, but check `main`, approved SQUALL root, clean tracked source, the validated release profile, and a parent-process supervision marker **before probes**.
- The release-specific history is under `%LOCALAPPDATA%\OnyxCore-v070-Release\Monitoring`. Development history under `OnyxCore-v070-Development` is neither read nor written by these entry points.
- Existing development launchers, baseline protections, and `main` remain unchanged by this package.
- `OnyxReleaseReadOnly.REQUIRED_TRACKED` now includes all runtime components. A release read-only view refuses an incomplete or altered tracked installation.

## Execution gates

1. Explicit `--live-read-only` consent; also `--initialize-new` on first use.
2. `approved_release_view(... require_store=False)` checks approved root/branch/runtime/source; `OnyxReleasePolicy` validates operation and release profile.
3. Offline preflight refuses partial, corrupt, redirected or unknown incident artifacts. For a first run, there may be **no leftover lock or prior observations**.
4. The Python runtime creates/obtains a **nonblocking exclusive incident-cycle lock**. It immediately rechecks the store **under the lock**. A new-store check can now recognize only this invocation's owned lock, but never a stale pre-existing lock.
5. Python launches a bounded (120-second) Windows PowerShell process running the release-only collector; the collector uses bounded restricted SSH, strict host-key checking and no repair.
6. Incoming JSON is strictly parsed and independently validated. Existing incident store is rechecked before commit. First-run checks reject surprise files, then the existing marker and atomic state-store transaction are used.
7. Result is sanitized. `repair_action=None` is enforced. A stale `Healthy` result must never be described as proof of live connectivity unless a new cycle actually completes.

## Historical-data behavior

The release collector **does not overwrite corrupted or clock-regressed `recovery-observations.json`**. It records an evidence-integrity problem, suppresses escalation, and leaves the source bytes available for manual recovery. It may still persist the corresponding incomplete incident cycle in the atomic incident store if its output passes strict validation.

A crash after the first run has created the cycle lock or initialization marker can block future first-run attempts. **Do not delete the files to make a failed test pass.** Investigate and back up the actual artifacts first. The release lock and marker are persistent safeguards, not disposable scratch files.

## Safety and test limitations

- SQUALL must run new Python tests, both original PowerShell offline suites, and `Test-OnyxReleaseOneShotOffline.ps1`; optional Windows junction/symlink cases may skip under restricted permissions.
- Automated tests use disposable stores and mocked collectors. They do not perform real Pi SSH, USB diagnostics, ICS changes, or production deployment.
- The PowerShell collector duplicates some reviewed development diagnostic implementation to maintain isolated execution modes; changes should be compared on later updates to avoid divergence.
- Release-only operational approval, first-use state initialization, release configuration verification (particularly adapter alias and receiver address), deployment/rollback procedure, and full end-to-end test on SQUALL are separate gates.
- The env supervision marker is **not a security secret**; local filesystem/Git permissions and strict validation are the protection against unintended or tampered execution.

## Proposed eventual operator invocation (NOT FOR CURRENT DEVELOPMENT WORKTREE)

On an approved, verified `main` installation only, after a separate live-probe authorization and deployment review:

```powershell
& 'C:\Python313\python.exe' `
  'D:\github_repos\onyx-core\windows\monitoring\OnyxReleaseLiveIncident.py' `
  --live-read-only
```

For a genuinely fresh release incident store, the operator would separately approve `--initialize-new`. Do not issue this command today: production has not been merged or reviewed for runtime enablement.

## Acceptance gates

- [ ] New offline tests pass on SQUALL and cross-version tests remain green.
- [ ] All expected files match package hashes and no unapproved files are changed.
- [ ] All four persistent development artifacts are byte-for-byte unchanged.
- [ ] Production `main`, its existing telemetry services and protected backup are untouched.
- [ ] Operator separately approves actual live release probe and/or first initialization after release readiness.
