# ONYX CORE v1.0.0 — M2-S2B Inactive Windows Sandbox Installation

## Scope and guarantees

This is an **inactive development sandbox installer**, not a system installer or a
finished release. It consumes **two separately pinned inputs**:

- M2-S1 deterministic core bundle (SHA-256 `b4e3c350e47d087bd06c4249aa163d96abe07b792109fc4e9b1032705e2c263d`)
- M2-S2A versioned dashboard (SHA-256 `16cec6731032a444bf944e165b22fdc179cca6ae6d48252520b77a51be6d8a57`)

The bundle must originate from local M1 source commit
`8df66f772d5b15464290b7040621e9b03635d49e`.

This checkpoint explicitly does **not** modify `C:\Program Files`, existing ONYX
CORE directories, Windows Scheduled Tasks, services, registry, firewall, network
adapters, DNS, DPAPI credentials, Pi services, or persistent application data.
It does not read credentials, perform connectivity tests, or start collector or
gateway processes. Only a newly named direct child of Windows OS Temp may be
published, with `--install --approve-inactive` on native Windows Python 3.13.
Default invocation is a read-only JSON preview.

## Contents

The installer selects the **12 Windows/common payload files** from the 20-file
M2-S1 core bundle (3 common, 9 Windows). The original bundled dashboard page
is overlaid *within the new sandbox only* with the M2-S2A versioned dashboard;
the versioned dashboard is also retained under its own filename. It adds:

- `config/windows.config.json` with caller-supplied receiver host, receiver
  port, source identity, network/USB adapter labels, gateway loopback port and
  collector interval; optional CPU temperature defaults off
- `bundle-manifest.json` copied byte-for-byte from the verified core bundle
- `installation-receipt.json` listing every installed file SHA-256 and size,
  plus explicit proof that no activation or credential enrollment occurred

The resulting sandbox contains exactly 16 files. The receipt is checked against
**the original verified bundle and dashboard bytes**; a self-modified receipt is
not authoritative.

Known production/development gateway ports `18766`, `18767`, `18768`, and
`18769` are refused. Port availability and receiver link routing are NOT
verified in this phase. The acceptance test uses port `18976` but does not bind
it. Production addresses and host labels are not inferred or configured.

## Acceptance and limitations

- Run `test_onyx_v100_windows_install.py` against pinned M2-S1 + M2-S2A assets.
- On SQUALL, run the guarded M2-S2B apply script. It verifies the seven existing
  untracked files before adding three new files; it then creates one inactive
  sandbox under `%TEMP%`, validates the receipt and exercises the installed
  collector/gateway **previews only**.
- Do not start an installed runtime, enroll secrets, register tasks, or use this
  sandbox as a production installation.
- A real user-scoped/system install, Windows ACL verification, port identity,
  dependencies other than Python 3.13, credentials, and clean-host onboarding
  remain for subsequent M2 steps. Pi work remains in M2-S3.
- No local commit, push, merge, tag, or deployment is authorized by this step.

## Operational note

The development sandbox is intentionally not automatically removed: it remains
available for inspection. The operator can remove it separately after reviewing
its receipt. It has no Windows autostart registration.
