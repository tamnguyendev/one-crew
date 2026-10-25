"""W06/W14a: one-slot adapter over shared ready_batch and Control admission.

Executors own their existing Control lifecycle. A callback cannot publish an
artifact until that attempt is settled; uncertainty holds the slot for existing
reconciliation. This module never launches a provider or implements recovery.
"""
import copy
import json
import re
from concurrent.futures import ThreadPoolExecutor
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
            affected=ip.affected_revision(definition['nodes'] if definition else [],updated['nodes'],
                                          contract_changed=contract_sha!=payload['contract_sha'])
            fresh = _fresh(updated['nodes'])
            for nid, record in fresh.items():
                record['valid_internal_revisions']=[payload['internal_revision']]
                if nid in records:
                    if nid not in affected:
                        fresh[nid] = copy.deepcopy(records[nid])
                        fresh[nid]['valid_internal_revisions']=list(dict.fromkeys(records[nid].get('valid_internal_revisions',[])+[payload['internal_revision']]))
                    else:
                        record['generation'] = records[nid]['generation'] + 1
                        record['early_runs'] = copy.deepcopy(records[nid]['early_runs'])
            definition, records = updated, fresh
            internal_revision, contract_sha, contract_revision = payload['internal_revision'], payload['contract_sha'], payload['revision']
            continue
        nid = payload.get('node')
        if (nid not in records or payload.get('generation') != records[nid]['generation']
                or payload.get('internal_revision') not in records[nid].get('valid_internal_revisions',[internal_revision])):
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
            record['verification_result'] = payload['result']
            if payload['result'] == 'pass': record.update(phase='complete', state='verified')
        elif event['kind'] == 'node.accepted':
            record['state'] = 'accepted'
        elif event['kind'] == 'node.held':
            record.update(phase='held', reason=payload['reason'], classification=payload.get('classification'))
            if payload.get('candidate'): record['retained_candidate'] = payload['candidate']
        elif event['kind'] == 'node.resumed':
            fresh = _fresh([next(item for item in definition['nodes'] if item['id'] == nid)])[nid]
            fresh.update(generation=record['generation'] + 1, early_runs=copy.deepcopy(record['early_runs']))
            if payload.get('resume_artifact'):                   # W36: the continuation starts from the partial candidate
                fresh.update(resume_artifact=payload['resume_artifact'], continues=payload.get('continues_attempt'))
            fresh['valid_internal_revisions']=[internal_revision]
            records[nid] = fresh
    approved = root['approved'] or {}
    inflight, active_nodes = False, []
    definitions={node['id']:node for node in definition['nodes']} if definition else {}
    for nid,record in records.items():
        if record['attempt']:
            attempt = conn.execute('SELECT status FROM attempts WHERE id=?', (record['attempt'],)).fetchone()
            if attempt and attempt['status'] != 'settled':
                inflight = True
                active_nodes.append({'node':nid,'attempt':record['attempt'],'write':definitions[nid]['write']})
    from . import finding_scope, runtime_unknowns
    failed_blockers={}
    if definition:
        failure_projection=ip.influence_projection(definition['nodes'])
        for nid,record in records.items():
            if record.get('verification_result')=='fail':
                for target in dependency_core.affected_tasks(failure_projection,[nid]):
                    failed_blockers.setdefault(target,[]).append(nid)
    return {'root': root['task_id'], 'selector': root['selector'], 'root_status': root['status'],
            'contract_revision': approved.get('revision'), 'contract_sha': approved.get('sha'),
            'definition_contract_revision': contract_revision, 'definition_contract_sha': contract_sha,
            'internal_revision': internal_revision, 'definition': definition, 'nodes': records, 'inflight': inflight,
            'active_nodes':active_nodes,'capabilities':list(root.get('capabilities',())),
            'unknown_blockers': runtime_unknowns.blockers(ledger, root['selector'], conn),
            'finding_blockers': finding_scope.blockers(ledger, root['selector'], definition['nodes'] if definition else [], conn),
            'request_blockers': finding_scope.request_blockers(ledger, root['selector'], definition['nodes'] if definition else [], conn),
            'failed_blockers':failed_blockers}


