"""W04: a workflow's internal decomposition, separate from its owner contract."""
import copy
import datetime as dt
import json
import math
import re

from ..ledger import LedgerError, canonical, content_hash, text_field, utcnow
from ..snapshots import Snapshots, scope_list
from .. import budget_core
from . import authority, contract as contracts, estimates, namespaces, plan as plans

KIND = 'plan.revised'


def context(ledger, conn, selector, capability='internal-plan'):
    state = plans.anchor_events(ledger, conn, selector)
    if not namespaces.has_capability(state, capability) or not namespaces.has_capability(state, 'root-budget'):
        raise LedgerError('This root does not declare the required ' + capability + ' capability.')
    if state['status'] != 'approved':
        raise LedgerError('Internal workflow changes require the current approved root.')
    contract, sha = plans.load(ledger, state)
    return state, contract, sha


def current(ledger, selector, conn=None):
    if conn is None:
        with ledger.transaction() as connection:
            return current(ledger, selector, connection)
    state = plans.anchor_events(ledger, conn, selector)
    row = conn.execute("SELECT seq,payload FROM events WHERE task_id=? AND kind=? ORDER BY seq DESC LIMIT 1", (state['task_id'], KIND)).fetchone()
    if row is None:
        return {'internal_revision': 0, 'contract_revision': state['approved']['revision'] if state['approved'] else None,
                'definition': None, 'event': None}
    body = json.loads(row['payload'])
    definition = json.loads(Snapshots(ledger.state_root).read_blob(body['definition']))
    if content_hash(definition) != body['definition_sha']:
        raise LedgerError('Internal plan definition hash mismatch.')
    return dict(body, definition=definition, event=row['seq'], contract_revision=body['revision'])


def projection(nodes):
    return {'tasks': [{'id': node['id'], 'owned': node['write'],
                       'depends_on': [edge['node'] for edge in node['depends']]} for node in nodes]}


def influence_projection(nodes):
    """Represent input readers as directed dependencies, never reverse writes."""
    return {'tasks':[{'id':node['id'],'owned':list(node['write']),
        'depends_on':sorted(set([edge['node'] for edge in node['depends']]+
            [writer['id'] for writer in nodes if writer['id']!=node['id'] and set(writer['write']) & set(node['read'])]))}
        for node in nodes]}


def affected_revision(previous,updated,*,contract_changed=False):
    old={node['id']:node for node in previous}
    known={node['id'] for node in updated}
    removed={path for nid,node in old.items() if nid not in known for path in node['write']}
    changed=[node['id'] for node in updated if contract_changed or old.get(node['id'])!=node
             or removed & set(node['read']+node['write'])]
    if not changed:return set()
    graph=influence_projection(updated)
    from .. import dependency_core
    return dependency_core.affected_tasks(graph,changed)


def _admit_revision(ledger,conn,state,before,nodes):
    affected=affected_revision(before['definition']['nodes'] if before['definition'] else [],nodes,
                               contract_changed=before.get('contract_sha') not in (None,state['approved']['sha']))
    parallel=namespaces.has_capability(state,'parallel-engine')
    active=conn.execute("SELECT json_extract(e.payload,'$.node') AS node FROM events e JOIN attempts a ON a.id=json_extract(e.payload,'$.attempt') WHERE e.task_id=? AND e.kind='node.started' AND a.status!='settled'",(state['task_id'],)).fetchall() if conn.execute("SELECT 1 FROM sqlite_master WHERE name='attempts'").fetchone() else []
    known={node['id'] for node in nodes}
    if any(not parallel or row['node'] in affected or row['node'] not in known for row in active):
        raise LedgerError('Reconcile the affected active workflow attempt before revising the plan.')
    from . import managed_executor
    pending=managed_executor.unresolved(ledger,state['selector'],conn)
    if any(not parallel or item['node'] in affected or item['node'] not in known for item in pending):
        raise LedgerError('Reconcile the unknown managed operation result before revising; a new generation cannot replay it.')


def ceilings(ledger, conn, state):
    shared = budget_core.group(conn, state['task_id'])
    if shared is None:
        raise LedgerError('The workflow root has no sealed shared budget.')
    return {'remaining_calls': shared['remaining_calls'], 'deadline': shared['deadline'],
            'remaining_seconds': max(0, (dt.datetime.fromisoformat(shared['deadline']) - dt.datetime.fromisoformat(utcnow())).total_seconds())}


