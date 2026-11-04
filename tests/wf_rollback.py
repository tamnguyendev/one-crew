"""W41 — the upgrade / rollback / roll-forward drill (R00), reusable by every release.

It runs on a COPY of a ledger (never a real state root). `compat scan` (the new code's read-only scan) is the gate: the rollback script
REFUSES while any block condition holds (read B4 or continue B2) and RUNS only when the last scan reports 0, on the same ledger hash. The
reject branch and the success branch are separate return shapes. The old version is the archived rollback binary (ee46539) run from a
parallel checkout; the new version is this tree.
"""
import shutil
from pathlib import Path

from onecrew.v2 import compat_scan
import tests.wf_oldversion as ov


def copy_ledger(src_state_root, dest):
    """A disposable COPY of a state root (the drill never touches the original)."""
    dest = Path(dest)
    shutil.copytree(src_state_root, dest)
    return dest


def rollback_drill(state_root):
    """Run the rollback gate on a state-root COPY. Returns:
        {'ran': False, 'reason': 'blocked', 'blocks': [...], 'scan': <report>}   when any block holds (reject branch), or
        {'ran': True, 'scan': <report>}                                           when the last scan reports 0 (success branch).
    It scans, refuses on any block, and only then would the install be swapped. It never writes the ledger."""
    scan = compat_scan.scan(state_root)
    blocks = [b for root in scan['roots'] for b in root['blocks']]
    if scan['blocking']['total'] > 0:
        return {'ran': False, 'reason': 'blocked', 'blocks': blocks,
                'conditions': sorted({b['id'] for b in blocks}), 'scan': scan}
    # success branch: the last scan reports 0 on this exact ledger (its hash is in the receipt).
    return {'ran': True, 'scan': scan, 'ledger_sha': scan['ledger_sha']}


def old_can_read(old, proj, state_root, name):
    """After a rollback, the old binary reads and (for an open root) continues `name`. Returns the S/G/C reading."""
    return ov.read(old, proj, state_root, name)
