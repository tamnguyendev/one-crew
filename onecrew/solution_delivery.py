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


def submit(ledger, goal, key, plan=None, solution_id=None, solution_revision=None, *, max_calls=None, max_seconds=None,
           provider=None, model=None):
    """Seal a delivery root. With plan=None the approved SOL envelope is the authority and OneCrew plans."""
    from .delivery_plan import validate
    from .delivery_planner import validate_envelope, covers, envelope_permissions
    from .model_preferences import resolve, read
    from .conversations import approved
    from .control import migrate
    if not isinstance(goal,str) or not 1 <= len(goal) <= 2000: raise LedgerError('Bounded root goal required.')
    if not solution_id or not solution_revision: raise LedgerError('Approved solution id and revision required.')
    key_field(key)
    migrate(ledger)
    with ledger.transaction() as conn:
        sol,_=approved(ledger,conn,solution_id,solution_revision)
        old=conn.execute('SELECT payload FROM tasks WHERE project_id=? AND request_key=?',(ledger.project_id,key)).fetchone()
    solution=json.loads(sol['payload']) if isinstance(sol['payload'],str) else sol['payload']
    envelope=validate_envelope(solution['envelope'],solution) if solution.get('envelope') else None
    if plan is None:
        if not envelope: raise LedgerError('OneCrew planning needs an approved solution envelope; submit an explicit plan otherwise.')
        budget=envelope['budget']
        if (max_calls or budget['max_calls'])!=budget['max_calls'] or (max_seconds or budget['max_seconds'])!=budget['max_seconds']:
            raise LedgerError('Budget must equal the approved envelope; only the user can change it.')
        max_calls,max_seconds=budget['max_calls'],budget['max_seconds']
        provider=provider or envelope['worker']['provider'];model=model or envelope['worker']['model']
        sealed={'planned':True,'envelope':envelope,'envelope_hash':content_hash(envelope)}
        permissions=envelope_permissions(envelope)
    else:
        plan=validate(plan)
        if envelope:
            findings=covers(envelope,plan)
            if findings: raise LedgerError('Plan exceeds the approved envelope: '+'; '.join(findings)[:1500])
            if (max_calls or 100)>envelope['budget']['max_calls'] or (max_seconds or 7200)>envelope['budget']['max_seconds']:
                raise LedgerError('Budget exceeds the approved envelope.')
        max_calls,max_seconds=max_calls or 100,max_seconds or 7200
        sealed=plan
        permissions=['discover','report','native.test']
        if any(n['kind']=='change' for n in plan['nodes']):permissions+=['candidate.write','sandbox.test','workspace.apply']
        if any(n['kind']=='build' for n in plan['nodes']):permissions+=['android.build']
        if any(n['kind']=='device' for n in plan['nodes']):permissions+=['android.device']
    if envelope:provider=provider or envelope['worker']['provider'];model=model or envelope['worker']['model']
    previous=json.loads(old[0]).get('owned_execution') if old else read(ledger)
    provider,model=resolve(ledger,provider,model,previous)
    if provider!='claude': raise LedgerError('Delivery V1 uses the existing Claude native adapter.')
    grant=validate_grant({'schema_version':1,'permissions':permissions,
                         'limits':{'max_calls':max_calls,'max_seconds':max_seconds},'source':'operator: delivery submit'})
    payload=dict(schema_version=1,project_id=ledger.project_id,project_path=ledger.project_path,
        spec_id='SOLUTION-DELIVERY',spec_revision=content_hash(sealed),spec_text=goal,title=goal,goal=goal,
        owned_execution={'mode':'solution_delivery','provider':provider,'model':model,
                         'budget_policy':{'version':2,'warning_fraction':0.7}},solution_delivery=sealed,
        solution_required=True,solution_id=solution_id,solution_revision=solution_revision,grant=grant)
    plan=sealed
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


