# M1-S6A: Pi configuration-driven receiver runtime (development only)

This checkpoint provides an executable, config-driven Python launcher and a versioned
receiver variant generated from the reviewed v0.9.0 receiver code. It deliberately does
**not** overwrite `pi/services/receiver/receiver.py`, the production Pi filesystem,
or any systemd unit. Do not enable or start a v1 service as part of this step.

## Preview and activation separation

`onyx_v100_pi_launch.py` validates the Pi config, inspects a single configured USB
interface, selects exactly one IPv4 address in the configured private subnet, and
constructs actual receiver arguments including the configured port and persistent
SQLite paths. By default it outputs a JSON preview without starting anything.
The selector rejects ambiguous or missing matches, regardless of other addresses.

Native execution is an **unapproved future step**: `--run --approve-execution` on Linux
with a real interface, an existing storage directory and an already provisioned
`ONYXCORE_TOKEN`. The launcher never reads `/etc/onyxcore/receiver.env` itself and
never generates or changes secrets. Its intended process supervisor will supply the
credential through an appropriately protected service environment.

`onyx_v100_make_receiver.py` makes the versioned `receiver_v100.py` from the
repository's original receiver source. The guarded Windows application step verifies
that source against its Git object before generation. The generated version has an
explicit `--usb-subnet` argument instead of the hardcoded legacy /24 restriction.
No legacy source file or runtime is overwritten.

## Outstanding integration and acceptance

- No receiver has been started or installed on `svr-onyxcore`.
- The generated `receiver_v100.py` requires native Pi dry execution and end-to-end
  HTTP/SQLite testing before it can be accepted for production.
- The Pi-side launcher must be tested under systemd execution identity and sandbox
  permissions in a separately authorized, isolated deployment.
- Windows collector and gateway configuration integration follows in M1-S6B.
- Versioned artifact builder, provenance and installation receipts must be upgraded
  to include these new entry points before M2 installation acceptance.

The receiver generator accepts consistently LF or CRLF Git checkouts, produces
canonical LF output, and still refuses mixed line endings or changed signatures.

## M1-S10 source-identity compatibility correction (offline-only)

The v1 receiver now requires `--expected-source` from the validated Pi
`receiver.source` setting; this must equal the Windows collector's
`collector.source` on an installation. No default `SQUALL` identity exists in
`receiver_v100.py`. The HTTP handler, snapshot-only store, and SQLite bootstrap
use the same explicit validator. A wrong source is rejected with 422 and is not
written to history. This is *additional* validation, not a replacement for the
receiver bearer token; config validation alone cannot prove USB link identity.

`integrated_store_v100.py` preserves the established `history.py` database
schema and transactional append semantics, but uses an injected validated
snapshot policy instead of importing the SQUALL-only legacy `receiver.py`.
If a previously cached snapshot does not match the configured source and the
SQLite DB has not been created, startup refuses **before creating the DB**:
never silently relabel or discard the snapshot. Existing authoritative SQLite
history is retained across source-name changes; operator-controlled backup and
upgrade/cutover are still required. This does not modify legacy store modules.

`onyx_v100_make_receiver.py` now independently pins the full legacy receiver
Git blob `53e4a8a18d443269fb34dde19e5240450b1d232a`, accepting only
consistent LF/CRLF checked-out source and emitting canonical LF output. The
correction is not a deployed Pi service or an authorized database migration.
Native ARMv6 acceptance remains for M2/M5.