def _rank(record):
    return 0 if record['phase'] == 'held' or record.get('verification_result')=='fail' else STATES.get(record.get('state'), 0)


def _early_key(upstream, record):
    return upstream + ':' + str(record.get('artifact'))


def eligible(view, nid):
    if view['root_status'] != 'approved' or _input_blocks(view, nid):
        return {'ready': False, 'reason': 'Root is not approved or this node has an unresolved fact/finding'}
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


def _slot_limit(view,slots):
    if type(slots) is not int or slots not in (1,2): raise LedgerError('Common engine slots must be 1 or 2; advanced resource scheduling is separate.')
    if slots==2 and 'parallel-engine' not in view.get('capabilities',()):
        raise LedgerError('This root did not declare the parallel-engine capability.')
    return slots


def _ready(view,slots=1):
    # State requirements become the existing scheduler's dependency tokens. It
    # alone chooses order and disjoint ownership; this adapter supplies slots.
    _slot_limit(view,slots)
    tasks, done, blocked = [], [], {}
    active=view.get('active_nodes',[])
    available=max(0,slots-len(active))
    owned=[path for item in active for path in item['write']]      # W14b: compared case-folded (dependency_core.owned_overlap)
    if view['definition'] and view['root_status'] == 'approved':
        for node in view['definition']['nodes']:
            nid, record = node['id'], view['nodes'][node['id']]
            rank = _rank(record)
            done.extend(nid + '@' + status for status, value in STATES.items() if rank >= value)
            if record['phase'] != 'pending': done.append(nid)
            dependencies = [edge['node'] + '@' + edge['requires'] for edge in node['depends']]
            if not eligible(view, nid)['ready'] or not available or dependency_core.owned_overlap(owned, node['write']):
                blocked[nid] = True
            tasks.append({'id': nid, 'owned': node['write'], 'depends_on': dependencies})
    return dependency_core.ready_batch({'plan': {'tasks': tasks}, 'done': done, 'branch_errors': blocked})[:available]


def ready(ledger, selector, *, slots=1):
    return _ready(state(ledger, selector),slots)


def _event(ledger, conn, view, nid, kind, **payload):
    plans.emit(ledger, conn, view['root'], kind, dict(plan=namespaces.parse(view['selector'])[0],
               revision=view['contract_revision'], internal_revision=view['internal_revision'], node=nid,
               generation=view['nodes'][nid]['generation'], **payload))


def _forecast(ledger, view, key, reason):
    if view['definition'] is None: return
    estimates.observe_internal(ledger,view['selector'],reason=reason,evidence=['internal-plan:'+str(view['internal_revision'])])


def _publication_current(current, original, nid):
    return (current['root_status'] == 'approved'
            and current['contract_sha'] == original['contract_sha']
            and current['contract_revision'] == original['contract_revision']
            and nid in current['nodes']
            and original['internal_revision'] in current['nodes'][nid].get('valid_internal_revisions',[current['internal_revision']])
            and next((node for node in current['definition']['nodes'] if node['id']==nid),None)==next((node for node in original['definition']['nodes'] if node['id']==nid),None)
            and not _input_blocks(current, nid)
            and current['nodes'][nid]['generation'] == original['nodes'][nid]['generation'])


def _input_blocks(view, nid):
    pending, seen = [nid], set()
    nodes = {node['id']: node for node in (view['definition'] or {}).get('nodes', [])}
    while pending:
        target = pending.pop()
        if target in seen: continue
        seen.add(target)
        # A node's OWN failed verification is not an input block: the same generation may be checked again (T38c
        # "superseded failure") or repaired. Its dependents, and any upstream failure, do block.
        failed = [source for source in view.get('failed_blockers', {}).get(target, []) if not (target == nid and source == nid)]
        # A finding holds a node and (through affected_tasks) its dependents, so an upstream hold normally holds `nid` too. The one
        # exception is W21/W19: a prepared repair releases the nodes it re-issues from that finding; an upstream node the same finding
        # still holds (in scope, already verified, not re-issued) then no longer blocks them — otherwise the repair could never run.
        own = set(view.get('finding_blockers', {}).get(nid, []))
        findings_ = [f for f in view.get('finding_blockers', {}).get(target, []) if target == nid or f in own]
        if view.get('unknown_blockers', {}).get(target) or view.get('request_blockers', {}).get(target) or findings_ or failed: return True
        pending.extend(edge['node'] for edge in nodes.get(target, {}).get('depends', []))
    return False


