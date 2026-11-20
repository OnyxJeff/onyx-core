# ONYX CORE v1.0.0 - M1-S4 ARMv6 Pi observational readiness

**Status:** development-only, read-only implementation. Not installed or executed on the production Pi.

## Purpose

`tools/installation/pi/onyx_v100_pi_readiness.py` consumes the strict M1-S3
Pi configuration and inspects only local OS, network-interface, account, and
filesystem **metadata**. It distinguishes unsupported hosts from missing
configuration or provisioning tasks. It does not claim a clean install or
receiver activation succeeded.

This is an implementation of Pi prerequisite discovery, not a service installer.
An original Pi Zero Rev 1.3 running 32-bit Raspberry Pi OS Trixie and Python
3.13.x is the current supported candidate environment. Additional OS and Python
versions require separately reviewed compatibility testing. `debian`/`raspbian`
Trixie identification is a preliminary family check, not OS image provenance.

## Offline tests (run on SQUALL)

```powershell
& 'C:\Python313\python.exe' -I -B `
    'D:\github_repos\onyx-core-v100\tests\installation\test_onyx_v100_pi_readiness.py'
```

Tests inject synthetic Pi observations and do not start, stop or inspect
production tasks, Pi services, USB links, database files or credential data.
The Python module is compatible with `-I -B` and has only standard-library
requirements. The shared M1-S3 configuration validator is required and is not
replaced by this patch.

## Native Pi inspection (requires *separate* operator approval)

Only after reviewing the source and transferring the verified module and config
validator to a non-production staging location on the Pi, run:

```sh
python3 -I -B /path/to/stage/tools/installation/pi/onyx_v100_pi_readiness.py \
    --config /path/to/stage/docs/v1.0.0/examples/pi-armv6.config.example.json
```

Do not run from a production release tree or replace production configuration.
The command inspects local `uname` architecture, `/proc/device-tree/model`,
`/etc/os-release`, service and state *metadata*, and selected interface IPv4
metadata using `ip -j -4 address show dev <interface>` (kernel netlink query,
not a remote network probe). It reads neither `receiver.env` contents nor
SQLite. It does not send packets, modify ICS, call systemd, install dependencies,
or write state.

The example configuration has `usb0` and `/var/lib/onyxcore` values for
illustration. Real deployment must validate the selected address, authenticated
USB peer, task/service status, filesystem access, and potential legacy state.
This checker intentionally does not verify them end to end.

## Protected credential metadata on existing installations

Existing production installations can intentionally use `/etc/onyxcore` with
root-owned mode 0700. The normal `onyxpi` user cannot traverse that directory.
An unprivileged checker may therefore **not be able to determine** whether
`receiver.env` is present. This is not an absent credential or a reason to
re-enroll it. The checker returns JSON `null` for uninspectable presence and
an explicit operator action to request a *separately authorized* privileged,
read-only metadata check. It never reads the secret's contents.

`credential_file_metadata_inspected` distinguishes a verified presence/absence
from an unknown result. Known unsafe permissions remain a blocker. No
privileged commands, sudo invocations, or changes are performed automatically.

## Report contract

The script emits a single ASCII-safe JSON object with operation
`READ_ONLY_PI_INSTALL_PREFLIGHT`, `observation_only: true`,
`installation_accepted: false`, and classified `readiness.blockers` plus
`readiness.operator_actions`. No configured addresses, token values, sensitive
file contents, arbitrary device paths, or account IDs are included in output.

`BLOCKED` means a platform/dependency mismatch or existing unsafe metadata.
`REQUIRES_CONFIGURATION` means no such blocker was detected, but native network
and installation acceptance remains outstanding. There is intentionally no
`READY_TO_DEPLOY` or `INSTALLED` conclusion in M1.

## Next step

Build a config-driven *inactive* launch proposal for Windows and Pi, then adapt
the launchers in M2 behind a reviewed opt-in path. Preserve legacy scripts,
services, SQLite histories, protected monitoring, and all current credentials.

## M1-S5: real native dual-address finding

Native `svr-onyxcore` inspection observed both `192.168.137.167/24` and
`10.12.194.1/28` on `usb0`. These are both currently valid private addresses.
The Pi validator now requires a configured private `receiver.ipv4_subnet`; its
read-only readiness report evaluates ambiguity **within the selected subnet**
without probing or changing network configuration. A separate pure binding
selector accepts `ip -j` data and refuses none/multiple matching addresses.
Neither component starts the receiver or changes the existing service.
