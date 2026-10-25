"""W23b (R02) — the outcome of a plan root, in the format of v1's `learning.outcome` (class A of the event-type ledger, 00 §6.1), and the
orchestrator's interventions (`control.intervention`, written by v1's `interventions.record`).

An end is what `plan report` calls XONG (accepted), DỪNG (stopped_with_report) or HỎNG (a failure with no repair left); the definition is
`report._standing`, not a second one. One outcome is written per (plan, revision, end): the payload is a pure function of the ledger events up to
that end, so writing it again produces the same `id` and the v1 merge rule (`task_intake.append_outcome`, the rule `learning.record` uses) drops
it. A root stopped at revision 1 and accepted at revision 2 has two rows.

The writer never blocks the command it follows (`note`): a failure prints one stderr line and the root shows in `missing()`. It writes no lesson
and no skill state (`learning.record` does; this does not call it) and calls no model. The payload cannot be taken for a v1 goal's outcome: its
`mode` is `plan`, provider/model are None, `spec_revision` is the revision's contract sha and `signature` is None (skills.refresh skips it).
"""
import datetime as dt
import json
import sqlite3
import sys
from contextlib import closing

from .. import interventions, outcome_core
from ..ledger import LedgerError, content_hash, key_field, text_field
from . import compat, namespaces, plan as plans

END_PHASE = {'accepted': 'completed', 'stopped_with_report': 'blocked', 'failed': 'failed', 'closed': 'cancelled'}
_STANDING_END = {'accepted': 'accepted', 'stopped': 'stopped_with_report', 'failed': 'failed', 'closed': 'closed'}


def _anchor_events(ledger, name):
    with ledger.transaction() as conn:
        if conn is None: raise LedgerError(f'No plan named {name}.')
        root = namespaces.resolve(ledger, conn, name)
        row = conn.execute('SELECT * FROM tasks WHERE id=?', (root['id'],)).fetchone() if root else None
        if row is None: raise LedgerError(f'No plan named {name}.')
        rows = conn.execute('SELECT seq, kind, payload, created_at FROM events WHERE task_id=? ORDER BY seq', (row['id'],)).fetchall()
    return dict(row), [{'seq': r['seq'], 'kind': r['kind'], 'payload': json.loads(r['payload']), 'at': r['created_at']} for r in rows]


def ending(ledger, name):
    """The end the root is in now, or None while it is open: {'end', 'revision', 'phase', 'artifact_sha', 'event', 'sha'}."""
    from . import report
    task, events = _anchor_events(ledger, name)
    facts = report._lookup(ledger.state_root, task['request_key'], project_id=ledger.project_id)
    kind, _ = report._standing(facts)
    end = _STANDING_END.get(kind)
    if end is None: return None
    state = facts['state']
    revision = state['accepted']['revision'] if end == 'accepted' else state['latest']
    sha = state['revisions'][revision]['sha']
    mine = [e for e in events if e['payload'].get('revision') == revision]
    if end == 'accepted':
        done = [e for e in mine if e['kind'] == 'plan.accepted'][-1]
        artifact = done['payload'].get('artifact_sha')
    else:
        done = [e for e in mine if e['kind'] == {'stopped_with_report': 'milestone.stopped', 'failed': 'milestone.failed', 'closed': 'plan.closed'}[end]][-1]
        artifact = ([e for e in mine if e['kind'] == 'verdict.recorded' and e['seq'] < done['seq']] or [{'payload': {}}])[-1]['payload'].get('artifact_sha')
    return {'end': end, 'revision': revision, 'phase': END_PHASE[end], 'artifact_sha': artifact, 'event': done['seq'], 'sha': sha,
            '_task': task, '_events': events, '_facts': facts, '_done': done}


def _seconds(first, last):
    return max(0.0, (dt.datetime.fromisoformat(last) - dt.datetime.fromisoformat(first)).total_seconds())


