"""The v2 contract object and its immutable revisions: <state-root>/plans/<name>/v<N>.json.

The file holds only what the owner agrees to. It has no status field: approved/accepted/stopped exist only as ledger events
written by the commands in plan.py, so editing or forging a file cannot approve anything (the hash in the approval event
must match the file).
"""
import json
import re
from pathlib import Path

from ..ledger import LedgerError, canonical, content_hash, key_field, text_field
from ..snapshots import scoped_path

SCHEMA_VERSION = 2
FIELDS = {'schema_version', 'title', 'size', 'understanding', 'options', 'preconditions', 'output', 'scope', 'non_goals', 'items',
          'milestones', 'budget', 'attention', 'stop', 'profile_version', 'origin', 'decisions', 'presentation', 'authority', 'review_policy', 'solution_ref'}
MAX_DECISIONS = 10
MAX_NEUTRAL = 20
DECISION_ID = re.compile(r'D[1-9][0-9]?')
ORIGIN_SOURCE = 'origin'                   # items[].source: "origin" (the owner asked for it) or the id of a decision the author took
PRESENTATION_TEXTS, PRESENTATION_LISTS = ('request', 'not_doing', 'guard'), ('user_sees', 'acceptance_steps', 'risk')
SIZES = ('S', 'M', 'L')                    # S may omit options; M and L need the full step 0
CONFIDENCE = ('high', 'medium', 'low')
CLOSERS = ('doc', 'poc', 'owner')
CHECKS = ('repo_exists', 'ref_resolves', 'path_exists', 'command_ok', 'sdk_version')
MAX_OPTIONS, PRECONDITION_MAX_MINUTES = 5, 60
TIERS = ('must', 'should', 'wont')
MODES = ('once', 'until_pass')
VERIFIERS = ('command', 'owner-manual', 'reviewer')
MAX_CRITERIA, REVIEWER_MAX_MINUTES = 10, 30
MODEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,79}')
# Rough on purpose: a path separator, a source extension, or a word for a kind of change. It keeps "is the code good?" out of the contract.
NAMES_SOMETHING = re.compile(r'/|\\|\.(py|dart|js|ts|md|json|kt|java|txt)\b|\b(test|tests|assert|diff|file|files|line|lines|function|method|class|dòng|tệp)\b', re.I)
MAX_ITEMS, MAX_MILESTONES = 12, 5
MAX_REPAIRS_CAP = 5
# stop{}: the plan stops (stopped_with_report, one question) when a milestone fails max_stuck times in a row on the SAME artifact (the AI re-ran
# without changing anything), or when failed verdicts over all milestones of the revision pass max_repairs_total. Bounds, not defaults to widen.
STOP_DEFAULT = {'max_stuck': 3, 'max_repairs_total': 8}
STOP_RANGE = {'max_stuck': (2, 10), 'max_repairs_total': (1, 50)}
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
    from .verifiers import port
    available = VERIFIERS + port.names()
    if not isinstance(value, dict) or set(value) - {'type', 'config'} or value.get('type') not in available:
        raise LedgerError(name + ': verifier.type must be one of ' + ', '.join(available) + '.')
    config = value.get('config') or {}
    if value['type'] not in VERIFIERS:
        return {'type': value['type'], 'config': port.normalize(value['type'], config, name)}
    if value['type'] == 'command':
        if not isinstance(config, dict) or set(config) - {'argv', 'cwd', 'max_minutes'}:
            raise LedgerError(name + ': command verifier takes argv, cwd and max_minutes.')
        from ..work_contract import argv_value
        argv = argv_value(config.get('argv'), name + '.argv')
        cwd = config.get('cwd')
        if cwd is not None: text_field(cwd, name + '.cwd', 500)
        minutes = _int(config.get('max_minutes', 15), name + '.max_minutes', 1, COMMAND_MAX_MINUTES)
        return {'type': 'command', 'config': {'argv': argv, 'cwd': cwd, 'max_minutes': minutes}}
    if value['type'] == 'reviewer': return {'type': 'reviewer', 'config': _reviewer(config, name)}
    if config: raise LedgerError(name + ': owner-manual takes no config.')
    return {'type': 'owner-manual', 'config': {}}


