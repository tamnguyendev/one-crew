"""W23c - efficiency figures read from the ledger (00 §9.1, group A), classified by the v1 evaluation functions through an adapter (TD27).

What is measured, per plan root, from the anchor's events only (nothing is written, no model is called):
  * time to usable output - from the owner's first approval to the moment every milestone of the final revision has a passing verdict ("verified");
    "to acceptance" adds the wait for the owner to accept. Wall minutes; the owner's waits inside that window are shown and taken out;
  * waits - the owner's (approval, an open question until it is answered, acceptance); resource and external-service waits have no source yet: unknown;
  * rework - failed verdicts (repair rounds) and amends. The cause of an amend and a defect found after a pass are not in the ledger: unknown;
  * the owner's decisions - by verb (approve, accept, record, answer) and by request, who decided each (the v1 rule);
  * cost of the checks - seconds and reviewer calls from the receipts.
A figure with no source is `unknown` with the reason, never 0. The owner's ACTIVE minutes are written down by the owner (group B) and are never derived
from a wait. How many times someone asked for the status leaves no event (plan show and plan report are read-only): unknown (group C).

Classification delegates to the pure v1 evaluation functions extracted into evaluation_core, shared unchanged by the checkout and wheel.
"""
import argparse
import collections
import datetime as dt
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from ..ledger import LedgerError
from ..snapshots import Snapshots
from . import plan as plans

UNKNOWN = 'unknown'
V1_MODULES = ('onecrew.evaluation_core',)
V1_FUNCTIONS = ('signals', 'decision_source', 'role', 'completion_level', 'assistance_level', 'outcome')
OWNER = ('owner', 'user')


class EvaluatorUnavailable(LedgerError):
    pass


def v1_evaluator():
    """The v1 evaluation functions, as one object. Looked up by module name when called (see the module docstring)."""
    found = {}
    for module in V1_MODULES:
        try:
            loaded = importlib.import_module(module)
        except ImportError as error:
            raise EvaluatorUnavailable(f'the shared v1 evaluation functions ({module}) are unavailable: {error}') from error
        for name in V1_FUNCTIONS:
            if hasattr(loaded, name): found.setdefault(name, getattr(loaded, name))
    missing = [n for n in V1_FUNCTIONS if n not in found]
    if missing: raise EvaluatorUnavailable('the v1 evaluation modules do not define: ' + ', '.join(missing))
    return SimpleNamespace(**found)


class _Calls:
    """Calls the v1 functions on behalf of the measure and counts them."""

    def __init__(self, evaluator):
        self.evaluator, self.count = evaluator, 0

    def __getattr__(self, name):
        function = getattr(self.evaluator, name)

        def call(*args, **kwargs):
            self.count += 1
            return function(*args, **kwargs)
        return call


def _time(text):
    value = dt.datetime.fromisoformat(str(text))
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def _minutes(start, end):
    return round((_time(end) - _time(start)).total_seconds() / 60, 2)


def _events(conn, task_id):
    return [{'seq': r['seq'], 'kind': r['kind'], 'p': json.loads(r['payload']), 'at': r['created_at']}
            for r in conn.execute('SELECT seq,kind,payload,created_at FROM events WHERE task_id=? ORDER BY seq', (task_id,))]


def plan_names(ledger):
    with ledger.transaction() as conn:
        if conn is None: return []
        return sorted(r['request_key'] for r in conn.execute(
            "SELECT request_key FROM tasks WHERE project_id=? AND (request_key LIKE 'plan:%' OR request_key LIKE 'plan-ns:%')", (ledger.project_id,)))


def _verified_at(events, state, contract, revision):
    """When the last milestone of the final revision got the verdict it was accepted / stands on; None while one has none."""
    recorded = [e for e in events if e['kind'] == 'verdict.recorded']
    times = []
    accepted = state['accepted'] if state['accepted'] and state['accepted']['revision'] == revision else None
    for milestone in contract['milestones']:
        if accepted:
            wanted = (accepted.get('receipts') or {}).get(milestone['id'])
            hit = [e for e in recorded if wanted and e['p'].get('receipt') == wanted]
        else:
            mine = [e for e in recorded if e['p'].get('revision') == revision and e['p'].get('milestone') == milestone['id']]
            hit = mine[-1:] if mine and mine[-1]['p'].get('result') == 'pass' else []
        if not hit: return None
        times.append(_time(hit[-1]['at']))
    return max(times).isoformat() if times else None


