"""W26: engine consumers of the existing rules, never model decision authority.

Every configured node check is mandatory. Optional reviews are separate approved
policy IDs and never publish node.verification, acceptance, or a human request.
Injected checkers own their usual provider/budget boundary; this adapter does not
select models, change pins or implement provider fallback.
"""
import contextvars
import copy
import datetime as dt
import json
import hashlib
import os
import uuid

from ..ledger import LedgerError, canonical, content_hash, key_field
from ..snapshots import Snapshots
from . import contract as contracts, engine, internal_plan as ip, plan, review_advice, review_policy, review_request


def _context(ledger, selector, node, conn=None):
    key_field(node)
    if conn is None:
        with ledger.transaction() as connection:
            return _context(ledger, selector, node, connection)
    root, contract, sha = ip.context(ledger, conn, selector, 'sequential-engine')
    view = engine.state(ledger, root['selector'], conn)
    if not view['definition'] or node not in view['nodes']: raise LedgerError('Unknown review node.')
    if view['definition_contract_sha'] != sha:
        raise LedgerError('Revise the internal plan against the current approved contract before review.')
    item = next(n for n in view['definition']['nodes'] if n['id'] == node)
    record = view['nodes'][node]
    facts = {'node': node, 'contract_sha': sha, 'internal_revision': view['internal_revision'], 'generation': record['generation'],
             'artifact': record['artifact'], 'inputs': record['inputs'], 'checks_sha': content_hash(item['checks']),
             'state': record['state'], 'phase': record['phase'],
             'unknowns': sorted(view.get('unknown_blockers', {}).get(node, [])),
             'findings': sorted(view.get('finding_blockers', {}).get(node, []))}
    return root, contract, item, facts


def _decide(ledger, selector, review_id, facts, *, required):
    ready = facts['state'] in ('produced', 'verified', 'accepted') and facts['phase'] != 'held'
    unknowns = facts['unknowns'] + (['node-held:' + facts['node']] if facts['phase'] == 'held' else [])
    decision = review_policy.decide(ledger, selector, review_id, artifact_sha=facts['artifact'] or 'unproduced:' + facts['node'],
        ready=ready, unknowns=unknowns, findings=facts['findings'], evidence=['engine-input:' + content_hash(facts)], required=required, input_state=facts)
    action = decision.get('action')
    if action not in review_policy.ACTIONS or (required and action == 'SKIP'):
        raise LedgerError('A mandatory engine check cannot be skipped by a review decision.')
    return decision


def required(ledger, selector, node, check_ids):
    """Gate invoked by engine.verify before its checker; no caller can weaken checks."""
    root, _, item, facts = _context(ledger, selector, node)
    configured = [check['id'] for check in item['checks']]
    if (not isinstance(check_ids, (list, tuple)) or any(not isinstance(c, str) for c in check_ids) or len(check_ids) != len(configured)
            or set(check_ids) != set(configured)):
        raise LedgerError('Required review must include every configured node check.')
    decision = _decide(ledger, root['selector'], node, facts, required=True)
    if _context(ledger, root['selector'], node)[3] != facts:
        raise LedgerError('Engine input changed before required verification; recompute the decision.')
    return decision


def _request(ledger, root, contract, item, facts, review_id, execution):
    return review_request.build(root={'project_id': ledger.project_id, 'task_id': root['task_id']},
        contract_revision=root['approved']['revision'], contract_sha=root['approved']['sha'],
        review_id=review_id, required=False, facts=facts,
        scope={k: item.get(k, []) for k in ('read', 'write', 'acceptance')}, criteria=item['checks'],
        policy=review_policy.normalize(contract.get('review_policy', review_policy.DEFAULT)),
        authority=contract.get('authority', {}), budget=contract['budget'], execution=execution)


_RUN_KINDS = ('review.run_started', 'review.run_result', 'review.run_finished', 'review.run_held')


# ---- 2.5-B cycle 2: one claim/observe/reconcile lifecycle for every check door ---------------------------------------------------
#
# The cycle-1 events (class A, compat.CLASS_A) now carry every check a door executes, not only optional observations:
#   review.run_started  {run_id, check, door, request, request_id, subject, parent, pid, host, started, independence, grants_authority}
#   review.run_result   {run_id, request_id, receipt}           the result blob, written BEFORE anything is published (the effect is known)
#   review.run_held     {run_id, request_id, reason}            outcome unknown (exception, lost process, caller timeout): never replayed
#   review.run_finished {run_id, request_id, receipt, applicable, outcome, ...}   outcome: published | stale | observed | not_dispatched
#                                                              | released (an explicit decision with reason/actor; budget is not reset)
# `check` is 'optional' (absent on cycle-1 rows), 'node-verification' (engine.verify, every engine door) or 'milestone' (one approved
# milestone on one candidate tree; CandidateChecker claims it; verdict.run records the same request id on its own verdict.run_started).
# Same request id + an unfinished run -> the next caller observes it (pending/held/issued), it never dispatches the check again.

CHECK_NODE, CHECK_MILESTONE = 'node-verification', 'milestone'
CLAIM_SECONDS = 3600                   # a run with no node cap to derive from; an investigation may take 30 minutes and a provider its own margin
_CURRENT = contextvars.ContextVar('onecrew_check_run', default=None)


class NotDispatched(LedgerError):
    """Raised by a check port BEFORE any verifier/provider was started because the same work is in another run: the outcome here is known
    (nothing ran), so this run is not held. `claim` is what claim_check answered about the blocking run."""
    def __init__(self, message, claim=None):
        super().__init__(message)
        self.claim = claim or {}


def current_run():
    """The node-verification run a checker is executing for (set by engine.verify around the checker call), or None."""
    return _CURRENT.get()


def _optional_work(request):
    """The optional door's in-flight key: the same review asked the same way from another shell is one piece of work (environment and
    provenance aside); another question or another reviewer is other work."""
    identity = dict(request['identity'])
    execution = identity.get('execution')
    if isinstance(execution, dict):
        identity['execution'] = {k: v for k, v in execution.items() if k not in ('environment', 'provenance', 'complete', 'missing')}
    return content_hash(identity)


