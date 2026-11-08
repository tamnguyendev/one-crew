"""W20 bounded repair/diagnosis using the exact shared v1 recovery policy."""
import copy
import datetime as dt
import json

from .. import recovery_core
from ..ledger import LedgerError, canonical, content_hash, text_field, utcnow
from ..snapshots import Snapshots
from . import engine, internal_plan as ip, plan, repair_tasks

KIND = 'workflow.recovery_decided'
REPLAN = 'workflow.recovery_replanned'


def _history(conn, task):
    return [dict(json.loads(row['payload']),event=row['seq']) for row in conn.execute(
        'SELECT seq,payload FROM events WHERE task_id=? AND kind=? ORDER BY seq',(task,KIND))]


def _clock(now):
    value=now or utcnow()
    try:
        parsed=value if isinstance(value,dt.datetime) else dt.datetime.fromisoformat(value)
        if parsed.tzinfo is None: raise ValueError('timezone required')
        return parsed
    except (TypeError,ValueError) as error:
        raise LedgerError('now: an ISO time with timezone.') from error


def _ceiling(conn, root, sha, clock):
    """What the root has spent against its sealed ceilings, the ceiling it has reached (or None), and the authority basis.

    T18a [E3]: the root budget is reached when used+reserved calls equal the sealed max_calls, or the clock is at/after the
    sealed deadline. Read from the ledger (budget_core.group), never from the policy's own count; nothing here changes a ceiling."""
    from .. import budget_core
    shared=budget_core.group(conn,root['task_id']) or {}
    spent={key:shared.get(key) for key in ('max_calls','used_calls','reserved_calls','remaining_calls','deadline')}
    stop=None
    calls=(shared.get('used_calls') or 0)+(shared.get('reserved_calls') or 0)
    if shared.get('max_calls') is not None and calls>=shared['max_calls']:
        stop={'ceiling':'calls','limit':shared['max_calls'],'spent':calls,'observed_at':clock.isoformat()}
    elif shared.get('deadline') and clock>=dt.datetime.fromisoformat(shared['deadline']):
        # The whole time window is spent: nothing is admitted after the deadline.
        stop={'ceiling':'deadline','limit':shared['deadline'],'spent':shared['deadline'],'observed_at':clock.isoformat()}
    basis={'approval':{'revision':root['approved']['revision'],'sha':root['approved']['sha']},'contract_sha':sha,
           'budget':{'authority':shared.get('authority'),'revision':shared.get('revision'),'source_approval':shared.get('source_approval')},
           'policy':{'module':'onecrew.recovery_core','version':recovery_core.POLICY_VERSION},
           'scope':'the unchanged approved grant','grants_authority':False}
    return spent, stop, basis


def _attempts(conn, task, node):
    return [dict(json.loads(row['payload']),event=row['seq']) for row in conn.execute(
        "SELECT seq,payload FROM events WHERE task_id=? AND kind='node.verification' AND json_extract(payload,'$.node')=? AND json_extract(payload,'$.result')='fail' ORDER BY seq",
        (task,node))]


def _durable(ledger, history, view):
    durable=json.loads(Snapshots(ledger.state_root).read_blob(history[-1]['state_blob'])) if history else {}
    # The core's material-progress identity receives actual artifacts and
    # passed checks. Merely incrementing a generation is not progress here.
    durable.update(source={'hash':content_hash({nid:record['artifact'] for nid,record in view['nodes'].items() if record['artifact']})},
                   nodes={nid:{'phase':'passed' if record['state'] in ('verified','accepted') and record['phase']!='held' else 'pending'}
                          for nid,record in view['nodes'].items()},generation=None)
    return durable


def _stop_next(stop):
    if stop['ceiling']=='calls':
        return f'Root call budget reached ({stop["spent"]}/{stop["limit"]}): stop here with this evidence. It was sealed at the first approval and an amendment cannot raise it; the remaining work needs a new plan the owner approves.'
    return f'Root deadline reached ({stop["limit"]}): stop here with this evidence. It was sealed at the first approval and an amendment cannot move it; the remaining work needs a new plan the owner approves.'


