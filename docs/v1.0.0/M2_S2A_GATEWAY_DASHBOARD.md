# ONYX CORE v1.0.0 — M2-S2A Gateway Dashboard Portability

## Purpose

The M2-S1 deterministic core candidate has passed integrity checks. It is not
installable by itself. Its inherited `gateway-dashboard.html` recognizes only
127.0.0.1 ports 18766, 18767 and 18768, which conflicts with configured ports
and with existing production. When loaded via another loopback port it falls
back to a browser-token flow, although the local gateway is designed to inject
the credential into upstream HTTP requests and never disclose it to the browser.

This development-only step adds `gateway-dashboard-v100.html` as a distinct
versioned asset generated from the reviewed legacy dashboard. A source-pinned
generator replaces the fixed-port gateway detection with a same-host loopback
origin check and removes the SQUALL-specific page branding.

## Safety boundaries

* Neither the tracked legacy dashboard nor the approved M2-S1 core candidate is changed.
* The generator verifies the canonical SHA256 of the legacy dashboard and fails
  closed on mixed line endings, unknown changes or an existing output.
* No credentials, network probes, Windows Scheduled Tasks, running processes or
  gateway listeners are accessed.
* This new page is **not yet wired into the M1 Windows launcher** and is **not
  yet included in the M2-S1 candidate**. M2-S2 installation work must select
  this reviewed asset explicitly and rebuild the final deterministic release
  package after appropriate source-control authorization.
* The separate v0.8 monitoring view remains limited to its approved ports;
  this step does not extend monitoring or release services.
* Legacy OBS overlay branding and Pi dashboard branding are not corrected by
  this isolated Windows gateway step. Their portability must be tracked before
  the final v1.0.0 release.

## Acceptance

1. Exact approved original source hash.
2. Versioned HTML bytes reproducible from LF and CRLF checkouts.
3. No workstation-specific dashboard title/header.
4. Gateway origin detection works for arbitrary `http://127.0.0.1:<port>`.
5. Source integrity, production baseline and 3 preexisting M2-S1 files stay unchanged.
6. No deployment, commit or activation.