def _retain(ledger, conn, original, nid, reason, **evidence):
    # Reference the execution's original identities, never a newer generation.
    _event(ledger, conn, original, nid, 'node.result_retained', reason=reason,
           contract_sha=original['contract_sha'], grants_delivery=False, **evidence)


def publish_retained(ledger, selector, *, node=None):
    """A resolved fact can release a settled result without another model call."""
    with ledger.transaction(write=True) as conn:
        root, _, _ = ip.context(ledger, conn, selector, 'sequential-engine')
        view = state(ledger, root['selector'], conn)
        for nid, record in view['nodes'].items():
            if node is not None and nid!=node: continue
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
                try:
                    body = json.loads(Snapshots(ledger.state_root).read_blob(candidate['receipt']))
                except ValueError:
                    body = {}                                        # an opaque receipt of another executor: never partial
                if isinstance(body, dict) and body.get('partial') is True:
                    # W36 (T07b E16): the retained candidate is partial (the worker paused with work left): it is never published as the
                    # node's result; a new attempt continues from it once the hold is clear
                    _continue(ledger, conn, view, nid, candidate, record['attempt'], body.get('continuation'))
                    return {'node': nid, 'state': 'continuing', 'generation': record['generation'] + 1, 'resume_artifact': candidate['artifact'],
                            'continues_attempt': record['attempt'], 'released_retained': True}
                from .retention import pin_evidence
                pin_evidence(ledger, root['selector'], candidate['artifact'])
                _event(ledger, conn, view, nid, 'node.produced', progress_status='unknown', retained_event=row['seq'], **candidate)
                return {'node': nid, 'state': 'produced', 'released_retained': True, **candidate}
    return adopt_managed(ledger, selector, node=node)


def adopt_managed(ledger, selector, *, node=None):
    """W37b/W36 (crash point d): the controller died after ManagedExecutor saved the `candidate` checkpoint and before the engine published
    it, so the node stays `running` on a settled attempt and nothing would ever run it again. On restart the engine adopts that saved, bound
    candidate exactly as `step` would have: published as node.produced (same attempt, no new process, no new charge), held when a pause was
    asked, continued when it is partial, retained when its inputs are held — or, when the node's generation has moved since, recorded as
    node.result_retained under the attempt's original identities (never published into the new generation). One adoption per call."""
    from . import managed_executor
    with ledger.transaction() as conn:
        root, _, _ = ip.context(ledger, conn, selector, 'sequential-engine')
        rows = [r for r in managed_executor.adoptable(ledger, conn, root['task_id']) if node is None or r['node'] == node]
    if not rows: return None
    adapter = managed_executor.ManagedExecutor(ledger, initialize=False)
    for row in rows:
        if 'pause_requested' in row['phases'] and 'paused' not in row['phases']:
            adapter._ack_pause(row['attempt'])          # the acknowledgement the crashed controller did not reach (the real safe point check)
    with ledger.transaction(write=True) as conn:
        root, _, _ = ip.context(ledger, conn, selector, 'sequential-engine')
        view = state(ledger, root['selector'], conn)
        for row in managed_executor.adoptable(ledger, conn, root['task_id']):
            if node is not None and row['node'] != node: continue
            return _adopt(ledger, conn, root, view, row)
    return None


