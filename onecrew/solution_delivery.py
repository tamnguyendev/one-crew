"""Durable, serial delivery coordinator. The host chat is not a scheduler."""
import datetime as dt
import json
import uuid
from pathlib import Path

from .ledger import LedgerError, canonical, content_hash, key_field, utcnow, validate_grant
from .owned import Owned
from .workflow import task_lock
from .control import CapacityWait
from . import delivery_store as db


def submit(ledger, goal, key, plan, solution_id, solution_revision, *, max_calls=100, max_seconds=7200,
           provider=None, model=None):
    from .delivery_plan import validate
    from .model_preferences import resolve, read
    from .conversations import approved
    from .control import migrate
    if not isinstance(goal,str) or not 1 <= len(goal) <= 2000: raise LedgerError('Bounded root goal required.')
    key_field(key); plan=validate(plan)
    migrate(ledger)
    with ledger.transaction() as conn:
        old=conn.execute('SELECT payload FROM tasks WHERE project_id=? AND request_key=?',(ledger.project_id,key)).fetchone()
    previous=json.loads(old[0]).get('owned_execution') if old else read(ledger)
    provider,model=resolve(ledger,provider,model,previous)
    if provider!='claude': raise LedgerError('Delivery V1 uses the existing Claude native adapter.')
    permissions=['discover','report','native.test']
    if any(n['kind']=='change' for n in plan['nodes']):permissions+=['candidate.write','sandbox.test','workspace.apply']
    if any(n['kind']=='build' for n in plan['nodes']):permissions+=['android.build']
    if any(n['kind']=='device' for n in plan['nodes']):permissions+=['android.device']
    grant=validate_grant({'schema_version':1,'permissions':permissions,
                         'limits':{'max_calls':max_calls,'max_seconds':max_seconds},'source':'operator: delivery submit'})
    payload=dict(schema_version=1,project_id=ledger.project_id,project_path=ledger.project_path,
        spec_id='SOLUTION-DELIVERY',spec_revision=content_hash(plan),spec_text=goal,title=goal,goal=goal,
        owned_execution={'mode':'solution_delivery','provider':provider,'model':model,
                         'budget_policy':{'version':2,'warning_fraction':0.7}},solution_delivery=plan,
        solution_required=True,solution_id=solution_id,solution_revision=solution_revision,grant=grant)
    revision=content_hash(payload)
    with ledger.transaction(write=True) as conn:
        db.ensure(conn,ledger); sol,decision=approved(ledger,conn,solution_id,solution_revision)
        old=conn.execute('SELECT * FROM tasks WHERE project_id=? AND request_key=?',(ledger.project_id,key)).fetchone()
        if old:
            if old['revision']!=revision: raise LedgerError('Delivery key already bound to another plan or grant.')
            return ledger._task_view(conn,old)
        for peer in conn.execute('SELECT task_id FROM solution_bindings WHERE solution=?',(solution_id,)):
            latest=conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='workflow.checkpoint' ORDER BY seq DESC LIMIT 1",(peer[0],)).fetchone()
            if not latest or json.loads(latest[0])['phase'] not in ('completed','cancelled','failed'):
                raise LedgerError('Solution already has live work; do not reparent or race it.')
        tid='TASK-'+uuid.uuid4().hex; now=utcnow()
        end=(dt.datetime.fromisoformat(now)+dt.timedelta(seconds=max_seconds)).isoformat()
        conn.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',(tid,ledger.project_id,ledger.project_path,key,revision,canonical(payload),now,end))
        conn.execute('INSERT INTO solution_bindings VALUES(?,?,?,?,?)',(tid,sol['conversation'],solution_id,solution_revision,decision['id']))
        conn.execute('INSERT INTO delivery_roots VALUES(?,?,?)',(tid,canonical(plan),content_hash(plan)))
        ledger._event(conn,tid,'task.submitted',{'revision':revision,'request_key':key,'mode':'solution_delivery'})
        return ledger._task_view(conn,ledger._task(conn,tid))