def _work_key(request):
    """The check being asked for, without how/where it would run: two callers whose environments differ (another shell, another TEMP) are
    two requests for reuse, but one piece of work while it is in flight. Reuse always needs the exact request id."""
    identity = dict(request['identity'])
    identity.pop('execution', None)
    if isinstance(identity.get('evidence'), dict):
        identity['evidence'] = {k: v for k, v in identity['evidence'].items() if k not in ('environment', 'configuration')}
    return content_hash(identity)


def _milestone_execution(ledger, milestone, sha, env=None):
    """What the runtime executes for this milestone, read from the APPROVED contract and the effective verifier environment, never
    declared by the caller: verifier type and config, the reviewer provider/model pin, the environment fingerprint. `env` is the snapshot
    the verifier will really receive, when the caller already took it."""
    from .verifiers import command
    from . import verification_evidence
    env = command.verifier_env(ledger.project) if env is None else env
    kind, config = milestone['verifier']['type'], milestone['verifier']['config']
    method = 'command' if kind == 'command' else 'reviewer' if kind == 'reviewer' else 'adapter'
    return {'method': method, 'implementation': 'onecrew.v2.verifiers.' + (kind if kind in ('command', 'reviewer') else 'port:' + kind),
            'provider': config.get('provider', 'claude') if kind == 'reviewer' else None,
            'model': config.get('model') if kind == 'reviewer' else None,
            # review of dev18 (#4): a check that runs on a checkout says which checkout policy, so a pass of another one is a different request
            'configuration': dict({k: v for k, v in config.items() if k != 'max_minutes'}, checkout_policy=command.CHECKOUT_POLICY),   # every type
            'environment': verification_evidence.environment(env),
            'provenance': {'source': 'approved-contract', 'plan_sha': sha, 'milestone': milestone['id']}}


def _milestone_criteria(milestone, criterion=None):
    """What the check is asked: a reviewer's approved criteria; for a command or an adapter (whose check IDs exist only in its receipt) the
    milestone itself, or the finding criterion a recheck has to cover."""
    configured = milestone['verifier']['config'].get('criteria')
    if configured: return configured
    return [{'id': criterion or milestone['id'], 'covers': milestone.get('covers', []), 'verifier': milestone['verifier']['type']}]


def _milestone_request(ledger, task_id, name, revision, sha, contract, milestone, candidate, env=None, criterion=None):
    """review_request.build_check for one approved milestone on one candidate; the execution facts are also the evidence inputs."""
    from . import verification_evidence
    from .verifiers import command
    subject = {'plan': name, 'milestone': milestone['id'], 'candidate': candidate, 'plan_sha': sha}
    env = command.verifier_env(ledger.project) if env is None else env
    execution = _milestone_execution(ledger, milestone, sha, env)
    criteria = _milestone_criteria(milestone, criterion)
    acceptance = dict(zip(contracts.output_ids(contract['output']), contract['output']))
    return review_request.build_check(kind='milestone', root={'project_id': ledger.project_id, 'task_id': task_id},
        contract_revision=revision, contract_sha=sha, subject=subject, required=True,
        criteria=criteria,
        scope={'owned': sorted(contract['scope']['owned'])},
        policy=review_policy.normalize(contract.get('review_policy', review_policy.DEFAULT)),
        authority=contract.get('authority', {}), budget=contract['budget'],
        inputs={'artifact': candidate, 'revision': revision,
                'acceptance': {'milestone': milestone['id'], 'covers': {key: acceptance.get(key) for key in milestone.get('covers', [])}},
                'inputs': {'milestone': milestone['id']}, 'configuration': {'plan_sha': sha, 'verifier': execution['configuration'], 'type': milestone['verifier']['type']},   # carries checkout_policy
                'environment': verification_evidence.environment(env), 'checks': [row['id'] for row in criteria]},
        execution=execution)


def milestone_request(ledger, selector, milestone_id, candidate):
    """The request of one approved milestone on one candidate tree/artifact (the subject both verdict.run and CandidateChecker execute)."""
    with ledger.transaction() as conn:
        state = plan.anchor_events(ledger, conn, selector)
        target = plan.resolve(ledger, state)
        if target is None: raise LedgerError('Plan ' + str(selector) + ' has nothing approved to check.')
        contract, sha = plan.load(ledger, state, target['revision'])
    milestone = next((m for m in contract['milestones'] if m['id'] == milestone_id), None)
    if milestone is None: raise LedgerError('Unknown milestone ' + str(milestone_id) + '.')
    return _milestone_request(ledger, state['task_id'], state['name'], target['revision'], sha, contract, milestone, candidate)


def _state(run):
    if run['finished']: return 'finished'
    if run['issued']: return 'issued'
    if run['held']: return 'held'
    return 'running'


def _parented(runs):
    """A child claim (CandidateChecker milestone claim) that never finished follows its parent node run: held with it, released with it."""
    for run in runs.values():
        parent = runs.get(run.get('parent'))
        if parent is None or run['finished'] or run['issued']: continue
        if parent['finished'] and parent['finished'].get('outcome') == 'released':
            run['finished'] = dict(parent['finished'], run_id=run['run_id'], inherited_from=parent['run_id'])
        elif parent['held'] and not run['held']:
            run['held'] = dict(parent['held'], run_id=run['run_id'], inherited_from=parent['run_id'])
    return runs


def _lost(run):
    """Its process is gone here, or it is past its own deadline (what keeps a reused pid or another machine's run from pending forever).
    Lost is not a result: the run is held, never replayed."""
    from .verdict import this_host, process_alive, _when, _now
    if run.get('host') == this_host() and not process_alive(run.get('pid')): return True
    deadline = _when(run.get('deadline')) if run.get('deadline') else None
    return deadline is None or _now() > deadline                  # like verdict.lost_reason: a row with no readable deadline holds nothing for ever


def _deadline(seconds):
    from .verdict import _now, RUN_GRACE_SECONDS
    return (_now() + dt.timedelta(seconds=seconds + RUN_GRACE_SECONDS)).isoformat()


