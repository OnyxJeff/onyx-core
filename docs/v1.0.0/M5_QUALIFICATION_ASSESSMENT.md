# M5-S6.7 / S7 qualification assessment

Status: M5 accepted on 2026-11-26 after successful final offline integration and evidence
preservation on both hosts. No complete clean-host qualification is claimed. No release
publication, new live monitoring observation or production activation is authorized here.

## Native evidence already accepted

| Scope | Result | Boundary |
|---|---|---|
| M5/S5 operational Windows and Pi | Passed | Existing installation, not clean host |
| Dashboard layouts and OBS overlays | Passed | M5/S5 visual acceptance |
| Supervised monitoring | Passed | Explicit one-shot observation; no unattended monitor |
| Windows restart, Pi reboot, logical USB interruption | Passed | Physical removal required manual ICS restoration; physical hot-plug not qualified |
| R2 offline regression | Linux 85 passed / 2 skipped; Windows 81 passed / 6 skipped | No failures; native PowerShell parser passed |
| R2 Windows component fixture | Passed | Native DACL, packaged loopback gateway, synthetic DPAPI, demand-only task with synthetic child, rollback after task exit |
| R2 Pi ARMv6 component fixture | Passed | Native POSIX publication, isolated credentials, authenticated synthetic telemetry, separate SQLite DB, active temporary systemd rollback |
| Complete clean-host install and rollback | Not qualified | No independent pristine hosts available; production guards remain intact |

R2 archives (SHA-256):

- Windows: `c7de690db4e885ef48d5ea2ebc7f327ace233326450d00af6db4a3a9a7f04d5f`
- Pi ARMv6: `c9ebfb764fb5065729c879d38cea270b9003f9a3a0319c4b827a405fe6211521`

Fixture correlation ID: `5d57f363c7bc40ed905d85fdfe520fc2`.
Windows transcript reported `WINDOWS_NATIVE_COMPONENTS_ACCEPTED=True`,
`WINDOWS_FIXTURE_ROLLBACK_ACCEPTED=True`, task removed, ports released and protected
baseline verified. Pi transcript reported `PI_NATIVE_COMPONENTS_ACCEPTED=True`,
`PI_FIXTURE_ROLLBACK_ACCEPTED=True`, `ACTIVE_FIXTURE_ROLLBACK=True`, unit removed,
port released, fixture data retained and protected receiver preserved (PID 621 and
boot identity unchanged). No new monitoring observation, production activation or reboot.

Evidence retained externally (not distributable): Windows `%TEMP%` fixture publication
and task directories, Pi `/var/tmp` fixture, root-only staging, quarantined unit under
`/run/systemd/system`. An authenticated copy of the volatile rollback unit was preserved
in persistent root-owned evidence storage before reboot, with the original retained.
Windows final review reverified fixture receipts and runtime files. Only hashes and
nonsecret metadata belong in review logs. Never commit fixture credentials, database,
raw task receipts or host backups.

## Final source delta

Restore `//B //Nologo` before the launcher script path in generated Windows task arguments,
matching the accepted operational task. Preserve the existing launcher and all executors.
Add targeted plan regression coverage and reconcile the installation guide. Rebuild both
roles because the shared planner and guide are distributed in each. R2 native evidence
remains attributable to R2; final rebuild does not constitute a new native qualification.

Final M5 review: Linux 86 passed / 2 skipped; Windows 82 passed / 6 skipped, no failures.
The WScript switch placement regression passed. Both final M5 archive hashes matched
independent reference builds:

- Windows: `4a24dc9280976eaf16543da36fb9a91c02ae5e5e0c9da38b13d9e68b51060817`
- Pi ARMv6: `994ddef25f7ec4c88cce710ecf332f44a8e2436b0cfe5e1e331b95be8f2382d0`

These are M5 candidate hashes, not a committed-source provenance record. The final
release manifest remains `native_qualified: false`.

## Release decision

The operator selected `v1.0.0-rc.1` for the intended prerelease. Promotion to independently qualified stable
installation requires a genuine clean-host test using authenticated release artifacts
and the unmodified executors, including preparation, startup, end-to-end telemetry and
rollback. Do not misrepresent component qualification as complete installation acceptance.
