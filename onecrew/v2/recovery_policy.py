"""W20 bounded repair/diagnosis using the exact shared v1 recovery policy."""
import copy
import json

from .. import recovery_core
from ..ledger import LedgerError, canonical, content_hash, text_field
from ..snapshots import Snapshots
from . import engine, internal_plan as ip, plan, repair_tasks

KIND = 'workflow.recovery_decided'
REPLAN = 'workflow.recovery_replanned'


def _history(conn, task):
    return [dict(json.loads(row['payload']),event=row['seq']) for row in conn.execute(
        'SELECT seq,payload FROM events WHERE task_id=? AND kind=? ORDER BY seq',(task,KIND))]


def assess(ledger, selector, failed_node):
    """One decision per authentic failed receipt; no provider or owner request."""
    with ledger.transaction(write=True) as conn:
        root, contract, sha=ip.context(ledger,conn,selector,'sequential-engine')
        view=engine.state(ledger,root['selector'],conn)
        receipt, source_event, failed=repair_tasks._source(ledger,conn,view,failed_node)
        history=_history(conn,root['task_id'])
        old=next((item for item in history if item['source_receipt']==receipt),None)
        if old: return old
        durable=json.loads(Snapshots(ledger.state_root).read_blob(history[-1]['state_blob'])) if history else {}
        # The core's material-progress identity receives actual artifacts and
        # passed checks. Merely incrementing a generation is not progress here.
        durable.update(source={'hash':content_hash({nid:record['artifact'] for nid,record in view['nodes'].items() if record['artifact']})},
                       nodes={nid:{'phase':'passed' if record['state'] in ('verified','accepted') and record['phase']!='held' else 'pending'}
                              for nid,record in view['nodes'].items()},generation=None)
        action, record=recovery_core.decide(durable,failed_node,'product',sorted(failed),'Configured checks still fail: '+', '.join(failed))
        replanned=conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind=? AND json_extract(payload,'$.signature')=?",
                              (root['task_id'],REPLAN,record['signature'])).fetchone()
        disposition='repair' if action=='repair' else 'blocked' if replanned else 'diagnose'
        value={'plan':root['name'],'revision':root['approved']['revision'],'contract_sha':sha,
               'node':failed_node,'source_receipt':receipt,'source_event':source_event,
               'signature':record['signature'],'policy_version':recovery_core.POLICY_VERSION,
               'action':action,'disposition':disposition,'record':record,
               'diagnosis':{'failed_checks':failed,'previous_failure_count':record['count']-1,
                            'current_artifact':view['nodes'][failed_node]['artifact'],
                            'next':'Repair the failed checks first.' if disposition=='repair' else
                                   'Propose one materially different plan inside the unchanged grant.' if disposition=='diagnose' else
                                   'Retain a blocker with failed receipts; do not repeat the same repair.'},
               'state_blob':Snapshots(ledger.state_root).blob(canonical(durable).encode()),
               'grants_authority':False,'creates_owner_request':False,'resets_budget':False}
        plan.emit(ledger,conn,root['task_id'],KIND,value)
        return _history(conn,root['task_id'])[-1]


def authorize_repair(ledger, selector, failed_node):
    decision=assess(ledger,selector,failed_node)
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
        row=conn.execute("SELECT payload FROM events WHERE task_id=? AND kind=? AND json_extract(payload,'$.node')=? ORDER BY seq DESC LIMIT 1",
                         (root['task_id'],REPLAN,failed_node)).fetchone()
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
        if conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind=? AND json_extract(payload,'$.signature')=?",
                        (root['task_id'],REPLAN,decision['signature'])).fetchone():
            raise LedgerError('This failure already used its bounded diagnostic replan.')
    if nodes==before['definition']['nodes']: raise LedgerError('A diagnostic replan must change the proposed approach.')
    rebound=repair_tasks.rebind_order(ledger,selector,nodes,expected_revision=before['internal_revision'])
    nodes_blob=Snapshots(ledger.state_root).blob(canonical(rebound).encode())
    # Use an explicit durable reservation BEFORE plan mutation: a crash does not
    # silently refund the one permitted diagnostic replan.
    with ledger.transaction(write=True) as conn:
        current=ip.current(ledger,root['selector'],conn)
        if current['internal_revision']!=before['internal_revision']:
            raise LedgerError('Plan changed before diagnostic replan reservation.')
        if conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind=? AND json_extract(payload,'$.signature')=?",
                        (root['task_id'],REPLAN,decision['signature'])).fetchone():
            raise LedgerError('This failure already reserved its diagnostic replan.')
        reservation={'plan':root['name'],'revision':root['approved']['revision'],'contract_sha':sha,'node':failed_node,
            'signature':decision['signature'],'source_receipt':decision['source_receipt'],'reason':reason,
            'evidence':refs,'internal_revision':before['internal_revision'],'caller_proposal_sha':proposal_hash,
            'proposed_nodes_sha':content_hash(rebound),'proposed_nodes_blob':nodes_blob,
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