def check_deadline(cap_seconds, checks, root_deadline):
    """Liveness allowance includes snapshot work but never extends the root."""
    from .verifiers import command
    limit = _deadline(2 * cap_seconds + 3 * max(1, checks) * command.snapshot_seconds())
    return min(dt.datetime.fromisoformat(limit), dt.datetime.fromisoformat(root_deadline)).isoformat()


def verdict_conflict(conn, task_id, request):
    """An unfinished lifecycle run of the same work (any door), for verdict._begin_run's own claim transaction; None when none."""
    key = _work_key(request)
    for run in reversed(list(_parented(_runs(conn, task_id)).values())):
        if _work_key(run['request']) == key and _state(run) != 'finished':
            return {'run_id': run['run_id'], 'door': run.get('door', 'optional'), 'state': _state(run)}
    return None


def _check_view(run, status, **extra):
    return dict({'status': status, 'run_id': run['run_id'], 'request_id': run['request']['id'], 'door': run.get('door', 'optional'),
                 'check': run.get('check', 'optional'), 'subject': run.get('subject'),
                 'reason': (run['held'] or {}).get('reason') if status == 'held' else None,
                 'grants_authority': False}, **extra)


def claim_check(ledger, selector, request, *, door, subject, check=CHECK_MILESTONE, parent=None, deadline=None, conn=None):
    """One atomic claim per request id. Returns {'status': 'claimed'|'pending'|'held'|'issued', 'run_id', ...}.
    pending: the same request runs now (in any door, verdict.run included); held: its outcome is unknown (never replayed);
    issued: a result exists and must be reconciled, not re-run. Finished runs are not consulted here (reuse is the caller's rule)."""
    if conn is None:
        with ledger.transaction(write=True) as connection:
            return claim_check(ledger, selector, request, door=door, subject=subject, check=check, parent=parent, deadline=deadline, conn=connection)
    from .verdict import this_host, unsettled_run
    from ..ledger import utcnow
    root = plan.anchor_events(ledger, conn, selector)
    key = _work_key(request)
    deadline = deadline or _deadline(CLAIM_SECONDS)
    for run in reversed(list(_parented(_runs(conn, root['task_id'])).values())):
        if _work_key(run['request']) != key or run['finished']: continue
        if run['issued']: return _check_view(run, 'issued')
        if run['held']: return _check_view(run, 'held')
        if _lost(run):
            reason = 'The process of this check is gone or past its deadline and it issued no result: its effect is unknown; it is not run again by itself.'
            plan.emit(ledger, conn, root['task_id'], 'review.run_held',
                      {'run_id': run['run_id'], 'request_id': request['id'], 'reason': reason, 'grants_authority': False})
            return _check_view(dict(run, held={'reason': reason}), 'held')
        return _check_view(run, 'pending')
    found = unsettled_run(ledger, conn, root['task_id'], lambda other: _work_key(other) == key)
    if found:
        state, other, reason = found
        view = {'status': 'held' if state == 'held' else 'pending', 'run_id': other.get('run_id'), 'request_id': request['id'], 'door': 'verdict.run',
                'check': CHECK_MILESTONE, 'subject': subject, 'reason': reason, 'grants_authority': False}
        if state == 'held':
            view['next'] = (f"Check what the run did, then `onecrew verdict release-run --plan {other.get('plan')} --run {other.get('run_id')} --reason \"...\"`. "
                            'Nothing is run again by itself.')
        return view
    run = {'run_id': uuid.uuid4().hex, 'check': check, 'door': door, 'request': request, 'subject': subject, 'parent': parent,
           'root': root['task_id'], 'pid': os.getpid(), 'host': this_host(), 'started': utcnow(), 'deadline': deadline,
           # identity metadata may be complete; independence is a separate judgement made from actual provenance (never declared here)
           'independence': 'not_established', 'grants_authority': False}
    plan.emit(ledger, conn, root['task_id'], 'review.run_started', dict(run, request_id=request['id']))
    return _check_view(dict(run, issued=None, finished=None, held=None), 'claimed')


def issue_check(ledger, selector, run_id, receipt):
    """Announce the result blob of a run before any publication. Returns the run state at that moment ('running' or 'held': a late
    result of a held run is kept as evidence and only reconcile may publish it; 'finished': released/closed meanwhile)."""
    with ledger.transaction(write=True) as conn:
        root = plan.anchor_events(ledger, conn, selector)
        run = _parented(_runs(conn, root['task_id'])).get(run_id)
        if run is None: raise LedgerError('Unknown check run in this root.')
        if not run['issued']:
            plan.emit(ledger, conn, root['task_id'], 'review.run_result',
                      {'run_id': run_id, 'request_id': run['request']['id'], 'receipt': receipt, 'grants_authority': False})
        return 'finished' if run['finished'] else 'held' if run['held'] else 'running'


def finish_check(ledger, conn, task_id, run_id, *, outcome, receipt=None, applicable=False, **extra):
    """Close a run inside the caller's transaction (the publication and the end of the run commit together). Idempotent."""
    run = _runs(conn, task_id).get(run_id)
    if run is None or run['finished']: return False
    plan.emit(ledger, conn, task_id, 'review.run_finished', dict({'run_id': run_id, 'request_id': run['request']['id'], 'receipt': receipt,
              'applicable': bool(applicable), 'outcome': outcome, 'door': run.get('door', 'optional'), 'grants_authority': False}, **extra))
    return True


def active_checks(ledger, selector):
    """Unfinished, unheld lifecycle runs (what is being checked now, by which door). Read-only: the hook and status views use it."""
    with ledger.transaction() as conn:
        root = plan.anchor_events(ledger, conn, selector)
        runs = _parented(_runs(conn, root['task_id']))
    return [{'run_id': r['run_id'], 'door': r.get('door', 'optional'), 'check': r.get('check', 'optional'),
             'node': (r.get('subject') or {}).get('node', r.get('node')), 'milestone': (r.get('subject') or {}).get('milestone'),
             'request_id': r['request']['id'], 'started': r.get('started'), 'state': _state(r)}
            for r in runs.values() if _state(r) in ('running', 'issued') and not _lost(r)]