def build_payload(ledger, name, found=None):
    """The learning.outcome payload of the root's current end (v1's keys; see the module note for what is deliberately not v1's identity)."""
    found = found or ending(ledger, name)
    if found is None: raise LedgerError(f'Plan {name} has not ended; there is no outcome to record.')
    facts, task, events, done = found['_facts'], found['_task'], found['_events'], found['_done']
    views = [v for v in facts['views']]
    failures = sum(v['failures'] for v in views)
    passed = sum(v['state'] == 'passed' for v in views)
    contract = facts['contract']
    data = {'version': 1, 'task': task['id'], 'task_revision': task['revision'], 'spec_revision': found['sha'], 'phase': found['phase'],
            'mode': 'plan', 'provider': None, 'model': None, 'provider_handoffs': [], 'snapshot': found['artifact_sha'],
            'verification': 'passed' if found['end'] == 'accepted' else 'unknown' if found['end'] == 'closed' else 'failed',
            'acceptance': 'accepted' if found['end'] == 'accepted' else 'not_requested',
            'progress': {'milestones': {v['id']: v['state'] for v in views}}, 'recovery': None, 'managed_calls': None, 'usage': None,
            'assistance': 'unknown', 'quality_score': None, 'routing_policy': 'v2-plan', 'device_tested': False, 'candidate_files': None,
            'signature': None, 'procedure': [], 'skills': [],
            'timing': {'wall_seconds': _seconds(events[0]['at'], done['at']), 'settled_attempt_seconds': None, 'wait_seconds': None,
                       'includes_waits': True, 'active_compute_seconds': None},
            'budget': contract.get('budget') if contract else None, 'budget_policy': None, 'repair_rounds': failures,
            'test_results': {'passed': passed, 'failed': failures},
            # what makes it a v2 root's outcome, and the dedupe key (plan, revision, end)
            'source': 'v2-plan', 'plan': namespaces.parse(name)[0], 'plan_anchor': task['request_key'],
            'plan_revision': found['revision'], 'end': found['end'], 'end_event': found['event']}
    data['id'] = outcome_core.outcome_id(data)
    return data