def decide(ledger, state, contract, sha, action, ctx, component, key=None):
    result = authority.decide(contract, action, ctx)
    decision = authority.record(ledger, state['task_id'], contract, action, result, name=state['selector'],
                                revision_sha=sha, component=component, key=key)
    if not result['in_authority']:
        raise LedgerError(str(result['class'] or 'held') + ': ' + result['reason'])
    return decision


NO_GRANT, DELEGATED, NOT_DELEGATED = 'no_workflow_grant', 'delegated', 'not_delegated'


def self_decided(ledger, selector, q, nodes, component, *, key, **facts):
    """T16b [E6] / round 8 G: the authority verdict of a class OneCrew acts on without a call site of its own (Q5 repair, Q8 finding hold,
    Q10 outcome), through the same authority.decide/record as Q1/Q2/Q4/Q9. The grant is the root's APPROVED revision (an ended root keeps
    it, so Q10 can be recorded after plan.closed). `key` makes the record idempotent for the same subject.

    Returns {'delegation', 'decision', 'result', 'action', 'ctx'} and never decides FOR the caller what to do next - the three classes differ (r8-g notes):
      * NO_GRANT (no approved revision, or a root whose contract has no `authority` field - a legacy/schema-2 root, authority.effective
        'declared' False): nothing is recorded, the caller keeps its pre-T16b behaviour (compatibility, unchanged);
      * DELEGATED (`q` in grant.self_decide): the HD-05 record through decide(); a delegated class that is still out of authority (e.g. the
        repair ceiling, U2) raises like decide();
      * NOT_DELEGATED (a declared workflow grant that does not list `q`): the U3 out-of-authority verdict is RECORDED (authority.record, the
        same HD-05 record) and returned, not raised: Q5 must then hold and ask instead of repairing, Q8 keeps its safety hold, Q10 keeps
        its evidence. The old `None` that let every caller go on is gone."""
    with ledger.transaction() as conn:
        state = plans.anchor_events(ledger, conn, selector)
        if not state or not state.get('approved'): return {'delegation': NO_GRANT, 'decision': None, 'result': None}
        contract, sha = plans.load(ledger, state, state['approved']['revision'])
        grant = authority.effective(contract)
        if not grant['declared']: return {'delegation': NO_GRANT, 'decision': None, 'result': None}
        try:
            ctx = ceilings(ledger, conn, state)
        except LedgerError:
            ctx = {}
    action = dict(facts, kind='decision', q=q, nodes=sorted(nodes))
    if q in grant['self_decide']:
        return {'delegation': DELEGATED, 'decision': decide(ledger, state, contract, sha, action, ctx, component, key=key),
                'result': {'in_authority': True, 'class': None, 'q': q}, 'action': action, 'ctx': ctx}
    result = authority.decide(contract, action, ctx)                      # U3: '<q> is not delegated to OneCrew by this root'
    decision = authority.record(ledger, state['task_id'], contract, action, result, name=state['selector'],
                                revision_sha=sha, component=component, key=key)
    return {'delegation': NOT_DELEGATED, 'decision': decision, 'result': result, 'action': action, 'ctx': ctx}


def _checks(nodes):
    result = {}
    for node in nodes:
        for check in node.get('checks', []):
            if isinstance(check, dict) and isinstance(check.get('id'), str):
                if check['id'] in result and result[check['id']] != check:
                    raise LedgerError('A check id cannot carry different obligations.')
                result[check['id']] = check
    return result


# 2.3-B (Q6): an 8.3 alias (up to 6 characters, ~digits, an optional 1-3 character extension) names the same file as its long path;
# ownership is compared on one spelling only, so the alias form is refused in node scopes. Exclusivity holds per state root.
SHORT_NAME = re.compile(r'[^~.]{1,6}~[0-9]{1,6}(\.[^.]{1,3})?')