def _reviewer(config, name):
    """One verifier per milestone (a command and a reviewer are two milestones): the schema stays one {type, config} pair. A criterion is a
    narrow question the reviewer can answer with file:line, so a question that names no file or kind of change is refused here, at propose."""
    if not isinstance(config, dict) or set(config) - {'provider', 'model', 'criteria', 'max_minutes'} or {'provider', 'model', 'criteria'} - set(config):
        raise LedgerError(name + ': reviewer verifier takes provider, model, criteria and max_minutes.')
    from .providers import PROVIDERS
    if config['provider'] not in PROVIDERS:
        raise LedgerError(f'{name}.provider: one of {", ".join(PROVIDERS)} (each takes a model).')
    model = config['model']
    if not isinstance(model, str) or not MODEL.fullmatch(model): raise LedgerError(name + '.model: expected a model id such as claude-haiku-5-5.')
    criteria = _list(config['criteria'], name + '.criteria', 1, MAX_CRITERIA, lambda c: _criterion(c, name))
    if len({c['id'] for c in criteria}) != len(criteria): raise LedgerError(name + '.criteria: duplicate id.')
    return {'provider': config['provider'], 'model': model, 'criteria': criteria,
            'max_minutes': _int(config.get('max_minutes', 10), name + '.max_minutes', 1, REVIEWER_MAX_MINUTES)}


FIELDS = FIELDS | {'advisor'}


def _advisor(value):
    """The advisor `plan advise` uses when no model is given on the command line: {provider, model}, the same providers and model ids as a reviewer."""
    from .providers import PROVIDERS
    if not isinstance(value, dict) or set(value) != {'provider', 'model'}: raise LedgerError('advisor: expected {"provider": ..., "model": ...}.')
    if value['provider'] not in PROVIDERS: raise LedgerError(f'advisor.provider: one of {", ".join(PROVIDERS)} (each takes a model).')
    if not isinstance(value['model'], str) or not MODEL.fullmatch(value['model']): raise LedgerError('advisor.model: expected a model id such as claude-haiku-5-5.')
    return {'provider': value['provider'], 'model': value['model']}


def _criterion(value, name):
    if not isinstance(value, dict) or set(value) != {'id', 'question'}: raise LedgerError(name + '.criteria: each takes id and question.')
    cid = _id(value['id'], name + '.criteria id')
    question = text_field(value['question'], f'{name}.criteria[{cid}].question', 500)
    if not NAMES_SOMETHING.search(question):
        raise LedgerError(f'{name}.criteria[{cid}].question: name a file (a path, .py, .dart) or a kind of change (test, assert, diff, line) so the answer can cite file:line.')
    return {'id': cid, 'question': question}


