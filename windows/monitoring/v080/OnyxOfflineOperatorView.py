#!/usr/bin/env python3
"""ONYX CORE v0.8.0 M4: read-only, in-memory SYNTHETIC operator view.

No file I/O, real monitoring, HTTP listener, network clients, task manipulation,
notification transport, identity authentication, alert acknowledgement action,
or incident persistence. CLI ONLY exposes --check-inert. Library functions
accept M3 synthetic data (not real diagnostics) and return strings/dicts.
"""
from __future__ import annotations

import argparse
import copy
from html import escape
import json
from pathlib import Path
import re
import sys
from typing import Any

# With Python -I, import only the fixed M3 sibling. No production adapters.
_SIBLING = str(Path(__file__).resolve().parent)
if _SIBLING not in sys.path:
    sys.path.insert(0, _SIBLING)
import OnyxOfflineAlertLifecycle as alerts

SOURCE = "OnyxV080M4SyntheticOperatorView"
PROVENANCE = "SyntheticFixtureOnly"
SCHEMA = 1
MAX_RENDER_BYTES = 131072
RESULT_FIELDS = frozenset((
    "source", "provenance", "simulation_only", "runtime_enabled",
    "live_probe_authorized", "task_creation_authorized", "notification_enabled",
    "delivery_permitted", "store_modified", "repair_action", "processed_new_events",
    "suppressed_duplicate_events", "proposed_intents", "state", "display_status",
))
ACK_FIELDS = frozenset((
    "source", "provenance", "simulation_only", "notification_enabled",
    "delivery_permitted", "runtime_enabled", "live_probe_authorized",
    "task_creation_authorized", "store_modified", "repair_action", "changed", "state",
))
PROPOSAL_FIELDS = frozenset((
    "source", "provenance", "intent_key", "event_id", "incident_id",
    "kind", "timestamp_utc", "simulation_only", "delivery_permitted",
))
INTENT_KINDS = frozenset(alerts.INTENTS.values())
NONE_IID = "none"


class OfflineViewError(ValueError):
    """Malformed or non-synthetic view data refused, with no side effects."""


def _require(predicate: bool, reason: str) -> None:
    if not predicate:
        raise OfflineViewError(reason)


def _json_size(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, allow_nan=False,
                              separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError, OverflowError, UnicodeError) as exc:
        raise OfflineViewError("non-serializable view input") from exc


def _inert_claims(item: dict) -> None:
    _require(item.get("source") == alerts.SOURCE and
             item.get("provenance") == alerts.PROVENANCE and
             item.get("simulation_only") is True and
             item.get("notification_enabled") is False and
             item.get("delivery_permitted") is False and
             item.get("runtime_enabled") is False and
             item.get("live_probe_authorized") is False and
             item.get("task_creation_authorized") is False and
             item.get("store_modified") is False and
             item.get("repair_action") == "None", "non-synthetic or live-capable input")


def _verify_proposal(item: Any, state: dict) -> None:
    _require(type(item) is dict and set(item) == PROPOSAL_FIELDS,
             "proposal shape invalid")
    _require(item["source"] == alerts.SOURCE and
             item["provenance"] == alerts.PROVENANCE and
             item["simulation_only"] is True and
             item["delivery_permitted"] is False, "proposal not synthetic-only")
    kind = item["kind"]
    key = item["intent_key"]
    iid = item["incident_id"]
    eid = item["event_id"]
    _require(type(kind) is str and kind in INTENT_KINDS and
             type(key) is str and key in state["intent_keys"] and
             type(eid) is str and alerts.EVENT_ID.fullmatch(eid) is not None and
             any(entry["event_id"] == eid for entry in state["seen_events"]),
             "proposal not linked to state")
    _require(iid is None or (type(iid) is str and
             alerts.INCIDENT_ID.fullmatch(iid) is not None), "proposal incident invalid")
    _require(key == f"{iid or NONE_IID}|{next(name for name, val in alerts.INTENTS.items() if val == kind)}",
             "proposal intent mismatch")
    _require(type(item["timestamp_utc"]) is str, "proposal time invalid")
    try:
        parsed = alerts._utc(item["timestamp_utc"])
    except (alerts.OfflineAlertError, ValueError) as exc:
        raise OfflineViewError("proposal time invalid") from exc
    _require(state["last_timestamp_utc"] is not None and
             parsed <= alerts._utc(state["last_timestamp_utc"]), "proposal is in future of state")


