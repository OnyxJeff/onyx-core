# ONYX CORE v0.9.0 RC2 — Native acceptance and release candidate status

- **Evidence date:** 2026-11-19
- **Candidate source commit:** `ed41e4d0cf8049b627bc2b2613d0d231b9bb7478`
- **Release candidate version:** `0.9.0-rc2`
- **Scope:** Windows 11 SQUALL + original Raspberry Pi Zero ARMv6 `svr-onyxcore`; already-provisioned USB RNDIS/ICS environment
- **Status:** Native **manual-only** installation/cutover/rollback rehearsal **ACCEPTED**; final unattended deployment, clean-host provisioning, and reboot/logon acceptance **NOT YET ACCEPTED**.

## Provenance and reproducibility

| Item | Native-accepted result |
| --- | --- |
| Windows ZIP | `ONYX_CORE-v0.9.0-rc2-windows.zip`, 124 files |
| Windows archive SHA-256 | `9a9b1e6d7faeb974821b3faef3846e9fee803c9dd16b704e8559e3d91dfa1f22` |
| Pi ARMv6 ZIP | `ONYX_CORE-v0.9.0-rc2-pi-armv6.zip`, 48 files |
| Pi archive SHA-256 | `b9c3d9856e79a9ebe3d1f150d710699bfe4a5bbb62c9912d252d1a1b22c2f30d` |
| Reproducibility | Two independent builds of both archives produced byte-identical results |
| Installed provenance | Both native installers emitted `PREPARED`, inactive receipts and passed installed-file verification |
| Windows runtime access | Non-elevated `SQUALL` user verified all 124 files and the inspected explicit read/execute ACL entries; not a complete effective-access denial proof |

The source commit above is the **hardware-tested RC2 runtime baseline**. Subsequent documentation/CI-only branch commits may change generated ZIP hashes because documentation is packaged. Do not label a later commit's artifacts with the baseline ZIP digests or claim native acceptance for a new runtime commit without checking its differences.

## Native activation acceptance

1. RC1 candidate task/service definitions were retired only after archival. Existing Windows and Pi production workloads remained running during installation. RC1 release trees and private rollback evidence were preserved.
2. Pi RC2 rollback escrow created, then an independent SQLite-consistent pre-cutover backup completed without a receiver restart.
3. Original Pi receiver was quiesced and guarded. RC2 candidate became active on the USB-only `192.168.137.167:8765` listener, with the legacy service disabled.
4. Original Windows tasks were escrowed and quiesced. RC2 collector and gateway activated under candidate Scheduled Tasks, with **no logon triggers**; Windows gateway listened on `127.0.0.1:18766`.
5. Live telemetry was verified: SQUALL sequence **11** at `2026-11-19T19:51:59Z` advanced to sequence **12** at `2026-11-19T19:52:31Z`. Receiver health was `healthy`, sample age **2 seconds**, SQLite-backed history returned samples, and `/dashboard`, `/overlay`, and `/overlay-portrait` returned HTTP 200.
6. Rollback order was **Windows StopCandidate → Pi rollback → Windows RestoreLegacy**. All three native controller operations succeeded without manual service/task repair. After restoration, SQUALL emitted a new sample at `2026-11-19T20:09:52Z`, with receiver health `healthy`, age **6 seconds**, and all three dashboard/overlay endpoints HTTP 200.

### Data protection evidence

- Native backup ID: `v090-rc2-ed41e4d-20261119T190655Z`.
- Backup contained **11,109 historical samples**, SQLite `user_version=2`, and tables `acceptance_watermark` and `samples`.
- Backup database SHA-256: `ac7de995a88e61241d652619a4aab5918ecef991ec034b9241c502f00136804d`.
- No database restore or replacement was performed during activation or rollback. The original live SQLite database and latest snapshot were retained; backup and earlier RC1 evidence were preserved.
- No tokens, DPAPI contents, private task XML, receiver secrets or protected v0.8.0 monitoring history are included in this report.

## Verified final state after rehearsal

| Component | State |
| --- | --- |
| Original Windows collector task | Running |
| Original Windows gateway task | Running; owned loopback listener `127.0.0.1:18766` |
| Original Pi `onyxcore-receiver.service` | Active and enabled; owns USB listener `192.168.137.167:8765` |
| RC2 Windows candidate tasks | Disabled |
| RC2 Pi candidate unit | Inactive and disabled |
| Windows RC2 escrow journal | `rolled-back` |
| Pi RC2 escrow journal | `rolled-back` |
| Original production telemetry | Fresh and healthy |
| Source code / protected monitoring | No production Git or protected v0.8.0 monitoring changes |

## Explicit limitations and outstanding gates

- **Reboot/logon durability not exercised.** Both RC2 candidates were manual-only; the Pi and Windows candidates were rolled back before reboot. Native `promote-boot` / `PromoteBoot`, persistent startup, actual reboot, post-boot attestation, and user logon behavior remain separate acceptance work.
- **Fresh-host install not proven.** This rehearsal used existing system users, credentials, telemetry storage, USB gadget, Windows ICS, runtime dependencies and preconfigured monitoring/collector environment. It does **not** demonstrate unattended or one-command reproducible setup on a blank Windows/Pi pair.
- **Interrupted-state recovery paths not deliberately fault-injected on live hosts.** RC2 includes explicit recovery operations with synthetic/offline tests, but this healthy-path rollback does not demonstrate every interruption case on native hardware.
- **CI not yet accepted at the time of this evidence report.** GitHub Actions Windows/Linux jobs must pass on the pushed branch and PR; Windows and Linux CI cannot substitute for ARMv6 reboot testing.
- **Visual OBS composition not assessed.** The overlay endpoint HTTP responses were checked, not scene-by-scene visual alignment.
- **Protected v0.8.0 monitoring re-enrollment, alerts and notifications were not part of RC2 activation.** No claim of full monitored deployment is made.

## Merge and release criteria

1. Push the development feature branch after updating CI to include RC2-focused tests; review its source and docs diff.
2. Require successful GitHub Actions checks for the feature branch / pull request, and review any failures before merging.
3. Merge to `main` by operator approval. **Do not automatically tag, publish a release, or deploy** simply because this RC passed native manual-only acceptance.
4. If publishing final packages after merge, build from the **actual final merged commit** and record new SHA-256 values. The native evidence above remains tied to the frozen RC2 source commit.
5. Carry remaining clean-host and durable-startup limitations into the v1.0.0 plan rather than representing them as solved.