def _validate(nodes, outputs):
    if not isinstance(nodes, list) or not 2 <= len(nodes) <= 200:
        raise LedgerError('An internal plan requires 2..200 explicitly ordered nodes including integration.')
    fields = {'id', 'goal', 'input', 'output', 'acceptance', 'depends', 'read', 'write', 'resources',
              'estimate_seconds', 'execution_cap_seconds', 'budget_calls', 'checks', 'integration'}
    result, known = copy.deepcopy(nodes), set()
    for node in result:
        if not isinstance(node, dict) or not fields <= set(node) or set(node) - fields - {'executor', 'indivisible'}:
            raise LedgerError('Internal node fields must explicitly declare goal, inputs/outputs, acceptance, dependencies, scope, resources, estimate, cap, budget and checks.')
        contracts._id(node['id'], 'node id')
        if 'executor' in node:
            pin = node['executor']
            if (not isinstance(pin, dict) or set(pin) != {'role', 'provider', 'model'} or pin['role'] != 'worker'
                    or pin['provider'] not in ('claude', 'codex', 'kiro') or not isinstance(pin['model'], str)
                    or not contracts.MODEL.fullmatch(pin['model'])):
                raise LedgerError('Node executor must pin role=worker, provider and model.')
        if node['id'] in known:
            raise LedgerError('Internal node ids must be unique.')
        text_field(node['goal'], 'node goal', 1000)
        for field in ('input', 'output', 'resources'):
            if not isinstance(node[field], list) or len(node[field]) > 40:
                raise LedgerError('Node ' + field + ' must be a bounded list.')
            for value in node[field]: text_field(value, field, 500)
        if not isinstance(node['acceptance'], list) or not node['acceptance'] or not set(node['acceptance']) <= set(outputs):
            raise LedgerError('U1: node acceptance must refer to approved output ids.')
        for field in ('read', 'write'):
            if not isinstance(node[field], list): raise LedgerError('Node read/write scopes must be explicit file lists.')
            node[field] = scope_list(node[field]) if node[field] else []
            if any(SHORT_NAME.fullmatch(part) for path in node[field] for part in path.split('/')):
                raise LedgerError('A Windows 8.3 short-name component (like LONGNA~1.TXT) is refused in node read/write scopes: name the long '
                                  'path, so two spellings of one file can never hold two scopes (2.3-B Q6).')
        node['estimate_seconds'] = estimates.interval(node['estimate_seconds'])
        cap = node['execution_cap_seconds']
        exception = node.get('indivisible')
        if exception is not None:
            if (not isinstance(exception, dict) or set(exception) != {'reason','cap_seconds'}
                    or type(exception['cap_seconds']) not in (int,float) or not math.isfinite(exception['cap_seconds'])
                    or exception['cap_seconds'] != cap):
                raise LedgerError('An indivisible operation needs its reason and matching finite execution cap.')
            text_field(exception['reason'], 'indivisible reason', 1000)
            if len(exception['reason'].strip()) < 20:
                raise LedgerError('Explain why the operation cannot be split (at least 20 characters).')
        if (type(cap) not in (int, float) or not math.isfinite(cap) or cap < 1
                or cap > 7200 and exception is None
                or node['estimate_seconds'][1] > node['execution_cap_seconds']):
            raise LedgerError('Split a task above two hours, or give an indivisible operation reason and finite own cap; estimate must fit that cap.')
        if type(node['budget_calls']) is not int or not 1 <= node['budget_calls'] <= 10000:
            raise LedgerError('Node budget_calls must be a finite positive integer.')
        if type(node['integration']) is not bool or not isinstance(node['checks'], list) or not node['checks']:
            raise LedgerError('Every node needs checks and an explicit integration flag.')
        check_ids = set()
        for check in node['checks']:
            if not isinstance(check, dict) or set(check) != {'id', 'spec'}:
                raise LedgerError('Node checks require id and spec.')
            contracts._id(check['id'], 'check id'); text_field(check['spec'], 'check spec', 1000)
            if check['id'] in check_ids: raise LedgerError('Duplicate node check id.')
            check_ids.add(check['id'])
        if not isinstance(node['depends'], list): raise LedgerError('Node depends must be an explicit list.')
        seen = set()
        for edge in node['depends']:
            if (not isinstance(edge, dict) or set(edge) - {'node', 'requires', 'advance'} or
                    edge.get('node') not in known or edge['node'] in seen or edge.get('requires') not in ('produced', 'verified', 'accepted')):
                raise LedgerError('Nodes use ordered, unique dependencies with requires produced, verified or accepted.')
            seen.add(edge['node'])
            if 'advance' in edge:
                advance = edge['advance']
                if (edge['requires'] != 'produced' or not isinstance(advance, dict) or set(advance) != {'limit', 'discard_on_failure'}
                        or type(advance['limit']) is not int or not 1 <= advance['limit'] <= 100 or advance['discard_on_failure'] is not True):
                    raise LedgerError('Advance needs a finite limit and discard_on_failure=true on a produced edge.')
        known.add(node['id'])
    # W14b: across nodes, one file must be spelled one way. owned_match is case-folded, so 'a.txt' and 'A.txt' are the same grant and the
    # same Windows file; spelled differently they would pass as two disjoint writers.
    from ..dependency_core import owned_key
    spelled = {}
    for node in result:
        for path in node['write']:
            other = spelled.setdefault(owned_key(path), (path, node['id']))
            if other[0] != path:
                raise LedgerError(f'Write paths {other[0]!r} (node {other[1]}) and {path!r} (node {node["id"]}) are case-colliding spellings of one file; use one spelling.')
    if set().union(*(set(node['acceptance']) for node in result)) != set(outputs):
        raise LedgerError('U1: the internal plan must preserve every approved output.')
    integrations = [node for node in result if node['integration']]
    if not integrations:
        raise LedgerError('A mandatory integration node is required.')
    for node in integrations:
        if ({edge['node'] for edge in node['depends']} != known - {node['id']} or
                any(edge['requires'] == 'produced' for edge in node['depends'])):
            raise LedgerError('Integration must require verified/accepted evidence from every other node.')
    return result


