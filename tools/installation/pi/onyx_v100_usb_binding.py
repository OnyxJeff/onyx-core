#!/usr/bin/env python3
"""ONYX CORE v1.0.0 M1-S5: pure Pi USB IPv4 binding selection.

Given already-captured `ip -j -4 address show dev IFACE` output, select one
address belonging to the explicitly configured private IPv4 subnet. No OS,
network, filesystem or service operations occur in this module.
"""
from __future__ import annotations

import ipaddress
import json


class UsbBindRefused(ValueError):
    """No unique, trusted USB bind address could be selected."""


def selected_ipv4_from_json(raw, interface, subnet):
    if type(interface) is not str or not interface:
        raise UsbBindRefused('USB interface is invalid')
    try:
        network = ipaddress.IPv4Network(subnet, strict=True)
    except (ValueError, TypeError) as exc:
        raise UsbBindRefused('USB subnet is invalid') from exc
    accepted = (ipaddress.IPv4Network('10.0.0.0/8'),
                ipaddress.IPv4Network('172.16.0.0/12'),
                ipaddress.IPv4Network('192.168.0.0/16'),
                ipaddress.IPv4Network('169.254.0.0/16'))
    if not any(network.subnet_of(base) for base in accepted):
        raise UsbBindRefused('USB subnet must be RFC1918 or IPv4 link-local')
    if not 16 <= network.prefixlen <= 30:
        raise UsbBindRefused('USB subnet prefix must be between 16 and 30')
    if isinstance(raw, bytes):
        try:
            raw = raw.decode('utf-8')
        except UnicodeError as exc:
            raise UsbBindRefused('USB address metadata encoding invalid') from exc
    if type(raw) is not str or len(raw) > 8192:
        raise UsbBindRefused('USB address metadata invalid or oversized')
    try:
        entries = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise UsbBindRefused('USB address metadata is not JSON') from exc
    if type(entries) is not list:
        raise UsbBindRefused('USB address metadata must be a list')
    matched_interfaces = [e for e in entries if type(e) is dict and e.get('ifname') == interface]
    if len(matched_interfaces) != 1:
        raise UsbBindRefused('Exactly one requested USB interface is required')
    ips = matched_interfaces[0].get('addr_info')
    if type(ips) is not list:
        raise UsbBindRefused('USB address list invalid')
    selected = set()
    for info in ips:
        if type(info) is not dict:
            raise UsbBindRefused('USB address record invalid')
        if info.get('family') != 'inet':
            continue
        try:
            value = ipaddress.IPv4Address(info['local'])
        except (ValueError, KeyError, TypeError) as exc:
            raise UsbBindRefused('Malformed USB IPv4 address') from exc
        # Ignore other configured subnets, but never select network,
        # broadcast, loopback, multicast, unspecified or reserved addresses.
        if (value in network and value != network.network_address and
                value != network.broadcast_address and not value.is_loopback and
                not value.is_multicast and not value.is_unspecified and
                not value.is_reserved):
            selected.add(str(value))
    if len(selected) != 1:
        raise UsbBindRefused('Expected one unambiguous IPv4 address inside configured USB subnet')
    return selected.pop()