def _owner_waits(events, state, verified, accepted_at):
    items, first_approval = [], {}
    for e in events:
        if e['kind'] == 'plan.approved': first_approval.setdefault(e['p']['revision'], e['at'])
    for e in events:
        if e['kind'] in ('plan.proposed', 'plan.amended'):
            revision, to = e['p']['revision'], first_approval.get(e['p']['revision'])
            current = revision == state['latest']
            items.append({'kind': 'approval', 'id': f'revision {revision}', 'from': e['at'], 'to': to, 'open': to is None and current,
                          'minutes': _minutes(e['at'], to) if to else UNKNOWN})
    if verified:
        items.append({'kind': 'acceptance', 'id': 'acceptance', 'from': verified, 'to': accepted_at, 'open': accepted_at is None,
                      'minutes': _minutes(verified, accepted_at) if accepted_at else UNKNOWN})
    answers = {e['p'].get('request_id'): e['p'] for e in events if e['kind'] == 'request.answered'}
    for e in events:
        if e['kind'] != 'request.created': continue
        view, answer = e['p'], answers.get(e['p'].get('id'))
        stop = (answer or {}).get('recorded_at')
        items.append({'kind': 'request', 'id': view.get('id'), 'from': view.get('created_at') or e['at'], 'to': stop, 'open': stop is None,
                      'minutes': _minutes(view.get('created_at') or e['at'], stop) if stop else UNKNOWN})
    known = [i['minutes'] for i in items if i['minutes'] != UNKNOWN]
    return {'minutes': round(sum(known), 2) if known else UNKNOWN, 'items': items, 'open_items': sum(1 for i in items if i['open'])}


def _inside(items, start, end):
    """Minutes of the owner's closed waits that fall inside [start, end]."""
    intervals = []
    for i in items:
        if i['minutes'] == UNKNOWN or not i['to']: continue
        low, high = max(_time(i['from']), _time(start)), min(_time(i['to']), _time(end))
        if high > low: intervals.append((low, high))
    merged = []
    for low, high in sorted(intervals):
        if merged and low <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(high, merged[-1][1]))
        else:
            merged.append((low, high))
    return round(sum((high - low).total_seconds() / 60 for low, high in merged), 2)


def _check_cost(ledger, events):
    seconds, runs, unknown, calls, owner = 0.0, 0, 0, 0, 0
    store = Snapshots(ledger.state_root)
    for e in events:
        if e['kind'] != 'verdict.recorded': continue
        if e['p'].get('by') == 'owner': owner += 1; continue
        runs += 1
        calls += e['p'].get('calls') or 0
        try:
            body = json.loads(store.read_blob(e['p']['receipt']).decode('utf-8'))
            value = body.get('seconds')
        except (OSError, ValueError, LedgerError, KeyError, AttributeError):
            value = None
        if type(value) in (int, float): seconds += value
        else: unknown += 1
    return {'seconds': round(seconds, 2), 'runs': runs, 'unknown_runs': unknown, 'calls': calls, 'owner_verdicts': owner}


def classify_decisions(rows, root, evaluator):
    """The runtime signals of the answers and interventions on the anchor: the v1 `signals`, unchanged."""
    signals = evaluator.signals(rows, root)
    return {k: signals[k] for k in ('decisions_answered', 'decisions_by_source', 'interventions')} | {'signals': signals}


def _owner_source(event, evaluator):
    """Who decided an owner verb: the v1 `decision_source` over a receipt-shaped provenance. Only a process that declared itself the owner
    (ai_session False) is the user's own; anything else stays unknown."""
    own = event['p'].get('ai_session') is False
    return evaluator.decision_source({'provenance': {'by': 'user' if own else None, 'decided_by': 'user' if own else None}})


