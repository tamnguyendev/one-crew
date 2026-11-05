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
from . import verification_evidence as evidence

VERSION = 1
CHECK_VERSION = 2      # 2.5-A cycle 2: build_check descriptors; v1 (build) descriptors stay valid and stable
KINDS = ('node', 'milestone')
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


_V1_KEYS = {'root', 'contract_revision', 'contract_sha', 'review_id', 'required',
            'facts', 'scope', 'criteria', 'policy', 'authority', 'budget', 'execution'}
_V2_KEYS = _V1_KEYS | {'kind', 'target', 'evidence'}
_EVIDENCE_KEYS = {'candidate', 'revision', 'acceptance', 'inputs', 'configuration', 'environment', 'checks'}


def _valid_evidence(value):
    if not isinstance(value, dict) or set(value) != _EVIDENCE_KEYS: return False
    try: evidence._identity(value['candidate'])
    except LedgerError: return False
    if type(value['revision']) is not int or value['revision'] < 1: return False
    return all(isinstance(value[k], str) and _HEX.fullmatch(value[k]) for k in _EVIDENCE_KEYS - {'candidate', 'revision'})


def _valid_target(identity):
    target = identity['target']
    ids = target.get('criteria_ids') if isinstance(target, dict) else None
    if not isinstance(ids, list) or not ids or any(not isinstance(i, str) or not i for i in ids) or ids != sorted(set(ids)): return False
    refs = {k: v for k, v in target.items() if k != 'criteria_ids'}
    if identity['kind'] == 'milestone':
        if set(refs) != {'plan', 'milestone', 'plan_sha'} or any(not isinstance(v, str) or not v for v in refs.values()): return False
        return identity['facts'] == content_hash(refs)
    return (set(refs) == {'node', 'generation', 'internal_revision'} and isinstance(refs['node'], str) and bool(refs['node'])
            and type(refs['generation']) is int and type(refs['internal_revision']) is int)


def kind_of(request):
    """'node' | 'milestone' for a valid descriptor (a v1 `build` descriptor is a node descriptor); None when invalid."""
    if not _valid(request): return None
    return 'node' if request['version'] == VERSION else request['identity']['kind']


def _valid(request):
    try:
        if not isinstance(request, dict) or set(request) != {'version', 'id', 'identity', 'execution_complete', 'missing'}:
            return False
        if type(request['version']) is not int or request['version'] not in (VERSION, CHECK_VERSION): return False
        version = request['version']
        identity = request['identity']
        if not isinstance(identity, dict) or set(identity) != (_V1_KEYS if version == VERSION else _V2_KEYS): return False
        _json(request, 'descriptor')
        if version == CHECK_VERSION and (identity['kind'] not in KINDS or not _valid_evidence(identity['evidence'])
                                         or not _valid_target(identity)): return False
        root = identity['root']
        if not isinstance(root, dict) or set(root) != {'project_id', 'task_id'}: return False
        for key in root: _text(root[key], key)
        _positive(identity['contract_revision'], 'contract revision'); _text(identity['review_id'], 'review ID')
        if type(identity['required']) is not bool: return False
        for key in ('contract_sha', 'facts', 'scope', 'criteria', 'policy', 'authority', 'budget'):
            if not isinstance(identity[key], str) or not _HEX.fullmatch(identity[key]): return False
        if request['id'] != 'review-' + content_hash({'version': version, 'identity': identity}): return False
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
    except (KeyError, TypeError, ValueError, RecursionError, AttributeError):
        return False


def _changed(previous, current):
    """Changed identity dimensions of two valid descriptors of one version. `evidence` is split per dimension; `target` is a readable
    echo of facts (compared only for its criteria_ids)."""
    out = []
    for key in sorted(current['identity']):
        if key == 'target':
            if previous['identity'][key]['criteria_ids'] != current['identity'][key]['criteria_ids']: out.append('target.criteria_ids')
            continue
        if key == 'evidence':
            out += ['evidence.' + k for k in sorted(current['identity'][key]) if previous['identity'][key][k] != current['identity'][key][k]]
        elif previous['identity'][key] != current['identity'][key]: out.append(key)
    return out


def applicability(previous, current):
    """Exact applicability only; no neutral-change inference or policy authority.

    A false reusable result forbids authenticated cache reuse. A true result
    still requires the caller's authentic receipt, current grant/budget and
    independence checks. This function never turns an observation into pass.
    """
    if not _valid(previous) or not _valid(current):
        return {'applicable': False, 'reusable': False, 'reasons': ['review request missing, malformed or inconsistent']}
    if previous['version'] != current['version']:
        return {'applicable': False, 'reusable': False, 'reasons': ['review request identity version changed']}
    changed = _changed(previous, current)
    if changed:
        return {'applicable': False, 'reusable': False, 'reasons': ['review ' + k + ' changed' for k in changed]}
    missing = current['missing']
    return {'applicable': True, 'reusable': not missing,
            'reasons': ['review execution identity incomplete: ' + ', '.join(missing)] if missing else []}


# ---- 2.5-A cycle 2: one identity for node and milestone checks, and evidence validity ------------------------------------------------

