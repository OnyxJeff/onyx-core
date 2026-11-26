# M5-S2B - Deterministic integrated runtime candidates

Status: offline candidate build contract; native installation and activation not accepted.

Source: a8ca64b2d06940952f6181a52b9682c0b75bcad6
Tree: 15e8e437ec3e4b4bdc9301777ec39d450e29918c

## Scope

The M2 historical bundle and publishers are deliberately unchanged. They are
pinned to M1 and are not compatible with these M5 archives. The new builder
reads regular Git blobs from the frozen M4 commit, validates exact source SHA-256
pins and produces separate deterministic Windows and Pi ARMv6 runtime ZIPs.
The package manifest is prospective; it is not an installation receipt.

The Windows candidate includes the generated M4 dashboard and alias, both OBS
overlays, v100 collector, v100 gateway, v100 monitoring view, journal,
assessment and recorder, plus the explicitly selected v080 read-only worker,
projector, journal, job runner, native admission and PowerShell diagnostic
helpers. It preserves the M2 collector mutex, log directory and DPAPI path
isolation. The derived gateway admits its adjacent module directories under
Python -I. The derived launcher retains -I -B, preview default, execution opt-in
and legacy task refusal, adds v100 task refusal and an explicit monitoring-view
switch for the gateway. This is not a live cutover launcher. The package's
example gateway port is 18976, not a legacy reserved port.

The Pi candidate includes the M4 health/store, v100 receiver and config-driven
USB launcher and its dependencies. Both example configs and the derived launcher
require /var/lib/onyxcore-v100, not legacy state. No unit, credential, active
configuration, installation receipt or database is generated or included.
No private SSH material is included; the native diagnostic still requires the
separately provisioned restricted Pi SSH identity and forced-command helper.

## Offline operation

On the frozen M4 worktree, apply the reviewed three-file M5-S2B development patch.
Run test_onyx_v100_m5_candidate.py using unittest discovery. The builder allows
untracked development tooling but refuses tracked or staged source modifications.
The CLI never accepts a source export as the build input; it reads the pinned Git
commit directly. The test-only fixture environment is not a CLI override.

For each role (windows, pi-armv6), run the builder with `plan --repo <absolute
repo> --role <role>`, then `build --repo <absolute repo> --role <role>
--archive <new absolute ZIP outside repo> --approve-build`, then `verify` with
the same repo, role and archive (without approval). A second independent build
must be byte-identical. The verifier reconstructs the exact ZIP bytes from the
same committed inputs, rather than trusting archive-supplied hashes alone.

Output is inert. Do not use the old M2 installer or Pi publisher on these ZIPs.
Do not extract into a live installation or run as root. A native publication
contract with reviewed ACL/ownership, complete inventory, immutable rollback
source, task/unit handover, retained config/credentials/state and interruption
recovery must be prepared and separately authorized. No native execution,
credential read, monitoring record, task or service change is part of this gate.

## Acceptance boundaries

Offline tests exercise deterministic bytes, input and artifact tamper refusal,
no-overwrite, role separation, Windows isolation, standalone -I imports and
NoData projection using a stub server, standalone recorder/assessment help,
Pi entrypoint imports and legacy state refusal. Windows PowerShell parsing and
real Git blob extraction remain native SQUALL acceptance steps; real Windows
runtime, Pi ARMv6, clean installation, activation and rollback remain pending.
The test-only synthetic token is never included in a runtime archive.