def measure(ledger, name, evaluator=None):
    """The figures of plan root `name`, from its ledger events (read-only)."""
    use = _Calls(evaluator or v1_evaluator())
    with ledger.transaction() as conn:
        state = plans.anchor_events(ledger, conn, name)
        events = _events(conn, state['task_id'])
        revision = (state['accepted'] or state['approved'] or {}).get('revision') or state['latest']
        contract = plans.load(ledger, state, revision)[0]
    approvals = [e for e in events if e['kind'] == 'plan.approved']
    approved_at = approvals[0]['at'] if approvals else None
    verified = _verified_at(events, state, contract, revision) if approvals else None
    if verified and state['status'] != 'accepted':
        views = plans.milestone_views(contract, state, revision, ledger)
        if any(v['state'] != 'passed' or v.get('stale') for v in views):
            verified = None
        from . import namespaces
        if namespaces.has_capability(state, 'finding-register'):
            from .findings import list_findings
            if list_findings(ledger, name, task_id=state['task_id'], open_only=True):
                verified = None
    accepted_at = next((e['at'] for e in events if e['kind'] == 'plan.accepted'), None)
    waits = _owner_waits(events, state, verified, accepted_at)
    both = bool(approved_at and verified)
    inside = _inside(waits['items'], approved_at, verified) if both else UNKNOWN
    wall = _minutes(approved_at, verified) if both else UNKNOWN
    time_to_output = {'approved_at': approved_at, 'verified_at': verified, 'accepted_at': accepted_at, 'wall_minutes': wall,
                      'to_acceptance_minutes': _minutes(approved_at, accepted_at) if approved_at and accepted_at else UNKNOWN,
                      'owner_wait_inside_minutes': inside, 'excluding_owner_wait_minutes': round(wall - inside, 2) if both else UNKNOWN}
    recorded = [e for e in events if e['kind'] == 'verdict.recorded']
    failed = [e['p']['milestone'] for e in recorded if e['p'].get('result') != 'pass']
    rework = {'repair_rounds': len(failed), 'by_milestone': dict(collections.Counter(failed)), 'amends': sum(1 for e in events if e['kind'] == 'plan.amended'),
              'amend_causes': UNKNOWN, 'late_defects': UNKNOWN}
    # the owner's decisions: owner verbs by who ran them, answers and interventions by the v1 signals
    verbs = {'approve': 0, 'accept': 0, 'record': 0, 'answer': 0}
    by_source = {'user': 0, 'relayed': 0, 'entry': 0, 'unknown': 0}
    for e in events:
        verb = ('approve' if e['kind'] == 'plan.approved' else 'accept' if e['kind'] == 'plan.accepted' else
                'record' if e['kind'] == 'verdict.recorded' and e['p'].get('by') == 'owner' else None)
        if verb and e['p'].get('by') in OWNER:
            verbs[verb] += 1
            by_source[_owner_source(e, use)] += 1
    rows = [{'task_id': state['task_id'], 'kind': e['kind'], 'payload': json.dumps(e['p'])} for e in events if e['kind'] in ('request.answered', 'control.intervention')]
    classified = classify_decisions(rows, state['task_id'], use)
    verbs['answer'] = classified['decisions_answered']
    for key, count in classified['decisions_by_source'].items(): by_source[key] += count
    created = {e['p'].get('id'): e['p'] for e in events if e['kind'] == 'request.created'}
    by_request = []
    for e in events:
        if e['kind'] != 'request.answered': continue
        question = (created.get(e['p'].get('request_id')) or {}).get('question') or {}
        by_request.append({'request': e['p'].get('request_id'), 'type': (question.get('action') or {}).get('type'), 'choice': e['p'].get('choice'),
                           'decided_by': use.decision_source(e['p'], None)})
    roles = collections.Counter(use.role(i) for i in classified['interventions'] or [])
    decisions = {'total': sum(verbs.values()), 'by_verb': verbs, 'by_request': by_request, 'by_source': by_source,
                 'interventions': None if classified['interventions'] is None else {'count': len(classified['interventions']), 'by_role': dict(roles)}}
    phase = {'accepted': 'completed', 'approved': 'running', 'stopped_with_report': 'waiting'}.get(state['status'], 'planning')
    task_view = {'task': state['task_id'], 'phase': phase, 'verification': 'passed' if verified else 'pending', 'delivery': None, 'gates': {}, 'gaps': [],
                 'pending_requests': [], 'assistance': 'unknown', 'assistance_kinds': [], 'recorded_interventions': [],
                 'metrics': dict(classified['signals'], plan_provenance=None, pending_escalations=None, failure_classes=None)}
    level, level_gaps = use.completion_level(task_view)
    helped, helped_reasons = use.assistance_level(task_view)
    kind, kind_reasons = use.outcome(task_view)
    return {'plan': state['name'], 'selector': state['selector'], 'revision': revision, 'status': state['status'], 'time_to_output': time_to_output,
            'waits': {'owner': waits, 'resource': {'minutes': UNKNOWN, 'why': 'no source in the ledger yet'},
                      'external_service': {'minutes': UNKNOWN, 'why': 'no source in the ledger yet'}},
            'owner_active_minutes': {'value': UNKNOWN, 'why': 'the owner writes it down (group B); it is never derived from a wait or from the time between two events'},
            'rework': rework, 'owner_decisions': decisions, 'check_cost': _check_cost(ledger, events),
            'status_queries': {'value': UNKNOWN, 'why': 'plan show and plan report are read-only and leave no event; the source is the chat log (group C)'},
            'v1_view': {'completion_level': level, 'completion_gaps': level_gaps, 'assistance_level': helped, 'assistance_reasons': helped_reasons,
                        'outcome': kind, 'outcome_reasons': kind_reasons},
            'v1_calls': use.count}


