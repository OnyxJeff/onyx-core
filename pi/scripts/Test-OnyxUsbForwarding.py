#!/usr/bin/env python3
"""ONYX CORE v0.6.0: read-only Pi USB/ICS forwarding diagnostic."""
import argparse
import datetime
import json
import socket
import subprocess
import urllib.request

INTERFACE = "usb0"
GATEWAY = "192.168.137.1"


def classify(interface_ready, route_via_usb, gateway_reachable,
             external_tcp, dns_resolves, https_works):
    if not interface_ready:
        return "UsbInterfaceNotReady"
    if not route_via_usb:
        return "RouteNotViaUsb"
    if not gateway_reachable:
        return "GatewayUnreachable"
    if not external_tcp:
        return "ExternalTcpUnverified"
    if not dns_resolves:
        return "DnsUnverified"
    if not https_works:
        return "HttpsUnverified"
    return "PiInternetVerified"


def command_ok(args, timeout=5):
    try:
        return subprocess.run(
            args, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout, check=False, text=True
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def tcp_works():
    try:
        with socket.create_connection(("1.1.1.1", 443), timeout=4):
            return True
    except OSError:
        return False


def https_works():
    try:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({})
        )
        req = urllib.request.Request(
            "https://example.com", method="HEAD"
        )
        with opener.open(req, timeout=7) as response:
            return 200 <= response.status < 400
    except (OSError, ValueError):
        return False


def self_test():
    cases = [
        ("UsbInterfaceNotReady",
         (False, False, False, False, False, False)),
        ("RouteNotViaUsb",
         (True, False, False, False, False, False)),
        ("GatewayUnreachable",
         (True, True, False, False, False, False)),
        ("ExternalTcpUnverified",
         (True, True, True, False, False, False)),
        ("DnsUnverified",
         (True, True, True, True, False, False)),
        ("HttpsUnverified",
         (True, True, True, True, True, False)),
        ("PiInternetVerified",
         (True, True, True, True, True, True)),
    ]
    for expected, inputs in cases:
        actual = classify(*inputs)
        if actual != expected:
            raise AssertionError(
                "Expected %s; got %s" % (expected, actual)
            )
        print("PASS: " + expected)
    print("PASS: All 7 Pi classifications")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return

    addr = command_ok(
        ["ip", "-4", "-br", "addr", "show", INTERFACE]
    )
    interface_ready = bool(
        addr and addr.returncode == 0
        and "UP" in addr.stdout.split()
        and "192.168.137." in addr.stdout
    )

    route = command_ok(
        ["ip", "-4", "route", "get", "1.1.1.1"]
    )
    words = (
        route.stdout.split()
        if route and route.returncode == 0 else []
    )
    route_via_usb = (
        "dev" in words
        and words.index("dev") + 1 < len(words)
        and words[words.index("dev") + 1] == INTERFACE
        and "via" in words
        and words.index("via") + 1 < len(words)
        and words[words.index("via") + 1] == GATEWAY
    )

    gateway_reachable = False
    external_tcp = False
    dns_resolves = False
    https_available = False

    if interface_ready and route_via_usb:
        ping = command_ok(
            ["ping", "-n", "-c", "2", "-W", "2", GATEWAY],
            timeout=6
        )
        gateway_reachable = bool(
            ping and ping.returncode == 0
        )

    if gateway_reachable:
        external_tcp = tcp_works()
        dns = command_ok(
            ["getent", "ahostsv4", "example.com"],
            timeout=7
        )
        dns_resolves = bool(
            dns and dns.returncode == 0
            and dns.stdout.strip()
        )
        if dns_resolves:
            https_available = https_works()

    print(json.dumps({
        "timestamp_utc": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "classification": classify(
            interface_ready, route_via_usb,
            gateway_reachable, external_tcp,
            dns_resolves, https_available
        ),
        "interface": INTERFACE,
        "interface_ready": interface_ready,
        "route_via_usb": route_via_usb,
        "gateway_reachable": gateway_reachable,
        "external_tcp_443": external_tcp,
        "dns_resolves": dns_resolves,
        "https_works": https_available,
        "repair_action": "None",
        "note": "Probe failures do not independently prove ICS is at fault"
    }, indent=2))


if __name__ == "__main__":
    main()