def red_only(node, receipt):
    """Actionable feedback when every test passed but a declared red check did not fail by assertion on the
    unchanged code; None for any other failure (a real failing test still needs a production fix)."""
    counts=receipt.get('counts') or {}
    missing=[r for r in receipt.get('red') or [] if not r.get('behavioral_failure')]
    if node['kind']!='regression' or receipt.get('failure_kind')!='test' or receipt.get('errors') or counts.get('failed') or not missing:
        return None
    patterns={r['test']:r['error_pattern'] for r in node['config'].get('red') or []}
    lines=['All tests pass on the changed code; only the red evidence is missing. Production files are reviewed and correct: '
           'do NOT change them. Change test files only.']
    for r in missing:
        loaded=(r.get('counts') or {}).get('passed',0)>0 or (r.get('counts') or {}).get('failed',0)>1
        lines.append('On the UNCHANGED code '+r['test']+' must compile and fail by an assertion whose message matches '
                     +repr(patterns.get(r['test'],''))+'. It '+('ran but failed with a different message' if loaded else
                     'did not load (it uses something that exists only after the change, e.g. a new function or class)')+
                     '. Keep that file using only what already exists on the unchanged code (pump the existing widget, enter text, '
                     'tap, expect the visible text); rewrite or remove assertions on symbols added by the change.')
    return ' '.join(lines)[:2000]


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
            planned=bool(plan.get('planned'))
            state=dict(mode='owned_execution',phase='running',verification='pending',acceptance='pending',
                snapshot=None,message='OneCrew planning pending.' if planned else 'Delivery preflight pending.',pending=None,step=0,response=None,
                plan=None if planned else plan,files={},original={},receipts=[],tests=[],deliveries=[],usage=[],outputs=[],worker=payload['owned_execution'],
                delivery={'version':1,'generation':0,'repairs':0,'child_intent':None,'source':None,'baseline':None,
                    'nodes':{} if planned else {n['id']:{'phase':'pending','generation':0,'receipt':None,'child':None} for n in plan['nodes']},
                    'history':[],'criteria':{} if planned else {a['id']:'pending' for a in plan['acceptance']},'delivery_status':'pending',
                    'planning':{'mode':'onecrew','stage':'discover','envelope_hash':plan['envelope_hash']} if planned else {'mode':'entry'},
                    'failures':{},'recoveries':[],'escalations':[]})
            self.persist(task_id,seq,state); return state

    def seal(self, task_id, s, plan, provenance):
        """Bind a OneCrew-derived plan to the root; child authority then reads it like an entry plan."""
        from .delivery_plan import validate
        from .delivery_planner import covers
        plan=validate(plan);envelope=self.ledger.task(task_id,full=True)['handoff']['solution_delivery']['envelope']
        findings=covers(envelope,plan)
        if findings:raise LedgerError('Derived plan exceeds the approved envelope: '+'; '.join(findings)[:1500])
        with self.ledger.transaction(write=True) as conn:
            conn.execute('UPDATE delivery_roots SET plan=?,revision=? WHERE task_id=?',(canonical(plan),content_hash(plan),task_id))
            self.ledger._event(conn,task_id,'delivery.plan_sealed',{'plan_revision':content_hash(plan),**provenance})
        d=s['delivery'];s['plan']=plan
        d['nodes']={n['id']:{'phase':'pending','generation':0,'receipt':None,'child':None} for n in plan['nodes']}
        d['criteria']={a['id']:'pending' for a in plan['acceptance']}
        d['planning'].update(provenance,stage='sealed',plan_revision=content_hash(plan))
        s['message']='OneCrew plan sealed inside the approved envelope; preflight pending.'

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
                # 'uncertain' stays: run() reconciles read-only or applies the user's answer; never a blind replay.
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
            # A superseded generation must be terminal, or intake refuses the new writer for the same solution.
            with self.ledger.transaction() as conn:
                older=[r[0] for r in conn.execute('SELECT task_id FROM delivery_children WHERE root=? AND node=? AND generation<?',
                                                   (task_id,node['id'],row['generation']))] if db.installed(conn) else []
            for old in older:self._retire_child(old,node['id'])
            intent={'node':node['id'],'generation':row['generation'],'goal':goal}
            s['delivery']['child_intent']=intent
            seq=self.state(task_id)[0];self.persist(task_id,seq,s)
            task=self.ledger.task(task_id,full=True)['handoff']; limits=task['grant']['limits']
            child=child_submit(self.ledger,goal,f"delivery:{task_id}:{node['id']}:{row['generation']}",mode='change',
                provider=s['worker']['provider'],model=s['worker']['model'],max_calls=limits['max_calls'],max_seconds=limits['max_seconds'],
                native_change=node['config']['recipe'],solution_id=task['solution_id'],solution_revision=task['solution_revision'],
                _delivery_parent=task_id,_delivery_node=node['id'],_delivery_generation=row['generation'],
                _delivery_scope=row.get('scope'))
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
            pending=self._child_questions(row['child'])
            s['delivery']['child_questions']=pending
            from .delivery_recovery import FENCE
            import re
            answered=not pending and (
                (child_state['phase']=='blocked' and (child_state.get('waiting_reason')=='solution' or re.search(FENCE,str(child_state.get('message') or ''),re.I)))
                or (child_state['phase']=='waiting' and child_state.get('waiting_reason')=='user'))
            if not answered:
                raise LedgerError('Child '+row['child']+': '+str(child_state.get('message'))[:1200])
            # The child only waited for a question that is now answered, or for this root: continue it, no failure.
            if child_state['phase']=='blocked':self._revive_child(row['child'])
        run=status(self.ledger,row['child'])
        if run['status']=='stopped': start(self.ledger,row['child'])
        return None

    def _child_questions(self, child):
        """Pending task requests and solution questions (CREQ) that hold this child."""
        from .desktop_notifications import questions
        with self.ledger.transaction() as conn:return questions(conn,child)

    def _repair(self, s, node, receipt):
        if receipt.get('failure_kind') not in ('test','product','review'): return False
        candidates=[n for n in s['plan']['nodes'] if n['kind']=='change' and n['id'] in node['depends']]
        # Only an explicitly bound repair target; never let the model choose new ownership.
        target=node['config'].get('repair_node')
        if target: candidates=[n for n in s['plan']['nodes'] if n['id']==target and n['kind']=='change']
        elif not candidates:
            # A later node (build/device) has one unambiguous upstream owner only when the plan has one change.
            changes=[n for n in s['plan']['nodes'] if n['kind']=='change']
            candidates=changes if len(changes)==1 else []
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
        red=red_only(node,receipt)
        if red:
            # Trial 6 (12/10): the reviewed production code was right and every test passed; only the red evidence was
            # missing (the red test called a helper that exists only after the change, so it could not compile on the
            # unchanged code). Such a repair touches tests only, and the worker is told exactly what is wrong.
            d['nodes'][target]['scope']='tests';d['nodes'][target]['feedback']=red
        else:d['nodes'][target].pop('scope',None)
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

    def _answer(self, task_id, s):
        """Apply a user's answer to the root escalation. True when the checkpoint changed."""
        from . import delivery_recovery as rc
        d=s['delivery'];esc=d.get('escalation')
        if not esc:return False
        request=self.ledger.request(esc['request'])
        if request['state']=='pending':
            if s['phase']!='waiting':
                s.update(phase='waiting',waiting_reason='decision');return True
            return False
        answer=request['answer'];choice=answer['choice']
        if any(r.get('reply_id')==answer['id'] for r in s.get('consumed_replies',[])):
            d.pop('escalation',None)  # already applied once; the next failure opens a new decision episode
            return True
        if choice not in ('retry','stop'):raise LedgerError('Unknown recovery choice; no action applied.')
        from .eval_observe import decision_source
        who={'user':'the user','relayed':'the user (relayed by the entry)','entry':'the entry under delegation'}.get(
            decision_source(answer),'an unattributed reply')
        record=d['failures'].get(esc['signature'])
        d.pop('escalation',None);s.pop('waiting_reason',None)
        s.setdefault('consumed_replies',[]).append({'request_id':request['id'],'reply_id':answer['id'],
            'effect':'Recovery decision: '+choice+'; scope, budget and failure history unchanged.'})
        if choice=='stop':
            self.control.cancel(task_id)
            s.update(phase='cancelled',message='Stopped by '+who+' at a recovery decision; evidence retained.')
            return True
        if record:record['allowance']+=1;record['status']='user_retry'
        row=d['nodes'].get(esc.get('node') or '')
        if row and row['phase'] in ('blocked','uncertain','running'):row['phase']='pending'
        if s.get('pending'):
            # A failed model result is never replayed after a retry answer; a live attempt is left to settle.
            from .supervisor import Supervisor
            attempt=self.control.attempt(s['pending'])
            if attempt['status']=='settled' or Supervisor(self.control).reconcile(attempt['id'])['status']=='settled':
                s.setdefault('dropped_attempts',[]).append({'attempt':attempt['id'],'reason':'user_retry_after_failure','at':utcnow()})
                s['pending']=None;s.pop('pending_solution_context',None);s.pop('revalidate_pending',None)
                context=(d.get('planning') or {}).get('context')
                if context:context.update(session=str(uuid.uuid4()),started=False)
                if row:row.pop('review_context',None)
        for other in d['nodes'].values():
            if other.get('child') and other['phase'] in ('running','blocked','pending'):self._revive_child(other['child'])
        if esc.get('needs') is not None:d['planning']['stay_inside']=(d['planning'].get('stay_inside') or [])+esc['needs']
        d.pop('retry_after',None)
        s.update(phase='running',message='Retry chosen by '+who+'; resuming within the existing grant.')
        return True

    def _recover(self, task_id, s, node, cls, key, detail):
        """Apply the recovery policy to one classified failure; escalates at most once per state."""
        from . import delivery_recovery as rc
        d=rc.migrate(s['delivery']);node_id=node['id'] if node else None;original=cls
        # A replay-safe scenario may retry a failed UI assertion; the record keeps the real class.
        policy='transient' if cls=='device_assertion' and node and node['config'].get('replay_safe') else cls
        action,record=rc.decide(d,node_id or 'preflight',cls,key,detail,policy=policy)
        row=d['nodes'].get(node_id) if node_id else None
        def automatic(name):
            d['recoveries'].append({'signature':record['signature'],'class':cls,'action':name,'node':node_id,'at':utcnow(),'step':s['step']})
        if action=='wait':
            s.update(phase='waiting',waiting_reason='decision',message='Waiting for an answer to a pending question: '+str(detail)[:600])
            return
        if action in ('retry','replay') or (action=='reconcile' and node and node['kind']!='device'):
            if node and node['kind']=='change' and row and row.get('child'):
                if not self._revive_child(row['child']):
                    record['attempts'][-1]['action']='wait_settle';rc.schedule_retry(s,record,self.control.clock());return
            else:
                if action=='replay' and s.get('pending'):
                    # Only a settled (reconciled) attempt may be dropped; an unsettled one is never duplicated, and
                    # the row stays 'running' so the next due pass re-enters this replay path, not execute().
                    from .supervisor import Supervisor
                    attempt=self.control.attempt(s['pending'])
                    if attempt['status']!='settled' and Supervisor(self.control).reconcile(attempt['id'])['status']!='settled':
                        if row:row['phase']='running'
                        record['attempts'][-1]['action']='wait_settle';rc.schedule_retry(s,record,self.control.clock());return
                    s['pending']=None;s.pop('pending_solution_context',None)
                    if row:row.pop('review_context',None)
                if row and row['phase'] in ('running','blocked','uncertain','continuing'):row['phase']='pending'
            automatic(action);rc.schedule_retry(s,record,self.control.clock())
            return
        if action=='calibrate' and node and node['kind']=='device' and row:
            from .delivery_calibrate import MAX_CALIBRATIONS
            receipt=row.get('receipt') or {}
            if row.get('calibrations',0)<MAX_CALIBRATIONS:
                # The next pass re-authors only the unresolved selectors from the live-UI snapshot, then reruns the stage.
                d['history'].append({'device_failed':node_id,'generation':row['generation'],'receipt':receipt})
                row['calibrate']={'failure':receipt.get('selector_failure'),'snapshot':receipt.get('ui_snapshot'),'at':utcnow()}
                row['phase']='pending';automatic('calibrate')
                s['message']='Device selector did not resolve on the live UI; OneCrew recalibrates its scenario.'
                return
            action='ask'
        if action=='reconcile':
            from .delivery_android import reconcile
            outcome=reconcile(self,task_id,s,node,row)
            d['history'].append({'reconcile':node_id,'generation':row['generation'],'outcome':outcome})
            if outcome.get('replay'):
                row['phase']='pending';automatic('reconcile');rc.schedule_retry(s,record,self.control.clock());return
            record['detail']=(record['detail']+' Reconcile: '+outcome.get('detail',''))[:500];action='ask'
        if action=='repair' and node:
            receipt=row.get('receipt') if row else None
            if receipt and cls=='product' and receipt.get('failure_kind') not in ('test','product','review'):
                receipt=dict(receipt,failure_kind='product')  # e.g. a Dart compile error found by the build
            if receipt and (self._repair(s,node,receipt) or self._clean_rebuild(s,node,receipt)):
                automatic('repair');s['message']='Verified failure assigned to bounded repair.';return
        if action=='repair' and node and node['kind']=='change' and self._regenerate(s,node,row,detail):
            automatic('regenerate');s['message']='Child failed within scope; new child generation with feedback.';return
        receipt=(row or {}).get('receipt') or {}
        if (node and node['kind']=='device' and node['config'].get('optional') and original in ('environment','transient','permission')
                and row and not receipt.get('uncertain') and not receipt.get('scenario_started') and not receipt.get('steps')):
            # Only an environment that was never usable becomes 'not run'; a scenario that ran and failed is a finding.
            self._skip_optional(s,node,row,detail);return
        if row and row['phase'] in ('running','pending'):row['phase']='blocked'
        record['status']='escalated';record['class']=original
        from .delivery_recovery import escalate
        escalate(self,task_id,s,dict(record,signature=record.get('signature')),node_id)

    def _criteria(self, s):
        d=s['delivery']
        for a in s['plan']['acceptance']:
            rows=[d['nodes'][n] for n in a['nodes']]
            d['criteria'][a['id']]=('not_run' if any((r.get('receipt') or {}).get('skipped') for r in rows) else
                                    'passed' if all(r['phase']=='passed' for r in rows) else 'pending')

    def _skip_optional(self, s, node, row, detail):
        """An optional E2E environment that is unavailable is reported as not run, never as passed."""
        d=s['delivery']
        if row.get('receipt'):d['history'].append({'skipped_optional':node['id'],'receipt':row['receipt']})
        row['receipt']={'passed':True,'skipped':True,'source':d['source']['hash'],'detail':'Optional device stage not run: '+str(detail)[:400]}
        row['phase']='passed';row['finished_at']=utcnow()
        d['recoveries'].append({'class':'environment','action':'skip_optional','node':node['id'],'at':utcnow(),'step':s['step']})
        self._criteria(s);s.update(phase='running',message='Optional device stage unavailable; recorded as not run.')

    def _revive_child(self, child_id):
        """Resume a technically stopped child. A settled failed attempt is dropped, never re-launched blindly."""
        child=Owned(self.ledger)
        with task_lock(self.ledger,child_id):
            seq,cs=child.state(child_id)
            if not cs or cs['phase'] in ('completed','cancelled','failed'):return False
            if self.ledger.requests(child_id,pending=True):return False
            if cs.get('pending'):
                attempt=self.control.attempt(cs['pending'])
                if attempt['status']!='settled':return False
                result=json.loads(attempt['result'] or '{}') if isinstance(attempt.get('result'),str) else (attempt.get('result') or {})
                if result.get('reason') or result.get('exit_code') not in (0,None):
                    cs['pending']=None;cs.pop('pending_solution_context',None)
                    cs.setdefault('dropped_attempts',[]).append({'attempt':attempt['id'],'reason':result.get('reason'),'at':utcnow()})
                    seq=child.persist(child_id,seq,cs)
        if cs['phase'] in ('blocked','paused','waiting'):
            try:child.resume(child_id)
            except (ValueError,OSError):return False  # e.g. the root is fenced; retried after backoff, never forced
        return True

    def _retire_child(self, child_id, node_id):
        """Close a superseded child generation: cancel, then a terminal checkpoint when nothing is in flight."""
        try:self.control.cancel(child_id)
        except (ValueError,OSError):pass
        child=Owned(self.ledger)
        try:
            with task_lock(self.ledger,child_id):
                seq,cs=child.state(child_id)
                if not cs or cs['phase'] in ('completed','cancelled','failed'):return True
                if any(a['status']!='settled' for a in self.control.status(child_id)['attempts']):return False
                cs.update(phase='cancelled',message='Superseded by a new generation of delivery node '+node_id+'; evidence retained.')
                child.persist(child_id,seq,cs)
                return True
        except (ValueError,OSError):return False

    def _regenerate(self, s, node, row, detail):
        d=s['delivery']
        if not row or d['repairs']>=s['plan']['max_repairs']:return False
        d['history'].append({'regenerate':node['id'],'child':row.get('child'),'detail':str(detail)[:1000]})
        if row.get('child'):self._retire_child(row['child'],node['id'])
        d['repairs']+=1;d['generation']+=1;affected={node['id']}
        for n in s['plan']['nodes']:
            if set(n['depends'])&affected:affected.add(n['id'])
        for name in affected:
            r=d['nodes'][name]
            if r.get('receipt'):d['history'].append({'invalidated':name,'receipt':r['receipt']})
            r.update(phase='pending',receipt=None,child=None,generation=r['generation']+1);r.pop('review_context',None)
        d['nodes'][node['id']]['feedback']=('Previous child stopped without an accepted result: '+str(detail))[:2000]
        d['criteria']={a['id']:'pending' for a in s['plan']['acceptance']}
        return True

    def deadline_exhausted(self, task_id):
        """The root deadline passed: one typed budget question (never 'blocked', never an automatic extension)."""
        from . import delivery_recovery as rc
        with task_lock(self.ledger,task_id):
            seq,s=self.state(task_id)
            if not s or s['phase'] in ('completed','cancelled','failed'):return s
            d=rc.migrate(s['delivery'])
            if d.get('escalation'):
                # An answer recorded after the deadline is still the user's decision: 'stop' must cancel here,
                # because the runner exits on the deadline before any run() could apply it.
                changed=self._answer(task_id,s)
                if not changed or s['phase']=='cancelled' or d.get('escalation'):
                    if changed:self.persist(task_id,seq,s)
                    return s
                # A consumed 'retry' while the deadline is still exhausted opens the next budget episode below.
            node=next((k for k,v in d['nodes'].items() if v['phase'] in ('running','continuing','blocked')),None)
            for row in d['nodes'].values():
                if row['phase']=='continuing':row['phase']='pending'
            _,record=rc.decide(d,node or 'deadline','budget','deadline','Root deadline exhausted, including queue/user/pause waits.')
            rc.escalate(self,task_id,s,record,node)
            self.persist(task_id,seq,s);return s

    def coordinator_lost(self, task_id, detail, cls='runtime_bug'):
        """Keeper could not keep the coordinator alive: one user-visible runtime blocker."""
        from . import delivery_recovery as rc
        with task_lock(self.ledger,task_id):
            seq,s=self.state(task_id)
            if not s or s['phase'] in ('completed','cancelled','failed'):return s
            d=rc.migrate(s['delivery'])
            if d.get('escalation'):
                # Only a pending question stands. An answer the dead coordinator never applied is applied first,
                # as at the deadline: a 'stop' cancels, a 'retry' is consumed and this loss is asked anew.
                changed=self._answer(task_id,s)
                if not changed or s['phase']=='cancelled' or d.get('escalation'):
                    if changed:self.persist(task_id,seq,s)
                    return s
            action,record=rc.decide(d,'coordinator',cls,rc.normalize(detail),detail)
            rc.escalate(self,task_id,s,record,None)
            self.persist(task_id,seq,s);return s

    def asking(self, s):
        """True when the checkpoint waits on a pending root recovery question, the one its notice shows."""
        esc=((s or {}).get('delivery') or {}).get('escalation')
        return bool(esc) and self.ledger.request(esc['request'])['state']=='pending'

    def controller_error(self, task_id, error):
        """An exception escaped run() in the runner: one typed runtime_bug question instead of an untyped block."""
        s=self.coordinator_lost(task_id,'Controller error: '+type(error).__name__+': '+str(error)[:1200])
        if s and s['phase'] not in ('completed','cancelled','failed') and not self.asking(s):
            raise LedgerError('Controller error raised no typed question; the runner blocks the root instead.')
        return s

    def run(self, task_id, steps=1):
        from .delivery_steps import fingerprint, execute
        from .solution_gate import check
        from .sandbox_gate import task_guard
        from . import delivery_recovery as rc
        with task_lock(self.ledger,task_id):
            seq,s=self.state(task_id)
            if not s: raise LedgerError('Enable delivery first.')
            if s['phase'] in ('completed','failed','cancelled','blocked'): return s
            previous=content_hash(s);ready=None
            try:
                d=rc.migrate(s['delivery'])
                if self._answer(task_id,s) or d.get('escalation'):
                    if content_hash(s)!=previous:self.persist(task_id,seq,s)
                    return s
                if s['phase']=='waiting_operation' and s.get('waiting_reason')=='recovery':
                    if not rc.due(s,self.control.clock()):return s
                    s.update(phase='running',message='Retrying after automatic recovery backoff.');s.pop('waiting_reason',None)
                    d.pop('retry_after',None)
                if s['phase']=='waiting' and s.get('waiting_reason')=='decision':
                    s.update(phase='running');s.pop('waiting_reason',None)
                check(self.ledger,task_id); task_guard(self.control,task_id)()
                from .effort_watch import check as effort
                seq,waiting=effort(self,task_id,seq,s)
                if waiting:return s
                if s['plan'] is None:
                    from .delivery_planner import step as plan_step
                    plan_step(self,task_id,s)
                    if content_hash(s)!=previous:self.persist(task_id,self.state(task_id)[0],s)
                    return s
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
                if row['phase']=='uncertain':
                    self._recover(task_id,s,ready,'side_effect_unknown',{'generation':row['generation']},
                                  'Operation outcome unknown after an interruption.')
                    self.persist(task_id,self.state(task_id)[0],s);return s
                if row['phase']=='running' and ready['kind']!='change':
                    # The coordinator died inside this node: replay-safe captures replay once, device effects reconcile.
                    from .delivery_steps import interrupted
                    cls=interrupted(self,task_id,s,ready,row)
                    self._recover(task_id,s,ready,cls,{'generation':row['generation'],'interrupted':True},
                                  'Coordinator stopped during '+ready['id']+'.')
                    self.persist(task_id,self.state(task_id)[0],s);return s
                if ready['kind']=='device' and row.get('calibrate'):
                    from .delivery_calibrate import step as calibrate
                    calibrate(self,task_id,s,ready,row)
                    if content_hash(s)!=previous:self.persist(task_id,self.state(task_id)[0],s)
                    return s
                if row['phase']=='continuing':row['phase']='running'
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
                    row['phase']='running';self.persist(task_id,self.state(task_id)[0],s)
                    receipt=execute(self,task_id,s,ready,row)
                if receipt is None:
                    s['phase']='waiting_operation'
                    # A bounded continuation (e.g. review turn limit) is not an interruption.
                    if ready['kind']!='change':row['phase']='continuing'
                    if content_hash(s)!=previous:self.persist(task_id,self.state(task_id)[0],s)
                    return s
                if ready['kind']!='change' and fingerprint(self.ledger.project,s['plan']['source_roots'])['hash']!=d['source']['hash']:
                    raise LedgerError('Source changed during execution; receipt cannot satisfy acceptance.')
                row['receipt']=receipt
                if not receipt.get('passed'):
                    if receipt.get('packaging_anomaly') and self._clean_rebuild(s,ready,receipt):
                        d['recoveries'].append({'class':'artifact','action':'clean_rebuild','node':ready['id'],'at':utcnow(),'step':s['step']})
                        s['message']='APK packaging anomaly: one clean rebuild.'
                    else:
                        cls,key=rc.classify_receipt(ready,receipt)
                        row['phase']='uncertain' if cls=='side_effect_unknown' else 'blocked'
                        self._recover(task_id,s,ready,cls,key,receipt.get('detail','Acceptance failed'))
                else:
                    if receipt.get('source')!=d['source']['hash']:raise LedgerError('Receipt missing current source provenance.')
                    row['phase']='passed'
                    row['finished_at']=utcnow()
                    self._criteria(s)
                    if ready['kind']=='handover':
                        if any(v not in ('passed','not_run') for v in d['criteria'].values()): raise LedgerError('Required criteria unresolved.')
                        gaps=[k for k,v in d['criteria'].items() if v=='not_run']
                        verification='passed' if not gaps else 'partial'
                        s.update(phase='completed',verification=verification,acceptance='not_requested',
                                 message=('Solution delivery technically verified; report ready.' if not gaps else
                                          'Delivered with optional criteria not run: '+', '.join(gaps)+'.')+' User acceptance and Windows receipt are separate.')
                        d['technical_verified']=not gaps;d['product_acceptance']='not_requested'
                        s['outputs'].append({'stage':'solution_delivery','summary':s['report'],'verification':verification,'acceptance':'not_requested'})
                s['step']+=1
            except CapacityWait:
                if ready and ready['kind'] not in ('change','device') and s['delivery']['nodes'][ready['id']]['phase']=='running':
                    s['delivery']['nodes'][ready['id']]['phase']='continuing'
                s.update(phase='running',waiting_reason='capacity',message='Waiting for existing worker capacity; no new call charged.')
            except (ValueError,OSError) as error:
                try:self._failed(task_id,s,ready,error)
                except (ValueError,OSError) as inner:
                    # Recovery itself failed: still one typed question, never an untyped controller block.
                    from . import delivery_recovery as rc
                    action,record=rc.decide(rc.migrate(s['delivery']),'coordinator','runtime_bug',rc.normalize(inner),
                                            'Recovery bookkeeping failed: '+str(inner)[:600]+' (after: '+str(error)[:600]+')')
                    rc.escalate(self,task_id,s,record,ready['id'] if ready else None)
            except Exception as error:
                # Any other exception is a controller defect (e.g. KeyError): the same typed path, as runtime_bug.
                import traceback
                traceback.print_exc()
                self._failed(task_id,s,ready,LedgerError('Controller error: '+type(error).__name__+': '+str(error)[:1200]),'runtime_bug')
            # Compare with the latest checkpoint, not the starting one: a mid-step checkpoint (row 'running') must be superseded.
            latest_seq,latest=self.state(task_id)
            if content_hash(latest)!=content_hash(s):self.persist(task_id,latest_seq,s)
            return s

    def _failed(self, task_id, s, node, error, cls=None):
        """Every coordinator exception becomes a classified, bounded recovery or one question."""
        from . import delivery_recovery as rc
        d=rc.migrate(s['delivery']);row=d['nodes'].get(node['id']) if node else None
        cls=cls or rc.classify_error(error);key=rc.normalize(error);detail=str(error)[:1500]
        if node and node['kind']=='change' and row and row.get('child') and str(error).startswith('Child '):
            cs=Owned(self.ledger).state(row['child'])[1]
            cls=rc.classify_child(cs,self._child_questions(row['child']))
            key={'child':cls,'message':rc.normalize((cs or {}).get('message'))}
        effect=False
        if row and row['phase']=='running' and node['kind']!='change':
            # The exception ended this node inside a live coordinator: no unknown outcome unless a device effect began.
            from .delivery_steps import interrupted
            effect=node['kind']=='device' and interrupted(self,task_id,s,node,row)=='side_effect_unknown'
            row['phase']='uncertain' if effect else 'pending'
            if effect:cls='side_effect_unknown'
        c=self.control.status(task_id)
        if c['cancel_requested']:
            # The user's own cancel: one terminal outcome, no recovery and no question.
            d['history'].append({'stopped':'cancel','node':node['id'] if node else None,'detail':detail[:500],'at':utcnow()})
            s.update(phase='cancelled',message='Cancelled by user during '+(node['id'] if node else 'preparation')+'; evidence retained.')
            return
        if c['status']=='paused':
            if row and row['phase']=='uncertain':row['phase']='running'  # reconciled read-only after resume
            s.update(phase='running',message='Paused by user; the interrupted step reruns safely after resume.')
            return
        if self.control.clock()>=dt.datetime.fromisoformat(c['deadline']) and not effect:cls='budget'
        if cls=='fenced':
            # The child stopped only because this root was waiting; nothing failed.
            if not self._revive_child(row['child']):rc.schedule_retry(s,{'attempts':[],'class':'fenced'},self.control.clock())
            return
        self._recover(task_id,s,node,cls,key,detail)

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
