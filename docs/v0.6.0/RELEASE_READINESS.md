# ONYX CORE v0.6.0 — Reliability Release Readiness

**Status:** Candidate review only. Not merged, deployed, or released.

**Baseline:** v0.5.1 production `main` at `6d1e599`.
**Milestone 5 development checkpoint:** `725ed95`, branch `feature/v0.6.0-reliability`.
**Worktree:** `D:\github_repos\onyx-core-v060`.
**Release scope:** Read-only Windows/Pi USB-ICS diagnostics, evidence correlation, bounded history, and tests/docs. **No automated ICS repair.**

## Why v0.6.0 exists

The original Raspberry Pi Zero uses USB RNDIS networking to receive authenticated Windows telemetry; Windows Internet Connection Sharing provides Pi upstream access. The new diagnostics distinguish USB-interface initialization, Pi/Windows connectivity, and corroborated upstream failures. They do **not** diagnose ICS with certainty or change networking.

## Existing v0.5.1 production contracts to protect

- Telemetry collector still submits authenticated samples to the Pi receiver. Do not alter its DPAPI token or scheduled task.
- Pi receiver and SQLite history, health/latest APIs, and replay protections are unchanged.
- Windows gateway stays on `127.0.0.1:18766` and continues serving `/dashboard`, `/overlay` (landscape), and `/overlay-portrait` (portrait).
- OBS dimensions: landscape **1280×720**, portrait **450×800**; neither overlay is replaced by a network-monitoring UI.
- Existing gateway task `ONYX CORE - Local Gateway` is not restarted as part of Milestone 6.
- No exposed LAN/WAN service, gateway port change, credential migration, or production file edit is authorized by this milestone.

## Milestones and evidence

| Milestone | Focus | Status |
| --- | --- | --- |
| 1–3 | Read-only USB/ICS probes, decision policy, evidence collector | Committed before `049bd72` |
| 4 | Restricted forced-command SSH, finite timeouts, bounded persistent history | `049bd72`; acceptance tests passed |
| 5 | Adversarial SSH/history/decision testing and DNS/HTTPS evidence forwarding | `725ed95`; 35 policy scenarios and live read-only diagnostics passed |
| 6 | Baseline regression suite, scope audit, operating and rollback documentation | In development; must be validated and committed |

## Milestone 6 gates (all must pass before recommending merge)

- [ ] Development branch has intended ancestry and no unexplained changed files.
- [ ] Production `main` still at the expected checkpoint; pre-existing untracked backup is untouched.
- [ ] No changes to v0.5.1 collector, gateway, overlays, receiver, credentials, or scheduled tasks.
- [ ] Milestone 4 and 5 suites can be rerun after commit without hardcoded-HEAD breakage.
- [ ] Engine, Pi diagnostic, and Windows diagnostic self-tests pass.
- [ ] Receiver regression suite passes (`python -m unittest discover -s tests/services -p 'test_*.py' -v`).
- [ ] Gateway regression suite passes (`python windows/gateway/Test-OnyxGateway.py`).
- [ ] CPU-temperature integration tests pass (`powershell.exe -NoProfile -ExecutionPolicy Bypass -File windows/collector/Test-OnyxCpuTemperature.ps1`).
- [ ] Live read-only USB diagnostics and local gateway HTTP routes pass (explicit opt-in).
- [ ] OBS landscape and portrait visuals are manually checked with fresh telemetry. HTTP 200 alone is insufficient.
- [ ] Documentation explicitly states history bounds, false-positive limits, no repairs, and no automatic scheduling.
- [ ] Deployment and rollback plan reviewed; decision to merge/deploy taken separately.

## Commands from the development worktree

```powershell
$Dev = 'D:\github_repos\onyx-core-v060'
$Test = Join-Path $Dev 'windows\networking\Test-OnyxRecoveryMilestone6.ps1'

# Offline: local diagnostic tests, Git scope audit, mock SSH and history fault cases
& $Test

# Explicitly run existing v0.5.1 receiver, gateway and temperature regression suites
& $Test -RunBaselineTests

# Explicitly perform read-only live diagnostics and localhost gateway GET checks
& $Test -LiveReadOnly
```

The default suite does not invoke the live collector, open HTTP connections, or modify production. The two optional switches are separate, affirmative operations. The live checks may update **development-only** history and contact the Pi over the restricted monitoring key.

## Decision interpretation

| Decision | Meaning | Response |
| --- | --- | --- |
| `Healthy` | Current Windows and Pi checks agree connectivity is working | No action |
| `WaitAndRetry` | Startup grace/adapter initialization or insufficient repeated evidence | Wait, run manually again later |
| `Investigate` | Evidence incomplete, contradictory, stale, malformed, or unavailable | Inspect read-only details; **do not presume ICS failure** |
| `PossibleIcsFailure` | At least three sufficiently spaced, corroborated observations | Manual investigation; **not** repair authorization |

Every decision must retain `repair_action = None`. Three corroborated observations require separate time samples spaced at least 30 seconds apart, within the five-minute evidence window. They are a suspicion threshold, **not** proof that ICS is the cause.

## Known limits / blockers

- This milestone is not an unattended monitor. No task or service is installed for repeated evidence collection.
- A successful probe does not establish post-reboot resilience or automatic recovery from a physical USB disconnect. Those should be validated as controlled manual operational tests before claiming them.
- Live HTTP 200 checks confirm route availability, not render quality or telemetry freshness; check both OBS scenes visually.
- No automatic restart of Windows ICS, Windows services, the Pi, or network adapters is designed or authorized.
- Findings are conditional on the reference hardware, Pi forced-command monitoring setup, and Windows PowerShell 5.1 environment.

## Exit criteria

The milestone is ready to commit only after all its test outcomes are reviewed and no unexpected files changed. Release publication, merge into `main`, and deployment are **separate** operations requiring explicit approval after regression review.
