# ONYX CORE v1.0.0 — M2-S4B: Integrated Windows Runtime Installer

Status: **offline development and SQUALL acceptance pending**. This is not a release or a production installer authorization.

## Purpose

Bring the previously accepted M2-S4A collector, DPAPI helper, and Windows launcher into the M2-S2B inactive Windows sandbox receipt/inventory while retaining the M2-S2A versioned gateway dashboard. Evaluate the same integrated bytes for an M2-S2C user-scoped preview. Do not execute an actual user-scoped installation yet.

## Pinned inputs

- M2-S1 deterministic runtime ZIP (20 committed source files), SHA-256: `b4e3c350e47d087bd06c4249aa163d96abe07b792109fc4e9b1032705e2c263d`.
- M2-S2A versioned dashboard, SHA-256: `16cec6731032a444bf944e165b22fdc179cca6ae6d48252520b77a51be6d8a57`.
- M2-S4A isolation manifest, SHA-256: `be3cd0e4bb066ca76f00fc6948ca44bcf0834cce5995eb46ff6c2909c49c6d7f`.
- The precise M2-S2B, M2-S2C, M2-S4A, and ACL-helper source fingerprints are pinned in `onyx_v100_windows_integrated_install.py`. No source checkout fallback is accepted.
- M1 source commit: `8df66f772d5b15464290b7040621e9b03635d49e`.

## Verified installation file inventory

- Exactly 12 original Windows/common runtime source files are selected from the verified ZIP.
- Exactly **three** existing original files are replaced **in the installation payload only** by the SHA-256-pinned derived bytes: collector, DPAPI gateway helper, runtime launcher.
- One new root-level `runtime-isolation-manifest.json` records the exact derivation and isolated paths.
- The original dashboard is overlaid with the M2-S2A version at both `windows/gateway/gateway-dashboard.html` and `windows/gateway/gateway-dashboard-v100.html`.
- The immutable `bundle-manifest.json`, generated `config/windows.config.json`, and `installation-receipt.json` are included.
- The resulting sandbox has **17 installed files including the receipt**; the per-file receipt binds the three isolated replacements, isolation manifest, and dashboard overlays to their actual digests.
- No DPAPI token, log history, monitoring database, or production runtime is bundled.

## Allowed operations

`onyx_v100_windows_integrated_install.py` supports these CLI modes:

1. `preview-sandbox` (default): pure read-only runtime plan.
2. `preview-user`: read-only native LocalAppData Known Folder and target validation. No ACL action and no installation.
3. `install-sandbox --approve-inactive-sandbox`: creates **one** new, isolated direct child of the operating-system Temp directory. It rejects any existing target and validates the installed receipt.

There is **no user-scoped installation CLI mode** in M2-S4B. Native PS 5.1 checks must parse all three installed derived `.ps1` assets. Collector and gateway launchers may be exercised only in their non-activating preview mode.

## Safety invariants

- No changes to the M1 Git commit, original runtime ZIP, legacy gateway, collector, tasks, DPAPI store, or protected monitoring histories.
- No credential read/enrollment, collector send, gateway listener, Pi access, network probe, registry change, service enablement, or deployment.
- Source file injection, bundle alteration, dashboard alteration, manifest tampering, modified installed bytes, extra files, partial CLI approval, and repeated installation are rejected.
- Reserved loopback gateway ports 18766–18769 are blocked; preview uses 18976.
- User-scoped installation remains unavailable until separately authorized and tested with native Windows ACLs.

## SQUALL acceptance

1. Verify the frozen M1 development HEAD and production `main` HEAD, the one protected backup, the approved runtime candidate, and the hashes of all **30** existing M2 files. Require no staged or modified tracked development files and exactly 30 expected untracked files.
2. Verify exactly three patch members with exact SHA-256; stage their pinned dependencies from development after verification.
3. Run 24 tests from stage, including a native Known Folder preview test on Windows. Validate Python 3.13 source parsing.
4. Add three new untracked development files only. Repeat tests using the actual added sources.
5. Preview a new user-scoped target only. Create and verify exactly one inactive **Temp** sandbox with the derived assets, then parse and preview the installed PowerShell launchers without activation.
6. Verify exactly 33 expected untracked M2 files, unchanged Git HEADs, unchanged approved bundle/dashboard/backup, and no production writes.

## Not yet demonstrated

- Real persistent user-scoped install, native ACL enforcement on the true installation tree, token enrollment, actual telemetry delivery, reboot persistence, native ARMv6 deployment, rollback, and end-to-end upgrade acceptance.

**Separate authorization is required** before any commit, push, merge, tag, persistent installation, credential enrollment, service/task registration, or live activation.
