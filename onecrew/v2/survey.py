"""W31a - a step-0 survey / PoC with a cap, an end condition and a read-only scope. No model is called here.

An unknown that blocks the choice of an option is not argued about: a survey is opened for it. The survey is bounded:

  * a CAP - minutes of time and a number of calls (the budget); the survey stops AT the cap, never past it;
  * an END CONDITION - what counts as an answer, written when the survey is opened;
  * a READ-ONLY SCOPE - the paths it may read; every write, and every read outside the paths, is refused and recorded.

The unknown carries `affected` (what its answer changes) and `required_by` (what waits for it) from the moment it is proposed.

A survey ends in exactly one of two ways, and never in neither:
  answered - an answer WITH evidence that resolves (a hypothesis refuted is still a success); the unknown it was opened for is closed,
             by `poc`, with that evidence;
  blocked  - a blocker WITH evidence (the cap was reached, the scope was violated, nothing was found, the worker failed); the unknown stays
             open and the run log is the evidence.

The worker is passed in (`run(..., worker)`); survey_worker supplies the provider-pinned read-only CLI consumer. Tests use explicit providers
without certifying a real provider's behavior. The
cap and the scope are enforced on every operation of the context given to the worker; a worker that never uses the context cannot be
interrupted here, so its result is checked after the fact (an answer that arrives past the cap is discarded; a change made to the project
behind the context is detected and blocks the survey). Containing a real process is the executor's job (OS containment, a later release).

Events (class A on the plan anchor, compat.py): survey.opened, survey.finished, survey.denied.
"""
import hashlib
import json
import os
import time
from pathlib import Path

from ..ledger import LedgerError, canonical, key_field, text_field
from ..snapshots import Snapshots, scoped_path

OPENED, FINISHED, DENIED = 'survey.opened', 'survey.finished', 'survey.denied'
MAX_MINUTES, MAX_CALLS = 120, 50
DEFAULT_SPEC = {'cap': {'minutes': 10, 'calls': 5}, 'end_condition': 'an answer that cites a file:line, a URL or a stored blob as evidence, or the cap (then a blocker)',
                'scope': {'mode': 'read_only', 'paths': ['.']}}
REQUIRED_BY = ('option_choice', 'estimate', 'approval')
HYPOTHESIS = ('refuted', 'confirmed', 'unknown')
MAX_FILES, MAX_FILE_BYTES = 5000, 1 << 20            # the project tree is compared before/after a survey (a change behind the context is detected)


class SurveyDenied(LedgerError):
    """The survey tried something its scope does not allow (a write, or a read outside its paths)."""


class CapReached(LedgerError):
    """The survey reached its time or call cap: nothing more may run."""


class InvestigationCapReached(LedgerError):
    """2.4-C: the step-0 investigation declared on the proposal has no room left for this survey (the stop point)."""


# ---- the spec -----------------------------------------------------------------------------------------------------------------

def _int(value, name, low, high):
    if type(value) is not int or not low <= value <= high: raise LedgerError(f'survey {name}: expected an integer {low}-{high}.')
    return value


def validate_spec(spec):
    """The bounded form of a survey: cap {minutes, calls}, end_condition, scope {mode: read_only, paths}; an optional hypothesis."""
    if not isinstance(spec, dict) or set(spec) - {'hypothesis', 'cap', 'end_condition', 'scope', 'question'}:
        raise LedgerError('survey: expected cap, end_condition, scope (and optionally hypothesis, question).')
    cap = spec.get('cap')
    if not isinstance(cap, dict) or set(cap) != {'minutes', 'calls'}:
        raise LedgerError(f'survey cap: a survey without a cap does not end - give {{"minutes": 1-{MAX_MINUTES}, "calls": 1-{MAX_CALLS}}}.')
    scope = spec.get('scope')
    if not isinstance(scope, dict) or set(scope) != {'mode', 'paths'} or scope['mode'] != 'read_only':
        raise LedgerError('survey scope: a survey is read-only - give {"mode": "read_only", "paths": [...]}.')
    paths = scope['paths']
    if not isinstance(paths, list) or not 1 <= len(paths) <= 20: raise LedgerError('survey scope.paths: 1-20 relative paths.')
    out = {'cap': {'minutes': _int(cap['minutes'], 'cap.minutes', 1, MAX_MINUTES), 'calls': _int(cap['calls'], 'cap.calls', 1, MAX_CALLS)},
           'end_condition': text_field(spec.get('end_condition'), 'survey end_condition', 500),
           'scope': {'mode': 'read_only', 'paths': [p if p == '.' else scoped_path(p) for p in paths]}}
    if spec.get('hypothesis') is not None: out['hypothesis'] = text_field(spec['hypothesis'], 'survey hypothesis', 500)
    if spec.get('question') is not None: out['question'] = text_field(spec['question'], 'survey question', 500)
    return out


