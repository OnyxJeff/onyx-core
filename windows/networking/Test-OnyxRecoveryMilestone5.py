#!/usr/bin/env python3
"""Milestone 5: offline adversarial policy scenarios against actual v0.6.0 engine.

Does not import telemetry code, mutate system state, open sockets, or execute repairs.
"""
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ENGINE_PATH = Path(__file__).with_name("Evaluate-OnyxRecovery.py")
NOW = datetime(2026, 11, 5, 22, 0, tzinfo=timezone.utc)
TARGETS = ["1.1.1.1:443", "9.9.9.9:443"]


def load_engine():
    if not ENGINE_PATH.is_file():
        raise RuntimeError("Missing decision engine: " + str(ENGINE_PATH))
    spec = importlib.util.spec_from_file_location("onyx_m5_engine_under_test", ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load decision engine")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def observation(age=10, windows="WindowsPathReady", pi="PiInternetVerified",
                upstream=True, targets=None, gateway=True, **pi_extra):
    pi_state = {"classification": pi, "gateway_reachable": gateway}
    pi_state.update(pi_extra)
    if pi == "ExternalTcpUnverified":
        pi_state.setdefault("dns_resolves", True)
        pi_state.setdefault("https_works", False)
    return {
        "timestamp_utc": (NOW - timedelta(seconds=age)).isoformat(),
        "windows": {"classification": windows},
        "pi": pi_state,
        "windows_upstream_ok": upstream,
        "external_tcp_failed_targets": list(targets or []),
    }


def suspect(age, targets=None):
    return observation(age, pi="ExternalTcpUnverified",
                       targets=TARGETS if targets is None else targets)


def report(*observations, grace=True):
    return {"startup_grace_elapsed": grace, "observations": list(observations)}


def main():
    engine = load_engine()
    tests = [
        ("healthy connection", report(observation()), "Healthy"),
        ("SSH timeout/unavailable Pi", report(observation(pi="PiProbeUnavailable")), "Investigate"),
        ("invalid Pi classification", report(observation(pi="UnexpectedState")), "Investigate"),
        ("Pi gateway unreachable", report(observation(pi="GatewayUnreachable", gateway=False)), "Investigate"),
        ("Windows adapter missing", report(observation(windows="AdapterMissing")), "WaitAndRetry"),
        ("Windows adapter down", report(observation(windows="AdapterDown")), "WaitAndRetry"),
        ("Windows gateway missing", report(observation(windows="GatewayAddressMissing")), "WaitAndRetry"),
        ("Windows USB route wrong", report(observation(windows="RouteNotViaUsb")), "Investigate"),
        ("Windows receiver unavailable", report(observation(windows="ReceiverUnreachable")), "Investigate"),
        ("Windows upstream down", report(observation(10, pi="ExternalTcpUnverified", targets=TARGETS, upstream=False)), "Investigate"),
        ("Windows upstream unknown", report(observation(10, pi="ExternalTcpUnverified", targets=TARGETS, upstream=None)), "Investigate"),
        ("Pi DNS only failure", report(observation(pi="DnsUnverified")), "Investigate"),
        ("single TCP destination", report(suspect(10, [TARGETS[0]])), "Investigate"),
        ("duplicated TCP destination", report(suspect(10, [TARGETS[0], TARGETS[0]])), "Investigate"),
        ("TCP failures but HTTPS succeeds", report(observation(10, pi="ExternalTcpUnverified", targets=TARGETS, https_works=True)), "Investigate"),
        ("TCP failures but DNS unavailable", report(observation(10, pi="ExternalTcpUnverified", targets=TARGETS, dns_resolves=False)), "Investigate"),
        ("both target failure single probe", report(suspect(10)), "WaitAndRetry"),
        ("both target failure two probes", report(suspect(40), suspect(10)), "WaitAndRetry"),
        ("three spaced corroborated failures", report(suspect(70), suspect(40), suspect(10)), "PossibleIcsFailure"),
        ("four spaced corroborated failures", report(suspect(100), suspect(70), suspect(40), suspect(10)), "PossibleIcsFailure"),
        ("observations too close", report(suspect(29), suspect(20), suspect(10)), "WaitAndRetry"),
        ("interrupted suspect streak", report(suspect(100), observation(70), suspect(40), suspect(10)), "WaitAndRetry"),
        ("old suspect outside history window", report(suspect(310), suspect(40), suspect(10)), "WaitAndRetry"),
        ("healthy after two suspect samples", report(suspect(70), suspect(40), observation(10)), "Healthy"),
        ("unknown latest observation", report(suspect(70), suspect(40), observation(10, pi="PiProbeUnavailable")), "Investigate"),
        ("startup grace", report(suspect(70), suspect(40), suspect(10), grace=False), "WaitAndRetry"),
        ("startup grace unknown", report(suspect(70), suspect(40), suspect(10), grace=None), "Investigate"),
        ("stale latest sample", report(observation(121)), "Investigate"),
        ("future sample exceeds tolerance", report(observation(-10)), "Investigate"),
        ("no samples", report(), "Investigate"),
        ("non-dictionary report", None, "Investigate"),
        ("nonsensical observations field", {"startup_grace_elapsed": True, "observations": "no"}, "Investigate"),
        ("sample missing evidence", report({"timestamp_utc": observation()["timestamp_utc"]}), "Investigate"),
        ("out-of-order timestamps", report(observation(10), observation(40)), "Investigate"),
        ("duplicate timestamps", report(suspect(40), suspect(40), suspect(10)), "Investigate"),
    ]
    for label, payload, expected in tests:
        actual = engine.evaluate(payload, now=NOW)
        if not isinstance(actual, dict):
            raise AssertionError(label + ": evaluator returned non-object")
        if actual.get("repair_action") != "None":
            raise AssertionError(label + ": prohibited repair action detected")
        if actual.get("decision") != expected:
            raise AssertionError(
                "{}: expected {}, got {} (reason: {})".format(
                    label, expected, actual.get("decision"), actual.get("reason")))
        if actual.get("decision") == "PossibleIcsFailure" and actual.get("consecutive_suspected", 0) < 3:
            raise AssertionError(label + ": escalated without 3 corroborated observations")
        print("PASS: " + label)
    print("PASS: {} offline failure scenarios (repair_action=None throughout)".format(len(tests)))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("FAIL: " + str(exc), file=sys.stderr)
        sys.exit(1)
