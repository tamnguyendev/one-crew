"""W06/W14a: one-slot adapter over shared ready_batch and Control admission.

Executors own their existing Control lifecycle. A callback cannot publish an
artifact until that attempt is settled; uncertainty holds the slot for existing
reconciliation. This module never launches a provider or implements recovery.
"""
import copy
import json
import re
from pathlib import Path

from .. import dependency_core
from ..ledger import LedgerError, canonical, content_hash
from ..snapshots import Snapshots
from ..task_intake import submit
from . import authority, estimates, executors, internal_plan as ip, namespaces, plan as plans, progress_track

STATES = {'produced': 1, 'verified': 2, 'accepted': 3}
KINDS = ('plan.revised', 'node.started', 'node.produced', 'node.verification', 'node.accepted', 'node.held', 'node.resumed')


def _fresh(nodes):
    records = dependency_core.initial_node_states(nodes)
    for record in records.values():
        record.update(state=None, artifact=None, attempt=None, early_runs={}, inputs={})
    return records


def state(ledger, selector, conn=None):
    if conn is None:
        with ledger.transaction() as connection:
            return state(ledger, selector, connection)
    root = plans.anchor_events(ledger, conn, selector)
    marks = ','.join('?' for _ in KINDS)
    events = conn.execute(f'SELECT seq,kind,payload FROM events WHERE task_id=? AND kind IN ({marks}) ORDER BY seq', (root['task_id'], *KINDS)).fetchall()
    definition, records, internal_revision, contract_sha, contract_revision = None, {}, 0, None, None
    store = Snapshots(ledger.state_root)
    for event in events:
        payload = json.loads(event['payload'])
        if event['kind'] == 'plan.revised':
            updated = json.loads(store.read_blob(payload['definition']))
            if content_hash(updated) != payload['definition_sha']:
                raise LedgerError('Internal definition hash mismatch.')
            old = {item['id']: item for item in definition['nodes']} if definition else {}
            changed = [item['id'] for item in updated['nodes'] if old.get(item['id']) != item or contract_sha != payload['contract_sha']]
            affected = dependency_core.affected_tasks(ip.projection(updated['nodes']), changed) if changed else set()
            fresh = _fresh(updated['nodes'])
            for nid, record in fresh.items():
                if nid in records:
                    if nid not in affected:
                        fresh[nid] = copy.deepcopy(records[nid])
                    else:
                        record['generation'] = records[nid]['generation'] + 1
                        record['early_runs'] = copy.deepcopy(records[nid]['early_runs'])
            definition, records = updated, fresh
            internal_revision, contract_sha, contract_revision = payload['internal_revision'], payload['contract_sha'], payload['revision']
            continue
        nid = payload.get('node')
        if (nid not in records or payload.get('generation') != records[nid]['generation']
                or payload.get('internal_revision') != internal_revision):
            continue
        record = records[nid]
        if event['kind'] == 'node.started':
            record.update(phase='running', child=payload['child'], attempt=payload['attempt'], inputs=payload.get('inputs', {}))
            for dependency in payload.get('early_dependencies', []):
                record['early_runs'][dependency] = record['early_runs'].get(dependency, 0) + 1
        elif event['kind'] == 'node.produced':
            record.update(phase='complete', state='produced', artifact=payload['artifact'], receipt=payload['receipt'])
        elif event['kind'] == 'node.verification':
            record['verification_receipt'] = payload['receipt']
            if payload['result'] == 'pass': record.update(phase='complete', state='verified')
        elif event['kind'] == 'node.accepted':
            record['state'] = 'accepted'
        elif event['kind'] == 'node.held':
            record.update(phase='held', reason=payload['reason'], classification=payload.get('classification'))
            if payload.get('candidate'): record['retained_candidate'] = payload['candidate']
        elif event['kind'] == 'node.resumed':
            fresh = _fresh([next(item for item in definition['nodes'] if item['id'] == nid)])[nid]
            fresh.update(generation=record['generation'] + 1, early_runs=copy.deepcopy(record['early_runs']))
            records[nid] = fresh
    approved = root['approved'] or {}
    inflight = False
    for record in records.values():
        if record['attempt']:
            attempt = conn.execute('SELECT status FROM attempts WHERE id=?', (record['attempt'],)).fetchone()
            if attempt and attempt['status'] != 'settled': inflight = True
    from . import runtime_unknowns
    return {'root': root['task_id'], 'selector': root['selector'], 'root_status': root['status'],
            'contract_revision': approved.get('revision'), 'contract_sha': approved.get('sha'),
            'definition_contract_revision': contract_revision, 'definition_contract_sha': contract_sha,
            'internal_revision': internal_revision, 'definition': definition, 'nodes': records, 'inflight': inflight,
            'unknown_blockers': runtime_unknowns.blockers(ledger, root['selector'], conn)}