def _scoped_unknown(unknown):
    missing = [f for f in ('affected', 'required_by') if not unknown.get(f)]
    if missing:
        raise LedgerError(f'unknown {unknown.get("id")} has no {" and ".join(missing)}: an unknown is written with what it affects and what waits for it '
                          f'(required_by: {", ".join(REQUIRED_BY)} or milestone:<id>) before a survey is opened for it.')
    from .contract import _unknown_scope
    _unknown_scope(unknown, unknown['id'])
    return unknown


# ---- the ledger view ------------------------------------------------------------------------------------------------------------

def states(conn, task_id):
    """survey id -> {'opened': payload, 'finished': payload | None}, in the order they were opened."""
    out = {}
    for row in conn.execute('SELECT kind,payload FROM events WHERE task_id=? AND kind IN (?,?) ORDER BY seq', (task_id, OPENED, FINISHED)):
        payload = json.loads(row['payload'])
        if row['kind'] == OPENED: out[payload['survey']] = {'opened': payload, 'finished': None}
        elif payload['survey'] in out: out[payload['survey']]['finished'] = payload
    return out


def investigation_of(conn, task_id):
    """2.4-C: the investigation (cap, explicit paths, stop_when) declared by the latest proposal check of the plan that states one, or None."""
    found = None
    for row in conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='proposal.checked' ORDER BY seq", (task_id,)):
        declared = (json.loads(row['payload']).get('card_fields') or {}).get('investigation')
        if declared: found = declared
    return found


def totals(items):
    """What the plan's step-0 surveys reserved (sum of opened caps) and spent (sum of finished `spent`). The sum runs over the whole plan,
    not one revision: an answered survey closes its unknown by an amendment, which moves the revision."""
    opened = {'minutes': 0, 'calls': 0}
    spent = {'seconds': 0, 'calls': 0}
    for item in items.values():
        opened['minutes'] += item['opened']['cap']['minutes']; opened['calls'] += item['opened']['cap']['calls']
        if item['finished']:
            spent['seconds'] += (item['finished'].get('spent') or {}).get('seconds', 0) or 0
            spent['calls'] += (item['finished'].get('spent') or {}).get('calls', 0) or 0
    return opened, spent


def _within(path, roots):
    return any(path == root or path.startswith(root.rstrip('/') + '/') for root in roots)


def _next_id(known, unknown_id):
    base, n = f'S-{unknown_id}', 1
    while (base if n == 1 else f'{base}-{n}') in known: n += 1
    return base if n == 1 else f'{base}-{n}'


