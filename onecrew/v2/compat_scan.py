"""W46a — the read-only `compat scan` (R00, 00 §6.1), for every `plan:` root.

It is the ONE diagnostic component. It opens the ledger read-only (report._Reader: sqlite mode=ro + query_only; a write is an sqlite
error), never touches a file of the state root, and runs from a venv installed beside the old (rollback) binary. For each `plan:` root
it reports:

  - three properties, each separate: `unchanged` (the scan changes nothing, always true for a read), `old_readable` (the old binary's
    `plan show`/`digest` of this root do not crash), `old_continuable` (the old binary would amend / verdict-run / accept this root to the
    right state);
  - `status` by the OLD version's own rules: open (proposed/approved), paused (stopped_with_report), closed (accepted);
  - `anchor` and the event classes present (0 / A / B);
  - the block conditions, SPLIT by type: a read block (B4 — a class-0 payload the old reader cannot parse, so `show` and the whole-
    state-root `digest` crash KeyError, EVEN when the root is accepted) and a continue block (B2 — a class-B event, or a contract field
    the old version cannot write back, on a not-yet-accepted root);
  - a per-command prediction for the old binary (plan show / digest / report / amend / verdict run / propose), matching T49's command
    table, NOT one expectation for all commands.

`accepted` releases a continue block (the old binary refuses amend/verdict-run on an accepted root) but NEVER a read block (an accepted
root with a malformed class-0 payload still crashes the old reader). A paused / stopped_with_report root releases nothing.
"""
from pathlib import Path

from . import compat, plan as plans, report


# ---- block detection -------------------------------------------------------------------------------------------------------

def _class_b_events(events):
    return [kind for kind, _, _ in events if compat.event_class(kind) == 'B']


def _read_block_events(events):
    """Class-0 events whose payload drops a field the old reader needs (a B4 read block). The scan does not need the old binary to find
    these: the event-type ledger says which fields are load-bearing, and a missing one is exactly what makes the old reader crash (EV-K)."""
    bad = []
    for kind, _, payload in events:
        if compat.event_class(kind) == '0' and not compat.class0_payload_ok(kind, payload):
            missing = [f for f in compat.required_fields(kind) if not isinstance(payload, dict) or payload.get(f) is None]
            bad.append((kind, missing))
    return bad


def _status_from_events(events):
    """The OLD version's status (open | paused | closed), computed defensively from RAW events so a malformed class-0 payload (a B4 root
    the normal reader crashes on) still gets a status. Mirrors plan.status: latest revision, then accepted / stopped / approved."""
    latest, accepted_rev, stopped_revs, approved = 0, None, set(), None
    for kind, _, p in events:
        if not isinstance(p, dict):
            continue
        if kind in ('plan.proposed', 'plan.amended') and isinstance(p.get('revision'), int):
            latest = max(latest, p['revision'])
        elif kind == 'plan.accepted' and isinstance(p.get('revision'), int):
            accepted_rev = p['revision']
        elif kind == 'milestone.stopped' and isinstance(p.get('revision'), int):
            stopped_revs.add(p['revision'])
        elif kind == 'plan.approved' and isinstance(p.get('revision'), int):
            approved = p['revision']
    if not latest:
        return 'open'                      # proposed (treated open)
    if accepted_rev == latest:
        return 'closed'
    if latest in stopped_revs:
        return 'paused'
    return 'open'                          # approved or proposed: open to the old binary


# ---- per-command prediction (T49 command table, `plan:` columns) -----------------------------------------------------------

def _predict_commands(status, read_block, continue_block):
    """What each old command does on this `plan:` root. Keys are the T49 command rows. Each value is a short predicted outcome."""
    if read_block:
        # X1 column: every read or write crashes KeyError; digest of the WHOLE state root crashes too.
        return {'plan show': 'exit 1, KeyError', 'plan digest': 'exit 1, KeyError (whole state root)', 'plan report': 'exit 1, KeyError',
                'plan amend': 'exit 1, KeyError, writes nothing', 'verdict run': 'exit 1, KeyError', 'plan propose <same name>': 'refused, already exists'}
    if status == 'closed':
        # X2 column: accepted, history readable.
        return {'plan show': 'exit 0, accepted', 'plan digest': 'exit 0, listed', 'plan report': 'exit 0',
                'plan amend': 'refused, is accepted; writes nothing', 'verdict run': 'refused, nothing to verify',
                'plan propose <same name>': 'refused, already exists'}
    if continue_block:
        # R4 column: reads wrong / continues wrong (class B); exit 0 but the status is stale.
        return {'plan show': 'exit 0 but WRONG (stale status)', 'plan digest': 'exit 0, listed', 'plan report': 'exit 0',
                'plan amend': 'exit 0, ignores the class-B event (continues wrong)', 'verdict run': 'exit 0, runs anyway (continues wrong)',
                'plan propose <same name>': 'refused, already exists'}
    # R1 / DUPa column: open, class 0/A only — read and continue correctly.
    return {'plan show': 'exit 0, same status as the new version', 'plan digest': 'exit 0, listed', 'plan report': 'exit 0',
            'plan amend': 'exit 0, writes plans/<name>/v<N+1>.json', 'verdict run': 'exit 0 when approved',
            'plan propose <same name>': 'refused, already exists'}


