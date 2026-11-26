# v1.0.0-rc.1 release readiness — M6-A review

Selected designation: v1.0.0-rc.1 (prerelease), approved by the operator.
M6-A exact-scope local commit is separately authorized; push, merge, tag and publication
remain separate operations. This document itself grants no execution authorization.

## M5 final review

- M1–M4 and M5 S1–S5: accepted in prior operator checkpoints.
- S6.1–S6.4: R2 offline installation and deterministic build accepted.
- S6.5–S6.6: isolated Windows and Pi native components and fixture rollback accepted.
- S6.7/S7: accepted on 2026-11-26. Windows verified all 22 additions, retained fixture
  evidence and the WScript regression; the Pi preserved volatile rollback evidence in
  persistent root-owned storage without restarting the protected receiver. Final offline
  tests: Linux 86 passed / 2 skipped; Windows 82 passed / 6 skipped; no failures.
  Both M5 candidate archive identities reproduced.
- Complete clean-host install/rollback: explicitly not qualified. No spare hardware or
  independent clean environment; no guard bypass or teardown of the working installation.

See M5_QUALIFICATION_ASSESSMENT.md and M5_S6_INSTALLATION.md for scope and limits.
The final candidate is not yet native qualified as a complete release. Keep the manifest's
`native_qualified: false` status. No new scheduled monitoring, notification enrollment,
network repair or production deployment is included in finalization.

## M6 gates (separate authorization)

1. M6-A: verify the 22 accepted M5 additions, protected Git identities and both final
   M5 candidate archives; reconcile only the release documentation to the selected RC.
2. Stage exactly the reviewed 22 additions, verify the index and commit locally under
   the operator authorization. Record the actual commit and tree after execution.
3. Review release provenance: runtime M4 source identity is not the final release commit.
   Bind published archive checksums to the reviewed release commit using an external
   release evidence/checksum record; rebuild and compare from the final commit.
4. Verify documentation, source and artifact contents exclude credentials, live database,
   private qualification evidence and rollback backups. Validate release assets and notes.
5. Obtain separate approval for push, PR/merge, tag and publication. Publish as a
   prerelease; verify remote tag target, assets, checksums and release status.
6. Promote to stable only after the independent clean-install qualification gate is met
   or document any explicitly approved alternative release policy without claiming it passed.

Production runtime deployment and cleanup of retained evidence are separate operations.
