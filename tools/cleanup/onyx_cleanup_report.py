#!/usr/bin/env python3
"""Read-only ONYX CORE cleanup classification for an operator's Downloads folder.

No file contents, credentials, hashes, Scheduled Tasks, system files or Git refs
are read; no filesystem writes, deletions, moves or shell commands are made.
All classifications are proposed for later manual review, not deletion approval.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

MILESTONE_KITS = frozenset({
    'ONYX_CORE_v090_M0_M1_Devkit.zip',
    'ONYX_CORE_v090_M2_Sandbox_Devkit.zip',
    'ONYX_CORE_v090_M3_InactiveInstall_Devkit.zip',
    'ONYX_CORE_v090_M4_RuntimeRecovery_Devkit.zip',
})


def classify(filename: str) -> tuple[str, str]:
    low = filename.lower()
    if filename in MILESTONE_KITS:
        return ('HOLD_UNTIL_COMMITTED_RC', 'Development kit may be the only backup of uncommitted work')
    if 'onyx' not in low:
        return ('OUT_OF_SCOPE', 'Not identified as an ONYX CORE download')
    if re.search(r'(?i)(token|credential|secret|private|backup|rollback|recovery|dpapi|database|history|evidence|receipt|manifest)', filename):
        return ('REVIEW_PRESERVE', 'Potential credential, data, rollback asset or unique evidence')
    if re.search(r'(?i)(v070|v080|v0[.-]7|v0[.-]8)', filename):
        return ('REVIEW_HISTORICAL', 'Historical development artifact; compare with Git before archiving')
    return ('REVIEW_UNKNOWN', 'No proof this is safely reproducible')


def inventory(downloads: Path, *, max_examples: int = 12) -> dict:
    if not downloads.is_dir() or downloads.is_symlink():
        raise ValueError('Downloads directory unavailable or redirected')
    rows = []
    for path in sorted(downloads.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file() or path.is_symlink():
            continue
        classification, reason = classify(path.name)
        if classification == 'OUT_OF_SCOPE':
            continue
        rows.append({'file': path.name, 'bytes': path.stat().st_size,
                     'classification': classification, 'reason': reason})
    counts = dict(sorted(Counter(r['classification'] for r in rows).items()))
    kits = [r for r in rows if r['file'] in MILESTONE_KITS]
    examples = [r for r in rows if r['file'] not in MILESTONE_KITS][:max_examples]
    return {'status': 'READ_ONLY_REVIEW', 'total_matching': len(rows),
            'counts': counts, 'milestone_kits': kits,
            'example_other_files': examples,
            'not_shown': len(rows) - len(kits) - len(examples),
            'deletion_authorized': False,
            'notes': 'Only proposed classifications; no automatic safe-to-delete verdicts.'}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--downloads', type=Path, required=True)
    p.add_argument('--examples', type=int, default=12)
    args = p.parse_args(argv)
    try:
        if not 0 <= args.examples <= 100: raise ValueError('--examples must be 0..100')
        print(json.dumps(inventory(args.downloads, max_examples=args.examples), sort_keys=True, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print('STOP: ' + str(exc), file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
