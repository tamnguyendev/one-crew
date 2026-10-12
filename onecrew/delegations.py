"""User delegations and decision provenance v2. Evidence only: a delegation never widens a grant or answers a request."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import uuid

from .ledger import Ledger, LedgerError, canonical, content_hash, utcnow

CHANNELS = ('user_direct', 'entry_relay', 'entry_delegated', 'entry_undelegated', 'runtime_observed')
REFERENCE_KINDS = ('chat', 'window', 'cli')
# These decisions stay the user's (AGENTS.md: escalate business/architecture; never widen budget or permissions).
FORBIDDEN = ('business', 'architecture', 'permission', 'budget')
ENTRY_ACTORS = ('claude', 'codex', 'other-entry')
RUNTIME_ACTORS = ('onecrew', 'keeper')
CLASS = re.compile(r'[a-z][a-z0-9_]{0,39}\Z')
DELEGATION = re.compile(r'DLG-[0-9a-f]{32}\Z')
SHA256 = re.compile(r'[0-9a-f]{64}\Z')
MAX_DAYS = 30
# Request action types whose decision class is fixed; delivery recovery requests carry their own class.
QUESTION_CLASSES = {'job.effort_warning': 'budget', 'job.clarification': 'business', 'solution.slice_review': 'business'}
DDL = '''CREATE TABLE IF NOT EXISTS delegations(id TEXT PRIMARY KEY, project_id TEXT NOT NULL, identity TEXT NOT NULL,
    payload TEXT NOT NULL, revoked TEXT, created_at TEXT NOT NULL, UNIQUE(project_id, identity))'''


def instant(value):
    try:
        moment = dt.datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None
    return moment if moment is not None and moment.tzinfo is not None else None


def when(value, name):
    moment = instant(value)
    if moment is None:
        raise LedgerError(f'{name}: expected an ISO time with a timezone.')
    return moment


def reference(quote, kind='chat', quoted_at=None):
    """The user's words as evidence: only their hash is stored, never the text."""
    if not isinstance(quote, str) or not quote.strip() or len(quote) > 8000:
        raise LedgerError("User quote: expected the user's words, at most 8000 characters.")
    if kind not in REFERENCE_KINDS:
        raise LedgerError('User reference kind must be chat, window or cli.')
    at = quoted_at or utcnow()
    when(at, 'quoted_at')
    return {'kind': kind, 'quote_sha256': hashlib.sha256(quote.strip().encode('utf-8')).hexdigest(), 'quoted_at': at}


def valid_reference(value):
    return (isinstance(value, dict) and set(value) == {'kind', 'quote_sha256', 'quoted_at'} and value['kind'] in REFERENCE_KINDS
            and isinstance(value['quote_sha256'], str) and bool(SHA256.fullmatch(value['quote_sha256']))
            and instant(value['quoted_at']) is not None)


def decision_class(question):
    """The class of decision a request asks for; None when it cannot be shown (never delegable)."""
    action = question.get('action') if isinstance(question, dict) else None
    kind = action.get('type') if isinstance(action, dict) else None
    if kind == 'delivery.recovery':
        value = (action.get('parameters') or {}).get('class')
        return value if isinstance(value, str) and CLASS.fullmatch(value) else None
    return QUESTION_CLASSES.get(kind)


