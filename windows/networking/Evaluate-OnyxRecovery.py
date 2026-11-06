#!/usr/bin/env python3
"""ONYX CORE v0.6.0: dry-run recovery decision engine. Never repairs."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

MAX_LATEST_AGE = 120
MAX_HISTORY_AGE = 300
MIN_INTERVAL = 30


def utc_time(value):
    try:
        if not isinstance(value, str):
            return None
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def classify(observation):
    windows = observation.get("windows")
    pi = observation.get("pi")
    if not isinstance(windows, dict) or not isinstance(pi, dict):
        return "Investigate"
    win = windows.get("classification")
    pia = pi.get("classification")
    if (win == "WindowsPathReady" and pia == "PiInternetVerified"
            and observation.get("windows_upstream_ok") is True):
        return "Healthy"
    if win in ("AdapterMissing", "AdapterDown", "GatewayAddressMissing"):
        return "WaitAndRetry"
    failed = observation.get("external_tcp_failed_targets")
    corroborated = (
        isinstance(failed, list)
        and len(failed) >= 2
        and all(isinstance(x, str) and x for x in failed)
        and len(set(failed)) >= 2
    )
    if (win == "WindowsPathReady"
            and pia == "ExternalTcpUnverified"
            and pi.get("gateway_reachable") is True
            and pi.get("dns_resolves") is True
            and pi.get("https_works") is False
            and observation.get("windows_upstream_ok") is True
            and corroborated):
        return "SuspectedIcs"
    return "Investigate"


def evaluate(report, now=None):
    now = now or datetime.now(timezone.utc)

    def result(decision, reason, count=0):
        return {
            "decision": decision,
            "reason": reason,
            "consecutive_suspected": count,
            "repair_action": "None",
        }

    if not isinstance(report, dict):
        return result("Investigate", "Invalid report")
    grace = report.get("startup_grace_elapsed")
    if grace is False:
        return result("WaitAndRetry", "Startup grace period active")
    if grace is not True:
        return result("Investigate", "Startup grace status unknown")

    observations = report.get("observations")
    if not isinstance(observations, list) or not observations:
        return result("Investigate", "No diagnostic observations")
    if any(not isinstance(o, dict) for o in observations):
        return result("Investigate", "Invalid diagnostic observation")
    times = [utc_time(o.get("timestamp_utc")) for o in observations]
    if any(t is None for t in times):
        return result("Investigate", "Invalid or missing UTC timestamp")
    if any(b <= a for a, b in zip(times, times[1:])):
        return result("Investigate", "Observations not chronologically ordered")
    if times[-1] > now + timedelta(seconds=5):
        return result("Investigate", "Newest observation is in the future")
    if now - times[-1] > timedelta(seconds=MAX_LATEST_AGE):
        return result("Investigate", "Newest observation is stale")

    latest = classify(observations[-1])
    if latest == "Healthy":
        return result("Healthy", "Windows and Pi report healthy connectivity")
    if latest == "WaitAndRetry":
        return result("WaitAndRetry", "USB interface may be initializing")
    if latest != "SuspectedIcs":
        return result("Investigate", "Insufficient evidence to implicate ICS")

    count = 0
    for index in range(len(observations) - 1, -1, -1):
        if classify(observations[index]) != "SuspectedIcs":
            break
        if now - times[index] > timedelta(seconds=MAX_HISTORY_AGE):
            break
        if index < len(observations) - 1:
            if (times[index + 1] - times[index]).total_seconds() < MIN_INTERVAL:
                break
        count += 1
    if count < 3:
        return result("WaitAndRetry", "Awaiting three spaced, consistent failures", count)
    return result("PossibleIcsFailure", "Repeated corroborated failures; no repair authorized", count)


def self_test():
    now = datetime(2026, 11, 5, 8, tzinfo=timezone.utc)

    def obs(age, win="WindowsPathReady", pi="PiInternetVerified",
            upstream=True, targets=None, gateway=True, dns=True, https=None):
        return {
            "timestamp_utc": (now - timedelta(seconds=age)).isoformat(),
            "windows": {"classification": win},
            "pi": {"classification": pi, "gateway_reachable": gateway,
                   "dns_resolves": dns,
                   "https_works": (pi == "PiInternetVerified"
                                   if https is None else https)},
            "windows_upstream_ok": upstream,
            "external_tcp_failed_targets": targets or [],
        }

    def report(*observations, grace=True):
        return {"startup_grace_elapsed": grace, "observations": list(observations)}

    suspect = lambda age, targets=None: obs(
        age, pi="ExternalTcpUnverified",
        targets=["1.1.1.1:443", "9.9.9.9:443"] if targets is None else targets
    )
    tests = [
        ("healthy", report(obs(10)), "Healthy"),
        ("TCP failures but HTTPS succeeds",
         report(obs(10, pi="ExternalTcpUnverified", https=True,
                    targets=["1.1.1.1:443", "9.9.9.9:443"])), "Investigate"),
        ("TCP failures but DNS unavailable",
         report(obs(10, pi="ExternalTcpUnverified", dns=False,
                    targets=["1.1.1.1:443", "9.9.9.9:443"])), "Investigate"),
        ("Pi healthy, Windows upstream down",
         report(obs(10, upstream=False)), "Investigate"),
        ("Pi healthy, Windows upstream unknown",
         report({
             "timestamp_utc": obs(10)["timestamp_utc"],
             "windows": {"classification": "WindowsPathReady"},
             "pi": {"classification": "PiInternetVerified"}
         }), "Investigate"),
        ("adapter missing", report(obs(10, win="AdapterMissing")), "WaitAndRetry"),
        ("adapter down", report(obs(10, win="AdapterDown")), "WaitAndRetry"),
        ("gateway missing", report(obs(10, win="GatewayAddressMissing")), "WaitAndRetry"),
        ("bad route", report(obs(10, win="RouteNotViaUsb")), "Investigate"),
        ("receiver unavailable", report(obs(10, win="ReceiverUnreachable")), "Investigate"),
        ("DNS-only failure", report(obs(10, pi="DnsUnverified")), "Investigate"),
        ("Windows upstream down", report(obs(10, pi="ExternalTcpUnverified", upstream=False,
                                          targets=["1.1.1.1:443", "9.9.9.9:443"])), "Investigate"),
        ("one external target", report(suspect(10, ["1.1.1.1:443"])), "Investigate"),
        ("one suspect", report(suspect(10)), "WaitAndRetry"),
        ("two suspects", report(suspect(40), suspect(10)), "WaitAndRetry"),
        ("three suspects", report(suspect(70), suspect(40), suspect(10)), "PossibleIcsFailure"),
        ("too closely spaced", report(suspect(30), suspect(20), suspect(10)), "WaitAndRetry"),
        ("stale latest", report(obs(150)), "Investigate"),
        ("missing evidence", report({"timestamp_utc": obs(10)["timestamp_utc"]}), "Investigate"),
        ("recovered", report(suspect(70), suspect(40), obs(10)), "Healthy"),
        ("startup grace", report(obs(10), grace=False), "WaitAndRetry"),
        ("unknown startup", report(obs(10), grace=None), "Investigate"),
        ("Pi gateway unreachable", report(obs(10, pi="GatewayUnreachable")), "Investigate"),
    ]
    for name, payload, expected in tests:
        actual = evaluate(payload, now)["decision"]
        if actual != expected:
            raise AssertionError("%s: expected %s, got %s" % (name, expected, actual))
        print("PASS:", name)
    print("PASS: %d decision tests" % len(tests))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--input", type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test()
    elif args.input:
        print(json.dumps(evaluate(json.loads(args.input.read_text(encoding="utf-8"))), indent=2))
    else:
        parser.error("Supply --self-test or --input FILE")


if __name__ == "__main__":
    main()
