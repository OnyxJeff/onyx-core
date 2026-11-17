# ONYX CORE v0.8.0 — M4 Offline Operator Visibility

**Scope:** Static, read-only display of **synthetic M3** alert outcomes. No live monitoring, notifications, task changes, external content, persistent stores, or repair.

**Pinned development parent:** `c1aa63790a08603fa3b15d92d2f404ff78ef1a0f` on `feature/v0.8.0-continuous-monitoring`.

**Status:** SQUALL Windows offline acceptance passed (2026-11-10); staged review pending. A local commit and any live runtime remain separately unauthorized.

## Purpose and trust boundary

`windows/monitoring/v080/OnyxOfflineOperatorView.py` translates already-derived, simulated M3 results into a stable operator-facing summary. M4 is **not** an incident reducer, alert state store, authenticated user interface, notification engine, monitoring loop, network server, or acknowledgement endpoint.

Public library functions:

- `build_synthetic_operator_snapshot(m3_outcome, acknowledgement=None)` returns a copied, JSON-compatible, synthetic-only summary; it does not modify the original state.
- `render_synthetic_operator_text(m3_outcome, acknowledgement=None)` returns an accessible plain-text rendering.
- `render_synthetic_operator_html(m3_outcome, acknowledgement=None)` returns a self-contained **static HTML string**; it does not open a browser, bind an HTTP port, write files, or call an API.
- The **only executable CLI argument** is `--check-inert`, which prints disabled capabilities and exits. There is no CLI file input, server, `--render`, `--acknowledge`, `--notify`, or `--live` switch.

M4 imports only the fixed sibling `OnyxOfflineAlertLifecycle.py` for **pure validation** of M3 in-memory data. It does not import the v0.7.0 incident adapter or state store. A rendered HTML preview may be saved separately by a test or an operator's explicitly authorized tooling, but M4 itself writes nothing. The delivered example HTML is generated from hard-coded fake data **outside** the module.

## Exact synthetic source checks

The input is an M3 `ingest_synthetic_batch` result, optionally paired with an M3 `acknowledge_synthetic` result. Both must declare `source=OnyxV080M3SyntheticAlerts`, `provenance=SyntheticFixtureOnly`, and all live/notification/task/repair capabilities **false**. M4 refuses unknown/missing fields, non-JSON-compatible data, more than 32 events per input batch, malformed counters, proposals that reference absent event/intent ledgers, duplicated new intent keys, and inconsistent `display_status` versus evidence completeness.

M3's `validate_state` is required to accept the embedded state. An optional synthetic acknowledgement must preserve **every non-ack field** exactly; its `changed` flag must agree with the before/after fake acknowledgement, and its timestamp must not precede the last observed synthetic event. M4 never accepts an acknowledgement command or authenticates a Windows operator. Acknowledgement **does not resolve an incident**.

Input consistency checks do **not** establish cryptographic origin, actual Windows access rights, real patient/user identity, live connectivity, a working ICS path, or an authenticated operator. A malicious fixture creator could still supply internally consistent synthetic data. Only explicitly scoped future deployment work can extend the trust boundary.

## Rendering semantics

| Signal | Display behavior |
|---|---|
| Visible status | `Unknown` whenever evidence is `Incomplete` or `Unknown`; otherwise M3's synthetic incident phase |
| Incident phase | Last **synthetic** phase kept visible separately, including while displayed health is `Unknown` |
| Evidence | `Complete`, `Incomplete`, or `Unknown`; completeness is not proof of live health |
| Alert lifecycle | Whether a synthetic incident remains open, or a recovery **candidate** is recorded |
| Acknowledgement | Fake actor and timestamp as read-only text; never an actionable control or confirmed identity |
| Deduplication | Current-batch exact replay suppression; aggregate in-memory event and intent ledger counts |
| New proposals | Current-batch M3 intent proposals only; **not notifications sent** |
| Recovery | `Candidate only` only after a provided `IncidentRecovered` event; never independently inferred from restored evidence |

An `EvidenceRestored` transition does not by itself resolve an incident or establish recovery. M3's v0.7.0 reducer compatibility tests retain the 30–300-second two-cycle recovery rule; M4 only describes the already-present synthetic result. It **does not** claim the ICS service is the proven root cause. M3's 256-record deduplication ceiling and non-durable in-memory state remain unchanged. M4 does not refresh, poll, persist, or deduplicate independently.

## Static presentation and security

The HTML contains embedded CSS, text and tables only—**no JavaScript, buttons, forms, links, images, iframes, external fonts, network fetches, or live status refresh**. It includes a restrictive CSP meta tag (`default-src 'none'`, `connect-src 'none'`, `form-action 'none'`, and inline CSS only). All dynamic text is HTML escaped. It supports narrow displays and includes a plain-text equivalent. The page prominently labels itself **SYNTHETIC DATA / NOT LIVE MONITORING**.

## Acceptance requirements

On SQUALL, the guarded installer must confirm the exact production `main` HEAD, isolated M4 development parent, clean worktrees before installation, M1–M3 SHA-256 baseline, exact M4 package files and hashes, original collector backup, and the **five-file inventories and hashes** of both protected v0.7.0 release and development monitoring histories (including `incident-state.json.lock`). It must reject redirected source targets, existing M4 files, unexpected Git changes, or changed protected histories.

After installing **exactly three new untracked M4 files**, it must run `--check-inert` and the full existing-plus-M4 offline test suite. The known Windows symlink-creation test may skip; all M4 tests and real v0.7.0 reducer compatibility tests must pass. It then rechecks hashes, Git inventory, production and protected history. **No staging or local commit is authorized by this development approval.** Separate documentation/staging review and separate local commit authorization are required. Never repeat the installer after a partial installation; inspect the state instead.

## SQUALL Windows offline acceptance — 2026-11-10

**Result: PASS.** The operator verified the M4 source and installer package hashes and PowerShell 5.1 syntax, then ran the guarded no-overwrite installer on SQUALL using Python 3.13. The integrated offline M1–M4 suite reported `Ran 301 tests` and `OK (skipped=1)`: **300 passed, one skipped, zero failed**. All **64 new M4 tests** passed, including static HTML safety, synthetic provenance, evidence masking, read-only acknowledgement display, incident phase, deduplication and recovery-candidate semantics. Both M3 tests requiring the genuine checked-in v0.7.0 reducer passed; the only skipped test was the existing M2A Windows symlink-creation permission case.

The M4 `--check-inert` result declared `read_only=true`, `simulation_only=true`, `notification_enabled=false`, `delivery_permitted=false`, `runtime_enabled=false`, `live_probe_authorized=false`, `task_creation_authorized=false`, `store_modified=false`, and `repair_action=None`. The installer verified production `main`, the pinned M3 parent, all prior milestone source hashes, the original collector backup, and exact five-file release/development protected monitoring inventories and hashes. Exactly three M4 development files remained **untracked**, with no staging or commit. The installer made no Git remote, scheduled-task, diagnostic, notification, enrollment, deployment or repair calls.

This is **operator-provided evidence of offline, synthetic-only host acceptance**, not an authenticated live monitoring result, a production deployment, or authorization for a local commit.