def validate(value):
    """The normalized contract (defaults filled), or LedgerError. Unknown fields are refused, so no status can be smuggled in."""
    if not isinstance(value, dict) or set(value) - FIELDS:
        raise LedgerError('Contract: unknown fields ' + ','.join(sorted(set(value) - FIELDS)) if isinstance(value, dict)
                          else 'Contract must be a JSON object.')
    if value.get('schema_version') != SCHEMA_VERSION: raise LedgerError('Contract schema_version must be 2.')
    scope = value.get('scope')
    if not isinstance(scope, dict) or 'owned' not in scope or set(scope) - {'owned', 'neutral'}:
        raise LedgerError('scope: expected {"owned": [...]} and optionally "neutral": [globs].')
    items = _list(value.get('items'), 'items', 1, MAX_ITEMS, lambda v: _item(v))
    if len({i['id'] for i in items}) != len(items): raise LedgerError('items: duplicate id.')
    if not any(i['tier'] == 'must' for i in items): raise LedgerError('items: at least one must item.')
    milestones = _list(value.get('milestones'), 'milestones', 1, MAX_MILESTONES, lambda v: _milestone(v))
    if len({m['id'] for m in milestones}) != len(milestones): raise LedgerError('milestones: duplicate id.')
    output = _list(value.get('output'), 'output', 1, 12, lambda v: text_field(v, 'output', 500))
    ids = output_ids(output)
    uncovered = [oid for oid in ids if not any(oid in m['covers'] for m in milestones)]
    if uncovered:   # contract echo: every output criterion must be verified by some milestone
        raise LedgerError('output: no milestone covers ' + ', '.join(uncovered) + ' (milestones[].covers lists output ids ' + ids[0] + '..' + ids[-1] + ').')
    stray = sorted({c for m in milestones for c in m['covers']} - set(ids))
    if stray: raise LedgerError('milestones: covers names unknown output ' + ', '.join(stray) + '.')
    size = value.get('size')
    if size not in SIZES: raise LedgerError('size: S, M or L (a small contract may omit options; M and L need the full step 0).')
    for i in items:
        if i['milestone'] is not None and i['milestone'] not in {m['id'] for m in milestones}:
            raise LedgerError(f"items: {i['id']} names an unknown milestone.")
    budget = value.get('budget')
    if not isinstance(budget, dict) or set(budget) != {'max_calls', 'time'}: raise LedgerError('budget: expected max_calls and time.')
    attention = value.get('attention', {'questions': 1})
    if not isinstance(attention, dict) or set(attention) != {'questions'}: raise LedgerError('attention: expected {"questions": N}.')
    stop = value.get('stop', {})
    if not isinstance(stop, dict) or set(stop) - set(STOP_DEFAULT): raise LedgerError('stop: expected {"max_stuck": N, "max_repairs_total": N}.')
    stop = {k: _int(stop.get(k, STOP_DEFAULT[k]), 'stop.' + k, *STOP_RANGE[k]) for k in STOP_DEFAULT}
    if value.get('profile_version') is not None: raise LedgerError('profile_version must stay null in L1.')
    optional = _provenance(value)       # origin, decisions, presentation: only the ones given, so a contract without them stays byte-identical
    if 'solution_ref' in value:
        from . import solution_link
        optional['solution_ref'] = solution_link.normalize(value['solution_ref'])
    if 'review_policy' in value:
        from . import review_policy
        optional['review_policy'] = review_policy.normalize(value['review_policy'])
    if value.get('authority') is not None:
        from . import authority
        optional['authority'] = authority.normalize(value['authority'])
    if value.get('advisor') is not None: optional['advisor'] = _advisor(value['advisor'])      # W43: the provider and model of the advisor, when the contract pins them
    return {**optional, 'schema_version': SCHEMA_VERSION, 'title': text_field(value.get('title'), 'title', 200),
            'size': size, 'understanding': _understanding(value.get('understanding'), size),
            'options': _options(value.get('options'), size),
            'preconditions': _list(value.get('preconditions'), 'preconditions', 1, 10, _precondition), 'output': output,
            'scope': {'owned': _list(scope['owned'], 'scope.owned', 1, 40, lambda v: text_field(v, 'scope.owned', 300)),
                      **({'neutral': _list(scope['neutral'], 'scope.neutral', 0, MAX_NEUTRAL, lambda v: text_field(v, 'scope.neutral', 300))}
                         if 'neutral' in scope else {})},
            'non_goals': _list(value.get('non_goals', []), 'non_goals', 0, 20, lambda v: text_field(v, 'non_goals', 300)),
            'items': items, 'milestones': milestones,
            'budget': {'max_calls': _int(budget['max_calls'], 'budget.max_calls', 1, 10000),
                       'time': _int(budget['time'], 'budget.time (minutes)', 1, 28800)},
            'attention': {'questions': _int(attention['questions'], 'attention.questions', 1, 3)}, 'stop': stop, 'profile_version': None}


