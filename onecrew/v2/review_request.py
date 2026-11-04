"""2.5-A logical review identity, shared by existing review consumers.

Pure data adapter: no ledger writes, dispatch, provider calls, policy decisions,
receipt authentication or grants. Callers supply facts from their trusted current
root/context and authenticate stored receipts before asking about applicability.
An exact identity match is necessary, never sufficient, to authorize a review or
reuse its result. Incomplete execution metadata can describe an observation but
cannot authenticate cached reuse or reviewer independence.
"""
import json
import re

from ..ledger import LedgerError, canonical, content_hash

VERSION = 1
METHODS = ('command', 'adapter', 'reviewer', 'investigation')
_HEX = re.compile(r'[0-9a-f]{64}')
_VOLATILE_BUDGET = {'remaining_calls', 'remaining_seconds', 'used_calls', 'used_seconds', 'spent', 'usage'}


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise LedgerError('Review request needs a nonempty ' + name + '.')
    return value


def _positive(value, name):
    if type(value) is not int or value < 1:
        raise LedgerError('Review request needs a positive integer ' + name + '.')
    return value


def _json(value, name):
    def keys(item):
        if isinstance(item, dict):
            if any(not isinstance(k, str) for k in item): raise ValueError('non-string mapping key')
            for child in item.values(): keys(child)
        elif isinstance(item, list):
            for child in item: keys(child)
        elif item is not None and type(item) not in (str, int, float, bool):
            raise ValueError('non-JSON value')
    try:
        keys(value); encoded = canonical(value)
        if len(encoded.encode('utf-8')) > 65536: raise ValueError('data exceeds 64 KiB')
        return json.loads(encoded)
    except (ValueError, TypeError, RecursionError) as error:
        raise LedgerError('Review request ' + name + ' must be bounded JSON data.') from error


def _mapping(value, name, *, empty=False):
    if not isinstance(value, dict) or (not value and not empty):
        raise LedgerError('Review request ' + name + ' must be a mapping' + ('.' if empty else ' with explicit data.'))
    return _json(value, name)


def _names(value, name):
    if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value) or len(value) != len(set(value)):
        raise LedgerError('Review request ' + name + ' must contain unique names.')
    return sorted(value)


def _execution(value):
    value = {} if value is None else _mapping(value, 'execution', empty=True)
    allowed = {'method', 'implementation', 'provider', 'model', 'configuration', 'environment', 'provenance'}
    if set(value) - allowed:
        raise LedgerError('Unknown review execution metadata: ' + ', '.join(sorted(set(value) - allowed)))
    missing, result = [], {}
    for key in ('method', 'implementation', 'provider', 'model'):
        got = value.get(key)
        if got is not None and not isinstance(got, str):
            raise LedgerError('Review execution ' + key + ' must be text or unknown.')
        normalized = got.strip() if got is not None else None
        result[key] = normalized if normalized and normalized.casefold() not in ('unknown', 'unverified') else None
        if result[key] is not None: _text(result[key], 'execution.' + key)
    if result['method'] is not None and result['method'] not in METHODS:
        raise LedgerError('Unknown review execution method.')
    for key in ('method', 'implementation'):
        if result[key] is None: missing.append('execution.' + key)
    if result['method'] in ('reviewer', 'investigation'):
        for key in ('provider', 'model'):
            if result[key] is None: missing.append('execution.' + key)
    for key in ('configuration', 'environment', 'provenance'):
        got = value.get(key)
        if got is not None and not isinstance(got, dict):
            raise LedgerError('Review execution ' + key + ' must be a mapping or unknown.')
        if got is None or (not got and key != 'configuration'):
            missing.append('execution.' + key)
        result[key] = content_hash(got) if got is not None else None
    result.update(complete=not missing, missing=sorted(missing))
    return result


