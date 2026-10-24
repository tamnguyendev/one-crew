"""W46a/b — read-only compatibility scan (R00, 00 §6.1), for both plan anchors.

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
import hashlib
import json
import os
import sqlite3
from pathlib import Path

from ..ledger import LedgerError, content_hash
from . import compat, report, namespaces

# The d3120c6 pre-namespace reader's top-level contract surface. Extra fields may be
# readable as JSON but cannot be written back by its validator during amend.
OLD_REVISION = 'd3120c6'
OLD_FIELDS = frozenset(('schema_version', 'title', 'size', 'understanding', 'options', 'preconditions', 'output', 'scope', 'non_goals',
    'items', 'milestones', 'budget', 'attention', 'stop', 'profile_version', 'origin', 'decisions', 'presentation', 'advisor'))


def _unsupported_fields(contract):
    fields = sorted(set(contract) - OLD_FIELDS)
    milestones = contract.get('milestones', [])
    if isinstance(milestones, list):
        for index, milestone in enumerate(milestones):
            verifier = milestone.get('verifier') if isinstance(milestone, dict) else None
            if isinstance(verifier, dict) and verifier.get('type') not in ('command', 'reviewer', 'owner-manual'):
                fields.append(f'milestones[{index}].verifier.type={verifier.get("type")}')
    # R01 adds scope to individual unknowns without adding a top-level field.
    # The old _unknown validator refuses these keys during amend too.
    understanding = contract.get('understanding', {})
    if isinstance(understanding, dict):
        unknowns = understanding.get('unknowns', [])
        if isinstance(unknowns, list):
            for index, unknown in enumerate(unknowns):
                if isinstance(unknown, dict):
                    fields.extend(f'understanding.unknowns[{index}].{key}' for key in
                                  sorted(set(unknown) - {'id', 'question', 'status', 'closed_by', 'evidence'}))
    return fields


def _json_file(path, inputs):
    raw = path.read_bytes()
    inputs[str(path.resolve())] = hashlib.sha256(raw).hexdigest()
    value = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(value, dict):
        raise LedgerError(f'Compatibility input is not an object: {path}')
    return value


def _revision_match(path, sha, inputs):
    if not path.is_file():
        return False, None
    document = _json_file(path, inputs)
    value = document.get('contract')
    actual = content_hash(value) if isinstance(value, dict) else None
    return bool(actual and actual == sha == document.get('content_sha')), value


def _storage(state_root, row, events, inputs):
    """Inspect immutable revision files; never infer location from the name alone."""
    name, _ = namespaces.parse(row['request_key'])
    versions = [p for kind, _, p in events if kind in ('plan.proposed', 'plan.amended') and isinstance(p, dict)
                and type(p.get('revision')) is int and p['revision'] > 0]
    if not versions:
        # A malformed class-0 revision is already a B4; it must not turn into a
        # supposedly empty ledger just because storage cannot be derived.
        if _read_block_events(events):
            return {'relocated': False, 'unknown': True, 'unsupported_fields': []}
        raise LedgerError(f'Plan anchor {row["request_key"]} has no valid revision event.')
    latest = max(versions, key=lambda p: p['revision'])
    if not isinstance(latest.get('sha'), str):
        raise LedgerError(f'Plan anchor {row["request_key"]} has no revision hash.')
    base = Path(state_root) / 'plans'
    old = base / name / f'v{latest["revision"]}.json'
    new = base / row['project_id'] / name / f'v{latest["revision"]}.json'
    old_ok, old_contract = _revision_match(old, latest['sha'], inputs)
    new_ok, new_contract = _revision_match(new, latest['sha'], inputs)
    is_ns = row['request_key'].startswith(namespaces.NAMESPACED)
    if not (new_ok if is_ns else old_ok or new_ok):
        raise LedgerError(f'Plan {row["request_key"]} revision {latest["revision"]} is missing, corrupt, or does not match its ledger hash.')
    value = new_contract if is_ns or not old_ok else old_contract
    return {'relocated': not is_ns and not old_ok and new_ok, 'unknown': False,
            'global_matches': old_ok, 'revision': latest['revision'],
            'old_directory': str(old.parent), 'new_directory': str(new.parent),
            'next_global_revision_exists': (old.parent / f'v{latest["revision"] + 1}.json').exists(),
            'unsupported_fields': _unsupported_fields(value)}


def _active_documents(state_root, rows, inputs):
    """Read both old-hook-visible state copies and each known project copy.

    Expiry and pause do not release B1. Do not import hook_cli: its lookup can
    restore files/register projects, while a compatibility scan must only read.
    """
    candidates = {Path(r['project_path']) / '.onecrew' / 'active-plan.json' for r in rows}
    candidates.update((Path(state_root) / 'plans').glob('*/active-plan.json'))
    by_id = {r['id']: r for r in rows}
    result = {}
    root_path = Path(state_root).resolve()
    for path in sorted(candidates, key=str):
        if not path.exists():
            continue
        doc = _json_file(path, inputs)
        if doc.get('state_root') and Path(doc['state_root']).resolve() != root_path:
            continue
        if doc.get('status') not in ('approved', 'stopped_with_report', 'accepted', 'proposed'):
            raise LedgerError(f'Active-plan status cannot be diagnosed: {path}')
        if not isinstance(doc.get('project'), str) or not isinstance(doc.get('plan'), str):
            raise LedgerError(f'Active-plan project/name missing: {path}')
        project = os.path.normcase(str(Path(doc['project']).resolve()))
        matches = [r for r in rows if os.path.normcase(str(Path(r['project_path']).resolve())) == project]
        if doc.get('anchor_task'):
            target = by_id.get(doc['anchor_task'])
            matches = [r for r in matches if target and r['id'] == target['id']]
        if doc.get('anchor'):
            matches = [r for r in matches if r['request_key'] == doc['anchor']]
        else:
            matches = [r for r in matches if namespaces.parse(r['request_key'])[0] == doc['plan']]
        if len(matches) != 1 or namespaces.parse(matches[0]['request_key'])[0] != doc['plan']:
            raise LedgerError(f'Active plan has an unresolved or ambiguous root: {path}')
        result.setdefault(matches[0]['id'], []).append({'path': str(path.resolve()), 'status': doc['status'],
                                                        'expires': doc.get('expires')})
    return result


def _namespace_commands(name, global_exists, legacy_peer=False):
    if legacy_peer:
        # A bare old command addresses the colliding legacy root, never this one.
        return {'plan show': 'addresses the legacy plan: root; namespaced root is not read',
                'plan digest': 'lists only the legacy peer; namespaced root not listed',
                'plan report': 'addresses the legacy plan: root; namespaced root is not read',
                'plan amend': 'addresses the legacy plan: root; namespaced root remains frozen',
                'verdict run': 'addresses the legacy plan: root; namespaced root remains frozen',
                'plan propose <same name>': 'refused, already exists (global legacy directory)'}
    return {'plan show': 'refused, No plan named; writes nothing',
            'plan digest': 'exit 0, namespaced root not listed',
            'plan report': 'refused, No plan named; writes nothing',
            'plan amend': 'refused, No plan named; writes nothing',
            'verdict run': 'refused, No plan named; writes nothing',
            'plan propose <same name>': ('refused, already exists (global legacy directory)' if global_exists else
                                         f'exit 0, creates a separate plan:{name} root in plans/{name}/; namespaced root remains frozen')}


# ---- block detection -------------------------------------------------------------------------------------------------------

def _class_b_events(events):
    return [kind for kind, _, _ in events if compat.event_class(kind) == 'B']


def _read_block_events(events):
    """Class-0 events with missing or wrongly typed old-reader fields (B4)."""
    bad = []
    for kind, _, payload in events:
        if compat.event_class(kind) == '0' and not compat.class0_payload_ok(kind, payload):
            bad.append((kind, compat.class0_payload_errors(kind, payload)))
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
        return {'plan show': 'exit 1, KeyError/TypeError', 'plan digest': 'exit 1, KeyError/TypeError (whole state root)', 'plan report': 'exit 1, KeyError/TypeError',
                'plan amend': 'exit 1, KeyError/TypeError, writes nothing', 'verdict run': 'exit 1, KeyError/TypeError', 'plan propose <same name>': 'refused, already exists'}
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


def scan_root(state_root, row, *, events=None, storage=None, peers=(), active=(), inputs=None):
    """One row for either anchor, including the old reader's exact storage boundary."""
    name, _ = namespaces.parse(row['request_key'])
    events = _raw_events(state_root, row) if events is None else events
    storage = _storage(state_root, row, events, inputs if inputs is not None else {}) if storage is None else storage
    status = _status_from_events(events)
    read_bad = _read_block_events(events)
    class_b = _class_b_events(events)
    classes = sorted({compat.event_class(kind) or '?' for kind, _, _ in events})

    is_ns = row['request_key'].startswith(namespaces.NAMESPACED)
    duplicate = [{'project_id': p['project_id'], 'anchor': p['request_key']} for p in peers if p['id'] != row['id']]
    if is_ns:
        blocks = []
        governing = [d for d in active if d['status'] in ('approved', 'stopped_with_report') or
                     (d['status'] == 'accepted' and status != 'closed')]
        if governing:
            blocks.append({'id': 'B1', 'type': 'continue',
                           'why': 'active plan points to a root the old binary cannot see: ' + ', '.join(d['path'] for d in governing),
                           'released_by': 'accepted root and active copies exported as accepted, or owner removal of active copies',
                           'not_released_by': 'paused / stopped_with_report / expired active plan / acceptance without export'})
        legacy_peer = any(p['request_key'] == namespaces.LEGACY + name and p['project_id'] == row['project_id'] for p in peers)
        return {'name': name, 'project_id': row['project_id'], 'anchor': row['request_key'], 'status': status,
                'properties': {'unchanged': True, 'old_readable': False, 'old_continuable': False},
                'preserved_only': True, 'event_classes': classes, 'blocks': blocks, 'active_documents': list(active),
                'duplicates': duplicate, 'duplicate_note': 'same name, not a B3 write hazard' if duplicate else None,
                'storage': storage,
                'commands': _namespace_commands(name, (Path(state_root) / 'plans' / name / 'v1.json').exists(), legacy_peer)}

    # Legacy class B remains B2; namespaced class B is outside the old reader.
    continue_block = bool(class_b) and status != 'closed'
    # A read block (B4) holds for a malformed class-0 payload at ANY status, accepted included.
    read_block = bool(read_bad)

    blocks = []
    if read_block:
        blocks.append({'id': 'B4', 'type': 'read', 'why': 'class-0 payload the old reader cannot parse: ' +
                       '; '.join(f'{k}: {", ".join(m)}' for k, m in read_bad),
                       'released_by': 'none in this rollback (do not edit history; roll back to a target that reads this ledger, or roll forward)',
                       'not_released_by': 'paused / stopped_with_report / accepted'})
    if continue_block:
        blocks.append({'id': 'B2', 'type': 'continue', 'why': 'class-B event(s) on a plan: anchor: ' + ', '.join(sorted(set(class_b))),
                       'released_by': 'the root is accepted', 'not_released_by': 'paused / stopped_with_report'})

    relocated = storage['relocated']
    other_owner = [p for p in peers if p['project_id'] != row['project_id'] and p['request_key'] == namespaces.LEGACY + name
                   and p.get('_storage', {}).get('global_matches')]
    write_hazard = bool(relocated and other_owner and not storage.get('next_global_revision_exists') and not read_block and status != 'closed')
    extra_reasons = []
    if relocated:
        extra_reasons.append('legacy anchor revision lives in the new project directory; old amend writes into plans/' + name + '/')
    if storage.get('unsupported_fields'):
        extra_reasons.append('contract fields the old validator cannot write back: ' + ', '.join(storage['unsupported_fields']))
    if status != 'closed' and extra_reasons:
        ident = 'B3' if write_hazard else 'B2'
        existing = next((b for b in blocks if b['id'] == ident), None)
        reason = '; '.join(extra_reasons)
        if write_hazard:
            reason += '; writable next revision belongs to project ' + ', '.join(p['project_id'] for p in other_owner)
        if existing:
            existing['why'] += '; ' + reason
        else:
            blocks.append({'id': ident, 'type': 'continue', 'why': reason,
                           'released_by': 'this root is accepted',
                           'not_released_by': 'paused / stopped_with_report / accepting the other project root'})

    old_readable = not read_block and not relocated
    old_continuable = old_readable and not any(b['type'] == 'continue' for b in blocks)
    commands = _predict_commands(status, read_block, continue_block)
    if relocated and not read_block:
        commands.update({'plan show': 'refused, legacy revision file missing or hash differs',
                         'plan report': 'exit 0, partial report with unreadable-contract diagnostic',
                         'plan digest': 'exit 0, root listed with mốc ?/? (revision unreadable)',
                         'plan amend': ('refused, is accepted; writes nothing' if status == 'closed' else
                                        'refused, next global revision already exists' if storage.get('next_global_revision_exists') else
                                        'exit 0, writes plans/' + name + f'/v{storage["revision"] + 1}.json' +
                                        (' in another project directory (B3)' if write_hazard else ' (branches into global directory)')),
                         'verdict run': 'refused, nothing to verify or legacy revision unreadable'})
    elif storage.get('unsupported_fields') and not read_block and status != 'closed':
        commands['plan amend'] = 'refused when preserving the unsupported contract fields; old validator cannot write them back'
    return {
        'name': name, 'project_id': row['project_id'], 'anchor': row['request_key'], 'status': status,
        'properties': {'unchanged': True, 'old_readable': old_readable, 'old_continuable': old_continuable},
        'preserved_only': not old_readable,                        # "chỉ được bảo toàn" when the old binary cannot read it
        'event_classes': classes,
        'blocks': blocks,
        'commands': commands, 'storage': storage, 'duplicates': duplicate, 'active_documents': list(active),
        'duplicate_note': 'cross-project writable legacy directory' if write_hazard else ('same name, not a B3 write hazard' if duplicate else None),
    }


