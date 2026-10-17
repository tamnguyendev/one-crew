"""The v2 contract object and its immutable revisions: <state-root>/plans/<name>/v<N>.json.

The file holds only what the owner agrees to. It has no status field: approved/accepted/stopped exist only as ledger events
written by the commands in plan.py, so editing or forging a file cannot approve anything (the hash in the approval event
must match the file).
"""
import json
import re
from pathlib import Path

from ..ledger import LedgerError, canonical, content_hash, key_field, text_field

SCHEMA_VERSION = 2
FIELDS = {'schema_version', 'title', 'understanding', 'output', 'scope', 'non_goals', 'items', 'milestones', 'budget', 'attention',
          'profile_version'}
TIERS = ('must', 'should', 'wont')
MODES = ('once', 'until_pass')
VERIFIERS = ('command', 'owner-manual')
MAX_ITEMS, MAX_MILESTONES = 12, 5
MAX_REPAIRS_CAP = 5
COMMAND_MAX_MINUTES = 60
ID = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,31}')


def _id(value, name):
    if not isinstance(value, str) or not ID.fullmatch(value): raise LedgerError(name + ': expected a short id like M1.')
    return value


def _list(value, name, low, high, item=lambda v: v):
    if not isinstance(value, list) or not low <= len(value) <= high:
        raise LedgerError(f'{name}: expected a list of {low}-{high} entries.')
    return [item(v) for v in value]


def _int(value, name, low, high):
    if type(value) is not int or not low <= value <= high: raise LedgerError(f'{name}: expected an integer {low}-{high}.')
    return value


def _verifier(value, name):
    if not isinstance(value, dict) or set(value) - {'type', 'config'} or value.get('type') not in VERIFIERS:
        raise LedgerError(name + ': verifier.type must be one of ' + ', '.join(VERIFIERS) + '.')
    config = value.get('config') or {}
    if value['type'] == 'command':
        if not isinstance(config, dict) or set(config) - {'argv', 'cwd', 'max_minutes'}:
            raise LedgerError(name + ': command verifier takes argv, cwd and max_minutes.')
        from ..work_contract import argv_value
        argv = argv_value(config.get('argv'), name + '.argv')
        cwd = config.get('cwd')
        if cwd is not None: text_field(cwd, name + '.cwd', 500)
        minutes = _int(config.get('max_minutes', 15), name + '.max_minutes', 1, COMMAND_MAX_MINUTES)
        return {'type': 'command', 'config': {'argv': argv, 'cwd': cwd, 'max_minutes': minutes}}
    if config: raise LedgerError(name + ': owner-manual takes no config.')
    return {'type': 'owner-manual', 'config': {}}