def _run_rows(conn, task_id):
    """One neutral row per run of any door, from the events only (for reports and for authenticating a receipt)."""
    from .verdict import run_records, _reconcile_events, _hold_of
    rows = []
    for run in _parented(_runs(conn, task_id)).values():
        finished = run['finished'] or {}
        issued = run['issued'] or {}
        outcome = finished.get('outcome') or ('observed' if run['finished'] else None)
        rows.append({'run_id': run['run_id'], 'door': run.get('door', 'optional'), 'check': run.get('check', 'optional'), 'request_id': run['request']['id'],
                     'request': run['request'], 'subject': run.get('subject') or {'node': run.get('node'), 'review_id': run.get('review_id')},
                     'state': _state(run), 'outcome': outcome, 'receipt': finished.get('proof') or finished.get('receipt') or issued.get('receipt'),
                     'result': finished.get('result'), 'parent': run.get('parent'), 'started': run.get('started')})
    results = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='verdict.recorded' ORDER BY seq", (task_id,)).fetchall()
    recorded = {body.get('receipt'): body.get('result') for body in (json.loads(row['payload']) for row in results)}
    marks = _reconcile_events(conn, task_id)
    for run in run_records(conn, task_id):
        receipt = (run.get('receipt') or {}).get('receipt')
        own = marks.get(run.get('run_id'), {})
        state = 'issued' if receipt else 'abandoned' if run.get('abandoned') else 'running'
        outcome = 'recorded' if receipt in recorded else None
        if 'verdict.run_released' in own: state, outcome = 'finished', 'released'
        elif receipt in recorded: state = 'finished'
        elif _hold_of(own) is not None: state = 'held'
        rows.append({'run_id': run.get('run_id'), 'door': 'verdict.run', 'check': CHECK_MILESTONE, 'request_id': run.get('request_id'), 'request': run.get('request'),
                     'subject': {'milestone': run.get('milestone'), 'candidate': run.get('candidate')},
                     'state': state, 'outcome': outcome, 'receipt': receipt,
                     'result': recorded.get(receipt), 'parent': None, 'started': run.get('started')})
    return rows


def check_runs(ledger, selector):
    """Every check run of this root and how it stands. Read-only; a missing link stays None."""
    with ledger.transaction() as conn:
        root = plan.anchor_events(ledger, conn, selector)
        return _run_rows(conn, root['task_id'])


def run_of_receipt(conn, task_id, receipt):
    """The run that issued this very receipt blob, or None: a receipt no run issued is authentic evidence of nothing."""
    return next((row for row in _run_rows(conn, task_id) if row['receipt'] == receipt), None)


def recheck_request(ledger, selector, finding, receipt):
    """The request findings.close_from_recheck needs, built from a receipt a door really issued for the repaired output (2.5-A interface).
    A receipt no run of this root issued gets no request. Closing still judges the receipt itself; this only names what was checked."""
    with ledger.transaction() as conn:
        state = plan.anchor_events(ledger, conn, selector)
        run = run_of_receipt(conn, state['task_id'], receipt)
        target = plan.resolve(ledger, state)
    if run is None: raise LedgerError('No check run of this root issued this receipt; it cannot be a recheck.')
    if target is None: raise LedgerError('Plan ' + str(selector) + ' has nothing approved to check.')
    if finding.get('internal'):
        root, contract, item, facts = _context(ledger, selector, finding['node'])
        checks = [check['id'] for check in item['checks']]
        return review_request.build_check(kind='node', root={'project_id': ledger.project_id, 'task_id': root['task_id']},
            contract_revision=root['approved']['revision'], contract_sha=root['approved']['sha'], review_id=CHECK_NODE, required=True, subject=facts,
            scope={k: item.get(k, []) for k in ('read', 'write', 'acceptance')}, criteria=item['checks'],
            policy=review_policy.normalize(contract.get('review_policy', review_policy.DEFAULT)), authority=contract.get('authority', {}), budget=contract['budget'],
            inputs={'artifact': facts['artifact'], 'revision': root['approved']['revision'], 'acceptance': {key: True for key in item.get('acceptance', [])} or {'node': finding['node']},
                    'inputs': dict(facts['inputs']) or {'node': finding['node']}, 'configuration': {'checks_sha': facts['checks_sha']},
                    'environment': {'run': run['run_id']}, 'checks': checks},
            execution=None)
    contract, sha = plan.load(ledger, state, target['revision'])
    milestone = next((m for m in contract['milestones'] if m['id'] == finding['node']), None)
    if milestone is None: raise LedgerError('The finding names no milestone of the approved contract.')
    candidate = json.loads(Snapshots(ledger.state_root).read_blob(receipt)).get('artifact_sha')
    return _milestone_request(ledger, state['task_id'], state['name'], target['revision'], sha, contract, milestone, candidate, criterion=finding.get('criterion'))


def prior_pass(conn, task_id, request, *, exclude_proof=None):
    """The run whose pass of exactly this request may be reused: a finished candidate claim (its proof) or a verdict.run whose issued receipt
    was recorded. {run_id, door, proof} or None. Only the NEWEST result of this work counts, across both doors: a later fail or inconclusive
    stops reuse, whatever passed before it. Exact request id and complete execution identity only: an unknown checker is never equal to
    anything. The caller authenticates the proof against the approved milestone (proof_mismatch)."""
    from .verdict import run_records
    key, history = _work_key(request), []
    for run in _runs(conn, task_id).values():
        finished = run['finished']
        if run.get('check') == CHECK_MILESTONE and finished and finished.get('outcome') == 'observed' and _work_key(run['request']) == key:
            history.append((run['finished_seq'], finished.get('result'), run['request'],
                            {'run_id': run['run_id'], 'door': run.get('door'), 'proof': finished.get('proof')}))
    rows = conn.execute("SELECT seq,payload FROM events WHERE task_id=? AND kind='verdict.recorded' ORDER BY seq", (task_id,)).fetchall()
    recorded = {body.get('receipt'): (row['seq'], body.get('result')) for row, body in ((row, json.loads(row['payload'])) for row in rows)}
    for run in run_records(conn, task_id):
        receipt = (run.get('receipt') or {}).get('receipt')
        if receipt == exclude_proof: continue  # validate a derived receipt against its source, not against itself
        if isinstance(run.get('request'), dict) and _work_key(run['request']) == key and receipt in recorded:
            history.append((*recorded[receipt], run['request'], {'run_id': run.get('run_id'), 'door': 'verdict.run', 'proof': receipt}))
    if not history: return None
    _, result, previous, view = max(history, key=lambda row: row[0])
    if result != 'pass' or not view['proof'] or previous.get('id') != request['id']: return None
    return view if review_request.evidence_status(previous, request)['status'] == 'applies' else None