class Delivery(Owned):
    def enable(self, task_id):
        from .solution_gate import check
        from .control import migrate
        check(self.ledger,task_id); migrate(self.ledger)
        with task_lock(self.ledger,task_id):
            seq,state=self.state(task_id)
            if state: return state
            task=self.ledger.task(task_id,full=True); payload=task['handoff']; plan=payload['solution_delivery']
            self.control.configure(task_id,task['revision'],{'mode':'solution_delivery','profile':payload['owned_execution'],'capability':{'mode':'coordinator'}})
            state=dict(mode='owned_execution',phase='running',verification='pending',acceptance='pending',
                snapshot=None,message='Delivery preflight pending.',pending=None,step=0,response=None,
                plan=plan,files={},original={},receipts=[],tests=[],deliveries=[],usage=[],outputs=[],worker=payload['owned_execution'],
                delivery={'version':1,'generation':0,'repairs':0,'child_intent':None,'source':None,'baseline':None,
                    'nodes':{n['id']:{'phase':'pending','generation':0,'receipt':None,'child':None} for n in plan['nodes']},
                    'history':[],'criteria':{a['id']:'pending' for a in plan['acceptance']},'delivery_status':'pending'})
            self.persist(task_id,seq,state); return state

    def resume(self, task_id):
        from .solution_gate import check
        check(self.ledger,task_id)
        with task_lock(self.ledger,task_id):
            seq,s=self.state(task_id); c=self.control.status(task_id)
            if s['phase'] in ('completed','cancelled','failed') or c['cancel_requested']: raise LedgerError('Terminal delivery cannot resume.')
            if self.ledger.requests(task_id,pending=True): raise LedgerError('Pending root question must be answered.')
            if any(a['status']!='settled' for a in c['attempts']): raise LedgerError('Reconcile root attempts before resume.')
            for row in s['delivery']['nodes'].values():
                if not row['child'] or row['phase']=='passed':continue
                if self.ledger.requests(row['child'],pending=True):raise LedgerError('Resolve the child question before resume: '+row['child'])
                cc=self.control.status(row['child'])
                if any(a['status']!='settled' for a in cc['attempts']):raise LedgerError('Child operation must settle before resume.')
            for row in s['delivery']['nodes'].values():
                if row['phase']=='uncertain': raise LedgerError('An operation may have run; inspect its receipt before recovery.')
                if row['phase']=='blocked': row['phase']='pending'
            s['phase']='running';s['message']='Resuming existing delivery; counters and evidence retained.'
            self.persist(task_id,seq,s,unpause=True)
            for row in s['delivery']['nodes'].values():
                if not row['child'] or row['phase']=='passed':continue
                child=Owned(self.ledger);cs=child.state(row['child'])[1]
                if cs and cs['phase'] in ('blocked','paused','waiting'):
                    if self.ledger.requests(row['child'],pending=True):raise LedgerError('Resolve the child question before resume: '+row['child'])
                    child.resume(row['child'])
            return s

    def _child(self, task_id, s, node, row):
        from .owned_intake import submit as child_submit
        from .runner import start, status
        goal=node['config']['goal']
        if row.get('feedback'): goal+='\nRepair verified failure without weakening assertions: '+row['feedback'][:2000]
        if not row['child']:
            intent={'node':node['id'],'generation':row['generation'],'goal':goal}
            s['delivery']['child_intent']=intent
            seq=self.state(task_id)[0];self.persist(task_id,seq,s)
            task=self.ledger.task(task_id,full=True)['handoff']; limits=task['grant']['limits']
            child=child_submit(self.ledger,goal,f"delivery:{task_id}:{node['id']}:{row['generation']}",mode='change',
                provider=s['worker']['provider'],model=s['worker']['model'],max_calls=limits['max_calls'],max_seconds=limits['max_seconds'],
                native_change=node['config']['recipe'],solution_id=task['solution_id'],solution_revision=task['solution_revision'],
                _delivery_parent=task_id,_delivery_node=node['id'],_delivery_generation=row['generation'])
            row['child']=child['id'];row['phase']='running'
            self.persist(task_id,self.state(task_id)[0],s)
        child_runtime=Owned(self.ledger)
        child_state=child_runtime.state(row['child'])[1]
        if child_state is None: child_state=child_runtime.enable(row['child'])
        if child_state['phase']=='completed':
            from .delivery_steps import fingerprint,load_manifest,store_manifest
            native=child_state.get('native_change',{})
            if not child_state.get('workspace_applied') or not native.get('review_accepted'):
                raise LedgerError('Child completion lacks reviewed application evidence.')
            current=fingerprint(self.ledger.project,s['plan']['source_roots'])
            expected=dict(load_manifest(s['delivery']['source'])['files'])
            expected.update(native.get('changes',{}))
            if current['files']!=expected:raise LedgerError('Source differs from the exact child patch; external edits require reconciliation.')
            s['delivery']['source']=store_manifest(self,task_id,current)
            return {'passed':True,'source':s['delivery']['source']['hash'],'task':row['child'],
                    'snapshot':child_state['snapshot'],'verification':child_state['verification'],
                    'review_accepted':native.get('review_accepted') is True,
                    'tests':child_state.get('tests',[]),'timeout_checkpoints':len(native.get('timeout_checkpoints',[])),
                    'assistance':child_state.get('assistance','unknown')}
        if child_state['phase'] in ('blocked','waiting','paused','failed','cancelled'):
            s['delivery']['child_questions']=self.ledger.requests(row['child'],pending=True)
            raise LedgerError('Child '+row['child']+': '+str(child_state.get('message'))[:1200])
        run=status(self.ledger,row['child'])
        if run['status']=='stopped': start(self.ledger,row['child'])
        return None

    def _repair(self, s, node, receipt):
        if receipt.get('failure_kind') not in ('test','product','review'): return False
        candidates=[n for n in s['plan']['nodes'] if n['kind']=='change' and n['id'] in node['depends']]
        # Only an explicitly bound repair target; never let the model choose new ownership.
        target=node['config'].get('repair_node')
        if target: candidates=[n for n in s['plan']['nodes'] if n['id']==target and n['kind']=='change']
        if len(candidates)!=1 or s['delivery']['repairs']>=s['plan']['max_repairs']: return False
        failure=content_hash({'node':node['id'],'source':s['delivery']['source']['hash'],'kind':receipt['failure_kind'],
                              'detail':receipt.get('detail')})
        failures=s['delivery'].setdefault('failure_counts',{})
        if failures.get(failure,0)>=2:return False
        failures[failure]=failures.get(failure,0)+1
        target=candidates[0]['id']; affected={target}
        for n in s['plan']['nodes']:
            if set(n['depends']) & affected: affected.add(n['id'])
        d=s['delivery'];d['history'].append({'repair':target,'failed_node':node['id'],'receipt':receipt})
        d['repairs']+=1;d['generation']+=1
        for name in affected:
            row=d['nodes'][name]
            if row.get('receipt'): d['history'].append({'invalidated':name,'receipt':row['receipt']})
            row.update(phase='pending',receipt=None,child=None,generation=row['generation']+1)
            row.pop('review_context',None)
        d['nodes'][target]['feedback']=str(receipt.get('detail') or receipt)[:2000]
        d['criteria']={a['id']:'pending' for a in s['plan']['acceptance']}
        return True

    def _clean_rebuild(self,s,node,receipt):
        if node['kind']!='apk_audit' or not receipt.get('packaging_anomaly'):return False
        d=s['delivery'];build=node['config']['build_node'];seen=d.setdefault('clean_rebuilds',[])
        if build in seen or d['repairs']>=s['plan']['max_repairs']:return False
        seen.append(build);d['repairs']+=1;d['generation']+=1;affected={build}
        for n in s['plan']['nodes']:
            if set(n['depends'])&affected:affected.add(n['id'])
        d['history'].append({'clean_rebuild':build,'reason':'ZIP anomaly','receipt':receipt})
        for name in affected:
            r=d['nodes'][name]
            if r.get('receipt'):d['history'].append({'invalidated':name,'receipt':r['receipt']})
            r.update(phase='pending',receipt=None,generation=r['generation']+1)
        d['criteria']={a['id']:'pending' for a in s['plan']['acceptance']}
        return True

    def run(self, task_id, steps=1):
        from .delivery_steps import fingerprint, execute
        from .solution_gate import check
        from .sandbox_gate import task_guard
        with task_lock(self.ledger,task_id):
            seq,s=self.state(task_id)
            if not s: raise LedgerError('Enable delivery first.')
            if s['phase'] in ('completed','failed','cancelled','blocked'): return s
            previous=content_hash(s)
            try:
                check(self.ledger,task_id); task_guard(self.control,task_id)()
                from .effort_watch import check as effort
                seq,waiting=effort(self,task_id,seq,s)
                if waiting:return s
                d=s['delivery']
                if d['baseline'] is None:
                    source=fingerprint(self.ledger.project,s['plan']['source_roots'])
                    from .delivery_steps import capture,home,preflight,store_manifest
                    d['preflight']=preflight(self,task_id,s,source)
                    path=home(self,task_id)/('baseline-'+uuid.uuid4().hex[:10])
                    capture(self.ledger.project,source,path,s['plan']['source_roots'])
                    d['baseline']=store_manifest(self,task_id,source);d['source']=d['baseline'];d['baseline_path']=str(path)
                    s['message']='Preflight source captured; execution pending.'
                    self.persist(task_id,seq,s);return s
                ready=next((n for n in s['plan']['nodes'] if d['nodes'][n['id']]['phase']!='passed' and all(d['nodes'][x]['phase']=='passed' for x in n['depends'])),None)
                if not ready: raise LedgerError('No ready delivery node; dependencies or receipts unresolved.')
                row=d['nodes'][ready['id']]
                if row['phase']=='uncertain': raise LedgerError('Operation outcome unknown; no automatic replay.')
                if ready['kind']!='change' and fingerprint(self.ledger.project,s['plan']['source_roots'])['hash']!=d['source']['hash']:
                    raise LedgerError('Source drift after review/change; preserve evidence and reconcile before continuing.')
                from .delivery_steps import check_tools
                if ready['kind']!='change' or not row['child']:check_tools(d['preflight'])
                if ready['kind']=='change' and not row['child'] and fingerprint(self.ledger.project,s['plan']['source_roots'])['hash']!=d['source']['hash']:
                    raise LedgerError('Source drift before child dispatch.')
                if ready['kind']=='handover':
                    for n in s['plan']['nodes']:
                        if n['kind'] not in ('change','handover') and d['nodes'][n['id']]['receipt'].get('source')!=d['source']['hash']:
                            raise LedgerError('Stale verification evidence cannot satisfy handover.')
                s['message']='Delivery: '+ready['id'];s['phase']='running'
                row.setdefault('started_at',utcnow());row['input_source']=d['source']['hash']
                if ready['kind']=='change': receipt=self._child(task_id,s,ready,row)
                else:
                    if row['phase']=='running' and ready['kind'] not in ('regression','review','handover','apk_audit'):
                        row['phase']='uncertain';raise LedgerError('Interrupted native operation; inspect evidence before retry.')
                    row['phase']='running';self.persist(task_id,self.state(task_id)[0],s)
                    receipt=execute(self,task_id,s,ready,row)
                if receipt is None:
                    s['phase']='waiting_operation'
                    if content_hash(s)!=previous:self.persist(task_id,self.state(task_id)[0],s)
                    return s
                if ready['kind']!='change' and fingerprint(self.ledger.project,s['plan']['source_roots'])['hash']!=d['source']['hash']:
                    raise LedgerError('Source changed during execution; receipt cannot satisfy acceptance.')
                row['receipt']=receipt
                if not receipt.get('passed'):
                    if receipt.get('uncertain'):
                        row['phase']='uncertain';s.update(phase='blocked',message='Unknown device effect; inspect receipt before recovery.')
                    elif self._repair(s,ready,receipt) or self._clean_rebuild(s,ready,receipt): s['message']='Verified failure assigned to bounded repair.'
                    else:
                        row['phase']='blocked';s.update(phase='blocked',message=ready['id']+': '+str(receipt.get('detail','Acceptance failed'))[:1500])
                else:
                    if receipt.get('source')!=d['source']['hash']:raise LedgerError('Receipt missing current source provenance.')
                    row['phase']='passed'
                    row['finished_at']=utcnow()
                    for a in s['plan']['acceptance']:
                        d['criteria'][a['id']]='passed' if all(d['nodes'][n]['phase']=='passed' for n in a['nodes']) else 'pending'
                    if ready['kind']=='handover':
                        if any(v!='passed' for v in d['criteria'].values()): raise LedgerError('Required criteria unresolved.')
                        s.update(phase='completed',verification='passed',acceptance='not_requested',message='Solution delivery technically verified; report ready. User acceptance and Windows receipt are separate.')
                        d['technical_verified']=True;d['product_acceptance']='not_requested'
                        s['outputs'].append({'stage':'solution_delivery','summary':s['report'],'verification':'passed','acceptance':'not_requested'})
                s['step']+=1
            except CapacityWait:
                s.update(phase='running',waiting_reason='capacity',message='Waiting for existing worker capacity; no new call charged.')
            except (ValueError,OSError) as error:
                s.update(phase='blocked',message=str(error)[:1800])
            self.persist(task_id,self.state(task_id)[0],s)
            return s

    def card(self, task_id):
        _,s=self.state(task_id)
        if not s: return {'task':task_id,'phase':'queued'}
        c=self.control.status(task_id)
        from .desktop_notifications import status,snapshots
        notices=status(self.ledger)
        records=sorted([r for r in notices['records'] if r and r['task']==task_id],key=lambda r:r['created_at'])
        due=snapshots(self.ledger,task=task_id)
        current=[r for r in records if due and r['id']==due[0]['id']]
        latest=current[-1]['status'] if current else 'pending' if due else 'not_due'
        delivery_status=('shown' if latest in ('shown','closed') else 'uncertain' if latest=='launching' else latest)
        return {'task':task_id,'phase':s['phase'],'execution_status':c['status'],'message':s['message'],
                'delivery':dict(s['delivery'],delivery_status=delivery_status),
                'budget':c['budget'],'report':s.get('report'),'report_file':s.get('report_file'),
                'windows':{'enabled':notices['config']['enabled'],'receipts':records}}