def neutral_globs(contract):
    """The scope.neutral globs the contract itself declares: paths whose change does not count as a change of the artifact when a command verdict is
    carried over. There is no built-in list: a path the contract does not name is never neutral (code can sit under docs/, and Markdown can be read at
    run time), so a contract with no `neutral` has none."""
    scope = contract.get('scope') or {}
    return list(scope.get('neutral') or [])


def neutral_match(path, globs):
    """Is the repository path (posix, relative) matched by one of the globs? `*` and `?` stay inside one path part; `**` crosses parts (`docs/**` is
    everything under docs/, `**/*.md` is every .md at any depth, `*.md` only those at the top). Nothing else is special (no [classes])."""
    for glob in globs:
        out, i = [], 0
        while i < len(glob):
            if glob.startswith('**/', i): out.append('(?:.*/)?'); i += 3
            elif glob.startswith('**', i): out.append('.*'); i += 2
            elif glob[i] == '*': out.append('[^/]*'); i += 1
            elif glob[i] == '?': out.append('[^/]'); i += 1
            else: out.append(re.escape(glob[i])); i += 1
        if re.fullmatch(''.join(out), path): return True
    return False


def stop_limits(contract):
    """The stop limits of a stored contract (a revision written before the field existed has none: the defaults)."""
    return dict(STOP_DEFAULT, **(contract.get('stop') or {}))


def _item(v):
    if not isinstance(v, dict) or set(v) - {'id', 'title', 'tier', 'milestone', 'source'} or v.get('tier') not in TIERS:
        raise LedgerError('items: each item takes id, title, tier (must|should|wont), optional milestone and optional source.')
    milestone = v.get('milestone')
    item = {'id': _id(v.get('id'), 'item id'), 'title': text_field(v.get('title'), 'item title', 300), 'tier': v['tier'],
            'milestone': _id(milestone, 'item milestone') if milestone is not None else None}
    if 'source' in v: item['source'] = _source(v['source'], 'item ' + item['id'])
    return item


def _source(value, name):
    """Where an item comes from: the owner's own words ("origin") or a decision the author took (D1..). Whether that decision exists is
    checked at approve (step0: unknown_decision), not here, so a revision can be written before its decisions."""
    if value != ORIGIN_SOURCE and not (isinstance(value, str) and DECISION_ID.fullmatch(value)):
        raise LedgerError(f'{name}.source: "origin" or a decision id such as D1.')
    return value


def _provenance(value):
    """Optional origin {by, at, quote}, decisions [{id, choice, alternative, cost}] and presentation (the words of the two owner messages)."""
    out = {}
    if value.get('origin') is not None:
        origin = _keys(value['origin'], ('by', 'at', 'quote'), 'origin', ('by', 'at', 'quote'))
        out['origin'] = {'by': text_field(origin['by'], 'origin.by', 100), 'at': text_field(origin['at'], 'origin.at', 100),
                         'quote': text_field(origin['quote'], 'origin.quote', 500)}
    if value.get('decisions') is not None:
        out['decisions'] = _list(value['decisions'], 'decisions', 0, MAX_DECISIONS, _decision)
        if len({d['id'] for d in out['decisions']}) != len(out['decisions']): raise LedgerError('decisions: duplicate id.')
    if value.get('presentation') is not None:
        shown = _keys(value['presentation'], PRESENTATION_TEXTS + PRESENTATION_LISTS, 'presentation')
        out['presentation'] = {**{k: text_field(shown[k], 'presentation.' + k, 500) for k in PRESENTATION_TEXTS if k in shown},
                               **{k: _texts(shown[k], 'presentation.' + k, 10) for k in PRESENTATION_LISTS if k in shown}}
    return out


def _decision(value):
    value = _keys(value, ('id', 'choice', 'alternative', 'cost'), 'decision', ('id', 'choice', 'alternative', 'cost'))
    if not isinstance(value['id'], str) or not DECISION_ID.fullmatch(value['id']): raise LedgerError('decision.id: D1, D2, ...')
    return {'id': value['id'], **{k: text_field(value[k], 'decision.' + k, 300) for k in ('choice', 'alternative', 'cost')}}