def _criteria_ids(criteria):
    if (not isinstance(criteria, list) or not criteria
            or any(not isinstance(c, dict) or not isinstance(c.get('id'), str) or not c['id'] for c in criteria)):
        raise LedgerError('Review criteria need explicit check IDs.')
    criteria = _json(criteria, 'criteria')
    ids = [c['id'] for c in criteria]
    if len(set(ids)) != len(ids): raise LedgerError('Review criterion IDs must be unique.')
    return criteria, ids


def _evidence_dims(binding):
    """Fingerprint-only evidence dimensions of a verification_evidence binding (never the observed/raw environment)."""
    return {'candidate': binding['artifact'], 'revision': binding['revision'], 'acceptance': binding['acceptance'],
            'inputs': content_hash(binding['inputs']), 'configuration': binding['configuration'],
            'environment': binding['environment'], 'checks': content_hash(list(binding['checks']))}


def _bound(inputs, *, candidate, contract_revision, ids):
    if not isinstance(inputs, dict) or not inputs:
        raise LedgerError('Review check needs explicit evidence inputs (artifact/revision, acceptance, inputs, configuration, environment, checks).')
    value = inputs if 'version' in inputs else evidence.bind(**inputs)   # raw values are hashed by bind, never stored
    if not evidence._valid(value):
        raise LedgerError('Review check evidence binding is malformed.')
    if value['artifact'] != candidate:
        raise LedgerError('Review check evidence binds a different candidate than the request subject.')
    if value['revision'] != contract_revision:
        raise LedgerError('Review check evidence binds a different contract revision than the request.')
    if sorted(value['checks']) != sorted(ids):
        raise LedgerError('Review check evidence names different checks than the request criteria.')
    return value


def evidence_facts(subject):
    """The validity-relevant fingerprint of a node's engine facts, as a v2 node descriptor records it."""
    return content_hash({'node': subject['node'], 'contract_sha': subject['contract_sha'], 'inputs': subject['inputs'],
                         'checks_sha': subject['checks_sha'], 'unknowns': _names(subject['unknowns'], 'unknowns')})


def build_check(*, kind, root, contract_revision, contract_sha, subject, required, criteria, scope, policy, authority, budget, inputs,
                execution=None, review_id=None):
    """One identity for a node or a milestone check, bound to criteria, candidate/revision, scope, every evidence-validity factor and
    the execution actually used. Pure: no ledger write, no authority, no verdict.

    kind='node': `subject` is review_dispatch._context's facts. With `inputs=None` the result IS `build(...)` (v1: same id, so stored
    descriptors and their consumers are unchanged; `review_id` defaults to 'node-check:<node>'). With `inputs` (a verification_evidence
    binding, or its raw arguments which are hashed) the descriptor is v2: it also carries the evidence dimensions and its `facts`
    are the validity-relevant subset of the engine facts (see below), so unrelated workflow churn is not a change of evidence.
    kind='milestone': `subject` = {plan, milestone, candidate, plan_sha}; `inputs` is required; review_id defaults to the milestone id.
    The candidate lives in `evidence.candidate` only, so a candidate change is a separate, nameable dimension."""
    if kind not in KINDS: raise LedgerError('Unknown review request kind.')
    subject = _mapping(subject, 'subject')
    if kind == 'node':
        base = build(root=root, contract_revision=contract_revision, contract_sha=contract_sha,
                     review_id=review_id or 'node-check:' + str(subject.get('node')), required=required, facts=subject,
                     scope=scope, criteria=criteria, policy=policy, authority=authority, budget=budget, execution=execution)
        if inputs is None: return base
        identity = dict(base['identity'])
        # v2: `facts` is what the evidence validity depends on (node, contract, dependency inputs, checks, unknowns). Workflow state
        # (state/phase/finding blockers/internal revision) gates work but does not change what a check proves, and the candidate and
        # generation live in evidence.candidate / target: a repair elsewhere must not make an untouched node's evidence 'changed'.
        identity['facts'] = evidence_facts(subject)
        ids = sorted(c['id'] for c in criteria)
        binding = _bound(inputs, candidate=subject['artifact'], contract_revision=contract_revision, ids=ids)
        target = {'node': subject['node'], 'generation': subject['generation'], 'internal_revision': subject['internal_revision']}
    else:
        root = _mapping(root, 'root')
        if set(root) != {'project_id', 'task_id'}: raise LedgerError('Review root requires exactly project_id and task_id.')
        for key in root: _text(root[key], key)
        _positive(contract_revision, 'contract revision')
        if not isinstance(contract_sha, str) or not _HEX.fullmatch(contract_sha):
            raise LedgerError('Review contract SHA must be a SHA256 identity.')
        if type(required) is not bool: raise LedgerError('Review required flag must be boolean.')
        if set(subject) != {'plan', 'milestone', 'candidate', 'plan_sha'}:
            raise LedgerError('Milestone subject requires plan, milestone, candidate and plan_sha.')
        for key in ('plan', 'milestone'): _text(subject[key], key)
        evidence._identity(subject['candidate'])
        if not isinstance(subject['plan_sha'], str) or not _HEX.fullmatch(subject['plan_sha']):
            raise LedgerError('Milestone plan_sha must be a SHA256 identity.')
        criteria, ids = _criteria_ids(criteria)
        ids = sorted(ids)
        scope = {k: _names(v, 'scope.' + k) if isinstance(v, list) else v for k, v in _mapping(scope, 'scope').items()}
        policy = _mapping(policy, 'policy'); authority = _mapping(authority, 'authority', empty=True)
        budget = _mapping(budget, 'original budget')
        if _VOLATILE_BUDGET & set(budget):
            raise LedgerError('Review request budget must be original approved limits, not remaining usage.')
        binding = _bound(inputs, candidate=subject['candidate'], contract_revision=contract_revision, ids=ids)
        target = {'plan': subject['plan'], 'milestone': subject['milestone'], 'plan_sha': subject['plan_sha']}
        identity = {'root': root, 'contract_revision': contract_revision, 'contract_sha': contract_sha,
                    'review_id': _text(review_id or subject['milestone'], 'review ID'), 'required': required,
                    'facts': content_hash(target), 'scope': content_hash(scope), 'criteria': content_hash(criteria),
                    'policy': content_hash(policy), 'authority': content_hash(authority), 'budget': content_hash(budget),
                    'execution': _execution(execution)}
    identity.update(kind=kind, target=dict(target, criteria_ids=ids), evidence=_evidence_dims(binding))
    return {'version': CHECK_VERSION, 'id': 'review-' + content_hash({'version': CHECK_VERSION, 'identity': identity}),
            'identity': identity, 'execution_complete': identity['execution']['complete'],
            'missing': list(identity['execution']['missing'])}