def _historical_ends(ledger, name):
    """Replay terminal prefixes through the existing projector, never a second engine.

    A TEMP view on a read-only connection shadows events only for that
    connection. The source database, contract files and blobs are untouched.
    """
    from . import report
    task, events = _anchor_events(ledger, name)
    found = {}
    for index, done in enumerate(events):
        kind, payload = done['kind'], done['payload']
        if kind not in ('plan.accepted', 'milestone.stopped', 'milestone.failed', 'plan.closed'):
            continue
        # failed + stopped are published by one verdict transaction. The
        # intermediate failed event is not a second terminal outcome.
        following = events[index + 1] if index + 1 < len(events) else None
        if kind == 'milestone.failed' and following and following['kind'] == 'milestone.stopped':
            if all(following['payload'].get(k) == payload.get(k) for k in ('revision', 'milestone')):
                continue
        revision = payload['revision']
        prefix = events[:index + 1]
        artifact = payload.get('artifact_sha')
        if artifact is None:
            prior = [e for e in prefix if e['kind'] == 'verdict.recorded' and e['payload'].get('revision') == revision]
            artifact = prior[-1]['payload'].get('artifact_sha') if prior else None
        with closing(sqlite3.connect(ledger.path.as_uri() + '?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            seq = int(done['seq'])
            conn.execute(f'CREATE TEMP VIEW events AS SELECT * FROM main.events WHERE seq<={seq}')
            conn.execute('PRAGMA query_only=ON')
            state = plans.derive(ledger, conn, task['request_key'])
            contract, sha = plans.load(ledger, state, revision)
            views = plans.milestone_views(contract, state, revision, ledger, artifact=artifact)
        facts = {'state': state, 'contract': contract, 'views': views, 'requests': [], 'revision': revision}
        standing, _ = report._standing(facts)
        end = _STANDING_END.get(standing)
        expected = {'plan.accepted': 'accepted', 'milestone.stopped': 'stopped_with_report', 'milestone.failed': 'failed', 'plan.closed': 'closed'}[kind]
        if end != expected:
            continue
        key = (revision, end)
        found.setdefault(key, {'end': end, 'revision': revision, 'phase': END_PHASE[end], 'artifact_sha': artifact,
            'event': done['seq'], 'sha': sha, '_task': task, '_events': prefix, '_facts': facts, '_done': done})
    return list(found.values())


def record(ledger, name):
    """Write the outcome of the root's current end unless it is already there. {'recorded': bool, ...}; raises on a failure (see `note`)."""
    found = ending(ledger, name)
    if found is None: return {'recorded': False, 'reason': 'not_ended', 'plan': name}
    return _record_found(ledger, name, found)


def _record_found(ledger, name, found):
    data = build_payload(ledger, name, found)
    name = namespaces.parse(name)[0]
    key = {'plan': name, 'plan_revision': found['revision'], 'end': found['end']}
    with ledger.transaction(write=True) as conn:
        compat.check_write('learning.outcome', data, found['_task']['request_key'])
        same_key = [json.loads(r['payload']) for r in conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='learning.outcome'", (data['task'],))]
        if any(p.get('plan') == name and p.get('plan_revision') == found['revision'] and p.get('end') == found['end'] and p.get('id') != data['id'] for p in same_key):
            return dict(key, recorded=False, reason='already_recorded_for_this_end')
        event = outcome_core.append_outcome(conn, ledger, data['task'], data)        # the v1 merge rule
    if event is not None:
        # T16b [E6]: Q10 (an outcome changes nothing) leaves its HD-05 record through internal_plan's one decide(); only on a root
        # that delegates Q10, so a root without a workflow grant records exactly what it did before.
        from . import internal_plan
        internal_plan.self_decided(ledger, found['_task']['request_key'], 'Q10', [], 'onecrew.outcome', key='q10-outcome-' + str(event),
                                   outcome=data['id'], end=found['end'], plan_revision=found['revision'], evidence=['learning.outcome:' + str(event)])
    return dict(key, recorded=event is not None, event=event, id=data['id'], phase=data['phase'])


def note(ledger, name, found=None):
    """record(), after a command that already succeeded: a failure is one stderr line, never a failed command."""
    try:
        return _record_found(ledger, name, found) if found is not None else record(ledger, name)
    except Exception as error:                      # an outcome must never turn a success into a failure
        line = ' '.join(f'{type(error).__name__}: {error}'.split())
        print('Outcome not recorded: ' + line, file=sys.stderr)
        return {'recorded': False, 'reason': 'error', 'error': line[:300], 'plan': name}


def outcomes(ledger, name=None):
    """The learning.outcome rows of one root (or every v2 root of the project): [{'event', ...payload}]."""
    with ledger.transaction() as conn:
        if conn is None: return []
        root = namespaces.resolve(ledger, conn, name) if name is not None else None
        if name is not None and root is None:
            raise LedgerError(f'No plan named {name}.')
        rows = conn.execute("SELECT e.seq, e.payload FROM events e JOIN tasks t ON t.id=e.task_id WHERE t.project_id=? "
                            "AND (t.request_key LIKE 'plan:%' OR t.request_key LIKE 'plan-ns:%') AND e.kind='learning.outcome' "
                            + ('AND t.id=? ' if root is not None else '') + 'ORDER BY e.seq',
                            (ledger.project_id, root['id']) if root is not None else (ledger.project_id,)).fetchall()
    result = [dict(json.loads(r['payload']), event=r['seq']) for r in rows]
    return result


def missing(ledger):
    """The roots of this project that have ended and have no outcome for that end — the gap the measuring function lists (T35a E17)."""
    with ledger.transaction() as conn:
        if conn is None: return []
        names = [r['request_key'] for r in conn.execute(
            "SELECT request_key FROM tasks WHERE project_id=? AND (request_key LIKE 'plan:%' OR request_key LIKE 'plan-ns:%') ORDER BY created_at, id", (ledger.project_id,))]
    have = {(r['task'], r['plan_revision'], r['end']) for r in outcomes(ledger)}
    gaps = []
    for name in names:
        try:
            historical = _historical_ends(ledger, name)
        except (LedgerError, OSError, sqlite3.Error) as error:
            gaps.append({'plan': namespaces.parse(name)[0], 'selector': name, 'revision': None, 'end': None, 'error': str(error)})
            continue
        for found in historical:
            if (found['_task']['id'], found['revision'], found['end']) not in have:
                gaps.append({'plan': namespaces.parse(name)[0], 'selector': name, 'task': found['_task']['id'], 'revision': found['revision'], 'end': found['end']})
    return gaps


def reconcile(ledger):
    """Repair durable terminal gaps after a crash; callers choose a mutating checkpoint.

    Readers only expose missing(). No second queue/store or owner question is
    created, and each replay uses the common idempotent outcome merge rule.
    """
    results = []
    for gap in missing(ledger):
        if gap.get('error'):
            results.append({'recorded': False, 'reason': 'unreadable_root', **gap})
            continue
        found = next(f for f in _historical_ends(ledger, gap['selector']) if f['revision'] == gap['revision'] and f['end'] == gap['end'])
        results.append(note(ledger, gap['selector'], found))
    return {'results': results, 'missing': missing(ledger)}


def intervene(ledger, name, kind, reason, *, actor=None, key=None):
    """A reason-bearing intervention of the orchestrator on a root: one `control.intervention` on its anchor, written by v1's
    interventions.record (actor, command, reason, idempotent by key). `kind` is the type (e.g. state.fix); it is kept as the command
    `v2.<kind>` and in details. An owner actor is refused from inside an AI session by interventions.record itself."""
    key_field(kind); text_field(reason, 'reason', 500)
    task, _ = _anchor_events(ledger, name)
    compat.check_write('control.intervention', {}, task['request_key'])
    with ledger.transaction() as conn:
        state = plans.derive(ledger, conn, name)
    revision = state['latest'] if state else None
    name = namespaces.parse(name)[0]
    key = key or 'iv-' + content_hash({'task': task['id'], 'revision': revision, 'kind': kind, 'reason': reason})[:24]
    return interventions.record(ledger, task['id'], 'v2.' + kind, actor=actor, channel='cli', reason=reason,
                                details={'plan': name, 'revision': revision, 'kind': kind}, key=key)
