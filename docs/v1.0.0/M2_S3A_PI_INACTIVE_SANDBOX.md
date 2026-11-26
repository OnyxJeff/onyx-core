# ONYX CORE v1.0.0 — M2-S3A Pi inactive sandbox

Status: development-only; **not an installation onto a live Raspberry Pi**.

## Purpose

Validate that the approved M2-S1 core runtime candidate can be unpacked into
an inert, integrity-checked Pi runtime tree. It uses the exact M1 source commit
`8df66f772d5b15464290b7040621e9b03635d49e` and approved bundle SHA-256
`b4e3c350e47d087bd06c4249aa163d96abe07b792109fc4e9b1032705e2c263d`.

The selected payload contains eight Pi-specific files and three common files.
A host-specific `config/pi-armv6.config.json`, original bundle manifest, and
`installation-receipt.json` are added. No token, database, or service unit is
included. The state directory named in configuration is **not created or changed**.

## Preview and installation boundary

Default CLI is read-only. It works on Windows for offline development tests.
`--install` and `--approve-inactive` must both be supplied, and native execution
is restricted to Linux ARMv6 with Python 3.13. Even then the only permitted
location is a **new direct child of the system temp directory**, matching
`OnyxV100-Pi-*`. No `/opt`, `/etc`, `/var/lib`, USB networking, systemd,
credential enrollment, or runtime activation occurs. Inactive test trees in a
world-writable temp directory are not a secure long-term deployment target.

The use of ordinary POSIX directory rename here makes publication atomic when
its destination remains absent; it does **not** offer a race-free no-replace
primitive against an adversary creating the destination between checks. Such a
primitive, secure ownership/permissions, and durable paths are requirements for
M2-S3B native installation development, not claims of M2-S3A.

## Reproducibility and acceptance

`ONYX_V100_BUNDLE` must point to the independently verified M2-S1 candidate
when running `test_onyx_v100_pi_sandbox_install.py`. Offline tests simulate
native permission only inside disposable OS-temp roots; they do not use SSH.
SQUALL acceptance performs a preview, checks source hashes, and confirms the
existing production and v1 development Git HEADs remain unchanged.

Native Pi hardware acceptance is deferred. The existing `onyxcore-receiver`
service, its `/etc/onyxcore/receiver.env` secret, and SQLite history must remain
unchanged until a separately approved installation/upgrade workflow is ready.
