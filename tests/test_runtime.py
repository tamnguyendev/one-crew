import contextlib
import copy
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from onecrew.runtime import Runner,Halt,main,validate_artifacts,validate_schema,state_path,process_alive,save
from onecrew.profiles import AC,FILES,PLAN_SCHEMA,route,validate_plan
from onecrew.cv_gate import DockerGate

ROOT=Path(__file__).resolve().parents[1]
SANDBOX=ROOT/'.onecrew'/'runtime-tests'
PLAN={'title':'Form CV','brief':'Tạo form và kiểm soát gửi CV.','non_goals':['Không deploy'],
      'tasks':[{'id':'backend','title':'API','kind':'backend','risk':'high','depends_on':[],'acceptance_ids':AC[1:]},
               {'id':'frontend','title':'UI','kind':'frontend','risk':'medium','depends_on':['backend'],'acceptance_ids':['CV-UI']}]}

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        SANDBOX.mkdir(parents=True,exist_ok=True)
        self.temp=Path(tempfile.mkdtemp(prefix='runtime ',dir=SANDBOX)).resolve()
        self.calls=[]
    def tearDown(self):
        resolved=self.temp.resolve()
        self.assertTrue(resolved.is_relative_to(SANDBOX.resolve())); self.assertNotEqual(resolved,SANDBOX.resolve())
        def writable_retry(function,path,exc):
            checked=Path(path).resolve()
            self.assertTrue(checked.is_relative_to(resolved))
            if not isinstance(exc[1],PermissionError): raise exc[1]
            os.chmod(checked,stat.S_IWRITE|stat.S_IREAD)
            function(path)
        shutil.rmtree(resolved,onerror=writable_retry)
    def provider(self,stage,prompt,schema,selection):
        self.calls.append((stage,selection))
        if stage=='plan': return copy.deepcopy(PLAN)
        if stage=='review': return {'summary':'All local requirements met.','findings':[]}
        ownership=FILES.get(stage,['server.mjs'])
        return {'summary':'Fixture artifact','files':[{'path':p,'content':f'fixture {stage} {p}\n'} for p in ownership],'backlog':[]}
    def runner(self,**kwargs):
        return Runner(self.temp,self.temp/'output','Authorized local fixture',{'seconds':60,'calls':8,'repairs':2,'step_seconds':4},provider=kwargs.get('provider',self.provider))
    def execute(self,runner,gate_results=None):
        gate_results=gate_results or [{'passed':True,'checks':['fixture'],'failures':[]}]
        with patch.object(DockerGate,'preflight',lambda s:None),patch.object(DockerGate,'verify',side_effect=gate_results),contextlib.redirect_stdout(io.StringIO()):
            return runner.execute()
    def test_autonomous_full_lifecycle_and_separate_acceptance(self):
        r=self.runner(); state=self.execute(r)
        self.assertEqual(state['status'],'ready_for_review'); self.assertEqual(state['acceptance'],'pending_user_review')
        self.assertEqual([x[0] for x in self.calls],['plan','backend','frontend','review'])
        self.assertEqual(state['calls'],4); self.assertTrue((r.root/'delivery.json').exists())
        self.assertEqual(len(state['checkpoints']),2)
        for checkpoint in state['checkpoints']: self.assertTrue(Path(checkpoint['archive']).is_file())
        self.assertEqual(subprocess.check_output(['git','status','--porcelain'],cwd=r.output).strip(),b'')
    def test_gate_failure_repairs_automatically_without_resetting_calls(self):
        r=self.runner(); state=self.execute(r,[{'passed':False,'checks':[],'failures':[{'requirement':'CV-COMMIT','error':'bad replay'}]}, {'passed':True,'checks':['fixed'],'failures':[]}])
        self.assertEqual(state['status'],'ready_for_review'); self.assertEqual(state['calls'],5); self.assertEqual(state['repairs'],1)
        self.assertIn('repair',[x[0] for x in self.calls])
    def test_review_blocker_triggers_repair(self):
        reviews=0
        def provider(stage,*args):
            nonlocal reviews
            if stage=='review':
                reviews+=1
                return {'summary':'review','findings':[{'requirement':'CV-FILE','severity':'blocking','path':'server.mjs','evidence':'unbounded stream','fix':'cap size'}] if reviews==1 else []}
            return self.provider(stage,*args)
        r=self.runner(provider=provider); state=self.execute(r,[{'passed':True,'checks':[],'failures':[]}]*2)
        self.assertEqual(state['status'],'ready_for_review'); self.assertEqual(state['repairs'],1); self.assertEqual(state['calls'],6)
    def test_optional_review_feature_is_backlog_not_dispatch(self):
        def provider(stage,*args):
            if stage=='review': return {'summary':'review','findings':[{'requirement':'NEW-DASHBOARD','severity':'blocking','path':'new','evidence':'no dashboard','fix':'add feature'}]}
            return self.provider(stage,*args)
        r=self.runner(provider=provider); state=self.execute(r)
        self.assertEqual(state['status'],'ready_for_review'); self.assertEqual(state['repairs'],0); self.assertEqual(len(state['backlog']),1)
    def test_red_gate_never_delivery_after_repair_budget(self):
        r=self.runner(); r.state['limits']['repairs']=0; r.grant['limits']['repairs']=0
        # Limits are one shared immutable contract; seal after deliberate fixture setup.
        from onecrew.runtime import save,digest,canonical
        save(r.root/'grant.json',r.grant); r.state['grant_hash']=digest(canonical(r.grant))
        state=self.execute(r,[{'passed':False,'checks':[],'failures':['mandatory failure']}])
        self.assertEqual(state['status'],'failed'); self.assertFalse((r.root/'delivery.json').exists())
    def test_call_budget_exhaustion_not_reset_by_stage(self):
        r=self.runner(); r.state['calls']=8
        with self.assertRaises(Halt) as cm: r.invoke('plan','',PLAN_SCHEMA)
        self.assertEqual(cm.exception.status,'budget_exhausted'); self.assertEqual(self.calls,[])
    def test_deadline_exhaustion_before_dispatch(self):
        r=self.runner(); r.started-=61
        with self.assertRaises(Halt) as cm:r.invoke('plan','',PLAN_SCHEMA)
        self.assertEqual(cm.exception.status,'budget_exhausted'); self.assertEqual(self.calls,[])
    def test_cancel_before_result_cannot_apply_artifact(self):
        r=self.runner(); (r.root/'cancel.request').write_text('cancel')
        with self.assertRaises(Halt): r.apply({'summary':'x','files':[{'path':'server.mjs','content':'x'}],'backlog':[]},FILES['backend'],'x')
        self.assertFalse((r.output/'server.mjs').exists())
    def test_grant_tamper_detected(self):
        r=self.runner(); (r.root/'grant.json').write_text('{}')
        with self.assertRaises(Halt):r.check()
    def test_owned_paths_and_size_enforced_before_any_write(self):
        for path in ['../state.json','C:/secret.txt','.onecrew/state.json','package.json','public/../../gate.py','public/styles.css']:
            with self.assertRaises(ValueError):validate_artifacts({'summary':'x','files':[{'path':path,'content':'x'}],'backlog':[]},FILES['backend'])
        with self.assertRaises(ValueError):validate_artifacts({'summary':'x','files':[{'path':'server.mjs','content':'x'*400001}],'backlog':[]},FILES['backend'])
    def test_plan_dependencies_and_coverage_validated(self):
        self.assertEqual([t['id'] for t in validate_plan(PLAN)],['backend','frontend'])
        cycle=copy.deepcopy(PLAN); cycle['tasks'][0]['depends_on']=['frontend']
        with self.assertRaises(ValueError):validate_plan(cycle)
        incomplete=copy.deepcopy(PLAN); incomplete['tasks'][0]['acceptance_ids']=[]
        with self.assertRaises(ValueError):validate_plan(incomplete)
    def test_router_has_risk_floor_and_light_planning(self):
        self.assertEqual(route('plan')['tier'],'light')
        self.assertEqual(route('backend','low')['tier'],'strong')
        self.assertEqual(route('frontend','low')['tier'],'balanced')
        self.assertEqual(route('frontend','high')['tier'],'strong')
    def test_strict_schema_rejects_extra_permission_and_wrong_enum(self):
        value=copy.deepcopy(PLAN); value['allow_deploy']=True
        with self.assertRaises(ValueError):validate_schema(value,PLAN_SCHEMA)
        value=copy.deepcopy(PLAN); value['tasks'][0]['risk']='whatever'
        with self.assertRaises(ValueError):validate_schema(value,PLAN_SCHEMA)
    def test_preflight_blocked_makes_zero_model_calls(self):
        r=self.runner()
        with patch.object(DockerGate,'preflight',side_effect=Halt('blocked','Engine unavailable')),contextlib.redirect_stdout(io.StringIO()):state=r.execute()
        self.assertEqual(state['status'],'blocked'); self.assertEqual(state['calls'],0)
    def test_existing_output_refused(self):
        self.runner()
        with self.assertRaises(ValueError):self.runner()
    def test_status_outputs_and_cancel_never_call_provider(self):
        r=self.runner(); before=(r.root/'state.json').read_bytes()
        for command in ('status','outputs','list'):
            args=['--project',str(self.temp),'task',command]+([] if command=='list' else [r.id])
            with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(main(args),0)
        self.assertEqual(before,(r.root/'state.json').read_bytes()); self.assertEqual(self.calls,[])
        with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(main(['--project',str(self.temp),'task','cancel',r.id]),0)
        self.assertTrue((r.root/'cancel.request').exists()); self.assertEqual(r.state['status'],'running')
    def test_command_timeout_kills_process_and_records_no_success(self):
        r=self.runner()
        with self.assertRaises(Halt):r.command([sys.executable,'-c','import time; time.sleep(30)'],timeout=.4)
        self.assertIsNone(r.state['process'])
    def test_cancel_long_command_and_child_tree(self):
        r=self.runner(); marker=self.temp/'child.pid'
        script='import subprocess,sys,time,pathlib; p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); pathlib.Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(30)'
        def cancel():
            deadline=time.monotonic()+8
            while not marker.exists() and time.monotonic()<deadline:time.sleep(.05)
            (r.root/'cancel.request').write_text('cancel')
        thread=threading.Thread(target=cancel); thread.start()
        began=time.monotonic()
        try:
            with self.assertRaises(Halt) as cm:r.command([sys.executable,'-c',script,str(marker)],timeout=10)
            self.assertEqual(cm.exception.status,'cancelled'); self.assertLess(time.monotonic()-began,15)
            self.assertTrue(marker.exists()); self.assertFalse(process_alive(int(marker.read_text())))
        finally:thread.join(timeout=10)
    def test_run_id_traversal_rejected(self):
        with self.assertRaises(ValueError):state_path(self.temp,'../evil')
    def test_spec_comment_task_does_not_route_to_runtime(self):
        from onecrew.cli import main as cli_main
        with patch('onecrew.cli.specs.main',return_value=0) as spec:
            self.assertEqual(cli_main(['spec','request-changes','SPEC-001','--comment','task']),0)
            spec.assert_called_once()
    def test_context_cap_before_paid_call(self):
        r=self.runner()
        with self.assertRaises(Halt):r.invoke('plan','x'*80001,PLAN_SCHEMA)
        self.assertEqual(r.state['calls'],0)
    def test_failed_model_attempt_is_unknown_usage_not_pending_forever(self):
        def provider(*args): raise Halt('failed','provider timed out')
        r=self.runner(provider=provider); state=self.execute(r)
        self.assertEqual(state['status'],'failed')
        self.assertIsNone(state['usage_pending_attempt'])
        self.assertEqual(state['usage_missing_attempts'],[1])
    def test_cli_step_limit_is_bounded_by_total_budget(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['task','run','--autonomous','--brief','unused','--output','unused','--max-seconds','10','--step-seconds','20']),2)
    def test_atomic_state_replace_retries_transient_reader_lock(self):
        path=self.temp/'state.json'; save(path,{'old':True})
        replace=os.replace
        with patch('onecrew.runtime.os.replace',side_effect=[PermissionError('reader lock'),None]) as mocked:
            save(path,{'new':True})
            self.assertEqual(mocked.call_count,2)
            self.assertEqual(json.loads(path.read_text()),{'old':True})
        replace(path.with_name('state.json.tmp'),path)
        self.assertEqual(json.loads(path.read_text()),{'new':True})
    def test_atomic_state_permanent_lock_is_bounded_and_preserves_old(self):
        path=self.temp/'state.json'; save(path,{'old':True})
        with patch('onecrew.runtime.os.replace',side_effect=PermissionError('locked')) as mocked,patch('onecrew.runtime.time.sleep'):
            with self.assertRaises(PermissionError):save(path,{'new':True})
            self.assertEqual(mocked.call_count,10)
            self.assertEqual(json.loads(path.read_text()),{'old':True})
    def test_state_failure_after_spawn_still_terminates_child(self):
        r=self.runner(); spawned=[]; popen=subprocess.Popen; persist=r.persist
        def capture(*args,**kwargs):
            child=popen(*args,**kwargs); spawned.append(child); return child
        with patch('onecrew.runtime.subprocess.Popen',side_effect=capture),patch.object(r,'persist',side_effect=[PermissionError('persistent lock'),None]):
            with self.assertRaises(PermissionError):r.command([sys.executable,'-c','import time; time.sleep(30)'])
        self.assertIsNotNone(spawned[0].poll()); self.assertIsNone(r.state['process'])
    def test_artifacts_changed_during_review_cannot_be_delivered(self):
        def provider(stage,*args):
            if stage=='review':
                (r.output/'server.mjs').write_text('changed outside reviewed snapshot')
            return self.provider(stage,*args)
        r=self.runner(provider=provider); state=self.execute(r)
        self.assertEqual(state['status'],'failed'); self.assertFalse((r.root/'delivery.json').exists())

if __name__=='__main__': unittest.main()
