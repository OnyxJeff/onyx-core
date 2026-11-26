# ONYX CORE v1.0.0 - M2-S5B Windows No-Replace Publication Acceptance

## Objective

Prove, on native Windows 11, that one **inactive** 17-file, SHA-256-receipted ONYX CORE runtime can be DACL-hardened using the accepted M2-S5A-R3 method and then published to a previously absent directory with a **single no-replace directory move**. Independently prove that an existing destination is preserved when publication is attempted.

This is **not a user-profile installer**. It writes only to newly named direct children of the OS Temp directory with fixed `OnyxV100-S5A-ACL-<32 lowercase hex>` names and the accepted marker. It retains both fixtures, including failed fixtures, for review.

## Source and trust boundaries

- Development baseline: M2 local commit `00c6ba630a18b054308bb7119b610602790e44be`.
- Source candidate: approved M2-S1 runtime ZIP SHA-256 `b4e3c350e47d087bd06c4249aa163d96abe07b792109fc4e9b1032705e2c263d`.
- Versioned dashboard: SHA-256 `16cec6731032a444bf944e165b22fdc179cca6ae6d8a57`.
- Native ACL helper and S5A-R3 code are exact SHA-256-pinned inputs; their older unsafe `icacls` predecessor is *never executed*.
- All installation assets and receipts are derived from the previously accepted integrated installer contract.
- The Win32 `MoveFileExW` call uses `dwFlags=0`: **no replacement, no cross-volume copy, no delayed operation**. Staging and destination are direct siblings within one fixture root.
- Normal-case acceptance verifies the full 17-file installation receipt and published DACLs after the move.
- Collision-case acceptance creates a distinct disposable Temp fixture with an existing destination and tests the *native move call itself*; both source and destination witness files must remain unchanged.

## Controls and limitations

- Default CLI action is a read-only LocalAppData preview. Write mode is `native-temp` with **both** explicit flags `--approve-native-temp --approve-no-replace-test`.
- No arbitrary destination argument exists. Elevated sessions, other Python versions, and non-Windows write mode refuse.
- No credential enrollment, networking, gateway launch, Scheduled Task change, service registration, production change, or persistent LocalAppData installation.
- The existing committed M2-S2C helper remains unsafe and must be retired/replaced before a real installation is authorized.
- Native Windows acceptance is pending until run on SQUALL. Offline tests do **not** substitute for a Windows move or DACL audit.

## Future gate

The next checkpoint must replace the known-unsafe user-scoped helper and integrate this validated publication path under a separately approved, versioned inactive user installation. Do not enable the historical M2-S2C `--install` flow.

Reference: Microsoft Learn, [MoveFileExW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw) and [Moving Directories](https://learn.microsoft.com/en-us/windows/win32/fileio/moving-directories).