def open_in(ledger, conn, state, unknown, spec=None, investigation=None):
    """Write `survey.opened` for `unknown` (a dict with id, question, affected, required_by) inside the caller's write transaction. A survey for the same
    unknown that is still open is returned instead of opening a second one. Returns the opened payload.
    2.4-C: under a declared step-0 investigation (`investigation`, else the one of the plan's latest proposal check) the survey reads only
    the investigation's explicit paths, ends by its stop_when, and is refused (InvestigationCapReached, nothing written) when the caps
    already opened on the plan leave no room for it: the investigation stops there."""
    from . import plan as plans
    _scoped_unknown(unknown)
    existing = states(conn, state['task_id'])
    for sid, item in existing.items():
        if item['opened']['unknown'] == unknown['id'] and item['opened']['revision'] == state['latest'] and item['finished'] is None: return item['opened']
    investigation = investigation or investigation_of(conn, state['task_id'])
    if investigation:
        opened, _ = totals(existing)
        room = {'minutes': investigation['cap']['minutes'] - opened['minutes'], 'calls': investigation['cap']['calls'] - opened['calls']}
        if room['minutes'] < 1 or room['calls'] < 1:
            raise InvestigationCapReached(f'the step-0 investigation cap {investigation["cap"]} is used up by the surveys already opened ({opened}): '
                                          f'no survey for {unknown["id"]}; it stays open and what waits for it stays held.')
        base = {'cap': {'minutes': min(DEFAULT_SPEC['cap']['minutes'], room['minutes']), 'calls': min(DEFAULT_SPEC['cap']['calls'], room['calls'])},
                'end_condition': investigation['stop_when'], 'scope': {'mode': 'read_only', 'paths': list(investigation['paths'])}}
        spec = validate_spec(dict(base, **(spec or {})))
        if spec['cap']['minutes'] > room['minutes'] or spec['cap']['calls'] > room['calls']:
            raise InvestigationCapReached(f'survey cap {spec["cap"]} exceeds what the step-0 investigation has left ({room}).')
        if any(p == '.' or not _within(p, investigation['paths']) for p in spec['scope']['paths']):
            raise LedgerError('survey scope.paths must stay inside the investigation paths ' + ', '.join(investigation['paths']) + '.')
    else:
        spec = validate_spec(dict(DEFAULT_SPEC, **(spec or {})))
    payload = {'plan': state['name'], 'revision': state['latest'], 'survey': _next_id(existing, unknown['id']), 'unknown': unknown['id'],
               'question': spec.get('question') or unknown['question'], 'affected': list(unknown['affected']), 'required_by': unknown['required_by'],
               'hypothesis': spec.get('hypothesis'), 'cap': spec['cap'], 'end_condition': spec['end_condition'], 'scope': spec['scope']}
    plans.emit(ledger, conn, state['task_id'], OPENED, payload)
    return payload


def open_survey(ledger, name, unknown_id, spec):
    """Open a bounded survey for an open unknown of the plan's latest revision. The unknown must carry affected and required_by."""
    from . import plan as plans
    key_field(unknown_id)
    if not isinstance(spec, dict): raise LedgerError('survey: expected an object.')
    spec = validate_spec(spec)                                    # refused before anything is written
    with ledger.transaction(write=True) as conn:
        state = plans.anchor_events(ledger, conn, name)
        contract, _ = plans.load(ledger, state)
        unknown = next((u for u in contract['understanding']['unknowns'] if u['id'] == unknown_id), None)
        if unknown is None: raise LedgerError(f'Plan {name} has no unknown {unknown_id}.')
        if unknown['status'] != 'open': raise LedgerError(f'Unknown {unknown_id} is already closed.')
        payload = open_in(ledger, conn, state, unknown, spec)
    return payload | {'id': payload['survey']}


def show(ledger, name):
    from . import plan as plans
    with ledger.transaction() as conn:
        state = plans.anchor_events(ledger, conn, name)
        items = states(conn, state['task_id'])
    rows = [{'id': sid, 'unknown': i['opened']['unknown'], 'state': 'open' if i['finished'] is None else i['finished']['status'],
             'cap': i['opened']['cap'], 'scope': i['opened']['scope'], 'end_condition': i['opened']['end_condition'],
             'blocker': (i['finished'] or {}).get('blocker'), 'evidence': (i['finished'] or {}).get('evidence'),
             'answer': (i['finished'] or {}).get('answer'), 'spent': (i['finished'] or {}).get('spent')} for sid, i in items.items()]
    return {'plan': name, 'surveys': rows}


# ---- running ---------------------------------------------------------------------------------------------------------------------

def _tree(root):
    out, root = {}, Path(root)
    for base, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d != '.git')
        links = [d for d in dirs if (Path(base) / d).is_symlink() or getattr(Path(base) / d, 'is_junction', lambda: False)()]
        dirs[:] = [d for d in dirs if d not in links]
        for name in sorted(names + links):
            path = Path(base) / name
            try:
                digest = hashlib.sha256()
                if path.is_symlink() or name in links:
                    digest.update(('link:' + os.readlink(path)).encode('utf-8', 'surrogatepass'))
                else:
                    with path.open('rb') as stream:
                        for chunk in iter(lambda: stream.read(MAX_FILE_BYTES), b''):
                            digest.update(chunk)
                out[path.relative_to(root).as_posix()] = digest.hexdigest()
            except OSError as error:
                raise SurveyDenied(f'cannot verify the read-only project boundary at {path.name}: {error}') from error
            if len(out) > MAX_FILES:
                raise SurveyDenied(f'cannot verify the entire read-only project boundary: more than {MAX_FILES} files')
    return out