def _finish_initial(nodes, outputs):
    """The first internal plan has no predecessor: only coverage of every approved output is judged (no checks to weaken yet)."""
    covered = {item for node in nodes for item in node.get('acceptance', [])}
    changes = [{'path': f'acceptance:{oid}', 'kind': 'removed_result', 'acceptance': True, 'why': 'no node proves this approved output'}
               for oid in outputs if oid not in covered]
    return {'acceptance_changed': bool(changes), 'classification': 'U1' if changes else 'routine', 'changes': changes,
            'summary': '; '.join(c['path'] for c in changes) or 'initial plan covers every output'}


def _to_come(ledger, state, old_nodes, nodes, before, conn=None):
    """R10 D8: which nodes of a revision still cost calls/time, for the Q1 ceiling check. Counted: every node that is new or whose
    generation this revision moves (definition, dependency, input or contract change: affected_revision, the projector's own rule), and
    every node not finished with valid evidence - pending, produced but not verified, held, running/unknown, failed - so the mandatory
    integration node counts until it is verified. Reused (0 more): an unmoved node verified/accepted on its current generation whose
    recorded inputs still match its producers. The remaining calls/seconds it is compared with are the sealed root group after used and
    reserved spend (budget_core), so nothing already spent is given back. Returns (counted, reused) node-id sets. Read-only."""
    ids = [n['id'] for n in nodes]
    if not old_nodes: return set(ids), set()
    from . import engine
    moved = affected_revision(old_nodes, nodes, contract_changed=before.get('contract_sha') not in (None, state['approved']['sha']))
    records = engine.state(ledger, state['selector'], conn)['nodes']
    by_id = {n['id']: n for n in nodes}
    reused = set()
    for nid in ids:
        record = records.get(nid)
        if (nid in moved or record is None or record.get('state') not in ('verified', 'accepted') or record.get('phase') == 'held'
                or record.get('verification_result') == 'fail'):
            continue
        inputs = record.get('inputs') or {}
        if set(inputs) != {edge['node'] for edge in by_id[nid]['depends']} or any(
                source not in records or any(inputs[source].get(key) != records[source].get(key) for key in ('artifact', 'generation'))
                for source in inputs):
            continue
        reused.add(nid)
    return set(ids) - reused, reused


def _beyond_deadline(nodes, counted, remaining_seconds):
    """R11 finding C: the execution-cap deadline check over the same to-come set `_to_come` counts. A node reused with valid evidence
    does not run again, so its cap cannot block the remaining work; every counted node (new, moved, pending/failed/unknown, integration
    not verified) must fit what is left of the sealed root deadline. Never extends the deadline. Returns the offending node ids."""
    return sorted(node['id'] for node in nodes if node['id'] in counted and node['execution_cap_seconds'] > remaining_seconds)