def published_run(conn, task_id, node, receipt):
    """The node-verification run whose published receipt is `receipt` (None for a verification written before cycle 2)."""
    for run in _runs(conn, task_id).values():
        if (run.get('check') == CHECK_NODE and (run.get('subject') or {}).get('node') == node and run['finished']
                and run['finished'].get('outcome') == 'published' and run['finished'].get('receipt') == receipt):
            return run['run_id']
    return None


def settle_released_attempts(ledger, task_id, contexts, note):
    """A release decides that a run of unknown outcome may run again. Its metered provider attempts (Control refuses another call while one
    is open) settle as what they are: charged, never refunded, with the release as the reason. Attempts of other runs are not touched."""
    from ..control_core import Control, migrate
    if not contexts: return []
    migrate(ledger)
    marks = ','.join('?' for _ in contexts)
    with ledger.transaction() as conn:
        rows = conn.execute(f"SELECT id,generation FROM attempts WHERE status IN ('reserved','running','unknown') "
                            f"AND json_extract(operation,'$.verifier_root')=? AND json_extract(operation,'$.verifier_context') IN ({marks})",
                            (task_id, *contexts)).fetchall()
    control = Control(ledger)
    for row in rows:
        control.finish(row['id'], row['generation'], {'released': note, 'outcome': 'unknown', 'provider_invocations': 1})
    return [row['id'] for row in rows]


def _attempt_contexts(runs):
    contexts = []
    for run in runs:
        subject = run.get('subject') or {}
        if subject.get('milestone') and subject.get('node') and subject.get('artifact'):
            contexts.append('candidate:' + subject['node'] + ':' + subject['artifact'] + ':' + subject['milestone'])
        if run.get('review_id') and run.get('node') and run.get('artifact'):
            contexts.append('investigation:' + run['node'] + ':' + run['artifact'] + ':' + run['review_id'])
    return contexts


def issued_node_body(ledger, run):
    """The node-verifier receipt a run announced, or LedgerError: its blob is lost, damaged or not this run's."""
    receipt, subject = run['issued']['receipt'], run['subject']
    try:
        data = Snapshots(ledger.state_root).read_blob(receipt)
        if hashlib.sha256(data).hexdigest() != receipt: raise ValueError('receipt hash differs')
        body = json.loads(data)
        if (body.get('kind') != 'node-verifier-receipt' or body.get('root') != run['root'] or body.get('node') != subject['node']
                or body.get('generation') != subject['generation'] or body.get('artifact') != subject['artifact']):
            raise ValueError('receipt binding differs')
        return body
    except (OSError, ValueError, TypeError, LedgerError) as error:
        raise LedgerError('Issued check evidence of run ' + run['run_id'] + ' is missing or invalid: ' + type(error).__name__) from error


def _issued_readable(ledger, run):
    if not run['issued']: return True
    try:
        (issued_node_body if run.get('check') == CHECK_NODE else _issued_body)(ledger, run)
        return True
    except LedgerError:
        return False


def receipt_lost_view(ledger, selector, nid, run):
    """An issued result that cannot be read: not a pass and not a reason to run again. Held until a recorded decision (release_check)."""
    reason = ('The result of this run was issued but its receipt is missing or damaged. It is not a pass, and the check is not run again by itself.')
    _hold(ledger, selector, run['run_id'], reason)
    return {'status': 'held', 'node': nid, 'result': None, 'executed': False, 'reason': reason, 'next': _next(selector, run['run_id']),
            'check_run': node_check_view({'run_id': run['run_id'], 'request_id': run['request']['id'], 'door': run.get('door', 'optional')}, request=run['request'])}


def held_note(ledger, selector, nid):
    """What a door shows about the held required check of this node: {} when none."""
    with ledger.transaction() as conn:
        root = plan.anchor_events(ledger, conn, selector)
        runs = _parented(_runs(conn, root['task_id']))
    for run in reversed(list(runs.values())):
        if run.get('check') == CHECK_NODE and (run.get('subject') or {}).get('node') == nid and run['held'] and not run['finished']:
            return {'held_reason': run['held'].get('reason'), 'next': _next(root['selector'], run['run_id']),
                    'check_run': {'run_id': run['run_id'], 'request_id': run['request']['id'], 'door': run.get('door', 'optional'), 'state': 'held'}}
    return {}


def released_seq(conn, task_id):
    """node -> the ledger position of the last recorded decision that closed a held check of that node (automatic tries count from there)."""
    closed = {}
    for run in _runs(conn, task_id).values():
        if run.get('check') == CHECK_NODE and run['finished'] and run['finished'].get('outcome') in ('released', 'receipt_lost'):
            nid = (run.get('subject') or {}).get('node')
            closed[nid] = max(closed.get(nid, 0), run['finished_seq'])
    return closed