def _verify_outcome(outcome: Any) -> dict:
    _require(type(outcome) is dict and set(outcome) == RESULT_FIELDS, "M3 outcome fields invalid")
    _require(_json_size(outcome) <= MAX_RENDER_BYTES, "oversized operator input")
    _inert_claims(outcome)
    state = outcome["state"]
    try:
        alerts.validate_state(state)
    except (alerts.OfflineAlertError, TypeError, ValueError, KeyError) as exc:
        raise OfflineViewError("invalid M3 state") from exc
    expected_display = "Unknown" if state["evidence_status"] != "Complete" else state["phase"]
    _require(type(outcome["display_status"]) is str and
             outcome["display_status"] == expected_display, "display claim inconsistent with evidence")
    processed = outcome["processed_new_events"]
    suppressed = outcome["suppressed_duplicate_events"]
    _require(type(processed) is int and type(suppressed) is int and
             0 <= processed <= alerts.MAX_EVENTS_BATCH and
             0 <= suppressed <= alerts.MAX_EVENTS_BATCH and
             1 <= processed + suppressed <= alerts.MAX_EVENTS_BATCH,
             "batch counters invalid")
    proposals = outcome["proposed_intents"]
    _require(type(proposals) is list and len(proposals) <= processed,
             "proposal count incompatible with batch")
    keys = set()
    for proposal in proposals:
        _verify_proposal(proposal, state)
        _require(proposal["intent_key"] not in keys, "duplicate new proposal key")
        keys.add(proposal["intent_key"])
    return state


def _verify_ack(ack: Any, original: dict) -> dict:
    _require(type(ack) is dict and set(ack) == ACK_FIELDS, "M3 acknowledgement result fields invalid")
    _require(_json_size(ack) <= MAX_RENDER_BYTES, "oversized acknowledgement")
    _inert_claims(ack)
    _require(type(ack["changed"]) is bool, "acknowledgement changed flag invalid")
    final = ack["state"]
    try:
        alerts.validate_state(final)
    except (alerts.OfflineAlertError, TypeError, ValueError, KeyError) as exc:
        raise OfflineViewError("invalid acknowledgement state") from exc
    unchanged = {k for k in original if k not in ("acknowledged_by", "acknowledged_at_utc")}
    _require(all(final[k] == original[k] for k in unchanged),
             "acknowledgement changed phase, evidence or history")
    _require(original["incident_id"] is not None and
             original["phase"] in ("Suspected", "Active"), "acknowledgement without active incident")
    if ack["changed"]:
        _require(original["acknowledged_by"] is None and final["acknowledged_by"] is not None,
                 "changed acknowledgement inconsistent")
        _require(final["last_timestamp_utc"] is not None and
                 alerts._utc(final["acknowledged_at_utc"]) >=
                 alerts._utc(final["last_timestamp_utc"]), "ack before latest event")
    else:
        _require(final == original and original["acknowledged_by"] is not None,
                 "unchanged acknowledgement inconsistent")
    return final


def build_synthetic_operator_snapshot(outcome: dict, acknowledgement: dict | None = None) -> dict:
    """Validate simulated M3 output and return a display-only snapshot, never actions."""
    original = _verify_outcome(outcome)
    state = _verify_ack(acknowledgement, original) if acknowledgement is not None else original
    phase, evidence = state["phase"], state["evidence_status"]
    visible = "Unknown" if evidence != "Complete" else phase
    if phase == "Recovered" and evidence == "Complete":
        recovery = "Synthetic recovery event observed — candidate only"
    elif evidence != "Complete":
        recovery = "Not confirmable — evidence incomplete or unknown"
    else:
        recovery = "No synthetic recovery transition reported"
    if state["incident_id"] is not None:
        lifecycle = "Open synthetic incident (acknowledgement does not resolve)"
    elif phase == "Recovered":
        lifecycle = "Synthetic recovery candidate — no open incident"
    else:
        lifecycle = "No open synthetic incident"
    proposals = [{"kind": p["kind"], "intent_key": p["intent_key"],
                  "event_id": p["event_id"], "timestamp_utc": p["timestamp_utc"]}
                 for p in outcome["proposed_intents"]]
    return {"schema_version": SCHEMA, "source": SOURCE, "provenance": PROVENANCE,
            "simulation_only": True, "read_only": True,
            "notification_enabled": False, "delivery_permitted": False,
            "runtime_enabled": False, "live_probe_authorized": False,
            "task_creation_authorized": False, "store_modified": False,
            "repair_action": "None", "incident_phase": phase,
            "display_status": visible, "evidence_status": evidence,
            "incident_id": state["incident_id"], "acknowledged_by": state["acknowledged_by"],
            "acknowledged_at_utc": state["acknowledged_at_utc"],
            "last_event_utc": state["last_timestamp_utc"], "lifecycle": lifecycle,
            "recovery": recovery, "new_events": outcome["processed_new_events"],
            "suppressed_replays": outcome["suppressed_duplicate_events"],
            "tracked_event_ids": len(state["seen_events"]),
            "tracked_intent_keys": len(state["intent_keys"]),
            "total_proposed_intents": state["proposal_count"],
            "new_proposed_intents": proposals}