def installed(conn):
    return bool(conn and conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='delegations'").fetchone())


def view(row):
    return dict(json.loads(row['payload']), id=row['id'], revoked=json.loads(row['revoked']) if row['revoked'] else None)


def load(conn, project_id=None):
    """Every recorded delegation by ID (revoked ones included: a revocation is never retroactive)."""
    if not installed(conn):
        return {}
    rows = conn.execute('SELECT * FROM delegations' + (' WHERE project_id=?' if project_id else ''),
                        (project_id,) if project_id else ()).fetchall()
    return {row['id']: view(row) for row in rows}


def problem(record, cls, at):
    """None when the delegation covers a decision of this class at this time, else the reason it does not."""
    if not isinstance(record, dict):
        return 'unknown delegation'
    if cls is None:
        return 'decision class unknown'
    if cls in FORBIDDEN:
        return cls + " decisions stay the user's"
    if cls not in (record.get('classes') or ()):
        return 'class ' + cls + ' not delegated'
    if not valid_reference(record.get('user_reference')):
        return 'delegation lacks a user reference'
    moment, granted, until = instant(at), instant(record.get('granted_at')), instant(record.get('until'))
    if moment is None or granted is None or until is None:
        return 'time not provable'
    if moment < granted:
        return 'decision precedes the delegation'
    if moment >= until:
        return 'delegation expired'
    revoked = instant((record.get('revoked') or {}).get('at')) if record.get('revoked') else None
    if record.get('revoked') and (revoked is None or revoked <= moment):
        return 'delegation revoked'
    return None


def classes_field(value):
    items = value.split(',') if isinstance(value, str) else value
    if not isinstance(items, (list, tuple)):
        raise LedgerError('Delegation classes: expected a comma-separated list.')
    classes = sorted({str(item).strip() for item in items if str(item).strip()})
    if not 1 <= len(classes) <= 20 or not all(CLASS.fullmatch(c) for c in classes):
        raise LedgerError('Delegation classes: 1-20 lower-case decision class names.')
    refused = [c for c in classes if c in FORBIDDEN]
    if refused:
        raise LedgerError('A delegation cannot cover ' + ', '.join(refused) + " decisions; they stay the user's.")
    return classes


def actor_now(by=None):
    from .interventions import actor
    return by or actor()


def grant(ledger, quote, classes, until, *, by=None, kind='chat', quoted_at=None):
    """Record the user's delegation. The grant itself relays the user's words, so the quote is required."""
    classes = classes_field(classes)
    end, now = when(until, 'until'), dt.datetime.now(dt.timezone.utc)
    if end <= now:
        raise LedgerError('Delegation must end in the future.')
    if end > now + dt.timedelta(days=MAX_DAYS):
        raise LedgerError(f'Delegation may last at most {MAX_DAYS} days; ask the user again after that.')
    by = actor_now(by)
    ref = reference(quote, kind, quoted_at)
    identity = content_hash({'classes': classes, 'until': end.isoformat(), 'quote_sha256': ref['quote_sha256']})
    payload = {'project_id': ledger.project_id, 'classes': classes, 'until': end.isoformat(), 'granted_at': utcnow(),
               'user_reference': ref, 'by': by, 'channel': 'user_direct' if by == 'user' else 'entry_relay',
               'authority': 'evidence only; never widens a grant, budget or permission'}
    with ledger.transaction(write=True) as conn:
        conn.execute(DDL)
        old = conn.execute('SELECT * FROM delegations WHERE project_id=? AND identity=?', (ledger.project_id, identity)).fetchone()
        if old:
            return view(old)
        did = 'DLG-' + uuid.uuid4().hex
        conn.execute('INSERT INTO delegations VALUES(?,?,?,?,?,?)', (did, ledger.project_id, identity, canonical(payload), None, utcnow()))
        return view(conn.execute('SELECT * FROM delegations WHERE id=?', (did,)).fetchone())


def listing(ledger, everything=False):
    with ledger.transaction() as conn:
        rows = list(load(conn, ledger.project_id).values()) if conn else []
    now = utcnow()
    for row in rows:
        row['active'] = problem(row, row['classes'][0], now) is None
    return sorted((r for r in rows if everything or r['active']), key=lambda r: r['granted_at'])


def revoke(ledger, did, *, by=None, quote=None, kind='chat'):
    """Revoking narrows authority, so anyone may do it; decisions recorded before it keep their provenance."""
    if not isinstance(did, str) or not DELEGATION.fullmatch(did):
        raise LedgerError('Unknown delegation ID.')
    value = {'at': utcnow(), 'by': actor_now(by), 'user_reference': reference(quote, kind) if quote else None}
    with ledger.transaction(write=True) as conn:
        row = conn.execute('SELECT * FROM delegations WHERE id=? AND project_id=?', (did, ledger.project_id)).fetchone() if installed(conn) else None
        if row is None:
            raise LedgerError('Unknown delegation in this project.')
        if row['revoked']:
            return view(row)
        conn.execute('UPDATE delegations SET revoked=? WHERE id=?', (canonical(value), did))
        return view(conn.execute('SELECT * FROM delegations WHERE id=?', (did,)).fetchone())


def decision(ledger, by, decided_by=None, quote=None, kind=None, delegation=None, cls=None):
    """Provenance v2 for one decision record. A delegation claim that does not cover the decision is refused."""
    if decided_by not in (None, 'user', 'entry'):
        raise LedgerError('decided_by must be user or entry.')
    ref = reference(quote, kind or ('cli' if by == 'user' else 'chat')) if quote is not None else None
    channel = None
    if delegation is not None:
        if by not in ENTRY_ACTORS:
            raise LedgerError('Only an entry decides under a delegation; set ONECREW_ACTOR to the entry.')
        if decided_by == 'user':
            raise LedgerError("A relayed user decision needs the user's quote, not a delegation.")
        with ledger.transaction() as conn:
            record = load(conn, ledger.project_id).get(delegation) if conn else None
        why = problem(record, cls, utcnow())
        if why:
            raise LedgerError(f'Delegation {delegation} does not cover this decision: {why}.')
        decided_by, channel = 'entry', 'entry_delegated'
    elif by == 'user':
        if decided_by == 'entry':
            raise LedgerError('A user reply cannot be an entry decision.')
        decided_by, channel = 'user', 'user_direct'
    elif by in ENTRY_ACTORS:
        if decided_by is None and ref is not None:
            decided_by = 'user'  # the user's own words for this decision: the entry relays it
        channel = {'user': 'entry_relay', 'entry': 'entry_undelegated'}.get(decided_by)
    return {'channel': channel, 'by': by, 'decided_by': decided_by, 'user_reference': ref,
            'delegation': delegation, 'decision_class': cls}


def validate_decision(value):
    """Shape check for a provenance v2 record handed to a store (who/what it claims stays evidence)."""
    if value is None:
        return None
    fields = {'channel', 'by', 'decided_by', 'user_reference', 'delegation', 'decision_class'}
    if not isinstance(value, dict) or set(value) - fields:
        raise LedgerError('Invalid decision provenance.')
    if value.get('channel') not in (None, *CHANNELS) or value.get('decided_by') not in (None, 'user', 'entry'):
        raise LedgerError('Invalid decision channel.')
    if value.get('user_reference') is not None and not valid_reference(value['user_reference']):
        raise LedgerError('Invalid user reference.')
    if value.get('delegation') is not None and not DELEGATION.fullmatch(str(value['delegation'])):
        raise LedgerError('Invalid delegation ID.')
    if value.get('decision_class') is not None and not CLASS.fullmatch(str(value['decision_class'])):
        raise LedgerError('Invalid decision class.')
    by = value.get('by')
    if by is not None and (not isinstance(by, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,39}', by)):
        raise LedgerError('Invalid decision actor.')
    return json.loads(canonical(value))


READ_ONLY = {('delegation', 'list')}
RECORDED = {('delegation', 'grant'): 'delegation.grant', ('delegation', 'revoke'): 'delegation.revoke'}


def parser():
    p = argparse.ArgumentParser(prog='onecrew', description='User delegations: evidence for decision provenance, never authority.')
    p.add_argument('--project', type=Path, default=Path.cwd()); p.add_argument('--state-root', type=Path)
    sub = p.add_subparsers(dest='group', required=True).add_parser('delegation').add_subparsers(dest='command', required=True)
    q = sub.add_parser('grant')
    q.add_argument('--reference', required=True, help="The user's own words granting the delegation (stored as a hash).")
    q.add_argument('--classes', required=True, help='Comma-separated decision classes, e.g. transient,environment.')
    q.add_argument('--until', required=True, help='ISO end time with timezone.')
    q.add_argument('--reference-kind', choices=REFERENCE_KINDS, default='chat')
    sub.add_parser('list').add_argument('--all', action='store_true')
    q = sub.add_parser('revoke'); q.add_argument('id'); q.add_argument('--reference')
    return p


def execute(args, ledger):
    if args.command == 'grant':
        return grant(ledger, args.reference, args.classes, args.until, kind=args.reference_kind)
    if args.command == 'revoke':
        return revoke(ledger, args.id, quote=args.reference)
    return {'delegations': listing(ledger, args.all)}


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        ledger = Ledger(args.project, args.state_root)
        result = execute(args, ledger)
        command = RECORDED.get((args.group, args.command))
        if command:
            from .interventions import cli_note
            cli_note(ledger, command, scope=('delegation', result['id']), key=command + ':' + result['id'])
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, sqlite3.Error) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        return 2