def _value(root, sha, view, node, receipt, source_event, failed, action, record, disposition, attempts, spent, stop, basis, durable, ledger, **extra):
    return dict({'plan':root['name'],'revision':root['approved']['revision'],'contract_sha':sha,
                 'node':node,'source_receipt':receipt,'source_event':source_event,
                 'signature':record['signature'],'policy_version':recovery_core.POLICY_VERSION,
                 'action':action,'disposition':disposition,'record':record,
                 'diagnosis':{'failed_checks':failed,'previous_failure_count':record['count']-1,
                              'current_artifact':view['nodes'][node]['artifact'],
                              'attempts':[{'event':a['event'],'generation':a.get('generation'),'internal_revision':a.get('internal_revision'),'receipt':a.get('receipt')} for a in attempts],
                              'spent':spent,
                              'next':_stop_next(stop) if stop else
                                     'Repair the failed checks first.' if disposition=='repair' else
                                     'Propose one materially different plan inside the unchanged grant.' if disposition=='diagnose' else
                                     'Retain a blocker with failed receipts; do not repeat the same repair.'},
                 **({'stop':stop} if stop else {}),
                 # T18a [E1]: what the decision stands on - the approval, the contract and the sealed root budget; it grants nothing.
                 'authority_basis':basis,
                 'state_blob':Snapshots(ledger.state_root).blob(canonical(durable).encode()),
                 'grants_authority':False,'creates_owner_request':False,'resets_budget':False}, **extra)


def assess(ledger, selector, failed_node, now=None):
    """One decision per authentic failed receipt; no provider or owner request.

    When the root budget or deadline is reached (T18a [E3]) the decision is a `blocked` budget stop, decided by the same
    recovery_core.decide (class 'budget'), carrying spent == ceiling, the ceiling and the authority basis."""
    clock=_clock(now)
    with ledger.transaction(write=True) as conn:
        root, contract, sha=ip.context(ledger,conn,selector,'sequential-engine')
        view=engine.state(ledger,root['selector'],conn)
        receipt, source_event, failed=repair_tasks._source(ledger,conn,view,failed_node)
        # An owner-approved revision opens a new allowance of the bounded policy (it was the owner's decision to go on); the sealed call and time
        # ceilings of the root are not touched by it. Inside one revision nothing resets the counters.
        history=[item for item in _history(conn,root['task_id']) if item.get('revision')==root['approved']['revision']]
        old=next((item for item in history if item['source_receipt']==receipt),None)
        if old: return old
        durable=_durable(ledger,history,view)
        spent, stop, basis=_ceiling(conn,root,sha,clock)
        if stop:
            action, record=recovery_core.decide(durable,failed_node,'budget',stop['ceiling'],_stop_next(stop),now=clock.isoformat())
            disposition='blocked'
        else:
            action, record=recovery_core.decide(durable,failed_node,'product',sorted(failed),'Configured checks still fail: '+', '.join(failed))
            replanned=conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind=? AND json_extract(payload,'$.signature')=? AND json_extract(payload,'$.revision')=?",
                                  (root['task_id'],REPLAN,record['signature'],root['approved']['revision'])).fetchone()
            disposition='repair' if action=='repair' else 'blocked' if replanned else 'diagnose'
        # T18a [E2]: the blocker carries its evidence - every failed verification of this node so far (the attempts) and what the root
        # has spent against its sealed ceilings. Read from the ledger, never from the policy's own count.
        attempts=_attempts(conn,root['task_id'],failed_node)
        plan.emit(ledger,conn,root['task_id'],KIND,_value(root,sha,view,failed_node,receipt,source_event,failed,action,record,
                                                          disposition,attempts,spent,stop,basis,durable,ledger))
        return _history(conn,root['task_id'])[-1]


def decision_for(conn, task_id, receipt, revision):
    """The recorded decision for one failed receipt on this revision, or None. Read-only."""
    return next((item for item in _history(conn,task_id) if item['source_receipt']==receipt and item.get('revision')==revision),None)


def stop_at_ceiling(ledger, selector, node, now=None):
    """T18a [E3]: record the root budget/deadline stop for `node` as the blocker event; None while no ceiling is reached.

    For a stop with no new failed receipt (the next round is simply not admitted). Once per node and ceiling; the rule is
    recovery_core.decide (class 'budget'); no request, no budget or deadline change."""
    clock=_clock(now)
    with ledger.transaction(write=True) as conn:
        root, contract, sha=ip.context(ledger,conn,selector,'sequential-engine')
        view=engine.state(ledger,root['selector'],conn)
        if node not in view['nodes']: raise LedgerError('Unknown internal node.')
        spent, stop, basis=_ceiling(conn,root,sha,clock)
        if not stop: return None
        history=_history(conn,root['task_id'])
        old=next((item for item in history if item['node']==node and (item.get('stop') or {}).get('ceiling')==stop['ceiling']
                  and item['stop']['limit']==stop['limit']),None)
        if old: return old
        try:
            receipt, source_event, failed=repair_tasks._source(ledger,conn,view,node)
        except LedgerError:
            receipt, source_event, failed=None, None, []
        durable=_durable(ledger,history,view)
        action, record=recovery_core.decide(durable,node,'budget',stop['ceiling'],_stop_next(stop),now=clock.isoformat())
        attempts=_attempts(conn,root['task_id'],node)
        # source_receipt stays None: this stop is not the decision for a failed receipt (assess keys those).
        plan.emit(ledger,conn,root['task_id'],KIND,_value(root,sha,view,node,None,source_event,failed,action,record,'blocked',
                                                          attempts,spent,stop,basis,durable,ledger,last_failed_receipt=receipt))
        return _history(conn,root['task_id'])[-1]