def render_synthetic_operator_text(outcome: dict, acknowledgement: dict | None = None) -> str:
    """Accessible, human-readable snapshot. No write, no action, no transport."""
    s = build_synthetic_operator_snapshot(outcome, acknowledgement)
    actor = s["acknowledged_by"] or "Not acknowledged"
    lines = ["ONYX CORE v0.8.0 — M4 SYNTHETIC OPERATOR PREVIEW",
             "OFFLINE / READ-ONLY / NOT A LIVE HEALTH REPORT",
             f"Display: {s['display_status']}",
             f"Last synthetic incident phase: {s['incident_phase']}",
             f"Evidence: {s['evidence_status']}",
             f"Incident: {s['incident_id'] or 'None'}",
             f"Lifecycle: {s['lifecycle']}",
             f"Acknowledgement: {actor}",
             f"Acknowledged at: {s['acknowledged_at_utc'] or 'None'}",
             f"Recovery: {s['recovery']}",
             f"New events in batch: {s['new_events']}",
             f"Exact replays suppressed in batch: {s['suppressed_replays']}",
             f"Unique intent keys tracked: {s['tracked_intent_keys']}",
             f"New alert proposals this batch: {len(s['new_proposed_intents'])}",
             "No alerts delivered. No recovery, ICS fault or real-world health proven."]
    for p in s["new_proposed_intents"]:
        lines.append(f"PROPOSAL ONLY: {p['kind']} [{p['event_id']}]")
    return "\n".join(lines) + "\n"


def render_synthetic_operator_html(outcome: dict, acknowledgement: dict | None = None) -> str:
    """Self-contained static HTML with no scripts, links, forms or external resources."""
    s = build_synthetic_operator_snapshot(outcome, acknowledgement)
    def e(v: Any) -> str:
        return escape(str(v if v is not None else "—"), quote=True)
    def card(title: str, body: Any, details: str = "") -> str:
        return (f'<section class="tile"><h2>{e(title)}</h2><strong>{e(body)}</strong>'
                f'<p>{e(details)}</p></section>')
    badge_class = "uncertain" if s["display_status"] == "Unknown" else (
        "incident" if s["incident_phase"] in ("Suspected", "Active") else "neutral")
    ack = f"{s['acknowledged_by']} · {s['acknowledged_at_utc']}" if s["acknowledged_by"] else "Not acknowledged"
    rows = "".join(
        f'<tr><td>{e(p["kind"])}</td><td><code>{e(p["event_id"])}</code></td>'
        f'<td>{e(p["timestamp_utc"])}</td></tr>' for p in s["new_proposed_intents"])
    if not rows:
        rows = '<tr><td colspan="3">No new proposals in this synthetic batch</td></tr>'
    body = "".join((
        card("Evidence completeness", s["evidence_status"], "Incomplete or unknown evidence masks visible health"),
        card("Incident phase", s["incident_phase"], "Last synthetic reducer-derived state, not a live assertion"),
        card("Alert lifecycle", s["lifecycle"], "Proposals only — no delivery or action"),
        card("Acknowledgement", ack, "Synthetic record, not a control or authenticated user"),
        card("Recovery", s["recovery"], "M4 never independently confirms recovery"),
        card("Deduplication", f'{s["suppressed_replays"]} replays suppressed',
             f'{s["tracked_event_ids"]} event IDs · {s["tracked_intent_keys"]} unique intent keys tracked'),
        card("New events", s["new_events"], "Current batch only"),
        card("Alert proposals", len(s["new_proposed_intents"]),
             f'{s["total_proposed_intents"]} tracked lifetime proposals in this in-memory state'),
    ))
    result = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; form-action 'none'; base-uri 'none'; connect-src 'none'">
