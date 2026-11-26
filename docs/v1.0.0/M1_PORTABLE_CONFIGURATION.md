# ONYX CORE v1.0.0  -  M1-S3 portable configuration foundation

Status: offline-only configuration validation module and examples. **Not deployed.**

`tools/installation/common/onyx_v100_config.py` validates strict, platform-tagged
JSON using only the Python standard library. This is not yet connected to the
Windows collector, gateway or Pi systemd launcher. The validation CLI never
installs, creates credentials, probes the network, or writes configuration.

## Example use (read-only)

```powershell
& 'C:\Python313\python.exe' -I -B `
    'tools\installation\common\onyx_v100_config.py' `
    --platform windows `
    --config 'docs\v1.0.0\examples\windows.config.example.json'
```

```sh
python3 -I -B tools/installation/common/onyx_v100_config.py \
    --platform pi-armv6 \
    --config docs/v1.0.0/examples/pi-armv6.config.example.json
```

`load_config(path, platform)` provides an in-process strict loader for later
installation/controller integration. `summary(config)` intentionally omits
hostnames, adapter names, paths and CPU sensor details from CLI output.

## Security and integration boundaries

- Unknown keys, including credentials and tokens, are refused. **Never put
  credentials in these JSON documents.** Windows continues to use CurrentUser
  DPAPI; Pi receiver secrets remain in its separately protected env file.
- The Windows gateway is restricted to `127.0.0.1`. The Pi interface and
  storage path are configurable, not auto-deduced from SQUALL's lease.
- Validation is syntactic and structural. It **does not verify** that a host
  resolves onto the USB adapter, that an adapter exists, that permissions are
  safe, or that two hosts' ports and credentials agree.
- The Windows CPU sensor block is optional. If enabled, it requires an HTTP
  private/local `data.json` endpoint and an explicit sensor path; runtime
  support for actually consuming this configuration is a later milestone.
- The config examples are templates, not discovered host configuration and
  not instructions to change existing production settings.
- On Pi, the storage `state_dir` can vary by installation. The installer must
  separately check ownership, permissions, symlinks and service sandboxing.
- Persist actual configuration outside immutable versioned package trees.
  Suggested locations (to be approved): user-scoped Windows ONYX CORE state
  and root-managed Pi `/etc/onyxcore`; this module does not write either.

## Milestone evidence and next integration

M1-S3 acceptance requires offline tests of both example configs and security
refusals, native Windows Python 3.13 execution, and unchanged Git production.
It **does not** constitute a clean installation, configuration enrollment, or
runtime activation. The next code integration should teach the Windows
collector/gateway and Pi launcher to consume a validated installed config,
while preserving their existing behavior until an authorized test.

## M1-S5: explicit USB IPv4 subnet selector

The Pi receiver config now **requires** `receiver.ipv4_subnet` (canonical private
IPv4 CIDR, /16 to /30). The installer/runtime must match the configured
interface AND this subnet, and refuse zero or multiple eligible addresses.
It must not assume `192.168.137.0/24`, guess from assignment order, or delete
other addresses. M1-S3 example configurations were amended before a commit;
this is an intentional schema contract tightening, not a production migration.

## M1-S10: paired source identity (additive uncommitted schema tightening)

Pi configuration now requires a nonsecret `receiver.source` string, using the
same strict syntax as Windows `collector.source` (1–64 letters, digits,
underscore, period or hyphen, starting with a letter or digit). Its example
value is `MyWindowsPC`, matching the Windows example.

`validate_pair(windows, pi)` checks both configuration schemas and demands
matching source identities and receiver ports. It performs **no DNS lookup,
network probe or credential verification**; M2 must require this paired check
before candidate activation and separately verify that the receiver hostname
routes solely over the intended USB interface. The value is telemetry identity,
not a secret or an authorization credential.
