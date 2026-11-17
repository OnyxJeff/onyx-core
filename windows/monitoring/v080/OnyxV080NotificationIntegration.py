#!/usr/bin/env python3
"""ONYX CORE v0.8 R5: inert, per-event authorized M5 cursor adapter.

This module does not create notification grants, load credentials, open
webhooks or expose a live CLI. The future protected operator must supply a
TRUSTED grant loader, fresh native identity/source/session proofs, and a
provider-specific approved delivery callback. Never load approvals from
mutable JSON/env or treat caller-supplied booleans as Windows attestation.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Callable

import OnyxIncidentNotifications as watcher
import OnyxV080AlertAuthorization as auth


class NotificationIntegrationRefused(RuntimeError):
    pass


def poll_authorized_events(*, journal: Path, cursor: Path,
                           provider: str, destination: bytes,
                           load_grant: Callable[[], dict],
                           context: Callable[[], auth.AlertContext],
                           deliver: Callable[[dict], None],
                           now: Callable[[], datetime],
                           poll: Callable = watcher.poll_once) -> dict:
    """Use existing M5 cursor; check separate consent at startup and EACH send.

    ``poll`` defaults to the real M5 journal/cursor writer: the operator MUST
    restrict both paths to the protected release profile before invoking this
    API. Tests pass isolated temp files or an inert test poller. The loader
    and context provider are explicit trust boundaries, not authorization by
    themselves. If revoked mid-batch, cursor remains before the denied event.
    """
    if not isinstance(journal, Path) or not journal.is_absolute() or journal.name != 'incident-history.sqlite3':
        raise NotificationIntegrationRefused('unexpected incident journal location')
    if not isinstance(cursor, Path) or not cursor.is_absolute() or cursor == journal:
        raise NotificationIntegrationRefused('unexpected notification cursor location')
    if type(destination) is not bytes:
        raise NotificationIntegrationRefused('approved endpoint bytes required')
    if not all(callable(f) for f in (load_grant, context, deliver, now, poll)):
        raise NotificationIntegrationRefused('missing guarded delivery dependency')

    def permit(event_type: str) -> None:
        # Fresh loaders and exact endpoint binding at each event, not just at
        # watcher start. Never coerce False to True, or swallow denial.
        if auth.permit_event(grant=load_grant(), context=context(),
                             event_type=event_type, provider=provider,
                             endpoint=destination, now=now()) is not True:
            raise NotificationIntegrationRefused('notification consent refused')

    # Reject expired/untrusted approval BEFORE creating or reading a cursor.
    permit('Opened')

    def per_event(event: dict) -> None:
        if type(event) is not dict or event.get('event_type') not in ('Opened', 'Recovered'):
            raise NotificationIntegrationRefused('unexpected deliverable incident event')
        permit(event['event_type'])
        deliver(event)

    result = poll(journal, cursor, per_event)
    if type(result) is not dict or set(result) != {'initialized', 'last_event_id', 'sent', 'skipped'}:
        raise NotificationIntegrationRefused('unrecognized notification cursor result')
    if (type(result['initialized']) is not bool or type(result['last_event_id']) is not int or
            result['last_event_id'] < 0 or type(result['sent']) is not int or
            result['sent'] < 0 or type(result['skipped']) is not int or result['skipped'] < 0):
        raise NotificationIntegrationRefused('invalid notification cursor result')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='R5 inert authorized-notification composition')
    parser.add_argument('--check-inert', required=True, action='store_true')
    parser.parse_args(argv)
    print(json.dumps({'phase': 'R5-notification-integration', 'outbound_delivery_enabled': False,
                      'credential_issuer_enabled': False, 'trusted_operator_wired': False,
                      'release_status': 'HOLD'}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
