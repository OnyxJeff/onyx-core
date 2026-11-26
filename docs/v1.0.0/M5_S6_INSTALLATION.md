# v1.0.0 release installation candidate — M5-S6

Status: release candidate for review; native R2 components qualified, complete clean-host installation not qualified. Not published.
This new path is separate from the ten accepted M5 additions. Do not run native
publication against SQUALL or svr-onyxcore; those already have an accepted installation.

## Configuration and package contract

- Build from the exact M4 runtime inputs and accepted S5 launcher; the builder checks
  the accepted M5 and S5 archive identities internally. No historical installation or
  archive download is required. Historical builders are unchanged.
- `onyx_v100_release_build.py build --repo ABSOLUTE_REPO --role windows|pi-armv6
  --output ABSOLUTE_NEW_ZIP` writes a new deterministic ZIP outside the source tree.
  Use `verify` with the same arguments to compare the bytes. The manifest distinguishes
  runtime source identity from the not-yet-committed installer source.
- Verify each archive against its independently obtained SHA-256 before trusting any
  extracted code. The manifest is an inventory, not a signature. Candidate SHA-256
  values are not a substitute for authenticated final release checksums.
- Copy the two platform examples to separate operator configuration files. Set matching
  telemetry source and receiver port. Set the Windows receiver address within the Pi
  subnet, network-metric adapter, USB adapter, interval, loopback port and optional CPU
  sensor endpoint/path. Pi state is fixed at `/var/lib/onyxcore-v100`; never use legacy
  state. `cpu_temperature.enabled` may be false when no supported sensor is available.
- Reference profile used in native acceptance: source SQUALL; receiver 192.168.137.167:8765;
  adapter Ethernet; USB Ethernet 3; interval 30; gateway 127.0.0.1:18976;
  CPU endpoint http://192.168.137.1:8085/data.json; sensor path
  `/Sensor/SQUALL/AMD Ryzen 7 5800X/Temperatures/Core (Tctl/Tdie)`; Pi usb0,
  subnet 192.168.137.0/24. These are examples, not runtime defaults for all users.
- No credential value appears in configuration, archive, action or receipt. The collector
  uses the qualified hidden WScript launcher with host switches `//B //Nologo` before the script path, and user DPAPI credential; the gateway is
  loopback-only and exposes the read-only v100 monitoring view. No unattended monitor,
  notification enrollment or repair task is installed.

## Offline plan (no writes)

Run the reviewed `tools/installation/common/onyx_v100_release_install.py` with Python
3.13 `-I -B` and `plan --archive ABSOLUTE_ZIP --sha256 TRUSTED_HASH --role ROLE
--config ABSOLUTE_ROLE_CONFIG --peer-config ABSOLUTE_OTHER_CONFIG`. For Windows add
`--localappdata ABSOLUTE_NATIVE_LOCALAPPDATA --pythonw ABSOLUTE_PYTHONW_EXE
--systemroot ABSOLUTE_SYSTEMROOT`. The Windows path parameters use native drive paths,
including when previewing on another OS. The plan includes a deterministic inventory,
activation definitions and approval digest, but is not a native preflight result.

## Clean native inactive publication (future separate authorization)

Requires Windows 11, non-elevated same-user Python 3.13, PowerShell 5.1, WScript/VBScript
available, and an independently verified Windows ACL helper. On Pi: root on Raspberry Pi
OS Trixie ARMv6, Python 3.13, exclusive unprivileged `onyxcore-v100` user/group with
`/nonexistent` home and nologin shell; `/opt/onyxcore` must be safely root-owned and
traversable. Host preparation, USB gadget/ICS setup and account creation remain explicit
operator prerequisites, not implicitly performed by publication.

A new host must not have ONYX tasks or an existing release state/configuration. Inspect
service conflicts and ports separately before activation. Never run this clean route as
an upgrade. With separate approval, rerun the exact plan inputs with `publish` instead
of `plan`, plus `--approve-publication --approved-plan PLAN_SHA256`; on Windows also
`--acl-helper ABSOLUTE_REVIEWED_HELPER`. Targets are the versioned user directory
`OnyxCore-v100-Inactive-Release100` and `/opt/onyxcore/v1.0.0-release`. Both use the
previously qualified no-replace publication primitives and native permission audits.
The release installation receipt binds files, configuration and inactive activation plan.
Publication creates no task, unit, history, credentials or activation marker. An incomplete
stage is preserved for inspection, never silently removed.

## Inactive rollback (future separate authorization)

Before state/credential provisioning or activation, the exact approved publication can
be rolled back non-destructively using `rollback-inactive` instead of `publish`,
`--approve-inactive-rollback` instead of `--approve-publication`, the original plan
hash and identical inputs. Native guards refuse existing v100 state and ONYX tasks
or units. The exact published inventory and permissions must match. The directory is
renamed without replacement to a fixed quarantine name, preserving the full receipt
and all contents. A quarantine collision or modified runtime fails closed. This is
rollback of inactive code only; do not run against a live or manually launched runtime.

