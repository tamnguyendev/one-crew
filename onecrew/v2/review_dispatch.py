"""W26: engine consumers of the existing rules, never model decision authority.

Every configured node check is mandatory. Optional reviews are separate approved
policy IDs and never publish node.verification, acceptance, or a human request.
Injected checkers own their usual provider/budget boundary; this adapter does not
select models, change pins or implement provider fallback.
"""
import copy
import json
import hashlib
import os
import uuid

from ..ledger import LedgerError, canonical, content_hash, key_field
from ..snapshots import Snapshots
from . import engine, internal_plan as ip, plan, review_policy, review_request


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


def _runs(conn, task_id):
    runs = {}
    marks = ','.join('?' for _ in _RUN_KINDS)
    for row in conn.execute(f'SELECT kind,payload FROM events WHERE task_id=? AND kind IN ({marks}) ORDER BY seq',
                            (task_id, *_RUN_KINDS)):
        body = json.loads(row['payload']); run_id = body['run_id']
        if row['kind'] == 'review.run_started': runs[run_id] = dict(body, issued=None, finished=None, held=None)
        elif run_id in runs:
            runs[run_id][{'review.run_result': 'issued', 'review.run_finished': 'finished', 'review.run_held': 'held'}[row['kind']]] = body
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
        raise LedgerError('Issued optional review evidence is missing or invalid; no redispatch: ' + type(error).__name__) from error


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
    from .verdict import this_host, process_alive
    with ledger.transaction() as conn:
        root = plan.anchor_events(ledger, conn, selector)
        run = _runs(conn, root['task_id']).get(run_id)
    if run is None: raise LedgerError('Unknown optional review run in this root.')
    if run['issued']: return _publish_optional(ledger, root['selector'], run_id)
    alive = run.get('host') == this_host() and process_alive(run.get('pid'))
    if run['held'] or not alive:
        _hold(ledger, root['selector'], run_id, 'Outcome unknown; no issued result, no automatic retry.')
        return _run_result(run, status='held')
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
    request = _request(ledger, root, contract, item, facts, review_id, execution)
    context_request = _request(ledger, root, contract, item, facts, review_id, None)
    key = decision['record']['key']
    from .verdict import this_host
    reuse_run, reuse_completed = None, False
    with ledger.transaction(write=True) as conn:
        if _context(ledger, root['selector'], node, conn)[3] != facts:
            raise LedgerError('Engine input changed before optional claim; recompute the decision.')
        for old in reversed(list(_runs(conn, root['task_id']).values())):
            if old['request']['id'] != request['id']: continue
            if not old['finished']:
                reuse_run = old['run_id']; break
            if request['execution_complete'] and old['finished']['applicable']:
                _issued_body(ledger, old)
                reuse_run, reuse_completed = old['run_id'], True; break
        if reuse_run is None:
            if not callable(checker): raise LedgerError('A REVIEW decision requires a checker.')
            run = {'run_id': uuid.uuid4().hex, 'root': root['task_id'], 'revision': root['approved']['revision'],
                   'node': node, 'review_id': review_id, 'artifact': artifact, 'request': request, 'facts': facts,
                   'decision_key': key, 'context_request': context_request,
                   'pid': os.getpid(), 'host': this_host(), 'grants_authority': False}
            plan.emit(ledger, conn, root['task_id'], 'review.run_started', run)
    if reuse_run:
        recovered = reconcile_optional(ledger, root['selector'], reuse_run)
        recovered['cached_observation'] = bool(reuse_completed and recovered['cache_reusable'])
        return dict(result, **recovered)
    try:
        observed = checker(copy.deepcopy(item), artifact)
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
        _hold(ledger, root['selector'], run['run_id'], 'Outcome unconfirmed: ' + type(error).__name__)
        raise