def validate(value):
    """The normalized contract (defaults filled), or LedgerError. Unknown fields are refused, so no status can be smuggled in."""
    if not isinstance(value, dict) or set(value) - FIELDS:
        raise LedgerError('Contract: unknown fields ' + ','.join(sorted(set(value) - FIELDS)) if isinstance(value, dict)
                          else 'Contract must be a JSON object.')
    if value.get('schema_version') != SCHEMA_VERSION: raise LedgerError('Contract schema_version must be 2.')
    scope = value.get('scope')
    if not isinstance(scope, dict) or set(scope) != {'owned'}: raise LedgerError('scope: expected {"owned": [...]}.')
    items = _list(value.get('items'), 'items', 1, MAX_ITEMS, lambda v: _item(v))
    if len({i['id'] for i in items}) != len(items): raise LedgerError('items: duplicate id.')
    if not any(i['tier'] == 'must' for i in items): raise LedgerError('items: at least one must item.')
    milestones = _list(value.get('milestones'), 'milestones', 1, MAX_MILESTONES, lambda v: _milestone(v))
    if len({m['id'] for m in milestones}) != len(milestones): raise LedgerError('milestones: duplicate id.')
    for i in items:
        if i['milestone'] is not None and i['milestone'] not in {m['id'] for m in milestones}:
            raise LedgerError(f"items: {i['id']} names an unknown milestone.")
    budget = value.get('budget')
    if not isinstance(budget, dict) or set(budget) != {'max_calls', 'time'}: raise LedgerError('budget: expected max_calls and time.')
    attention = value.get('attention', {'questions': 1})
    if not isinstance(attention, dict) or set(attention) != {'questions'}: raise LedgerError('attention: expected {"questions": N}.')
    if value.get('profile_version') is not None: raise LedgerError('profile_version must stay null in L1.')
    return {'schema_version': SCHEMA_VERSION, 'title': text_field(value.get('title'), 'title', 200),
            'understanding': text_field(value.get('understanding'), 'understanding', 3000),
            'output': _list(value.get('output'), 'output', 1, 12, lambda v: text_field(v, 'output', 500)),
            'scope': {'owned': _list(scope['owned'], 'scope.owned', 1, 40, lambda v: text_field(v, 'scope.owned', 300))},
            'non_goals': _list(value.get('non_goals', []), 'non_goals', 0, 20, lambda v: text_field(v, 'non_goals', 300)),
            'items': items, 'milestones': milestones,
            'budget': {'max_calls': _int(budget['max_calls'], 'budget.max_calls', 1, 10000),
                       'time': _int(budget['time'], 'budget.time (minutes)', 1, 28800)},
            'attention': {'questions': _int(attention['questions'], 'attention.questions', 1, 3)}, 'profile_version': None}


def _item(v):
    if not isinstance(v, dict) or set(v) - {'id', 'title', 'tier', 'milestone'} or v.get('tier') not in TIERS:
        raise LedgerError('items: each item takes id, title, tier (must|should|wont) and optional milestone.')
    milestone = v.get('milestone')
    return {'id': _id(v.get('id'), 'item id'), 'title': text_field(v.get('title'), 'item title', 300), 'tier': v['tier'],
            'milestone': _id(milestone, 'item milestone') if milestone is not None else None}


def _milestone(v):
    if not isinstance(v, dict) or set(v) - {'id', 'title', 'verifier', 'mode', 'max_repairs'}:
        raise LedgerError('milestones: each takes id, title, verifier, mode and max_repairs.')
    mode = v.get('mode', 'once')
    if mode not in MODES: raise LedgerError('milestones: mode must be once or until_pass.')
    name = 'milestone ' + str(v.get('id'))
    return {'id': _id(v.get('id'), 'milestone id'), 'title': text_field(v.get('title'), 'milestone title', 300),
            'verifier': _verifier(v.get('verifier'), name), 'mode': mode,
            'max_repairs': _int(v.get('max_repairs', 1), name + '.max_repairs', 0, MAX_REPAIRS_CAP)}


# ---- immutable revisions on disk -------------------------------------------------------------------------------------

def plan_dir(ledger, name):
    return Path(ledger.state_root) / 'plans' / key_field(name)


def revision_path(ledger, name, revision):
    return plan_dir(ledger, name) / f'v{revision}.json'


def write_revision(ledger, name, revision, contract):
    """Write-once: an existing revision is never replaced."""
    path = revision_path(ledger, name, revision)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {'plan': name, 'revision': revision, 'content_sha': content_hash(contract), 'contract': contract}
    with path.open('xb') as stream:
        stream.write(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True).encode('utf-8'))
    return document['content_sha']


def read_revision(ledger, name, revision, expect_sha=None):
    path = revision_path(ledger, name, revision)
    try:
        document = json.loads(path.read_bytes().decode('utf-8-sig'))
    except (OSError, ValueError) as error:
        raise LedgerError(f'Plan {name} revision {revision} is unreadable: {error}') from error
    contract = document.get('contract')
    sha = content_hash(contract) if isinstance(contract, dict) else None
    if sha != document.get('content_sha') or (expect_sha is not None and sha != expect_sha):
        raise LedgerError(f'Plan {name} revision {revision} does not match the recorded hash; the file was changed.')
    return contract, sha