## Credential preparation, activation and active rollback (offline implementation)

All three operations require separate native authorization, the original authenticated
archive, unchanged role and peer configurations, and the exact approved installation
plan digest. Both configuration digests are bound into the receipt and plan. This
clean route requires the Windows receiver host to be the direct Pi IPv4 address.
DNS names are intentionally refused until native hostname qualification is available.

Use the role-specific Python executor from the independently authenticated release:

- `tools/installation/common/onyx_v100_release_windows_activation.py`
- `tools/installation/common/onyx_v100_release_pi_activation.py`

Use Python 3.13 with `-I -B`; arguments shared by both are
`OPERATION --archive ABSOLUTE_ZIP --sha256 TRUSTED_HASH --config ABSOLUTE_ROLE_CONFIG
--peer-config ABSOLUTE_OTHER_CONFIG --approved-plan PLAN_SHA256`. Windows also requires
`--localappdata ABSOLUTE_NATIVE_LOCALAPPDATA --pythonw ABSOLUTE_PYTHONW_EXE
--systemroot ABSOLUTE_SYSTEMROOT`. The selected role is implicit in the executor.
Do not call the internal PowerShell driver directly. No execution policy bypass is
used. The following order is the intended clean-host workflow, not permission to
execute it on existing installations or this development candidate.

1. Prepare and publish both inactive packages using the preceding plan/publication
   procedure. On the Pi, the dedicated service user/group and `/opt/onyxcore` parent
   must already exist; Windows and Pi OS, USB/ICS and dependencies must already be
   prepared. Native operations refuse other ONYX installations and abandoned stages.
2. Use `prepare --approve-credential-preparation` on each role. Supply the same
   operator-generated random URL-safe 32–128 character token twice through each
   secure interactive prompt. Never put the token in a CLI argument, configuration,
   archive, shell history, or transcript. Windows uses CurrentUser DPAPI and a
   restricted new state DACL; Pi uses a root-only environment file and dedicated
   service-owned empty state directory. Both refuse replacement and retain partial
   stages on failure. Account creation and OS/network provisioning are not automated.
3. Use `activate --approve-activation` on Pi first. Verify that the authenticated
   published runtime, state, credentials, USB IPv4, free port and absent competing
   unit satisfy the guard. The Pi writes a root-owned intent before publishing the
   exact unit without replacement, then reloads systemd, starts the unit, checks
   health and enables the service. No unrelated unit is intentionally changed.
4. Use `activate --approve-activation` on Windows. The native driver checks state
   DACLs, absence of ONYX tasks/processes, adapters and port. It creates exact
   interactive limited logon tasks via Task Scheduler create-only registration,
   records exported XML hashes before starting them, and requires fresh telemetry.
   Monitoring remains read-only; no unattended observation is installed.
5. To roll back a complete clean activation, use `rollback --approve-active-rollback`
   on Windows first and Pi second. Both authenticate the same release and plan,
   verify owned definitions before stopping anything, then remove only those
   definitions (Pi quarantines its exact unit file). Windows checks that collector
   and launcher processes have exited before unregistering tasks. Runtime files,
   credentials, logs, telemetry history, monitoring data and evidence are retained.
   Rollback is deactivation, not uninstallation or credential rotation.

An intent is not proof of successful activation. A partial operation fails closed;
never retry by deleting the receipt or existing data. If a crash happens before an
exact Windows task-definition receipt is available, or a unit is only partly loaded,
manual identity review is required. Do not automatically undo unverified definitions.
The supported executor invocations are serialized by a local lock; concurrent
external changes, logons and service-management operations are excluded from the
native qualification procedure. A completed rollback does not permit an in-place
reinstall or migration without a separate reviewed workflow.

## Qualification limits

Native lifecycle results apply to the M5/S5 installation. R2 isolated Windows and ARMv6
component publication, credentials, execution and rollback passed on the existing hosts.
The Windows task used a synthetic child and no logon trigger; the Pi fixture used loopback,
a separate database and a temporary service without boot enablement. These tests did not
execute the complete clean-install or active rollback executors. The original safety guards
remain unchanged. The final plan restores the two WScript host switches already used by the
accepted installation; the final candidate is an offline rebuild, not a new native installation.
The monitoring panel label is corrected in packaged HTML; R2 fixture HTTP byte checks passed,
not a new visual OBS/browser acceptance. Physical USB hot-plug is not qualified; logical
network interruption was accepted. Device removal required manual ICS restoration; the
secondary Windows USB address was not restored. WScript/VBScript availability is a prerequisite.
Use only as a candidate until release engineering and the release designation are approved.
A full clean-host test is required before claiming independently qualified stable installation.
See the repository qualification assessment and release readiness documentation.