def _adopt(ledger, conn, root, view, row):
    nid, attempt_id, candidate = row['node'], row['attempt'], row['candidate']
    record = view['nodes'].get(nid)
    if (record is None or record['phase'] != 'running' or record['attempt'] != attempt_id or record['generation'] != row['generation']
            or row['internal_revision'] not in record.get('valid_internal_revisions', [view['internal_revision']])):
        plans.emit(ledger, conn, view['root'], 'node.result_retained', {
            'plan': namespaces.parse(view['selector'])[0], 'revision': view['contract_revision'], 'internal_revision': row['internal_revision'],
            'node': nid, 'generation': row['generation'], 'attempt': attempt_id, 'candidate': candidate, 'contract_sha': view['contract_sha'],
            'grants_delivery': False, 'adopted_after_crash': True,
            'reason': 'Managed candidate saved before the controller was lost; the node generation moved since, so it is retained, not published'})
        return {'node': nid, 'state': 'retained', 'attempt': attempt_id, 'adopted_after_crash': True, **candidate}
    phases = set(row['phases'])
    held = 'paused' if 'paused' in phases else 'stop_requested' if 'stop_requested' in phases else 'pause_requested' if 'pause_requested' in phases else None
    if held:
        _event(ledger, conn, view, nid, 'node.held', reason='Managed candidate adopted after a crash; the attempt was asked to ' + held.replace('_', ' '),
               classification='executor_' + held, candidate=candidate, adopted_after_crash=True)
        return {'node': nid, 'state': 'held', 'executor_state': held, 'candidate': candidate, 'adopted_after_crash': True}
    try:
        body = json.loads(Snapshots(ledger.state_root).read_blob(candidate['receipt']))
    except ValueError:
        body = {}
    if not _publication_current(view, view, nid):
        _retain(ledger, conn, view, nid, 'Managed candidate adopted after a crash while its inputs are held', candidate=candidate, attempt=attempt_id)
        return {'node': nid, 'state': 'retained', 'adopted_after_crash': True, **candidate}
    if isinstance(body, dict) and body.get('partial') is True:
        _retain(ledger, conn, view, nid, 'Partial candidate: work remains after the safe point', candidate=candidate, attempt=attempt_id)
        _continue(ledger, conn, view, nid, candidate, attempt_id, body.get('continuation'))
        return {'node': nid, 'state': 'continuing', 'generation': record['generation'] + 1, 'resume_artifact': candidate['artifact'],
                'continues_attempt': attempt_id, 'adopted_after_crash': True}
    progress = progress_track.read(ledger, root['selector'], nid)
    progress_status = progress['checkpoint']['status'] if progress else 'unknown'
    if progress_status in ('blocked', 'waiting'):
        _event(ledger, conn, view, nid, 'node.held', reason=progress['checkpoint']['reason'], classification='progress_' + progress_status,
               candidate=candidate, adopted_after_crash=True)
        return {'node': nid, 'state': 'held' if progress_status == 'blocked' else 'waiting', 'progress': progress_status, 'adopted_after_crash': True}
    from .retention import pin_evidence
    pin_evidence(ledger, root['selector'], candidate['artifact'])
    _event(ledger, conn, view, nid, 'node.produced', progress_status=progress_status, adopted_attempt=attempt_id, adopted_after_crash=True, **candidate)
    return {'node': nid, 'state': 'produced', 'adopted_after_crash': True, **candidate}