def revise(ledger, selector, nodes, *, reason, evidence, expected_revision=None):
    reason = text_field(reason, 'internal revision reason', 1000)
    refs = estimates.evidence(evidence)
    if (not isinstance(nodes, list) or any(not isinstance(node, dict) or not isinstance(node.get('acceptance'), list)
                                         or not isinstance(node.get('checks'), list) for node in nodes)):
        raise LedgerError('Internal nodes require explicit acceptance and check lists.')
    with ledger.transaction() as conn:
        state, contract, sha = context(ledger, conn, selector)
        before = current(ledger, state['selector'], conn)
        ctx = ceilings(ledger, conn, state)
    outputs = contracts.output_ids(contract['output'])
    old_nodes = before['definition']['nodes'] if before['definition'] else []
    acceptance = {item for node in nodes for item in node.get('acceptance', [])}
    # W05/T21: wording-only spec changes and added checks are routine; a dropped output/check, a changed threshold or any change this
    # classifier cannot place is a change of acceptance (U1), decided through the same authority gate as before.
    from . import acceptance_diff
    diff = acceptance_diff.classify_nodes(old_nodes, nodes, outputs) if old_nodes else _finish_initial(nodes, outputs)
    if diff['acceptance_changed'] or acceptance != set(outputs):
        decide(ledger, state, contract, sha, {'kind': 'change_acceptance', 'nodes': [n.get('id') for n in nodes],
                                              'changes': diff['changes'][:20], 'summary': diff['summary']}, ctx, 'onecrew.internal_plan')
    normalized = _validate(nodes, outputs)
    if old_nodes:
        # W19 (T38c): a node whose generation this revision moves cannot keep a repair marker bound to its old generation.
        from . import repair_tasks
        moved = affected_revision(old_nodes, normalized, contract_changed=before.get('contract_sha') not in (None, state['approved']['sha']))
        normalized = repair_tasks.rebind_revised(ledger, state['selector'], old_nodes, normalized, moved, expected_revision=before['internal_revision'])
    with ledger.transaction() as conn:
        _admit_revision(ledger,conn,state,before,normalized)
    counted, reused = _to_come(ledger, state, old_nodes, normalized, before)
    if _beyond_deadline(normalized, counted, ctx['remaining_seconds']):
        raise LedgerError('A task execution cap exceeds the remaining root deadline; replanning cannot extend it.')
    paths = sorted({path for node in normalized for path in node['write']})
    if paths:
        # The same scope function used by the root authority gate, not another matcher.
        if authority.covers(authority.effective(contract), {'edit': True, 'paths': paths}):
            decide(ledger, state, contract, sha, {'kind': 'write', 'paths': paths, 'nodes': [n['id'] for n in normalized]}, ctx, 'onecrew.internal_plan')
    definition = {'version': 1, 'nodes': normalized, 'acceptance': {oid: [n['id'] for n in normalized if oid in n['acceptance']] for oid in outputs}}
    definition_sha = content_hash(definition)
    if before.get('definition_sha') == definition_sha and before.get('contract_revision') == state['approved']['revision'] and before.get('contract_sha') == sha:
        return before
    if expected_revision is not None and expected_revision != before['internal_revision']:
        raise LedgerError('Stale internal plan revision.')
    action = {'kind': 'decision', 'q': 'Q1', 'nodes': [n['id'] for n in normalized], 'acceptance_changed': False,
              'cost': {'calls': sum(n['budget_calls'] for n in normalized if n['id'] in counted),
                       'seconds': sum(n['estimate_seconds'][1] for n in normalized if n['id'] in counted)}}
    decision = decide(ledger, state, contract, sha, action, ctx, 'onecrew.internal_plan')
    blob = Snapshots(ledger.state_root).blob(canonical(definition).encode('utf-8'))
    revision = before['internal_revision'] + 1
    with ledger.transaction(write=True) as conn:
        again, _, current_sha = context(ledger, conn, state['selector'])
        from . import runtime_unknowns
        runtime_unknowns.validate_revision(ledger, state['selector'], normalized, conn)
        if current_sha != sha or current(ledger, state['selector'], conn)['internal_revision'] != before['internal_revision']:
            raise LedgerError('The root or internal plan changed before revision publication.')
        _admit_revision(ledger,conn,again,before,normalized)
        remaining = ceilings(ledger, conn, again)
        # The to-come set is recomputed under the publishing lock: a node invalidated after the decision is not published as reused.
        if (_to_come(ledger, again, old_nodes, normalized, before, conn) != (counted, reused)
                or action['cost']['calls'] > remaining['remaining_calls'] or action['cost']['seconds'] > remaining['remaining_seconds']
                or _beyond_deadline(normalized, counted, remaining['remaining_seconds'])):
            raise LedgerError('Remaining root budget/deadline changed before revision publication.')
        plans.emit(ledger, conn, again['task_id'], KIND, {'plan': state['name'], 'revision': state['approved']['revision'],
                   'internal_revision': revision, 'contract_sha': sha, 'definition': blob, 'definition_sha': definition_sha,
                   'reason': reason, 'decision': decision, 'evidence': refs,
                   'cost': dict(action['cost'], counted=sorted(counted), reused=sorted(reused)),
                   'acceptance_diff': {'classification': diff['classification'], 'summary': diff['summary'],
                                       'changes': [{k: c[k] for k in ('path', 'kind', 'acceptance')} for c in diff['changes'][:20]]}})
    estimates.observe_internal(ledger,state['selector'],reason=reason,evidence=refs)
    if namespaces.has_capability(state, 'finding-register'):
        from . import active_plan
        active_plan.export(ledger, state['selector'])
    return current(ledger, state['selector'])
