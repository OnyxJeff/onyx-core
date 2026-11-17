#!/usr/bin/env python3
"""ONYX CORE v0.8 R4: PURE, offline operational-alert consent boundary.

Does not issue grants, load credentials, read files, send webhooks, access the
network or activate notification watchers. Caller MUST first independently
verify grant storage provenance, release source and active Windows session.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re

HEX40 = re.compile(r'[0-9a-f]{40}\Z')
HEX64 = re.compile(r'[0-9a-f]{64}\Z')
SID = re.compile(r'S-1-(?:[0-9]+-)+[0-9]+\Z')
PROVIDERS = frozenset(('ntfy','discord','json'))
NOTIFICATION_EVENTS = frozenset(('Opened','Recovered'))


class AlertConsentRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class AlertContext:
    source_commit: str
    process_sid: str
    source_trusted: bool
    active_console: bool
    release_storage: bool


def destination_digest(destination: bytes) -> str:
    """Hash an exact caller-validated destination, never return the secret URL."""
    if type(destination) is not bytes or not 1 <= len(destination) <= 2048:
        raise AlertConsentRefused('invalid endpoint bytes')
    return hashlib.sha256(destination).hexdigest()


def _date(value: str) -> datetime:
    if type(value) is not str or not value.endswith('Z'):
        raise AlertConsentRefused('invalid UTC timestamp')
    try:
        parsed = datetime.strptime(value,'%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
        if parsed.strftime('%Y-%m-%dT%H:%M:%SZ') != value:
            raise ValueError('noncanonical')
        return parsed
    except (ValueError, OverflowError) as exc:
        raise AlertConsentRefused('invalid UTC timestamp') from exc


def permit_event(*, grant: dict, context: AlertContext, event_type: str,
                 provider: str, endpoint: bytes, now: datetime) -> bool:
    """Validate a separate short-lived user-approved alert grant, fail closed.

    This is NOT a trusted issuer or standalone admission system. Integration
    must independently verify native source ACLs and grant provenance on each
    event, and MUST prevent posting after user/session/source revocation.
    """
    if type(grant) is not dict or not isinstance(context, AlertContext):
        raise AlertConsentRefused('invalid alert consent inputs')
    expected = {'schema_version','approved','scope','source_commit','sid',
                'provider','destination_sha256','issued_utc','expires_utc',
                'event_types','storage_profile','notifications_enabled'}
    if set(grant) != expected or type(grant['schema_version']) is not int or grant['schema_version'] != 1:
        raise AlertConsentRefused('unsupported alert consent format')
    if (grant['approved'] is not True or grant['notifications_enabled'] is not True or
            grant['scope'] != 'foreground_incident_notifications' or
            grant['storage_profile'] != 'release'):
        raise AlertConsentRefused('alert delivery not explicitly approved')
    if (type(grant['source_commit']) is not str or not HEX40.fullmatch(grant['source_commit']) or
            type(grant['sid']) is not str or not SID.fullmatch(grant['sid']) or
            type(grant['destination_sha256']) is not str or not HEX64.fullmatch(grant['destination_sha256'])):
        raise AlertConsentRefused('invalid consent binding')
    if (grant['source_commit'] != context.source_commit or
            grant['sid'] != context.process_sid or
            context.source_trusted is not True or context.active_console is not True or
            context.release_storage is not True):
        raise AlertConsentRefused('untrusted release source/session/identity')
    if type(provider) is not str or provider not in PROVIDERS or grant['provider'] != provider:
        raise AlertConsentRefused('unapproved alert transport')
    if (type(event_type) is not str or event_type not in NOTIFICATION_EVENTS or
            type(grant['event_types']) is not list or
            grant['event_types'] != ['Opened','Recovered']):
        raise AlertConsentRefused('unapproved incident event type')
    if grant['destination_sha256'] != destination_digest(endpoint):
        raise AlertConsentRefused('notification destination changed')
    issued, expires = _date(grant['issued_utc']), _date(grant['expires_utc'])
    if (not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None):
        raise AlertConsentRefused('timezone-aware clock required')
    current = now.astimezone(timezone.utc)
    if not issued <= current < expires or not timedelta(0) < expires-issued <= timedelta(hours=24):
        raise AlertConsentRefused('notification approval expired or not yet valid')
    return True


def main(argv=None) -> int:
    p=argparse.ArgumentParser(description='Offline-only alert authorization contract')
    p.add_argument('--check-inert',action='store_true',required=True)
    p.parse_args(argv)
    print(json.dumps({'phase':'R4-alert-consent','live_webhooks_enabled':False,
                      'automatic_notifications_enabled':False,'grant_issuer_enabled':False,
                      'release_status':'HOLD'},sort_keys=True))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