def release_check(ledger, selector, run_id, reason):
    """The explicit decision that lets a held request be checked again (mirrors verdict.release_run). It records who and why, keeps the
    spent budget spent and promises no exactly-once: the first dispatch may have had an effect. A run with an issued result is settled
    by reconcile_check from that result, never released."""
    from ..ledger import text_field
    text_field(reason, 'reason', 2000)
    with ledger.transaction(write=True) as conn:
        root = plan.anchor_events(ledger, conn, selector)
        runs = _parented(_runs(conn, root['task_id']))
        run = runs.get(run_id)
        if run is None: raise LedgerError('Unknown check run in this root; a verdict run is released with `onecrew verdict release-run`.')
        payload = {'reason': reason.strip(), 'actor': os.environ.get('ONECREW_ACTOR') or 'unknown', 'budget_reset': False,
                   'note': 'A release lets the check run a second time; the first dispatch may have had an effect. Exactly-once is not promised.'}
        readable = _issued_readable(ledger, run)
        if run['finished'] and run.get('check', 'optional') == 'optional' and run['finished'].get('applicable') and not readable:
            # a finished observation whose receipt was lost later: retired, so it is not reused and not read again
            plan.emit(ledger, conn, root['task_id'], 'review.run_finished', dict(payload, run_id=run_id, request_id=run['request']['id'], receipt=None,
                      applicable=False, outcome='receipt_lost', door='optional', grants_authority=False))
            Snapshots(ledger.state_root).set_aside_damaged(run['issued']['receipt'])
            return dict(payload, run_id=run_id, request_id=run['request']['id'], status='receipt_lost', settled_attempts=[])
        if run['issued'] and not run['finished'] and readable:
            raise LedgerError(f'Run {run_id} has an issued result; settle it with reconcile-check instead of releasing it.')
        if _state(run) not in ('held', 'issued'):
            raise LedgerError(f'Run {run_id} is not held (it is {_state(run)}); only a held run of unknown outcome is released.')
        # a damaged or lost result is not a result: closed by this recorded decision, never a pass
        finish_check(ledger, conn, root['task_id'], run_id, outcome='receipt_lost' if run['issued'] else 'released', **payload)
        if run['issued']: Snapshots(ledger.state_root).set_aside_damaged(run['issued']['receipt'])
        children = [child for child in runs.values() if child.get('parent') == run_id and not child['finished'] and not child['issued']]
        for child in children:
            finish_check(ledger, conn, root['task_id'], child['run_id'], outcome='released', inherited_from=run_id, **payload)
    attempts = settle_released_attempts(ledger, root['task_id'], _attempt_contexts([run] + children), 'run ' + run_id + ': ' + payload['reason'][:300])
    return dict(payload, run_id=run_id, request_id=run['request']['id'], status='released', settled_attempts=attempts)


def reconcile_check(ledger, selector, run_id):
    """Settle one run from what is known, never by running it again: finished -> its outcome; an issued result -> published (or stale)
    from that very receipt; no result and a live process -> pending; otherwise held with the reason (release_check after checking)."""
    with ledger.transaction() as conn:
        root = plan.anchor_events(ledger, conn, selector)
        run = _parented(_runs(conn, root['task_id'])).get(run_id)
    if run is None: raise LedgerError('Unknown check run in this root.')
    closed = run['finished'] and run['finished'].get('outcome') in ('released', 'receipt_lost', 'not_dispatched')
    if run.get('check', 'optional') == 'optional' and not closed: return reconcile_optional(ledger, selector, run_id)
    if run['finished']: return _check_view(run, 'finished', outcome=run['finished'].get('outcome'), receipt=run['finished'].get('receipt'))
    if run['issued'] and run.get('check') == CHECK_NODE:
        return engine.publish_issued(ledger, root['selector'], run)
    if run['issued']: return _check_view(run, 'issued', receipt=run['issued']['receipt'])
    if run['held'] or _lost(run):
        if not run['held']:
            _hold(ledger, root['selector'], run_id, 'The process of this check is gone or past its deadline and it issued no result: its effect is unknown.')
            with ledger.transaction() as conn:
                run = _parented(_runs(conn, root['task_id']))[run_id]
        return _check_view(run, 'held', next=_next(root['selector'], run_id))
    return _check_view(run, 'pending')


def _next(selector, run_id):
    return (f'Check what the run did, then `onecrew engine release-check {selector} {run_id} --reason "..."`; '
            f'`onecrew engine reconcile-check {selector} {run_id}` shows it again. Nothing is run again by itself.')


def node_request(ledger, selector, nid, execution=None, conn=None):
    """The required node-verification request (review_request.build, the existing node descriptor) from the current engine facts."""
    root, contract, item, facts = _context(ledger, selector, nid, conn)
    return root, item, facts, review_request.build_check(kind='node', root={'project_id': ledger.project_id, 'task_id': root['task_id']},
        contract_revision=root['approved']['revision'], contract_sha=root['approved']['sha'],
        review_id=CHECK_NODE, required=True, subject=facts,
        scope={k: item.get(k, []) for k in ('read', 'write', 'acceptance')}, criteria=item['checks'],
        policy=review_policy.normalize(contract.get('review_policy', review_policy.DEFAULT)),
        authority=contract.get('authority', {}), budget=contract['budget'], inputs=None, execution=execution)


def claim_node_check(ledger, selector, nid, *, execution, door, expected):
    """engine.verify's claim: the request is computed from the facts read inside the same write transaction as the claim. `expected` is the
    (artifact, generation) the caller decided on: another door may have published or moved the node since, and that is not a new request."""
    with ledger.transaction(write=True) as conn:
        root, item, facts, request = node_request(ledger, selector, nid, execution, conn)
        if facts['state'] != 'produced' or facts['phase'] == 'held' or (facts['artifact'], facts['generation']) != tuple(expected):
            raise LedgerError('The node changed before its check was claimed (another door may have finished it); nothing was dispatched.')
        subject = {'node': nid, 'generation': facts['generation'], 'artifact': facts['artifact'],
                   'internal_revision': facts['internal_revision']}
        # the same allowance as the tools fence (engine._claim_tools): twice the node cap, the first check still has its own deadlines
        return claim_check(ledger, root['selector'], request, door=door, subject=subject, check=CHECK_NODE,
                           deadline=check_deadline(item['execution_cap_seconds'], len(item['checks']),
                               ip.ceilings(ledger, conn, root)['deadline']), conn=conn), request


def node_check_view(claim, *, executed=False, reconciled=False, request=None):
    request = request or {}
    return {'run_id': claim['run_id'], 'request_id': claim['request_id'], 'door': claim['door'], 'executed': executed,
            'reconciled': reconciled, 'cache_reusable': bool(request.get('execution_complete')),
            'identity_missing': list(request.get('missing', [])), 'grants_authority': False}