def _rank(record):
    return 0 if record['phase'] == 'held' else STATES.get(record.get('state'), 0)


def _early_key(upstream, record):
    return upstream + ':' + str(record.get('artifact'))


def eligible(view, nid):
    if view['root_status'] != 'approved' or _unknown_blocks(view, nid):
        return {'ready': False, 'reason': 'Root is not approved or this node requires an unresolved fact'}
    if view['definition'] is None or nid not in view['nodes']:
        return {'ready': False, 'reason': 'No internal node ' + nid}
    record = view['nodes'][nid]
    if record['phase'] != 'pending':
        return {'ready': False, 'reason': nid + ' is already ' + record['phase']}
    node = next(node for node in view['definition']['nodes'] if node['id'] == nid)
    early = []
    for edge in node['depends']:
        upstream = view['nodes'][edge['node']]
        if _rank(upstream) < STATES[edge['requires']]:
            return {'ready': False, 'reason': edge['node'] + ' requires ' + edge['requires']}
        if edge['requires'] == 'produced' and _rank(upstream) < STATES['verified']:
            key = _early_key(edge['node'], upstream)
            advance = edge.get('advance')
            if not advance or record['early_runs'].get(key, 0) >= advance['limit']:
                return {'ready': False, 'reason': 'Bounded advance exhausted or absent for ' + edge['node']}
            early.append(key)
    return {'ready': True, 'reason': 'Every dependency satisfies its declared state', 'early_dependencies': early}


def _ready(view):
    # State requirements become the existing scheduler's dependency tokens. It
    # alone chooses order and disjoint ownership; this adapter supplies one slot.
    tasks, done, blocked = [], [], {}
    if view['definition'] and view['root_status'] == 'approved':
        for node in view['definition']['nodes']:
            nid, record = node['id'], view['nodes'][node['id']]
            rank = _rank(record)
            done.extend(nid + '@' + status for status, value in STATES.items() if rank >= value)
            if record['phase'] != 'pending': done.append(nid)
            dependencies = [edge['node'] + '@' + edge['requires'] for edge in node['depends']]
            if not eligible(view, nid)['ready'] or view['inflight']:
                blocked[nid] = True
            tasks.append({'id': nid, 'owned': node['write'], 'depends_on': dependencies})
    return dependency_core.ready_batch({'plan': {'tasks': tasks}, 'done': done, 'branch_errors': blocked})[:1]


def ready(ledger, selector):
    return _ready(state(ledger, selector))


def _event(ledger, conn, view, nid, kind, **payload):
    plans.emit(ledger, conn, view['root'], kind, dict(plan=namespaces.parse(view['selector'])[0],
               revision=view['contract_revision'], internal_revision=view['internal_revision'], node=nid,
               generation=view['nodes'][nid]['generation'], **payload))


def _forecast(ledger, view, key, reason):
    if view['definition'] is None: return
    nodes = [node for node in view['definition']['nodes'] if _rank(view['nodes'][node['id']]) < STATES['verified']]
    estimates.reforecast(ledger, view['selector'], key, [sum(node['estimate_seconds'][i] for node in nodes) for i in (0, 1)],
                        reason, ['internal-plan:' + str(view['internal_revision'])])


def _publication_current(current, original, nid):
    return (current['root_status'] == 'approved'
            and current['contract_sha'] == original['contract_sha']
            and current['contract_revision'] == original['contract_revision']
            and current['internal_revision'] == original['internal_revision']
            and nid in current['nodes']
            and not _unknown_blocks(current, nid)
            and current['nodes'][nid]['generation'] == original['nodes'][nid]['generation'])


def _unknown_blocks(view, nid):
    pending, seen = [nid], set()
    nodes = {node['id']: node for node in (view['definition'] or {}).get('nodes', [])}
    while pending:
        target = pending.pop()
        if target in seen: continue
        seen.add(target)
        if view.get('unknown_blockers', {}).get(target): return True
        pending.extend(edge['node'] for edge in nodes.get(target, {}).get('depends', []))
    return False