def _milestone(v):
    if not isinstance(v, dict) or set(v) - {'id', 'title', 'verifier', 'mode', 'max_repairs', 'covers'}:
        raise LedgerError('milestones: each takes id, title, verifier, mode, max_repairs and covers.')
    mode = v.get('mode', 'once')
    if mode not in MODES: raise LedgerError('milestones: mode must be once or until_pass.')
    name = 'milestone ' + str(v.get('id'))
    return {'id': _id(v.get('id'), 'milestone id'), 'title': text_field(v.get('title'), 'milestone title', 300),
            'verifier': _verifier(v.get('verifier'), name), 'mode': mode,
            'max_repairs': _int(v.get('max_repairs', 1), name + '.max_repairs', 0, MAX_REPAIRS_CAP),
            'covers': _list(v.get('covers', []), name + '.covers', 0, 12, lambda c: _id(c, name + '.covers'))}


# ---- step 0: understanding, options, preconditions ----------------------------------------------------------------------

def output_ids(output):
    """Output criteria are identified by position: O1, O2, ... (so a criterion cannot be renamed away from its milestone)."""
    return ['O' + str(n) for n in range(1, len(output) + 1)]


def _texts(value, name, high):
    return _list(value, name, 0, high, lambda v: text_field(v, name, 500))


def _keys(value, allowed, name, required=None):
    if not isinstance(value, dict) or set(value) - set(allowed) or (required and set(required) - set(value)):
        raise LedgerError(f'{name}: expected an object with {", ".join(allowed)}.')
    return value


def _relative(value, name):
    if value in ('.', ''): return '.'
    if not isinstance(value, str): raise LedgerError(name + ': expected a relative path.')
    return scoped_path(value)


def _understanding(value, size):
    """The owner reads this, not the AI's prose: restated goal, the target to be checked mechanically, assumptions with their
    evidence, the confidence, and the unknowns. Anything the AI writes here is a claim until the ledger says otherwise
    (an unknown is closed only by an unknown.closed event, an assumption only counts with evidence)."""
    keys = ('restated_goal', 'target', 'assumptions', 'confidence', 'unknowns')
    value = _keys(value, keys + ('no_unknowns_because',), 'understanding', keys)
    if value['confidence'] not in CONFIDENCE: raise LedgerError('understanding.confidence: high, medium or low.')
    target = _keys(value['target'], ('repo', 'ref', 'paths'), 'understanding.target', ('repo', 'ref', 'paths'))
    ref = text_field(target['ref'], 'understanding.target.ref', 200)
    if ref.startswith('-'): raise LedgerError('understanding.target.ref: not a ref.')
    small = size == 'S'
    assumptions = _list(value['assumptions'], 'understanding.assumptions', 0 if small else 1, 3 if small else 10, _assumption)
    unknowns = _list(value['unknowns'], 'understanding.unknowns', 0, 10, _unknown)
    if len({u['id'] for u in unknowns}) != len(unknowns): raise LedgerError('understanding.unknowns: duplicate id.')
    out = {'restated_goal': text_field(value['restated_goal'], 'understanding.restated_goal', 600 if small else 3000),
           'target': {'repo': _relative(target['repo'], 'understanding.target.repo'), 'ref': ref,
                      'paths': _list(target['paths'], 'understanding.target.paths', 0, 20, scoped_path)},
           'assumptions': assumptions, 'confidence': value['confidence'], 'unknowns': unknowns}
    if 'no_unknowns_because' in value:       # step 0 asked for it when there are no unknowns (M/L); only written when given, so an older contract stays byte-identical
        out['no_unknowns_because'] = text_field(value['no_unknowns_because'], 'understanding.no_unknowns_because', 300)
    return out