<title>ONYX CORE · Synthetic Operator Preview</title>
<style>
:root{{color-scheme:dark;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#0b1220;color:#e8eef9}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;background:radial-gradient(ellipse at top,#15283b,#0b1220 65%);padding:28px}}
main{{max-width:1200px;margin:auto}}header{{display:flex;justify-content:space-between;gap:16px;align-items:center;flex-wrap:wrap;border-bottom:1px solid #28364a;padding-bottom:22px;margin-bottom:20px}}
.eyebrow{{letter-spacing:.16em;text-transform:uppercase;color:#7ab9d8;font-size:.73rem;font-weight:700}}h1{{font-size:clamp(1.65rem,3vw,2.6rem);margin:.35rem 0}}.sub{{color:#a8b8ce;margin:.2rem 0}}
.stamp{{border:1px solid #9e8743;color:#ffd982;background:#3a2f18;padding:10px 14px;font-weight:700;border-radius:9px;text-align:center}}
.banner{{display:flex;gap:16px;align-items:center;flex-wrap:wrap;border:1px solid #31445b;border-radius:12px;padding:16px 19px;background:#142236;margin-bottom:22px}}
.banner strong{{font-size:1.35rem}}.banner p{{margin:0;color:#a8b8ce}}.tag{{padding:6px 12px;border-radius:8px;font-weight:700}}
.uncertain{{background:#4c361c;color:#ffd78b}}.incident{{background:#44272b;color:#ffb3b9}}.neutral{{background:#213746;color:#b8e8ff}}
.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}.tile{{background:#142135;border:1px solid #273b51;border-radius:12px;padding:18px;min-width:0}}
h2{{color:#a7b9d0;font-size:.85rem;font-weight:650;margin:0 0 11px}}.tile strong{{font-size:1.08rem;overflow-wrap:anywhere}}
.tile p{{font-size:.81rem;line-height:1.5;color:#94a7c0;margin:11px 0 0}}.section{{margin:30px 0 10px;font-size:1.1rem}}
.tablewrap{{overflow-x:auto;border:1px solid #273b51;border-radius:12px}}table{{width:100%;border-collapse:collapse;background:#142135}}
th,td{{text-align:left;padding:12px 14px;border-bottom:1px solid #273b51;overflow-wrap:anywhere}}th{{font-size:.76rem;color:#9eb5ce;text-transform:uppercase;letter-spacing:.08em}}td{{font-size:.84rem}}
code{{font-size:.79rem;color:#c5d5ef}}footer{{margin-top:24px;font-size:.8rem;color:#a7b8c8;line-height:1.6}}
@media(max-width:650px){{body{{padding:15px}}.grid{{grid-template-columns:1fr}}}}
</style></head><body><main>
<header><div><div class="eyebrow">ONYX CORE · v0.8.0 · M4</div><h1>Operator visibility</h1>
<p class="sub">Read-only rendering from a synthetic M3 alert snapshot</p></div><div class="stamp">SYNTHETIC DATA<br>NOT LIVE MONITORING</div></header>
<div class="banner"><span class="tag {badge_class}">{e(s["display_status"])}</span>
<div><strong>Visible status</strong><p>Incident {e(s["incident_id"])} · last synthetic event {e(s["last_event_utc"])}</p></div></div>
<div class="grid">{body}</div>
<h2 class="section">New proposals · not notifications</h2>
<div class="tablewrap"><table><thead><tr><th>Intent</th><th>Event ID</th><th>Synthetic timestamp</th></tr></thead><tbody>{rows}</tbody></table></div>
<footer>All values are simulated fixture results. Acknowledgement is descriptive, never clickable. No notifications sent, no repairs attempted, and no live health, root cause, or recovery proven.</footer>
</main></body></html>'''
    _require(len(result.encode("utf-8")) <= MAX_RENDER_BYTES, "rendered view oversized")
    return result


def check_inert() -> dict:
    return {"source": SOURCE, "simulation_only": True, "read_only": True,
            "runtime_enabled": False, "live_probe_authorized": False,
            "task_creation_authorized": False, "notification_enabled": False,
            "delivery_permitted": False, "store_modified": False, "repair_action": "None"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-inert", action="store_true", required=True)
    parser.parse_args(argv)
    print(json.dumps(check_inert(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
