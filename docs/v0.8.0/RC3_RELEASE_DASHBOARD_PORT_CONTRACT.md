# ONYX CORE v0.8.0 — RC3 release gateway port contract (development only)

- Production `127.0.0.1:18766` remains the **existing** v0.7.0 gateway. An explicitly requested v0.8 monitoring API on 18766 remains refused.
- Development monitoring gateway `127.0.0.1:18767` remains supported with no new profile requirement.
- `127.0.0.1:18768` is reserved for **manually launched, opt-in v0.8 release dashboard**. Its CLI rejects use without `--v080-monitor-view` and without `ONYXCORE_V080_STORAGE_PROFILE=release`.
- The existing dashboard displays the M4 monitoring panel on 18767 and 18768, but not on 18766. Both M4 and browser view remain read-only.
- This change does **not** start any listener, change Scheduled Tasks, configure credential enrollment, create continuous monitoring, or enable notifications. Port 18768 is not a background service or production deployment.
- Gateway startup still requires the existing protected Pi bearer token through `--load-dpapi` or stdin. This patch does not bypass its token checks or change other gateway routes; the dashboard's unrelated Pi telemetry widgets require an authorized upstream connection.
- `--v080-monitor-view` on an arbitrary nonproduction port retains previous development/test behavior; only 18768 gains a strict release-profile check.
- Native browser and exact protected-source approval checks must be repeated on the **future frozen RC3**, not treated as passed by offline tests on the development checkout.
- Automatic notification delivery and unattended monitoring remain **outside RC2/RC3** until separately implemented and accepted; v0.8.0 release publication remains HOLD.