def build(*, root, contract_revision, contract_sha, review_id, required, facts,
          scope, criteria, policy, authority, budget, execution=None):
    """Describe exactly the review requested from trusted, current context.

    `facts` is review_dispatch._context's existing node snapshot. `budget` is the
    APPROVED original budget, not live remaining time/usage (checked by dispatch).
    Config/environment/provenance are fingerprinted, not copied into a receipt.
    Explicit execution metadata is a caller declaration, not proof of identity.
    """
    root = _mapping(root, 'root')
    if set(root) != {'project_id', 'task_id'}:
        raise LedgerError('Review root requires exactly project_id and task_id.')
    for key in root: _text(root[key], key)
    _positive(contract_revision, 'contract revision'); _text(review_id, 'review ID')
    if not isinstance(contract_sha, str) or not _HEX.fullmatch(contract_sha):
        raise LedgerError('Review contract SHA must be a SHA256 identity.')
    if type(required) is not bool: raise LedgerError('Review required flag must be boolean.')
    facts = _mapping(facts, 'facts')
    _text(facts.get('node'), 'node'); _text(facts.get('artifact'), 'artifact')
    _text(facts.get('state'), 'state'); _text(facts.get('phase'), 'phase')
    _positive(facts.get('internal_revision'), 'internal_revision')
    if type(facts.get('generation')) is not int or facts['generation'] < 0:
        raise LedgerError('Review request generation must be a nonnegative integer.')
    if facts.get('contract_sha') != contract_sha:
        raise LedgerError('Review facts belong to a different approved contract.')
    _mapping(facts.get('inputs'), 'inputs', empty=True)
    for key in ('unknowns', 'findings'): facts[key] = _names(facts.get(key), key)
    if not isinstance(criteria, list) or not criteria or any(not isinstance(c, dict) or not isinstance(c.get('id'), str) or not c['id'] for c in criteria):
        raise LedgerError('Review criteria need explicit check IDs.')
    criteria = _json(criteria, 'criteria')
    if len({c['id'] for c in criteria}) != len(criteria): raise LedgerError('Review criterion IDs must be unique.')
    if facts.get('checks_sha') != content_hash(criteria):
        raise LedgerError('Review criteria differ from the current node checks.')
    scope = _mapping(scope, 'scope')
    if set(scope) != {'read', 'write', 'acceptance'}:
        raise LedgerError('Review scope requires read, write and acceptance.')
    scope = {k: _names(v, 'scope.' + k) for k, v in scope.items()}
    policy = _mapping(policy, 'policy')
    authority = _mapping(authority, 'authority', empty=True)
    budget = _mapping(budget, 'original budget')
    if _VOLATILE_BUDGET & set(budget):
        raise LedgerError('Review request budget must be original approved limits, not remaining usage.')
    identity = {'root': root, 'contract_revision': contract_revision, 'contract_sha': contract_sha,
                'review_id': review_id, 'required': required,
                'facts': content_hash(facts), 'scope': content_hash(scope), 'criteria': content_hash(criteria),
                'policy': content_hash(policy), 'authority': content_hash(authority), 'budget': content_hash(budget),
                'execution': _execution(execution)}
    return {'version': VERSION, 'id': 'review-' + content_hash({'version': VERSION, 'identity': identity}),
            'identity': identity, 'execution_complete': identity['execution']['complete'],
            'missing': list(identity['execution']['missing'])}


def _valid(request):
    try:
        if not isinstance(request, dict) or set(request) != {'version', 'id', 'identity', 'execution_complete', 'missing'}:
            return False
        if type(request['version']) is not int or request['version'] != VERSION: return False
        identity = request['identity']
        if not isinstance(identity, dict) or set(identity) != {'root', 'contract_revision', 'contract_sha', 'review_id', 'required',
                'facts', 'scope', 'criteria', 'policy', 'authority', 'budget', 'execution'}: return False
        _json(request, 'descriptor')
        root = identity['root']
        if not isinstance(root, dict) or set(root) != {'project_id', 'task_id'}: return False
        for key in root: _text(root[key], key)
        _positive(identity['contract_revision'], 'contract revision'); _text(identity['review_id'], 'review ID')
        if type(identity['required']) is not bool: return False
        for key in ('contract_sha', 'facts', 'scope', 'criteria', 'policy', 'authority', 'budget'):
            if not isinstance(identity[key], str) or not _HEX.fullmatch(identity[key]): return False
        if request['id'] != 'review-' + content_hash({'version': VERSION, 'identity': identity}): return False
        execution = identity['execution']
        if not isinstance(execution, dict) or set(execution) != {'method', 'implementation', 'provider', 'model',
                'configuration', 'environment', 'provenance', 'complete', 'missing'}: return False
        if type(execution['complete']) is not bool: return False
        missing = []
        for key in ('method', 'implementation', 'provider', 'model'):
            if execution[key] is not None:
                _text(execution[key], 'execution.' + key)
                if execution[key] != execution[key].strip() or execution[key].casefold() in ('unknown', 'unverified'): return False
        if execution['method'] is not None and execution['method'] not in METHODS: return False
        for key in ('method', 'implementation'):
            if execution[key] is None: missing.append('execution.' + key)
        if execution['method'] in ('reviewer', 'investigation'):
            for key in ('provider', 'model'):
                if execution[key] is None: missing.append('execution.' + key)
        for key in ('configuration', 'environment', 'provenance'):
            value = execution[key]
            if value is not None and (not isinstance(value, str) or not _HEX.fullmatch(value)): return False
            if value is None or (key != 'configuration' and value == content_hash({})): missing.append('execution.' + key)
        if execution['missing'] != sorted(missing) or execution['complete'] != (not missing): return False
        return type(request['execution_complete']) is bool and request['execution_complete'] == execution['complete'] and request['missing'] == execution['missing']
    except (KeyError, TypeError, ValueError, RecursionError):
        return False


def applicability(previous, current):
    """Exact applicability only; no neutral-change inference or policy authority.

    A false reusable result forbids authenticated cache reuse. A true result
    still requires the caller's authentic receipt, current grant/budget and
    independence checks. This function never turns an observation into pass.
    """
    if not _valid(previous) or not _valid(current):
        return {'applicable': False, 'reusable': False, 'reasons': ['review request missing, malformed or inconsistent']}
    changed = [k for k in sorted(current['identity']) if previous['identity'][k] != current['identity'][k]]
    if changed:
        return {'applicable': False, 'reusable': False, 'reasons': ['review ' + k + ' changed' for k in changed]}
    missing = current['missing']
    return {'applicable': True, 'reusable': not missing,
            'reasons': ['review execution identity incomplete: ' + ', '.join(missing)] if missing else []}