def _assumption(value):
    value = _keys(value, ('text', 'evidence'), 'assumption', ('text',))
    evidence = value.get('evidence')
    return {'text': text_field(value['text'], 'assumption.text', 500),
            'evidence': text_field(evidence, 'assumption.evidence', 1000) if evidence else None}   # a missing one is refused at approve


def _unknown(value):
    value = _keys(value, ('id', 'question', 'status', 'closed_by', 'evidence', 'affected', 'required_by'), 'unknown', ('id', 'question', 'status'))
    status, closer, evidence = value['status'], value.get('closed_by'), value.get('evidence')
    if status not in ('open', 'closed'): raise LedgerError('unknown.status: open or closed.')
    if status == 'open' and (closer or evidence): raise LedgerError('unknown: an open unknown has no closed_by or evidence.')
    if status == 'closed' and (closer not in CLOSERS or not evidence):
        raise LedgerError('unknown: a closed unknown needs closed_by (doc|poc|owner) and evidence.')
    out = {'id': _id(value['id'], 'unknown id'), 'question': text_field(value['question'], 'unknown.question', 500), 'status': status,
           'closed_by': closer, 'evidence': text_field(evidence, 'unknown.evidence', 1000) if evidence else None}
    out.update(_unknown_scope(value, out['id']))
    return out


UNKNOWN_REQUIRED_BY = ('option_choice', 'estimate', 'approval')


def _unknown_scope(value, uid):
    """Both scope fields or neither; legacy unknowns stay byte-identical."""
    if 'affected' not in value and 'required_by' not in value: return {}
    if 'affected' not in value or 'required_by' not in value:
        raise LedgerError(f'unknown {uid}: give both affected and required_by, or neither.')
    required = value['required_by']
    if not (isinstance(required, str) and (required in UNKNOWN_REQUIRED_BY or re.fullmatch(r'milestone:[A-Za-z][A-Za-z0-9_-]{0,31}', required))):
        raise LedgerError(f'unknown {uid}.required_by: one of {", ".join(UNKNOWN_REQUIRED_BY)} or milestone:<id>.')
    return {'affected': _list(value['affected'], f'unknown {uid}.affected', 1, 10, lambda v: _id(v, f'unknown {uid}.affected')), 'required_by': required}


def _options(value, size):
    """Brainstorm result: >=2 options, exactly one recommended with a reason. There is deliberately no `chosen`: the owner's
    choice exists only in the plan.approved event (plan approve --choose), so the AI cannot make it."""
    if value is None:
        if size != 'S': raise LedgerError('options: size M and L need at least two options (only size S may omit them).')
        return None
    value = _keys(value, ('recommended', 'reason', 'items'), 'options', ('recommended', 'reason', 'items'))
    items = _list(value['items'], 'options.items', 2, MAX_OPTIONS, _option)
    if len({o['id'] for o in items}) != len(items): raise LedgerError('options: duplicate id.')
    if value['recommended'] not in {o['id'] for o in items}: raise LedgerError('options.recommended must name exactly one option id.')
    return {'recommended': value['recommended'], 'reason': text_field(value['reason'], 'options.reason', 500), 'items': items}


def _option(value):
    names = ('id', 'summary', 'evidence', 'strengths', 'weaknesses', 'unknowns', 'cost', 'risk')
    value = _keys(value, names, 'option', names)
    return {'id': _id(value['id'], 'option id'), 'summary': text_field(value['summary'], 'option.summary', 300),
            'evidence': _texts(value['evidence'], 'option.evidence', 5), 'strengths': _texts(value['strengths'], 'option.strengths', 5),
            'weaknesses': _texts(value['weaknesses'], 'option.weaknesses', 5), 'unknowns': _texts(value['unknowns'], 'option.unknowns', 5),
            'cost': text_field(value['cost'], 'option.cost', 200), 'risk': text_field(value['risk'], 'option.risk', 200)}