GROUPS = {'time_to_output': 'A', 'rework': 'A', 'check_cost': 'A', 'owner_decisions': 'A', 'owner_active_minutes': 'B', 'status_queries': 'C'}


def _known(metric, root):
    if metric == 'time_to_output': return root['time_to_output']['wall_minutes'] != UNKNOWN
    if metric == 'check_cost': return root['check_cost']['unknown_runs'] == 0
    if metric in ('owner_active_minutes', 'status_queries'): return root[metric]['value'] != UNKNOWN
    return True


def measure_all(ledger, evaluator=None):
    """Every plan root of the project, with, for each figure, how many roots have it (k of n) and the state of that (00 §9.3): `đủ` when all,
    `thiếu` when some, `không có` when none."""
    evaluator = evaluator or v1_evaluator()
    roots = [measure(ledger, name, evaluator) for name in plan_names(ledger)]
    n = len(roots)
    coverage = {}
    for metric, group in GROUPS.items():
        k = sum(1 for r in roots if _known(metric, r))
        coverage[metric] = {'k': k, 'n': n, 'status': 'đủ' if k == n and n else 'thiếu' if k else 'không có', 'group': group}
    known_waits = [r['waits']['owner']['minutes'] for r in roots if r['waits']['owner']['minutes'] != UNKNOWN]
    totals = {'roots': n, 'repair_rounds': sum(r['rework']['repair_rounds'] for r in roots), 'amends': sum(r['rework']['amends'] for r in roots),
              'check_seconds': round(sum(r['check_cost']['seconds'] for r in roots), 2), 'owner_decisions': sum(r['owner_decisions']['total'] for r in roots),
              'owner_wait_minutes': round(sum(known_waits), 2)}
    return {'roots': roots, 'coverage': coverage, 'totals': totals}


def render(report):
    lines = []
    for r in report['roots']:
        t, d = r['time_to_output'], r['owner_decisions']
        lines.append(f"{r['plan']} [{r['status']}] tới đầu ra {t['wall_minutes']} phút (trừ chờ chủ sở hữu: {t['excluding_owner_wait_minutes']}), tới nghiệm thu {t['to_acceptance_minutes']}; "
                     f"chờ chủ sở hữu {r['waits']['owner']['minutes']} phút; vòng sửa {r['rework']['repair_rounds']}, amend {r['rework']['amends']}; "
                     f"quyết định của chủ sở hữu {d['total']} {d['by_verb']}; kiểm {r['check_cost']['seconds']} s trong {r['check_cost']['runs']} lần; "
                     f"phút chủ động: không có dữ liệu (chủ sở hữu tự ghi)")
    for metric, c in report['coverage'].items(): lines.append(f"{metric} ({c['group']}): {c['k']}/{c['n']} {c['status']}")
    return '\n'.join(lines)


def _strip(argv):
    argv, out, i = list(argv), [], 0
    while i < len(argv):
        if argv[i] in ('--project', '--state-root'): out += argv[i:i + 2]; i += 2
        elif argv[i] in ('eval', 'plan-metrics') and argv[i] not in out: i += 1
        else: out.append(argv[i]); i += 1
    return out


def main(argv=None):
    p = argparse.ArgumentParser(prog='onecrew eval plan-metrics', description=__doc__)
    p.add_argument('--project', type=Path, default=Path.cwd()); p.add_argument('--state-root', type=Path)
    p.add_argument('--plan', action='append', help='Only these plans (default: every plan root of the project).')
    p.add_argument('--json', action='store_true')
    args = p.parse_args(_strip(sys.argv[1:] if argv is None else argv))
    from .lint import ReadOnlyLedger
    try:
        ledger = ReadOnlyLedger(args.project, args.state_root)
        evaluator = v1_evaluator()
        report = measure_all(ledger, evaluator) if not args.plan else None
        if report is None:
            roots = [measure(ledger, name, evaluator) for name in args.plan]
            report = {'roots': roots, 'coverage': {}, 'totals': {}}
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render(report))
        return 0
    except LedgerError as error:
        print(json.dumps({'error': str(error), 'type': type(error).__name__}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