def step(ledger, selector, executor, *, control=None, slots=1, _target=None):
    from . import answer_effects
    answer_effects.reconcile(ledger, selector)
    control = control or getattr(executor, 'control', None)
    if (control is None or control.ledger.project_id != ledger.project_id
            or Path(control.ledger.state_root).resolve() != Path(ledger.state_root).resolve()):
        raise LedgerError('A connected executor Control for this project/state root is required.')
    if slots==2:
        declaration=getattr(executor,'declaration',None)
        if declaration is None or not declaration.supports('isolate'):
            raise LedgerError('Parallel execution requires a declared isolate capability.')
    retained = publish_retained(ledger, selector,node=_target)
    if retained: return retained
    with ledger.transaction() as conn:
        root, contract, sha = ip.context(ledger, conn, selector, 'sequential-engine')
        view = state(ledger, root['selector'], conn)
        choices = _ready(view,slots)
        ctx = ip.ceilings(ledger, conn, root)
    if not choices: return {'state': 'waiting', 'internal_revision': view['internal_revision']}
    if view['definition_contract_sha'] != sha:
        raise LedgerError('Revise the internal plan against the current approved contract before dispatch.')
    if _target is not None:
        choices=[choice for choice in choices if choice['id']==_target]
        if not choices:return {'node':_target,'state':'waiting','internal_revision':view['internal_revision']}
    nid = choices[0]['id']
    item = copy.deepcopy(next(node for node in view['definition']['nodes'] if node['id'] == nid))
    if getattr(executor, 'requires_pin', False) and 'executor' not in item:
        raise LedgerError('This node has no pinned executor role/provider/model.')
    definitions = {node['id']: node for node in view['definition']['nodes']}
    inputs = {edge['node']: {**{key: view['nodes'][edge['node']][key] for key in ('artifact', 'state', 'generation')},
                            'write': definitions[edge['node']]['write'], 'receipt': view['nodes'][edge['node']]['receipt']}
              for edge in item['depends']}
    item['input_artifacts'] = inputs
    if view['nodes'][nid].get('resume_artifact'):
        item['resume_artifact'] = view['nodes'][nid]['resume_artifact']; item['continues'] = view['nodes'][nid].get('continues')
    ip.decide(ledger, root, contract, sha, {'kind': 'decision', 'q': 'Q2', 'nodes': [nid], 'eligible': True}, ctx, 'onecrew.engine')
    pin = item.get('executor', {})
    task = submit(ledger, item['goal'], f'wf:{root["task_id"]}:{nid}:g{view["nodes"][nid]["generation"]}',
                  plan_selector=root['selector'], plan_revision=root['approved']['revision'],
                  max_calls=item['budget_calls'], max_seconds=int(item['execution_cap_seconds']),
                  **({key: pin[key] for key in ('provider', 'model')} if pin else {}))
    execution = control.configure(task['id'], task['revision'], {'mode': 'common-workflow-node', 'node': nid})

    admitted = []

    def reserve(conn, attempt):
        current = state(ledger, root['selector'], conn)
        if (not _publication_current(current, view, nid)
                or nid not in {choice['id'] for choice in _ready(current,slots)}):
            raise LedgerError('The root slot or internal node changed before admission.')
        _event(ledger, conn, current, nid, 'node.started', attempt=attempt['id'], child=task['id'],
               early_dependencies=eligible(current, nid).get('early_dependencies', []), inputs=inputs)
        admitted.append(attempt['id'])

    attempt = control.reserve(task['id'], execution['revision'], 'node-run', {'unit': 'task:' + nid, 'stage': nid}, on_reserved=reserve)
    if attempt['id'] not in admitted:
        # T15c E8 / T08a: Control.reserve is idempotent per key, so a concurrent caller that read the node as ready before this node's
        # node.started was committed receives the attempt ANOTHER caller admitted (possibly already running). It must never be dispatched
        # a second time: one attempt has exactly one executor body; the owner of the attempt (or reconciliation) settles it.
        return {'node': nid, 'state': 'waiting', 'attempt': attempt['id'], 'attempt_status': attempt['status'],
                'reason': 'Attempt already admitted by another caller; one executor body per attempt, reconcile instead of re-running.'}
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
        receipt_bytes = Snapshots(ledger.state_root).read_blob(produced['receipt'])
        try:
            receipt_body = json.loads(receipt_bytes)                 # a native-node-receipt; other executors may seal opaque receipts
        except ValueError:
            receipt_body = {}
        partial = isinstance(receipt_body, dict) and receipt_body.get('partial') is True
        if callable(getattr(executor,'state',None)):
            execution_state=executor.state(attempt['id'])
            if execution_state['state'] in ('paused','pause_requested','stopped','stop_requested','unknown'):
                with ledger.transaction(write=True) as conn:
                    current=state(ledger,root['selector'],conn)
                    if _publication_current(current,view,nid):
                        _event(ledger,conn,current,nid,'node.held',reason=execution_state.get('text',execution_state['state']),
                               classification='executor_'+execution_state['state'],candidate=produced)
                    else:
                        _retain(ledger,conn,view,nid,'Managed result held after root/input change',candidate=produced,attempt=attempt['id'])
                return {'node':nid,'state':'held','executor_state':execution_state['state'],'candidate':produced}
        if partial:
            # W36 (T07b E16): the worker stopped at a safe point with work left: the candidate is kept, never published as the node's
            # result, and the node continues with a NEW attempt from it (generation + 1; spent budget stays spent).
            with ledger.transaction(write=True) as conn:
                current = state(ledger, root['selector'], conn)
                if not _publication_current(current, view, nid):
                    _retain(ledger, conn, view, nid, 'Root changed during execution', candidate=produced, attempt=attempt['id'])
                    return {'node': nid, 'state': 'retained', 'reason': 'Root changed; partial candidate retained', **produced}
                _retain(ledger, conn, current, nid, 'Partial candidate: work remains after the safe point', candidate=produced, attempt=attempt['id'])
                _continue(ledger, conn, current, nid, produced, attempt['id'], receipt_body.get('continuation'))
            return {'node': nid, 'state': 'continuing', 'generation': view['nodes'][nid]['generation'] + 1,
                    'resume_artifact': produced['artifact'], 'continues_attempt': attempt['id']}
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
        mine = current['nodes'].get(nid) or {}
        if (mine.get('attempt') == attempt['id'] and mine.get('generation') == view['nodes'][nid]['generation']
                and mine.get('phase') != 'running'):
            # W37b: the saved candidate of this attempt was already adopted (adopt_managed) — never published twice
            return {'node': nid, 'state': mine.get('state') or mine.get('phase'), 'already_adopted': True, **produced}
        if not _publication_current(current, view, nid) or current['nodes'][nid]['attempt'] != attempt['id']:
            _retain(ledger, conn, view, nid, 'Root changed before artifact publication', candidate=produced, attempt=attempt['id'])
            return {'node': nid, 'state': 'retained', 'reason': 'Root changed; candidate delivery is refused', **produced}
        from .retention import pin_evidence
        pin_evidence(ledger, root['selector'], produced['artifact'])
        _event(ledger, conn, current, nid, 'node.produced', progress_status=progress_status, **produced)
    _forecast(ledger, state(ledger, root['selector']), f'node-{nid}-g{view["nodes"][nid]["generation"]}-produced', 'Node produced an artifact; verification remains separate')
    return {'node': nid, 'state': 'produced', **produced}