def authorize_repair(ledger, selector, failed_node, now=None):
    decision=assess(ledger,selector,failed_node,now)
    if decision['disposition']=='repair':
        # The repair was decided on an earlier receipt; the root may have reached a ceiling since.
        decision=stop_at_ceiling(ledger,selector,failed_node,now) or decision
    if decision['disposition']!='repair':
        raise LedgerError('Recovery requires '+decision['disposition']+': '+decision['diagnosis']['next'])
    return decision


def replan(ledger, selector, failed_node, nodes, *, reason, evidence):
    """One recorded in-grant alternative; counters and root ceilings survive."""
    text_field(reason,'diagnosis/replan reason',1000)
    refs=ip.estimates.evidence(evidence)
    proposal_hash=content_hash(nodes)
    with ledger.transaction() as conn:
        root, _, _=ip.context(ledger,conn,selector,'sequential-engine')
        row=conn.execute("SELECT payload FROM events WHERE task_id=? AND kind=? AND json_extract(payload,'$.node')=? AND json_extract(payload,'$.revision')=? ORDER BY seq DESC LIMIT 1",
                         (root['task_id'],REPLAN,failed_node,root['approved']['revision'])).fetchone()
        reservation=json.loads(row['payload']) if row else None
    if reservation and reservation['state']=='reserved':
        if reservation.get('caller_proposal_sha',reservation['proposed_nodes_sha'])!=proposal_hash or reservation['evidence']!=refs or reservation['reason']!=reason:
            raise LedgerError('A diagnostic replan is already reserved; reconcile its exact proposal first.')
        return _finish_replan(ledger,selector,nodes,reservation)
    decision=assess(ledger,selector,failed_node)
    if decision['disposition']!='diagnose': raise LedgerError('No further automatic replan is available for this failure.')
    if decision['source_receipt'] not in refs:
        raise LedgerError('A diagnostic replan must cite the failed receipt it addresses.')
    with ledger.transaction() as conn:
        root, contract, sha=ip.context(ledger,conn,selector,'sequential-engine')
        before=ip.current(ledger,root['selector'],conn)
        if conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind=? AND json_extract(payload,'$.signature')=? AND json_extract(payload,'$.revision')=?",
                        (root['task_id'],REPLAN,decision['signature'],root['approved']['revision'])).fetchone():
            raise LedgerError('This failure already used its bounded diagnostic replan.')
    if nodes==before['definition']['nodes']: raise LedgerError('A diagnostic replan must change the proposed approach.')
    rebound=repair_tasks.rebind_order(ledger,selector,nodes,expected_revision=before['internal_revision'],failed_node=failed_node,
                                      source=decision['source_receipt'],failed_checks=decision['diagnosis']['failed_checks'])
    marker=next((value[len(repair_tasks.PREFIX):] for node in rebound for value in node['input'] if isinstance(value,str) and value.startswith(repair_tasks.PREFIX)),None)
    with ledger.transaction() as conn:
        counted,_=ip._to_come(ledger,root,before['definition']['nodes'],rebound,before,conn)
        room=ip.ceilings(ledger,conn,root)
    calls=sum(node['budget_calls'] for node in rebound if node['id'] in counted)
    seconds=sum(node['estimate_seconds'][1] for node in rebound if node['id'] in counted)
    if calls>room['remaining_calls'] or seconds>room['remaining_seconds']:
        raise LedgerError(f'U2: this replan needs {calls} calls and up to {seconds} s ({", ".join(sorted(counted))}); the root has {room["remaining_calls"]} calls and '
                          f'{int(room["remaining_seconds"])} s left. Nothing was changed; the sealed ceilings of the root cannot be raised here.')
    if marker:
        # It lifts holds as a repair does, so it stands on the same authority: Q5, delegated or answered by the owner.
        verdict=ip.self_decided(ledger,root['selector'],'Q5',sorted(counted),'onecrew.recovery_policy',key='q5-replan-'+proposal_hash[:48],
                                failed_node=failed_node,evidence=[decision['source_receipt'],marker])
        if verdict['delegation']==ip.NOT_DELEGATED:
            result=verdict['result']
            with ledger.transaction() as conn:
                view=engine.state(ledger,root['selector'],conn)
            request=engine.hold_out_of_authority(ledger,root,sha,view,verdict['ctx'],failed_node,verdict['action'],result,verdict['decision'],
                                                 affected=sorted(set(counted)&set(view['nodes'])))
            raise LedgerError(str(result['class'])+': '+result['reason']+'; the replan was not created (request '+request['id']+').')
    nodes_blob=Snapshots(ledger.state_root).blob(canonical(rebound).encode())
    # Use an explicit durable reservation BEFORE plan mutation: a crash does not
    # silently refund the one permitted diagnostic replan.
    with ledger.transaction(write=True) as conn:
        current=ip.current(ledger,root['selector'],conn)
        if current['internal_revision']!=before['internal_revision']:
            raise LedgerError('Plan changed before diagnostic replan reservation.')
        if conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind=? AND json_extract(payload,'$.signature')=? AND json_extract(payload,'$.revision')=?",
                        (root['task_id'],REPLAN,decision['signature'],root['approved']['revision'])).fetchone():
            raise LedgerError('This failure already reserved its diagnostic replan.')
        if marker:
            plan.emit(ledger,conn,root['task_id'],'workflow.repair_prepared',{'receipt':marker,'source_receipt':decision['source_receipt'],
                      'source_receipts':sorted(repair_tasks.finding_scope._sources_of(json.loads(Snapshots(ledger.state_root).read_blob(marker)))),'contract_sha':sha})
        reservation={'plan':root['name'],'revision':root['approved']['revision'],'contract_sha':sha,'node':failed_node,
            'signature':decision['signature'],'source_receipt':decision['source_receipt'],'reason':reason,
            'evidence':refs,'internal_revision':before['internal_revision'],'caller_proposal_sha':proposal_hash,
            'proposed_nodes_sha':content_hash(rebound),'proposed_nodes_blob':nodes_blob,
            'authority_basis':decision.get('authority_basis'),   # T18a [E1]: the replan stands on the diagnose decision's basis
            'state':'reserved','resets_budget':False}
        plan.emit(ledger,conn,root['task_id'],REPLAN,reservation)
    return _finish_replan(ledger,selector,nodes,reservation)