def _retain(ledger, conn, original, nid, reason, **evidence):
    # Reference the execution's original identities, never a newer generation.
    _event(ledger, conn, original, nid, 'node.result_retained', reason=reason,
           contract_sha=original['contract_sha'], grants_delivery=False, **evidence)


def publish_retained(ledger, selector):
    """A resolved fact can release a settled result without another model call."""
    with ledger.transaction(write=True) as conn:
        root, _, _ = ip.context(ledger, conn, selector, 'sequential-engine')
        view = state(ledger, root['selector'], conn)
        for nid, record in view['nodes'].items():
            if record['phase'] != 'running' or not _publication_current(view, view, nid): continue
            progress = progress_track.read(ledger, root['selector'], nid)
            if progress and progress['checkpoint']['status'] in ('blocked', 'waiting'): continue
            attempt = conn.execute('SELECT status FROM attempts WHERE id=?', (record['attempt'],)).fetchone()
            if not attempt or attempt['status'] != 'settled': continue
            for row in conn.execute("SELECT seq,payload FROM events WHERE task_id=? AND kind='node.result_retained' ORDER BY seq DESC", (view['root'],)):
                payload = json.loads(row['payload'])
                if (payload.get('node') != nid or payload.get('generation') != record['generation']
                        or payload.get('internal_revision') != view['internal_revision']
                        or payload.get('contract_sha') != view['contract_sha'] or payload.get('attempt') != record['attempt']):
                    continue
                candidate = payload.get('candidate')
                if not candidate: continue
                Snapshots(ledger.state_root).read_blob(candidate['receipt'])
                from .retention import pin_evidence
                pin_evidence(ledger, root['selector'], candidate['artifact'])
                _event(ledger, conn, view, nid, 'node.produced', progress_status='unknown', retained_event=row['seq'], **candidate)
                return {'node': nid, 'state': 'produced', 'released_retained': True, **candidate}
    return None