class Context:
    """What a survey worker is given. Every operation checks the cap first and the scope second; a refused operation is recorded, never run."""

    def __init__(self, ledger, name, task_id, opened, clock, project):
        self.ledger, self.name, self.task_id, self.opened, self.project = ledger, name, task_id, opened, Path(project).resolve()
        self.clock, self.start = clock, clock()
        self.cap_seconds, self.cap_calls = opened['cap']['minutes'] * 60, opened['cap']['calls']
        self.paths = [(self.project / p).resolve() for p in opened['scope']['paths']]
        self.ops, self.denied, self.calls, self.stopped = [], [], 0, False

    def elapsed(self):
        return self.clock() - self.start

    def over_cap(self):
        return self.elapsed() >= self.cap_seconds or self.calls >= self.cap_calls

    def _live(self):
        if self.stopped or self.over_cap():
            self.stopped = True                                     # once the cap is reached nothing runs, and nothing more is recorded
            raise CapReached('the survey reached its cap: no further operation runs.')

    def _count(self, op, path=None):
        self.calls += 1
        self.ops.append({'op': op, 'path': path, 'at': round(self.elapsed(), 3)})

    def _deny(self, op, path, reason):
        self.denied.append({'op': op, 'path': path, 'reason': reason, 'at': round(min(self.elapsed(), self.cap_seconds), 3)})
        raise SurveyDenied(reason)

    def tick(self, label=''):
        """One unit of work that is not a read (a model call of a real worker): counts against the cap."""
        self._live(); self._count('tick', label)

    def read(self, relative):
        self._live()
        if not isinstance(relative, str) or Path(relative).is_absolute() or '..' in Path(relative).parts:
            self._deny('read', str(relative), 'the read-only survey accepts relative paths inside its scope only.')
        target = (self.project / relative).resolve()
        if not any(target == base or base in target.parents for base in self.paths) or (self.project != target and self.project not in target.parents):
            self._deny('read', relative, f'the survey scope is read-only and limited to {", ".join(self.opened["scope"]["paths"])}: {relative} is outside it.')
        if target.stat().st_size > MAX_FILE_BYTES:
            self._deny('read', relative, f'the survey reads at most {MAX_FILE_BYTES} bytes from one file.')
        self._count('read', relative)
        return target.read_bytes()

    def write(self, relative, data=None):
        self._live()
        self._deny('write', relative, 'the survey scope is read-only: a survey never writes.')


def _blocker(reason, detail):
    return {'reason': reason, 'detail': str(detail)[:500]}


def run(ledger, name, survey_id, worker, clock=time.monotonic):
    """Run `worker(context)` for an opened survey and close it: answered or blocked, with evidence. A finished survey is not run again."""
    from . import plan as plans
    with ledger.transaction() as conn:
        state = plans.anchor_events(ledger, conn, name)
        item = states(conn, state['task_id']).get(survey_id)
        contract, _ = plans.load(ledger, state)
    if item is None: raise LedgerError(f'Plan {name} has no survey {survey_id}.')
    if item['finished'] is not None: return _view(item['finished'])
    opened = item['opened']
    context = Context(ledger, name, state['task_id'], opened, clock, ledger.project)
    answer, result = None, None
    blocker, before = None, None
    try:
        if opened['revision'] != state['latest']:
            raise SurveyDenied('the plan revision changed since this survey was opened; open a survey on the current input.')
        before = _tree(ledger.project)
        context._live()
        result = worker(context)
    except CapReached:
        blocker = _blocker('cap_reached', f'the survey reached its cap ({opened["cap"]["minutes"]} min / {opened["cap"]["calls"]} calls).')
    except SurveyDenied as error:
        blocker = _blocker('scope_violation', error)
    except Exception as error:                                       # a worker that fails is a blocker, not a crash of step 0
        blocker = _blocker('worker_error', f'{type(error).__name__}: {error}')
    else:
        blocker, answer = _judge(ledger, context, result)
    try:
        after = _tree(ledger.project) if before is not None else None
    except SurveyDenied as error:
        blocker, answer, after = _blocker('scope_violation', error), None, None
    changed = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p)) if before is not None and after is not None else []
    if changed:                                                      # a write made behind the context: detected, and it voids the answer
        blocker, answer = _blocker('scope_violation', 'the project changed during the survey: ' + ', '.join(changed[:10])), None
    if any(d['op'] == 'write' for d in context.denied):
        blocker, answer = _blocker('scope_violation', 'the survey scope is read-only: a write attempt was refused.'), None
    if answer and context.elapsed() >= context.cap_seconds:
        blocker, answer = _blocker('cap_reached', 'the read-only boundary verification reached the survey cap.'), None
    with ledger.transaction() as conn:
        current = plans.anchor_events(ledger, conn, name)
    if current['latest'] != opened['revision']:
        blocker, answer = _blocker('revision_changed', 'the plan input changed during the survey; its answer does not close the current unknown.'), None
    elapsed = min(context.elapsed(), context.cap_seconds)
    log = {'kind': 'survey-log', 'plan': name, 'survey': survey_id, 'ops': context.ops, 'denied': context.denied, 'changed': changed,
           'cap': opened['cap'], 'elapsed_seconds': elapsed}
    if isinstance(result, dict):
        log['reported'] = {key: str(result[key])[:1000] for key in ('answer', 'evidence', 'hypothesis', 'confidence') if key in result}
    blob = Snapshots(ledger.state_root).blob(canonical(log).encode('utf-8'))
    finished = {'plan': state['name'], 'revision': opened['revision'], 'survey': survey_id, 'unknown': opened['unknown'], 'status': 'blocked' if blocker else 'answered',
                'answer': answer['answer'] if answer else None, 'evidence': answer['evidence'] if answer else blob,
                'evidence_kind': answer['evidence_kind'] if answer else 'blob', 'hypothesis_result': answer['hypothesis'] if answer else None,
                'blocker': blocker, 'spent': {'seconds': elapsed, 'calls': min(context.calls, context.cap_calls)}, 'cap': opened['cap'],
                'ops': len(context.ops), 'last_op_at': max([o['at'] for o in context.ops], default=0), 'log': blob}
    _record(ledger, name, state, contract, context, finished)
    return _view(finished)