def run_held_view(selector, nid, claim, request=None):
    return {'status': claim['status'], 'node': nid, 'result': None, 'executed': False,
            'reason': claim.get('reason') or ('the same check is already running in ' + claim['door'] if claim['status'] == 'pending' else None),
            **({'next': claim.get('next') or _next(selector, claim['run_id'])} if claim['status'] == 'held' else {}),
            'check_run': node_check_view(claim, request=request)}


def _runs(conn, task_id):
    runs = {}
    marks = ','.join('?' for _ in _RUN_KINDS)
    for row in conn.execute(f'SELECT seq,kind,payload FROM events WHERE task_id=? AND kind IN ({marks}) ORDER BY seq',
                            (task_id, *_RUN_KINDS)):
        body = json.loads(row['payload']); run_id = body['run_id']
        if row['kind'] == 'review.run_started': runs[run_id] = dict(body, issued=None, finished=None, held=None, finished_seq=None)
        elif run_id in runs:
            runs[run_id][{'review.run_result': 'issued', 'review.run_finished': 'finished', 'review.run_held': 'held'}[row['kind']]] = body
            if row['kind'] == 'review.run_finished': runs[run_id]['finished_seq'] = row['seq']
    return runs


def _run_result(run, *, status, receipt=None, executed=False, cached=False, applicable=False):
    return {'status': status, 'run_id': run['run_id'], 'request_id': run['request']['id'],
            'node': run['node'], 'review_id': run['review_id'], 'artifact': run['artifact'],
            'executed': executed, 'receipt': receipt, 'cached_observation': cached,
            'cache_reusable': bool(applicable and run['request']['execution_complete']),
            'changes_node_state': False, 'grants_authority': False,
            'identity_missing': run['request']['missing']}


def _issued_body(ledger, run):
    """Only a receipt announced by this run can settle it; no caller-supplied result."""
    issued = run['issued']
    if not issued: raise LedgerError('Optional review has no issued result; its outcome remains unknown.')
    ref = issued['receipt']
    try:
        if (not review_request.applicability(run['request'], run['request'])['applicable']
                or not review_request.applicability(run['context_request'], run['context_request'])['applicable']
                or issued.get('request_id') != run['request']['id']):
            raise ValueError('run identity is invalid')
        original = {k: v for k, v in run['request']['identity'].items() if k != 'execution'}
        context = {k: v for k, v in run['context_request']['identity'].items() if k != 'execution'}
        if (original != context or original['root'] != {'project_id': ledger.project_id, 'task_id': run['root']}
                or original['contract_revision'] != run['revision'] or original['review_id'] != run['review_id']
                or original['required'] or original['facts'] != content_hash(run['facts'])):
            raise ValueError('run context binding differs')
        data = Snapshots(ledger.state_root).read_blob(ref)
        if hashlib.sha256(data).hexdigest() != ref: raise ValueError('receipt hash differs')
        body = json.loads(data)
        if (body.get('kind') != 'optional-review-observation' or body.get('root') != run['root']
                or body.get('run_id') != run['run_id'] or body.get('request') != run['request']
                or body.get('node') != run['node'] or body.get('review_id') != run['review_id']
                or body.get('inputs') != run['facts'] or body.get('decision_key') != run['decision_key']
                or body.get('authority') != 'none' or not isinstance(body.get('observed'), dict)):
            raise ValueError('receipt binding differs')
        return ref, body
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise LedgerError('Issued optional review evidence of run ' + run['run_id'] + ' is missing or invalid; no redispatch: ' + type(error).__name__
                          + '. `onecrew engine release-check PLAN RUN --reason "..."` records the decision to ask again.') from error


def _hold(ledger, selector, run_id, reason):
    with ledger.transaction(write=True) as conn:
        root = plan.anchor_events(ledger, conn, selector)
        run = _runs(conn, root['task_id']).get(run_id)
        if run and not run['finished'] and not run['held']:
            plan.emit(ledger, conn, root['task_id'], 'review.run_held',
                      {'run_id': run_id, 'request_id': run['request']['id'], 'reason': reason, 'grants_authority': False})


def _current_request(ledger, selector, run, conn):
    try:
        root, contract, item, facts = _context(ledger, selector, run['node'], conn)
        # Execution configuration/environment may contain secrets. Only their
        # fingerprints belong in the run. Reconcile proves the current root,
        # scope and inputs, not a newly observed provider/environment identity.
        return _request(ledger, root, contract, item, facts, run['review_id'], None)
    except LedgerError:
        return None


def _publish_optional(ledger, selector, run_id, *, executed=False):
    with ledger.transaction(write=True) as conn:
        root = plan.anchor_events(ledger, conn, selector)
        run = _runs(conn, root['task_id']).get(run_id)
        if run is None: raise LedgerError('Unknown optional review run in this root.')
        ref, body = _issued_body(ledger, run)
        current = _current_request(ledger, selector, run, conn)
        applicable = bool(current and review_request.applicability(run['context_request'], current)['applicable'])
        if run['finished']:
            applicable = applicable and run['finished']['applicable']
        else:
            plan.emit(ledger, conn, root['task_id'], 'review.observed', {
                'plan': root['name'], 'revision': run['revision'], 'node': run['node'], 'review_id': run['review_id'],
                'decision_key': run['decision_key'], 'receipt': ref, 'applicable': applicable,
                'internal_revision': run['facts']['internal_revision'], 'generation': run['facts']['generation'],
                'artifact': run['artifact'], 'run_id': run_id, 'request_id': run['request']['id'], 'grants_authority': False})
            plan.emit(ledger, conn, root['task_id'], 'review.run_finished',
                      {'run_id': run_id, 'request_id': run['request']['id'], 'receipt': ref,
                       'applicable': applicable, 'grants_authority': False})
    return dict(_run_result(run, status='observed' if applicable else 'stale_observation', receipt=ref,
                            executed=executed, applicable=applicable),
                reconciled=not executed and not bool(run['finished']))