def step(ledger, selector, executor, *, control=None):
    from . import answer_effects
    answer_effects.reconcile(ledger, selector)
    control = control or getattr(executor, 'control', None)
    if (control is None or control.ledger.project_id != ledger.project_id
            or Path(control.ledger.state_root).resolve() != Path(ledger.state_root).resolve()):
        raise LedgerError('A connected executor Control for this project/state root is required.')
    retained = publish_retained(ledger, selector)
    if retained: return retained
    with ledger.transaction() as conn:
        root, contract, sha = ip.context(ledger, conn, selector, 'sequential-engine')
        view = state(ledger, root['selector'], conn)
        choices = _ready(view)
        ctx = ip.ceilings(ledger, conn, root)
    if not choices: return {'state': 'waiting', 'internal_revision': view['internal_revision']}
    if view['definition_contract_sha'] != sha:
        raise LedgerError('Revise the internal plan against the current approved contract before dispatch.')
    nid = choices[0]['id']
    item = copy.deepcopy(next(node for node in view['definition']['nodes'] if node['id'] == nid))
    if getattr(executor, 'requires_pin', False) and 'executor' not in item:
        raise LedgerError('This node has no pinned executor role/provider/model.')
    definitions = {node['id']: node for node in view['definition']['nodes']}
    inputs = {edge['node']: {**{key: view['nodes'][edge['node']][key] for key in ('artifact', 'state', 'generation')},
                            'write': definitions[edge['node']]['write'], 'receipt': view['nodes'][edge['node']]['receipt']}
              for edge in item['depends']}
    item['input_artifacts'] = inputs
    ip.decide(ledger, root, contract, sha, {'kind': 'decision', 'q': 'Q2', 'nodes': [nid], 'eligible': True}, ctx, 'onecrew.engine')
    pin = item.get('executor', {})
    task = submit(ledger, item['goal'], f'wf:{root["task_id"]}:{nid}:g{view["nodes"][nid]["generation"]}',
                  plan_selector=root['selector'], plan_revision=root['approved']['revision'],
                  max_calls=item['budget_calls'], max_seconds=int(item['execution_cap_seconds']),
                  **({key: pin[key] for key in ('provider', 'model')} if pin else {}))
    execution = control.configure(task['id'], task['revision'], {'mode': 'common-workflow-node', 'node': nid})

    def reserve(conn, attempt):
        current = state(ledger, root['selector'], conn)
        if (not _publication_current(current, view, nid) or current['inflight']
                or not eligible(current, nid)['ready']):
            raise LedgerError('The root slot or internal node changed before admission.')
        _event(ledger, conn, current, nid, 'node.started', attempt=attempt['id'], child=task['id'],
               early_dependencies=eligible(current, nid).get('early_dependencies', []), inputs=inputs)

    attempt = control.reserve(task['id'], execution['revision'], 'node-run', {'unit': 'task:' + nid, 'stage': nid}, on_reserved=reserve)
    try:
        if hasattr(executor, 'declaration'):
            produced = executors.Dispatcher().send(executor, 'start', ledger, control, task, item, attempt)
        else:
            produced = executor(ledger, control, task, item, attempt)
        observed = control.attempt(attempt['id'])
        if observed['status'] != 'settled':
            raise LedgerError('Executor did not settle its Control attempt; reconciliation is required.')
        if (not isinstance(produced, dict) or set(produced) != {'artifact', 'receipt'}
                or not isinstance(produced['artifact'], str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', produced['artifact'])):
            raise LedgerError('Executor must return artifact identity and durable receipt.')
        Snapshots(ledger.state_root).read_blob(produced['receipt'])
        progress = progress_track.read(ledger, root['selector'], nid)
        progress_status = progress['checkpoint']['status'] if progress else 'unknown'
        if progress_status in ('blocked', 'waiting'):
            with ledger.transaction(write=True) as conn:
                current = state(ledger, root['selector'], conn)
                if _publication_current(current, view, nid):
                    _event(ledger, conn, current, nid, 'node.held', reason=progress['checkpoint']['reason'],
                           classification='progress_' + progress_status, candidate=produced)
                else:
                    _retain(ledger, conn, view, nid, 'Root changed during execution', candidate=produced, attempt=attempt['id'])
            return {'node': nid, 'state': 'held' if progress_status == 'blocked' else 'waiting', 'progress': progress_status}
    except Exception as error:
        if control.attempt(attempt['id'])['status'] != 'settled':
            control.unknown(attempt['id'], str(error)[:1000])
        with ledger.transaction(write=True) as conn:
            current = state(ledger, root['selector'], conn)
            if _publication_current(current, view, nid):
                _event(ledger, conn, current, nid, 'node.held', reason=str(error)[:1000], classification='unknown')
            else:
                _retain(ledger, conn, view, nid, str(error)[:1000], attempt=attempt['id'])
        return {'node': nid, 'state': 'held', 'reason': str(error)}
    with ledger.transaction(write=True) as conn:
        current = state(ledger, root['selector'], conn)
        if not _publication_current(current, view, nid) or current['nodes'][nid]['attempt'] != attempt['id']:
            _retain(ledger, conn, view, nid, 'Root changed before artifact publication', candidate=produced, attempt=attempt['id'])
            return {'node': nid, 'state': 'retained', 'reason': 'Root changed; candidate delivery is refused', **produced}
        from .retention import pin_evidence
        pin_evidence(ledger, root['selector'], produced['artifact'])
        _event(ledger, conn, current, nid, 'node.produced', progress_status=progress_status, **produced)
    _forecast(ledger, state(ledger, root['selector']), f'node-{nid}-g{view["nodes"][nid]["generation"]}-produced', 'Node produced an artifact; verification remains separate')
    return {'node': nid, 'state': 'produced', **produced}


def verify(ledger, selector, nid, checker):
    with ledger.transaction() as conn:
        root, contract, sha = ip.context(ledger, conn, selector, 'sequential-engine')
        view = state(ledger, root['selector'], conn)
        if nid not in view['nodes'] or view['nodes'][nid]['state'] != 'produced' or view['nodes'][nid]['phase'] == 'held':
            raise LedgerError('Only the current produced node can be verified.')
        item = next(node for node in view['definition']['nodes'] if node['id'] == nid)
        artifact = view['nodes'][nid]['artifact']
        ctx = ip.ceilings(ledger, conn, root)
    from . import review_dispatch
    decision = review_dispatch.required(ledger, root['selector'], nid, [check['id'] for check in item['checks']])
    if decision['action'] != 'REVIEW':
        raise LedgerError('The required verification is held or deferred by its rule decision.')
    with ledger.transaction() as conn:
        current = state(ledger, root['selector'], conn)
        if not _publication_current(current, view, nid) or current['nodes'][nid]['artifact'] != artifact:
            raise LedgerError('The node changed before checker dispatch; recompute its required decision.')
    observed = checker(item, artifact)
    rows = observed.get('checks', []) if isinstance(observed, dict) and isinstance(observed.get('checks'), list) else []
    configured = {check['id'] for check in item['checks']}
    actual = {row.get('id') for row in rows if isinstance(row, dict)}
    matches = isinstance(observed, dict) and observed.get('artifact') == artifact
    passed = matches and len(rows) == len(configured) and actual == configured and all(isinstance(row, dict) and row.get('result') == 'pass' for row in rows)
    evidence_errors = []
    for row in rows:
        try:
            if not isinstance(row, dict) or not row.get('evidence'): raise LedgerError('A check needs durable evidence.')
            Snapshots(ledger.state_root).read_blob(row['evidence'])
        except (OSError, LedgerError) as error:
            passed = False
            evidence_errors.append(str(error)[:300])
    failed = (matches and len(rows) == len(configured) and actual == configured and not evidence_errors
              and any(row.get('result') == 'fail' for row in rows)
              and all(row.get('result') in ('pass', 'fail', 'blocked') for row in rows))
    body = {'kind': 'node-verifier-receipt', 'root': root['task_id'], 'node': nid,
            'internal_revision': view['internal_revision'], 'generation': view['nodes'][nid]['generation'],
            'artifact': artifact, 'inputs': view['nodes'][nid]['inputs'], 'observed': observed,
            'evidence_errors': evidence_errors, 'checks_sha': content_hash(item['checks']),
            'result': 'pass' if passed else 'fail' if failed else 'inconclusive'}
    receipt = Snapshots(ledger.state_root).blob(canonical(body).encode())
    if matches:
        ip.decide(ledger, root, contract, sha, {'kind': 'decision', 'q': 'Q9', 'nodes': [nid],
                  'evidence': [receipt], 'artifact_matches': True}, ctx, 'onecrew.engine')
    with ledger.transaction(write=True) as conn:
        current = state(ledger, root['selector'], conn)
        publish = (_publication_current(current, view, nid)
                   and current['nodes'][nid]['artifact'] == artifact and current['nodes'][nid]['phase'] != 'held')
        if publish:
            _event(ledger, conn, current, nid, 'node.verification', result=body['result'], receipt=receipt)
        else:
            _retain(ledger, conn, view, nid, 'Root or node changed while checker ran', receipt=receipt)
    if not publish:
        raise LedgerError('The root or node changed while its checker ran; evidence was retained without verification.')
    _forecast(ledger, state(ledger, root['selector']), 'verification-' + receipt[:32], 'Node verification recorded')
    if body['result'] == 'fail':
        from . import recovery_policy
        try:
            body['recovery'] = recovery_policy.assess(ledger, root['selector'], nid)
        except LedgerError as error:
            # A concurrent replan/closure cannot erase the completed check or
            # authorize repair against its now-stale evidence.
            body['recovery'] = {'disposition': 'reconcile', 'reason': str(error),
                                'grants_authority': False, 'creates_owner_request': False}
    return body


def accept_node(ledger, selector, nid):
    with ledger.transaction() as conn:
        root, contract, sha = ip.context(ledger, conn, selector, 'sequential-engine')
        view = state(ledger, root['selector'], conn)
        ctx = ip.ceilings(ledger, conn, root)
    if nid not in view['nodes']: raise LedgerError('Unknown internal node.')
    ip.decide(ledger, root, contract, sha, {'kind': 'decision', 'q': 'Q12', 'nodes': [nid],
              'node_state': view['nodes'][nid]['state']}, ctx, 'onecrew.engine')
    with ledger.transaction(write=True) as conn:
        current = state(ledger, root['selector'], conn)
        if (not _publication_current(current, view, nid) or current['nodes'][nid]['state'] != 'verified'
                or current['nodes'][nid]['phase'] == 'held'):
            raise LedgerError('Internal acceptance requires the current verified node.')
        _event(ledger, conn, current, nid, 'node.accepted')
    return state(ledger, root['selector'])['nodes'][nid]


def review_optional(ledger, selector, nid, review_id, checker, artifact):
    from .review_dispatch import optional
    return optional(ledger, selector, nid, review_id, checker, artifact)


def request_action(ledger, selector, nid, action):
    with ledger.transaction() as conn:
        root, contract, sha = ip.context(ledger, conn, selector, 'sequential-engine')
        view = state(ledger, root['selector'], conn)
        ctx = ip.ceilings(ledger, conn, root)
    if nid not in view['nodes']: raise LedgerError('Unknown internal node.')
    action = dict(action, nodes=[nid])
    result = authority.decide(contract, action, ctx)
    authority.record(ledger, root['task_id'], contract, action, result, name=root['selector'], revision_sha=sha, component='onecrew.engine')
    if not result['in_authority']:
        affected = dependency_core.affected_tasks(ip.projection(view['definition']['nodes']), [nid])
        with ledger.transaction(write=True) as conn:
            current = state(ledger, root['selector'], conn)
            for target in sorted(affected):
                _event(ledger, conn, current, target, 'node.held', reason=result['reason'], classification=result['class'])
        if result['class'] in ('U1', 'U2', 'U3', 'U4'):
            parameters = {'plan': root['selector'], 'root': root['task_id'], 'contract_revision': root['approved']['revision'],
                          'contract_sha': sha, 'internal_revision': view['internal_revision'], 'node': nid,
                          'generation': view['nodes'][nid]['generation'], 'affected': sorted(affected),
                          'generations': {target: view['nodes'][target]['generation'] for target in sorted(affected)},
                          'reason_class': result['class'], 'requested_action': action}
            parameters['key'] = 'wfhold-' + content_hash(parameters)[:48]
            ledger.create_request(root['task_id'], parameters['key'], {'schema_version': 1,
                'question': 'Node ' + nid + ' needs a decision outside its current delegated action.',
                'reason': result['reason'], 'impact': 'Only ' + ', '.join(sorted(affected)) + ' is held; independent nodes may continue.',
                'options': [{'id': 'continue', 'label': 'Continue the affected work strictly inside the existing grant'},
                            {'id': 'stop', 'label': 'Close this root and retain its evidence'}],
                'recommendation': 'continue', 'action': {'type': 'v2.workflow_hold', 'parameters': parameters}})
    return result


def resume_held(ledger, selector, *, request_id, request_revision, contract_sha, generations, conn=None):
    """Apply an actual typed continue answer; never replay an unknown attempt."""
    if conn is None:
        with ledger.transaction(write=True) as connection:
            return resume_held(ledger, selector, request_id=request_id, request_revision=request_revision,
                               contract_sha=contract_sha, generations=generations, conn=connection)
    root, contract, sha = ip.context(ledger, conn, selector, 'sequential-engine')
    request = conn.execute('SELECT * FROM requests WHERE id=? AND task_id=?', (request_id, root['task_id'])).fetchone()
    if not request or request['revision'] != request_revision or request['state'] != 'answered':
        raise LedgerError('A current answered workflow request is required.')
    question, answer = json.loads(request['payload']), json.loads(request['answer'])
    action = question['action']; params = action['parameters']
    provenance = answer.get('provenance', {})
    if (action['type'] != 'v2.workflow_hold' or answer['choice'] != 'continue'
            or provenance.get('decided_by') != 'user' or provenance.get('by') != 'user'):
        raise LedgerError('Only the recorded owner continue answer can resume this workflow hold.')
    view = state(ledger, root['selector'], conn)
    if (sha != contract_sha or params.get('contract_sha') != sha or params.get('root') != root['task_id']
            or params.get('contract_revision') != root['approved']['revision']
            or params.get('internal_revision') != view['internal_revision'] or params.get('generations') != generations):
        raise LedgerError('The root contract/internal revision or held generations changed after the question.')
    affected = params['affected']
    nodes = {node['id']: node for node in view['definition']['nodes']}
    if set(generations) != set(affected): raise LedgerError('The answer must identify exactly the affected held scope.')
    ctx = ip.ceilings(ledger, conn, root)
    for nid in affected:
        if (nid not in nodes or view['nodes'][nid]['generation'] != generations[nid]
                or view['nodes'][nid]['phase'] != 'held'):
            raise LedgerError('A held node generation is stale or has already resumed.')
        if nodes[nid]['write'] and authority.covers(authority.effective(contract), {'edit': True, 'paths': nodes[nid]['write']}):
            raise LedgerError('The resumed node exceeds its original root grant.')
        attempt = view['nodes'][nid].get('attempt')
        if attempt:
            status = conn.execute('SELECT status FROM attempts WHERE id=?', (attempt,)).fetchone()
            if not status or status['status'] != 'settled':
                raise LedgerError('Reconcile the active/unknown attempt before resuming; an answer cannot reset it.')
    if sum(nodes[nid]['budget_calls'] for nid in affected) > ctx['remaining_calls'] or sum(nodes[nid]['estimate_seconds'][1] for nid in affected) > ctx['remaining_seconds']:
        raise LedgerError('The held work does not fit its remaining original budget/deadline.')
    if namespaces.has_capability(root, 'finding-register'):
        from . import findings
        opened = findings.list_findings(ledger, root['selector'], task_id=root['task_id'], open_only=True)
        paths = {path for nid in affected for path in nodes[nid]['read'] + nodes[nid]['write']}
        for finding in opened:
            scope = finding.get('scope') or {}
            if finding.get('node') in affected or paths & set(scope.get('read', []) + scope.get('write', [])):
                raise LedgerError('An unresolved finding still holds the affected work.')
    for nid in affected:
        _event(ledger, conn, view, nid, 'node.resumed', request_id=request_id, request_revision=request_revision,
               grants_authority=False, original_unauthorized_action_executed=False)
    return {'affected': list(affected), 'contract_sha': sha, 'internal_revision': view['internal_revision'],
            'generations_before': dict(generations), 'generations_after': {nid: generations[nid] + 1 for nid in affected},
            'grants_authority': False}


def verification_ready(ledger, selector):
    view = state(ledger, selector)
    if (view['root_status'] != 'approved' or view['unknown_blockers'] or not view['definition'] or view['definition_contract_sha'] != view['contract_sha'] or
            not any(node['integration'] for node in view['definition']['nodes'])):
        return False
    if not all(_rank(record) >= STATES['verified'] for record in view['nodes'].values()): return False
    for node in view['definition']['nodes']:
        inputs = view['nodes'][node['id']]['inputs']
        if set(inputs) != {edge['node'] for edge in node['depends']}: return False
        for source, observed in inputs.items():
            if any(observed[key] != view['nodes'][source][key] for key in ('artifact', 'generation')): return False
    return True


def root_ready(ledger, selector, artifact=None):
    """Final acceptance also needs an issued handoff of the integration candidate.

    The checkout producer does not apply files. Until an authorized CAS handoff
    adapter issues this proof, internal verification cannot accept a root.
    """
    if not verification_ready(ledger, selector): return False
    view = state(ledger, selector)
    with ledger.transaction() as conn:
        row = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='workflow.handoff' ORDER BY seq DESC LIMIT 1", (view['root'],)).fetchone()
    if row is None: return False
    try:
        proof = json.loads(Snapshots(ledger.state_root).read_blob(json.loads(row['payload'])['receipt']))
        integration = next(node for node in view['definition']['nodes'] if node['integration'])
        record = view['nodes'][integration['id']]
        if (proof.get('kind') != 'workflow-handoff-receipt' or proof.get('root') != view['root']
                or proof.get('contract_sha') != view['contract_sha'] or proof.get('internal_revision') != view['internal_revision']
                or proof.get('integration_artifact') != record['artifact'] or proof.get('generation') != record['generation']
                or proof.get('node') != integration['id'] or proof.get('child') != record['child']
                or proof.get('method') != 'v1-cas-apply' or not proof.get('apply_receipt')):
            return False
        applied = json.loads(Snapshots(ledger.state_root).read_blob(proof['apply_receipt']))
        if (applied.get('status') != 'verified' or applied.get('result', {}).get('candidate') != proof.get('delivered_artifact')
                or not applied.get('result', {}).get('verified')):
            return False
        with ledger.transaction() as conn:
            actual_action = conn.execute("SELECT 1 FROM actions WHERE task_id=? AND status='verified' AND receipt=?",
                                         (record['child'], canonical(applied))).fetchone()
        if actual_action is None: return False
        from .verifiers import command
        observed = command.artifact_sha(ledger.project)
        return proof.get('delivered_artifact') == observed and (artifact is None or artifact == observed)
    except (OSError, ValueError, KeyError, StopIteration):
        return False