def _raw_events(state_root, row):
    """Every event of the anchor as (kind, created_at, payload), read-only, WITHOUT deriving — so a malformed payload does not crash us."""
    import json
    reader = report._Reader(state_root, row['project_id'], row['project_path'])
    with reader.transaction() as conn:
        if conn is None:
            return []
        rows = conn.execute('SELECT kind, created_at, payload FROM events WHERE task_id=? ORDER BY seq', (row['id'],)).fetchall()
    out = []
    for e in rows:
        try:
            payload = json.loads(e['payload'])
        except ValueError:
            payload = None
        out.append((e['kind'], e['created_at'], payload))
    return out


def scan_root(state_root, row):
    """One row of the scan for one `plan:` root. Read-only, and defensive: it never derives (derive crashes on a B4 root)."""
    name = row['request_key'][len(plans.ANCHOR):]
    events = _raw_events(state_root, row)
    status = _status_from_events(events)
    read_bad = _read_block_events(events)
    class_b = _class_b_events(events)
    classes = sorted({compat.event_class(kind) or '?' for kind, _, _ in events})

    # A continue block (B2) holds for a class-B event on a `plan:` root that is NOT accepted. `accepted` releases it.
    continue_block = bool(class_b) and status != 'closed'
    # A read block (B4) holds for a malformed class-0 payload at ANY status, accepted included.
    read_block = bool(read_bad)

    blocks = []
    if read_block:
        blocks.append({'id': 'B4', 'type': 'read', 'why': 'class-0 payload the old reader cannot parse: ' +
                       '; '.join(f'{k} missing {", ".join(m)}' for k, m in read_bad),
                       'released_by': 'none in this rollback (do not edit history; roll back to a target that reads this ledger, or roll forward)',
                       'not_released_by': 'paused / stopped_with_report / accepted'})
    if continue_block:
        blocks.append({'id': 'B2', 'type': 'continue', 'why': 'class-B event(s) on a plan: anchor: ' + ', '.join(sorted(set(class_b))),
                       'released_by': 'the root is accepted', 'not_released_by': 'paused / stopped_with_report'})

    old_readable = not read_block
    old_continuable = (not read_block) and (not continue_block)
    return {
        'name': name, 'project_id': row['project_id'], 'anchor': row['request_key'], 'status': status,
        'properties': {'unchanged': True, 'old_readable': old_readable, 'old_continuable': old_continuable},
        'preserved_only': not old_readable,                        # "chỉ được bảo toàn" when the old binary cannot read it
        'event_classes': classes,
        'blocks': blocks,
        'commands': _predict_commands(status, read_block, continue_block),
    }


def scan(state_root):
    """Scan every `plan:` root in the state root. Read-only: it only reads, through report._Reader (mode=ro). Returns a report dict with a
    content hash of the ledger it read, so the rollback script can prove it acted on the same ledger."""
    from ..ledger import LedgerError
    try:
        anchors = report._anchors(state_root)
    except LedgerError:
        anchors = []                       # no ledger yet: a fresh state root has no roots and no blocks (a clean rollback target)
    roots = [scan_root(state_root, row) for row, _ in anchors]
    read_blocks = [b for r in roots for b in r['blocks'] if b['type'] == 'read']
    continue_blocks = [b for r in roots for b in r['blocks'] if b['type'] == 'continue']
    return {
        'state_root': str(Path(state_root).resolve()),
        'ledger_sha': _ledger_sha(state_root),
        'roots': roots,
        'blocking': {'read': len(read_blocks), 'continue': len(continue_blocks), 'total': len(read_blocks) + len(continue_blocks)},
        'read_only': True,
    }


def _ledger_sha(state_root):
    """A content hash of the ledger file the scan read, for the rollback receipt. Read-only."""
    import hashlib
    path = Path(state_root).resolve() / 'ledger.sqlite3'
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()