def _finish_replan(ledger,selector,nodes,reservation):
    if reservation.get('proposed_nodes_blob'):
        nodes=json.loads(Snapshots(ledger.state_root).read_blob(reservation['proposed_nodes_blob']))
        if content_hash(nodes)!=reservation['proposed_nodes_sha']:
            raise LedgerError('Stored diagnostic plan hash mismatch; its reservation remains retained.')
    with ledger.transaction() as conn:
        root,_,sha=ip.context(ledger,conn,selector,'sequential-engine')
        current=ip.current(ledger,root['selector'],conn)
    if sha!=reservation['contract_sha']: raise LedgerError('Root changed during diagnostic replan; reconcile the retained reservation.')
    if current['internal_revision']==reservation['internal_revision']:
        revised=ip.revise(ledger,selector,copy.deepcopy(nodes),reason=reservation['reason'],evidence=reservation['evidence'],
                          expected_revision=reservation['internal_revision'])
    elif (current['internal_revision']==reservation['internal_revision']+1
          and content_hash(current['definition']['nodes'])==reservation['proposed_nodes_sha']):
        revised=current
    else: raise LedgerError('Another internal revision superseded the reserved diagnostic replan.')
    with ledger.transaction(write=True) as conn:
        previous=conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind=? AND json_extract(payload,'$.signature')=? AND json_extract(payload,'$.state')='published'",
                              (root['task_id'],REPLAN,reservation['signature'])).fetchone()
        if not previous:
            plan.emit(ledger,conn,root['task_id'],REPLAN,dict(reservation,state='published',plan_event=revised['event']))
    return {'replanned':True,'internal_revision':revised['internal_revision'],'event':revised['event'],
            'source_receipt':reservation['source_receipt'],'resets_budget':False,'grants_authority':False}