def _status(status, reasons, changed=(), **extra):
    return dict({'status': status, 'reasons': list(reasons), 'changed': list(changed), 'reusable': status == 'applies'}, **extra)


_INSUFFICIENT_MARKS = ('without a recorded valid reuse basis', 'path-only', 'lacks evidence', 'not available', 'binding missing')


def evidence_status(previous, current, *, binding_previous=None, binding_current=None, changed_paths=None, basis=None):
    """Does the evidence of `previous` still apply to `current`? Pure, conservative.

    'applies'      identity equal and execution complete on both sides, or only the candidate changed and verification_evidence.assess
                   proves the change neutral from an explicit basis (both bindings given and bound to their descriptors). Only this
                   status lets a caller reuse a result, and only with its own authentic receipt, grant and budget checks.
    'recheck'      a known validity dimension changed (criteria, policy, scope, execution, candidate, environment, ...): `changed` names it.
    'insufficient' a descriptor or binding is missing/malformed/legacy-vs-v2, execution metadata is incomplete, or the impact of a
                   candidate change cannot be established: the caller must widen the check, never reuse.
    `basis` = {'neutral': [globs from the approved contract], 'kind': verifier kind ('command' default), 'submodule_changed': bool,
    'assertion': assess' own basis dict}; it is evidence for assess, never an assertion that is trusted by itself."""
    if not _valid(previous) or not _valid(current):
        return _status('insufficient', ['review request missing, malformed or inconsistent'])
    if previous['version'] != current['version']:
        return _status('insufficient', ['legacy (v1) and check (v2) descriptors cannot be compared; widen the check'])
    changed = _changed(previous, current)
    missing = sorted(set(previous['missing']) | set(current['missing']))
    if changed:
        only_candidate = changed == ['evidence.candidate'] and previous['version'] == CHECK_VERSION
        if not only_candidate:
            return _status('recheck', ['review ' + k + ' changed' for k in changed] +
                           (['execution identity incomplete: ' + ', '.join(missing)] if missing else []), changed)
    if missing:
        return _status('insufficient', ['execution identity incomplete: ' + ', '.join(missing)], changed)
    if not changed:
        return _status('applies', [], changed)
    # only the candidate changed (v2): neutral only with an explicit basis proven by verification_evidence.assess
    if not (evidence._valid(binding_previous) and evidence._valid(binding_current)):
        return _status('insufficient', ['candidate changed without evidence bindings; impact unknown'], changed)
    if (_evidence_dims(binding_previous) != previous['identity']['evidence'] or _evidence_dims(binding_current) != current['identity']['evidence']):
        return _status('insufficient', ['evidence binding does not belong to the request'], changed)
    basis = basis if isinstance(basis, dict) else {}
    result = evidence.assess(binding_previous, binding_current, neutral=basis.get('neutral') or (), changed_paths=changed_paths,
                             submodule_changed=bool(basis.get('submodule_changed')), kind=basis.get('kind', 'command'),
                             basis=basis.get('assertion'))
    if result['status'] in ('current', 'reuse_eligible') and result['reusable']:
        return _status('applies', ['candidate changed only inside declared neutral scope'], changed,
                       reuse_basis=result['reuse_basis'], requires_record=result['requires_record'])
    text = '; '.join(result['reasons'])
    return _status('insufficient' if any(m in text for m in _INSUFFICIENT_MARKS) or not result['reasons'] else 'recheck',
                   ['candidate changed: ' + text], changed, checks_to_rerun=result['checks_to_rerun'])