def run_batch(ledger,selector,executor,*,slots=1,control=None):
    """Run the existing scheduler's bounded batch through the same step port."""
    adopted=[]
    for _ in range(201):                        # W37b: candidates saved before a lost controller are adopted first (bounded: one per node)
        result=adopt_managed(ledger,selector)
        if not result:break
        adopted.append(result)
    if adopted:return {'slots':slots,'results':adopted,'state':'adopted'}
    view=state(ledger,selector)
    choices=_ready(view,slots)
    if slots==2:
        declaration=getattr(executor,'declaration',None)
        if declaration is None or not declaration.supports('isolate'):
            raise LedgerError('Parallel execution requires a declared isolate capability.')
    if not choices:return {'slots':slots,'results':[],'state':'waiting'}
    def execute(choice):
        try:return step(ledger,selector,executor,control=control,slots=slots,_target=choice['id'])
        except LedgerError as error:return {'node':choice['id'],'state':'waiting','reason':str(error)}
    with ThreadPoolExecutor(max_workers=slots) as pool:
        futures=[pool.submit(execute,choice) for choice in choices]
        results=[future.result() for future in futures]
    return {'slots':slots,'results':results}


def release_paused(ledger,selector,nid,executor):
    """Adopt the same safe-point candidate after its original inputs are clear."""
    with ledger.transaction(write=True) as conn:
        root,_,sha=ip.context(ledger,conn,selector,'sequential-engine')
        view=state(ledger,root['selector'],conn)
        record=view['nodes'].get(nid)
        if (not record or record['phase']!='held' or record.get('classification')!='executor_paused'
                or not _publication_current(view,view,nid) or view['definition_contract_sha']!=sha):
            raise LedgerError('Only the current safe-point paused candidate with clear prerequisites can be released.')
        for source,binding in record['inputs'].items():
            if any(binding[key]!=view['nodes'][source][key] for key in ('artifact','generation')):
                raise LedgerError('Paused candidate inputs changed; reverify the new generation instead of reusing it.')
        observed=executor.state(record['attempt'])
        candidate=record.get('retained_candidate')
        if (observed['state']!='paused' or not observed.get('safe_point_acknowledged')
                or not candidate or observed.get('candidate')!=candidate):
            raise LedgerError('A matching acknowledged safe-point candidate is required; unknown work is never replayed.')
        body=json.loads(Snapshots(ledger.state_root).read_blob(candidate['receipt']))
        if body.get('attempt')!=record['attempt'] or body.get('artifact')!=candidate['artifact']:
            raise LedgerError('Paused candidate receipt does not bind the original attempt/artifact.')
        if body.get('partial') is True:
            # W36 (T07b E16): the paused worker had work left -> continue with a NEW attempt from this candidate; the old attempt is
            # not reused for execution and the budget it spent stays spent.
            _continue(ledger,conn,view,nid,candidate,record['attempt'],body.get('continuation'))
            return {'node':nid,'state':'continuing','generation':record['generation']+1,'resume_artifact':candidate['artifact'],
                    'continues_attempt':record['attempt'],'reused_safe_candidate':False}
        _event(ledger,conn,view,nid,'node.produced',progress_status='unknown',reused_safe_candidate=True,**candidate)
    return {'node':nid,'state':'produced','reused_safe_candidate':True,**candidate}