def scan(state_root):
    """Scan both legacy and namespaced roots read-only, through report._Reader (mode=ro). Returns a report dict with a
    content hash of the ledger it read, so the rollback script can prove it acted on the same ledger."""
    state_root = Path(state_root).resolve()
    path = state_root / 'ledger.sqlite3'
    inputs = {}
    try:
        if not path.exists():
            if state_root.exists() and (not state_root.is_dir() or any(state_root.iterdir())):
                raise LedgerError('Ledger is absent but state-root data exists; cannot diagnose this as a fresh empty ledger.')
            return {'state_root': str(state_root), 'old_version': OLD_REVISION, 'ledger_sha': None, 'roots': [],
                    'blocking': {'read': 0, 'continue': 0, 'total': 0}, 'read_only': True,
                    'inputs_sha': content_hash({}), 'input_hashes': {}}
        before = _ledger_sha(state_root)
        anchors = report._anchors(state_root)
        rows = [dict(row) for row, _ in anchors]
        for row in rows:
            row['_events'] = _raw_events(state_root, row)
            row['_storage'] = _storage(state_root, row, row['_events'], inputs)
        active = _active_documents(state_root, rows, inputs)
        roots = [scan_root(state_root, row, events=row['_events'], storage=row['_storage'],
                           peers=[p for p in rows if namespaces.parse(p['request_key'])[0] == namespaces.parse(row['request_key'])[0]],
                           active=active.get(row['id'], []), inputs=inputs) for row in rows]
        if _ledger_sha(state_root) != before:
            raise LedgerError('Ledger changed during compatibility scan; rerun before rollback.')
        for filename, digest in inputs.items():
            if hashlib.sha256(Path(filename).read_bytes()).hexdigest() != digest:
                raise LedgerError('Compatibility input changed during scan: ' + filename)
    except (OSError, sqlite3.DatabaseError, ValueError, TypeError, KeyError) as error:
        raise LedgerError('Compatibility scan cannot safely read existing state: ' + str(error)) from error
    read_blocks = [b for r in roots for b in r['blocks'] if b['type'] == 'read']
    continue_blocks = [b for r in roots for b in r['blocks'] if b['type'] == 'continue']
    if read_blocks:
        for root in roots:
            root['commands']['plan digest'] = 'exit 1, KeyError/TypeError (whole state root has a B4 read block)'
    return {
        'state_root': str(Path(state_root).resolve()),
        'old_version': OLD_REVISION,
        'ledger_sha': before,
        'roots': roots,
        'blocking': {'read': len(read_blocks), 'continue': len(continue_blocks), 'total': len(read_blocks) + len(continue_blocks)},
        'read_only': True,
        'inputs_sha': content_hash(inputs), 'input_hashes': inputs,
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