def _minutes(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= PRECONDITION_MAX_MINUTES:
        raise LedgerError(f'{name}: minutes in (0, {PRECONDITION_MAX_MINUTES}].')
    return value


def _precondition(value):
    """A cheap check of the starting point, run once at approve with no AI call: right repo, right layout, a base that builds."""
    value = _keys(value, ('id', 'check', 'args', 'why'), 'precondition', ('id', 'check', 'args', 'why'))
    check, args = value['check'], value['args']
    if check not in CHECKS: raise LedgerError('precondition.check: one of ' + ', '.join(CHECKS) + '.')
    name = 'precondition ' + str(value.get('id'))
    if check in ('repo_exists', 'path_exists'):
        args = {'path': _relative(_keys(args, ('path',), name + '.args', ('path',))['path'], name + '.path')}
    elif check == 'ref_resolves':
        args = _keys(args, ('repo', 'ref'), name + '.args', ('ref',))
        ref = text_field(args['ref'], name + '.ref', 200)
        if ref.startswith('-'): raise LedgerError(name + '.ref: not a ref.')
        args = {'repo': _relative(args.get('repo', '.'), name + '.repo'), 'ref': ref}
    else:
        args = _keys(args, ('argv', 'cwd', 'max_minutes', 'pattern'), name + '.args', ('argv',) if check == 'command_ok' else ('argv', 'pattern'))
        from ..work_contract import argv_value
        if check == 'command_ok' and 'pattern' in args: raise LedgerError(name + ': command_ok takes no pattern.')
        clean = {'argv': argv_value(args['argv'], name + '.argv'), 'cwd': _relative(args.get('cwd', '.'), name + '.cwd'),
                 'max_minutes': _minutes(args.get('max_minutes', 5), name + '.max_minutes')}
        if check == 'sdk_version':
            try:
                re.compile(text_field(args['pattern'], name + '.pattern', 200))
            except re.error as error:
                raise LedgerError(name + '.pattern is not a regular expression: ' + str(error)) from error
            clean['pattern'] = args['pattern']
        args = clean
    return {'id': _id(value['id'], 'precondition id'), 'check': check, 'args': args, 'why': text_field(value['why'], name + '.why', 300)}


# ---- immutable revisions on disk -------------------------------------------------------------------------------------

def plan_dir(ledger, name):
    from . import namespaces
    return namespaces.plan_dir(ledger, name)


def revision_path(ledger, name, revision):
    return plan_dir(ledger, name) / f'v{revision}.json'


def require_unknown_scope(contract, previous=None):
    """W31a: an open unknown of a new (plan-ns) root is recorded WITH what it affects and what waits for it, at the moment it is proposed.
    Only writes of new revisions check this; reading an old revision (read_revision) never does, so old ledgers still load. An open unknown
    that the previous revision already carried unchanged (a root proposed before this rule) is left as it was."""
    before = {u.get('id'): u for u in ((previous or {}).get('understanding') or {}).get('unknowns') or []}
    for unknown in (contract.get('understanding') or {}).get('unknowns') or []:
        if before.get(unknown.get('id')) == unknown: continue
        if unknown.get('status') == 'open' and not (unknown.get('affected') and unknown.get('required_by')):
            raise LedgerError(f'unknown {unknown.get("id")}: an open unknown is proposed with affected (what its answer changes) and required_by '
                              f'({", ".join(UNKNOWN_REQUIRED_BY)} or milestone:<id>).')


def write_revision(ledger, name, revision, contract):
    """Write-once: an existing revision is never replaced. A revision of a plan-ns root must scope its open unknowns (require_unknown_scope)."""
    from . import namespaces
    if str(name).startswith(namespaces.NAMESPACED):
        previous = read_revision(ledger, name, revision - 1)[0] if revision > 1 and revision_path(ledger, name, revision - 1).exists() else None
        require_unknown_scope(contract, previous)
    path = revision_path(ledger, name, revision)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {'plan': namespaces.parse(name)[0], 'revision': revision, 'content_sha': content_hash(contract), 'contract': contract}
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