def _continue(ledger, conn, view, nid, candidate, attempt_id, continuation):
    """W36 (T07b E16): a new generation of `nid` that starts from `candidate` (the partial result of `attempt_id`). Written as
    `node.resumed`, the existing class-B kind the state projector already turns into a fresh pending record (generation + 1);
    the next `step` dispatches a NEW attempt whose base is the partial candidate. Nothing here resets a budget or a deadline."""
    _event(ledger, conn, view, nid, 'node.resumed', resume_artifact=candidate['artifact'], continues_attempt=attempt_id,
           continuation=continuation, reason='work remains after the safe point: a new attempt continues it', budget_reset=False)


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
    if publish and body['result'] == 'pass':
        # W48a: a verified node is a finished task; the context entry cites the published verifier receipt (code, no model).
        from . import context
        try:
            context.observe(ledger, root['selector'], {'type': 'task_done', 'source': {'type': 'receipt', 'key': receipt},
                            'text': f'Node {nid} (generation {view["nodes"][nid]["generation"]}, internal revision {view["internal_revision"]}) verified: '
                                    f'{len(configured)} check(s) passed on artifact {artifact[:12]}.'})
        except LedgerError:
            pass
    if not publish:
        raise LedgerError('The root or node changed while its checker ran; evidence was retained without verification.')
    if 'finding-register' in view['capabilities'] and body['result'] in ('pass', 'fail'):
        # W21 (T11): a failed check of a node is a finding in the shared register, scoped by the node's dependency edges; the same node
        # passing on a later generation closes them. The register, not the engine, owns the transition.
        from . import findings
        try:
            body['findings'] = findings.record_node_verification(ledger, root['selector'], nid, receipt, definition=view['definition']['nodes'])
        except LedgerError as error:
            body['findings'] = {'error': str(error)}
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
    from . import incidents
    try:body['learning']=incidents.after_node(ledger,root['selector'],nid,receipt)
    except (OSError,ValueError) as error:
        body['learning']={'status':'pending','reason':str(error),'changes_verification':False}
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
    decision = authority.record(ledger, root['task_id'], contract, action, result, name=root['selector'], revision_sha=sha, component='onecrew.engine')
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
            question = {'schema_version': 1,
                'question': 'Node ' + nid + ' needs a decision outside its current delegated action.',
                'reason': result['reason'], 'impact': 'Only ' + ', '.join(sorted(affected)) + ' is held; independent nodes may continue.',
                'options': [{'id': 'continue', 'label': 'Continue the affected work strictly inside the existing grant'},
                            {'id': 'stop', 'label': 'Close this root and retain its evidence'}],
                'recommendation': 'continue'}
            card, deadline = _hold_card(ledger, root, view, nid, sorted(affected), action, result, decision, ctx, question)
            parameters.update(card=card, decide_by_deadline=deadline)
            ledger.create_request(root['task_id'], parameters['key'],
                                  dict(question, action={'type': 'v2.workflow_hold', 'parameters': parameters}))
    return result