def reconcile_optional(ledger, selector, run_id):
    """Observe existing issued evidence; never rerun a checker or accept a claimed outcome."""
    with ledger.transaction() as conn:
        root = plan.anchor_events(ledger, conn, selector)
        run = _runs(conn, root['task_id']).get(run_id)
    if run is None: raise LedgerError('Unknown optional review run in this root.')
    if run['issued'] and (run['finished'] or _issued_readable(ledger, run)): return _publish_optional(ledger, root['selector'], run_id)
    if run['held'] or run['issued'] or _lost(run):
        reason = ('The result of this run was issued but its receipt is missing or damaged; it is not used and not run again by itself.'
                  if run['issued'] else 'Outcome unknown; no issued result, no automatic retry.')
        _hold(ledger, root['selector'], run_id, reason)
        return dict(_run_result(run, status='held'), reason=(run['held'] or {}).get('reason') or reason, next=_next(root['selector'], run_id))
    return _run_result(run, status='pending')


def optional(ledger, selector, node, review_id, checker, artifact, *, execution=None):
    """Skip/defer/hold before any call, or retain a non-authoritative observation."""
    key_field(review_id)
    root, contract, item, facts = _context(ledger, selector, node)
    nodes = engine.state(ledger, root['selector'])['definition']['nodes']
    mandatory = {m['id'] for m in contract['milestones']} | {n['id'] for n in nodes}
    mandatory.update(check['id'] for n in nodes for check in n['checks'])
    if review_id in mandatory:
        raise LedgerError('A required node, check or contract milestone is not an optional review.')
    policy = review_policy.normalize(contract.get('review_policy', review_policy.DEFAULT))
    if review_id not in policy['optional_reviews']:
        raise LedgerError('Optional review ID is not sealed in the approved root policy.')
    if artifact != facts['artifact']:
        raise LedgerError('Optional review artifact does not match the current node.')
    decision = _decide(ledger, root['selector'], review_id, facts, required=False)
    result = {'decision': decision, 'node': node, 'review_id': review_id, 'artifact': artifact,
              'executed': False, 'receipt': None, 'changes_node_state': False}
    if decision['action'] != 'REVIEW':
        return dict(result, status={'SKIP': 'skipped', 'DEFER': 'deferred', 'HOLD': 'held'}[decision['action']])
    if _context(ledger, root['selector'], node)[3] != facts:
        raise LedgerError('Engine input changed before optional review; recompute the decision.')
    # RD-A: a proposal shown next to the result. The decision above stays in force; failures fall back inside the call.
    result['advice'] = review_advice.compact(review_advice.advise_optional(ledger, root['selector'], node, review_id, facts=facts))
    request = _request(ledger, root, contract, item, facts, review_id, execution)
    context_request = _request(ledger, root, contract, item, facts, review_id, None)
    key = decision['record']['key']
    from .verdict import this_host
    reuse_run, reuse_completed = None, False
    with ledger.transaction(write=True) as conn:
        if _context(ledger, root['selector'], node, conn)[3] != facts:
            raise LedgerError('Engine input changed before optional claim; recompute the decision.')
        for old in reversed(list(_runs(conn, root['task_id']).values())):
            if old.get('check', 'optional') != 'optional' or not old['request'].get('identity'): continue
            if not old['finished']:
                if _optional_work(old['request']) == _optional_work(request):      # held or running from another shell is the same work
                    reuse_run = old['run_id']; break
                continue
            if old['request']['id'] != request['id']: continue
            if request['execution_complete'] and old['finished']['applicable']:
                _issued_body(ledger, old)
                reuse_run, reuse_completed = old['run_id'], True; break
        if reuse_run is None:
            if not callable(checker): raise LedgerError('A REVIEW decision requires a checker.')
            run = {'run_id': uuid.uuid4().hex, 'root': root['task_id'], 'revision': root['approved']['revision'],
                   'node': node, 'review_id': review_id, 'artifact': artifact, 'request': request, 'facts': facts,
                   'decision_key': key, 'context_request': context_request, 'deadline': _deadline(CLAIM_SECONDS),
                   'pid': os.getpid(), 'host': this_host(), 'grants_authority': False}
            plan.emit(ledger, conn, root['task_id'], 'review.run_started', run)
    if reuse_run:
        recovered = reconcile_optional(ledger, root['selector'], reuse_run)
        recovered['cached_observation'] = bool(reuse_completed and recovered['cache_reusable'])
        return dict(result, **recovered)
    try:
        token = _CURRENT.set(run['run_id'])
        try:
            observed = checker(copy.deepcopy(item), artifact)
        finally:
            _CURRENT.reset(token)
        if not isinstance(observed, dict) or len(canonical(observed).encode('utf-8')) > 65536:
            raise LedgerError('Optional review must return a bounded observation object.')
        # A receipt says what was observed, not that a mandatory check passed.
        body = {'kind': 'optional-review-observation', 'root': root['task_id'], 'review_id': review_id,
                'node': node, 'inputs': facts, 'decision_key': key, 'observed': observed, 'authority': 'none',
                'run_id': run['run_id'], 'request': request}
        receipt = Snapshots(ledger.state_root).blob(canonical(body).encode('utf-8'))
        with ledger.transaction(write=True) as conn:
            plan.emit(ledger, conn, root['task_id'], 'review.run_result',
                      {'run_id': run['run_id'], 'request_id': request['id'], 'receipt': receipt, 'grants_authority': False})
        return dict(result, **_publish_optional(ledger, root['selector'], run['run_id'], executed=True))
    except BaseException as error:
        if isinstance(error, NotDispatched) or getattr(error, 'not_dispatched', False):   # 2.5-B: refused before any effect: a known outcome, not a hold
            with ledger.transaction(write=True) as conn:
                finish_check(ledger, conn, root['task_id'], run['run_id'], outcome='not_dispatched', reason=str(error)[:500])
        else:
            _hold(ledger, root['selector'], run['run_id'], getattr(error, 'hold_reason', None) or 'Outcome unconfirmed: ' + type(error).__name__)
        raise
