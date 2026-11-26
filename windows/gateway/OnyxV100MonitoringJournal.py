"""v100 journal binding, with no runnable live monitor or implicit authority.

The trusted parent must supply a native storage attestor, a cross-session
exclusive lock and a fresh independent authorization check. These interfaces
are not an authorization issuer, and fixture callbacks do not prove trust.
"""
from pathlib import Path
from typing import Callable, ContextManager

from OnyxV100MonitoringView import history_path
import OnyxLiveIncidentHistory as journal


class JournalRefused(RuntimeError):
    """An explicit precondition for recording was not established."""


def record_observation(result: dict, *, authorize: Callable[[], bool],
                       attest_storage: Callable[[Path], bool],
                       exclusive: Callable[[], ContextManager]) -> dict:
    """Reuse the v080 confirmed lifecycle and durable cycle receipts.

    No caller-selected storage path. Never provisions directories or probes.
    The caller's native lock must span this operation, including reconciliation.
    The pre-COMMIT check is not an instantaneous revocation guarantee.
    """
    if not all(callable(item) for item in (authorize, attest_storage, exclusive)):
        raise JournalRefused('explicit authorization, storage and lock required')
    if authorize() is not True:
        raise JournalRefused('journal authorization denied')
    with exclusive():
        if authorize() is not True:
            raise JournalRefused('journal authorization denied')
        path = history_path()
        # Require native provisioning first; do not inherit an unreviewed ACL
        # by allowing the historical writer to create missing directories.
        def guarded_commit() -> bool:
            if authorize() is not True:
                raise JournalRefused('journal authorization denied')
            if (history_path() != path or not path.parent.is_dir() or
                    attest_storage(path) is not True or history_path() != path):
                raise JournalRefused('journal storage attestation denied')
            return True

        guarded_commit()
        operation_id = journal.cycle_operation_id(result)
        return journal.record_cycle(path, result,
                                    authorize_commit=guarded_commit,
                                    operation_id=operation_id,
                                    confirmed_incidents=True)