def _hold_card(ledger, root, view, nid, affected, action, result, decision, ctx, question):
    """T17c [E4] (HD-08): the hold request is ONE decision card in the cards.CARD_FIELDS shape - problem, options, recommendation,
    evidence, scope, decide_by - plus the decide-by deadline. Evidence: a content-addressed blob naming what produced the hold (the
    requested action, its HD-05 decision record, the first node.held event of each held node at this generation, the node's attempt,
    artifact and receipts), followed by the node's own receipt blobs. Every value is stable for the same hold, so asking again yields
    byte-identical content (the same request). The deadline is the root's sealed deadline (budget_core, via ip.ceilings) minus the
    upper execution estimate of the held nodes; it is never later than the root deadline and never invented."""
    from . import cards
    import datetime as dt
    with ledger.transaction() as conn:
        held = {}
        for target in affected:
            row = conn.execute("SELECT min(seq) AS seq FROM events WHERE task_id=? AND kind='node.held' AND json_extract(payload,'$.node')=? "
                               "AND json_extract(payload,'$.generation')=? AND json_extract(payload,'$.internal_revision')=?",
                               (root['task_id'], target, view['nodes'][target]['generation'], view['internal_revision'])).fetchone()
            if row and row['seq'] is not None: held[target] = row['seq']
    record = view['nodes'][nid]
    receipts = [record[k] for k in ('receipt', 'verification_receipt') if isinstance(record.get(k), str) and re.fullmatch(r'[0-9a-f]{64}', record[k])]
    store = Snapshots(ledger.state_root)
    blob = store.blob(canonical({'kind': 'workflow-hold-evidence', 'root': root['task_id'], 'plan': root['selector'], 'node': nid,
        'generation': record['generation'], 'internal_revision': view['internal_revision'], 'contract_sha': view['contract_sha'],
        'reason_class': result['class'], 'reason': result['reason'], 'requested_action': action, 'decision': decision,
        'hold_events': held, 'affected': affected, 'attempt': record.get('attempt'), 'artifact': record.get('artifact'),
        'retained_candidate': record.get('retained_candidate'), 'receipts': receipts}).encode())
    nodes = {item['id']: item for item in view['definition']['nodes']}
    reserved = sum(nodes[target]['estimate_seconds'][1] for target in affected if target in nodes)
    root_deadline = ctx.get('deadline')
    if root_deadline:
        at = (dt.datetime.fromisoformat(root_deadline) - dt.timedelta(seconds=reserved)).isoformat()
        basis = ('root deadline (sealed budget) minus the upper execution estimate of the held nodes ' + ', '.join(affected)
                 + f' ({reserved} s); after it the held work cannot finish inside the approved deadline')
    else:
        at, basis = None, 'the root has no approved deadline; decide before ' + nid + ' resumes'
    deadline = {'at': at, 'root_deadline': root_deadline, 'reserved_execution_seconds': reserved, 'basis': basis}
    card = cards.validate_card({'problem': question['question'], 'options': question['options'],
        'recommendation': [question['recommendation']], 'evidence': [blob, *receipts],
        'scope': (question['impact'] + ' Reason ' + str(result['class']) + ': ' + result['reason'])[:300],
        'decide_by': 'milestone:' + nid, 'parts': [{'id': nid}]}, ledger)
    return card, deadline


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
    if (view['root_status'] != 'approved' or view['unknown_blockers'] or view['finding_blockers'] or view.get('failed_blockers') or not view['definition'] or view['definition_contract_sha'] != view['contract_sha'] or
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
                or proof.get('node') != integration['id'] or proof.get('child') != record['child']):
            return False
        from ..common_handoff import receipt_valid
        if not receipt_valid(ledger,proof,record): return False
        from .verifiers import command
        observed = command.artifact_sha(ledger.project)
        return proof.get('delivered_artifact') == observed and (artifact is None or artifact == observed)
    except (OSError, ValueError, KeyError, StopIteration):
        return False