def _judge(ledger, context, result):
    """(blocker, answer) for a worker's return value. An answer counts only with a non-empty text AND evidence that resolves, inside the cap."""
    from . import step0
    if context.stopped or context.elapsed() >= context.cap_seconds or context.calls > context.cap_calls:
        return _blocker('cap_reached', 'the answer, if any, came after the cap: it is discarded.'), None
    if isinstance(result, dict) and result.get('blocked'): return _blocker('worker_blocked', result['blocked']), None
    if not isinstance(result, dict) or not str(result.get('answer') or '').strip() or not str(result.get('evidence') or '').strip():
        return _blocker('no_answer', 'the worker returned no answer with evidence: a survey ends with an answer and its evidence, or with a blocker.'), None
    hypothesis = result.get('hypothesis', 'unknown')
    if hypothesis not in HYPOTHESIS: return _blocker('no_answer', 'hypothesis: refuted, confirmed or unknown.'), None
    if result.get('confidence') == 'low' or result.get('hypothesis') == 'unknown' or result.get('resolved') is False:
        return _blocker('uncertain_answer', 'the answer is explicitly uncertain; the unknown remains open.'), None
    try:
        kind = step0.evidence_kind(ledger, str(result['evidence']), 'poc')
    except LedgerError as error:
        return _blocker('evidence_invalid', error), None
    return None, {'answer': str(result['answer']).strip()[:1000], 'evidence': str(result['evidence']).strip(), 'evidence_kind': kind, 'hypothesis': hypothesis}


def _record(ledger, name, state, contract, context, finished):
    """Write the denials and the end of the survey. An answer also closes the unknown it was opened for (by poc) in the same transaction."""
    from . import plan as plans, step0
    denied = [(DENIED, {'plan': name, 'survey': finished['survey'], **d}) for d in context.denied]
    unknown = next((u for u in contract['understanding']['unknowns'] if u['id'] == finished['unknown']), None)
    if finished['status'] == 'answered' and unknown is not None and unknown['status'] == 'open':
        step0._closing(ledger, name, finished['unknown'], 'poc', finished['evidence'], extra_events=denied + [(FINISHED, finished)])
        return
    with ledger.transaction(write=True) as conn:
        for kind, payload in denied + [(FINISHED, finished)]: plans.emit(ledger, conn, state['task_id'], kind, payload)


def _view(finished):
    return {'id': finished['survey'], 'unknown': finished['unknown'], 'status': finished['status'], 'answer': finished.get('answer'),
            'evidence': finished['evidence'], 'hypothesis_result': finished.get('hypothesis_result'), 'blocker': finished.get('blocker'),
            'spent': finished['spent']}
