import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from onecrew.eval_corpus import catalog
from onecrew.evaluation import (archive, case_status, clean_environment, compare, content_hash, execute_probe,
                                 environment, read_result, revision, seal, tree_hash)
from onecrew.eval_observe import assistance_note, observe, project_state


def run_value(status='passed'):
    corpus = {'version':1,'cases':[{'id':'one','tests':['tests.probe.C.test_behavior']}],'limits':[]}
    return {'version':1,'type':'runtime_replay','completed':True,'run_id':'run',
            'corpus':corpus,'corpus_hash':content_hash(corpus),'harness_hash':'same','grader_hash':'same',
            'environment':{'python':'same'},'repeat':1,'timeout_seconds':10,'target_mode':'single-revision',
            'targets':{'one':'a'*40},'results':[{'case':'one','trial':0,'status':status,'revision':'a'*40,
                'probes':[{'selector':'tests.probe.C.test_behavior','status':status,'tests':1,'skipped':0}]}]}


class GradingTests(unittest.TestCase):
    def test_catalog_uses_existing_selectors_and_never_claims_heldout(self):
        import importlib
        for c in catalog()['cases']:
            self.assertEqual(c['split'],'known_case')
            for selector in c['tests']:
                mod,cls,method=selector.rsplit('.',2)
                self.assertTrue(hasattr(getattr(importlib.import_module(mod),cls),method),selector)
        with self.assertRaises(ValueError):catalog(['invented'])

    def test_pass_needs_every_probe_skip_never_pass(self):
        self.assertEqual(case_status([]),'harness_error')
        for status in ('runtime_error','skipped','capability_unavailable','timed_out'):
            self.assertEqual(case_status([{'status':'passed'},{'status':status}]),status)

    def test_recovery_capability_and_inconclusive_are_separate(self):
        for status,expected in [('assertion_failed','recovered'),('runtime_error','recovered'),
                                ('capability_unavailable','capability_added'),('skipped','inconclusive'),
                                ('harness_error','inconclusive'),('timed_out','inconclusive')]:
            r=compare(run_value(status),run_value())
            self.assertEqual(r['changes'],{expected:1})
            self.assertIsNone(r['product_autonomy_rate'])
            self.assertEqual(r['promotion'],'manual_review_required')

    def test_regression_including_missing_or_skipped_after_is_visible(self):
        r=compare(run_value(),run_value('skipped'))
        self.assertEqual(r['changes'],{'regressed':1})
        self.assertEqual(r['after_passed'],0)

    def test_mismatched_environment_harness_and_budget_rejected(self):
        for key in ('environment','harness_hash','grader_hash','corpus_hash','repeat','timeout_seconds'):
            b=run_value();b[key]='changed'
            with self.assertRaises(ValueError):compare(run_value(),b)

    def test_missing_duplicate_and_relabelled_results_rejected(self):
        b=run_value();b['results']=[]
        with self.assertRaises(ValueError):compare(run_value(),b)
        b=run_value();b['results']*=2
        with self.assertRaises(ValueError):compare(run_value(),b)
        for key in ('selector','status'):
            b=run_value();b['results'][0]['probes'][0][key]='changed'
            with self.assertRaises(ValueError):compare(run_value(),b)

    def test_no_test_or_fake_pass_and_wrong_revision_rejected(self):
        for key,val in [('tests',0),('skipped',1)]:
            b=run_value();b['results'][0]['probes'][0][key]=val
            with self.assertRaises(ValueError):compare(run_value(),b)
        b=run_value();b['results'][0]['revision']='b'*40
        with self.assertRaises(ValueError):compare(run_value(),b)

    def test_partial_run_cannot_be_compared(self):
        b=run_value();b.pop('completed')
        with self.assertRaises(ValueError):compare(run_value(),b)

    def test_changed_oracle_without_updated_hash_rejected(self):
        b=run_value();b['corpus']['cases'][0]['tests']=[]
        with self.assertRaisesRegex(ValueError,'Corpus'):compare(run_value(),b)

    def test_result_integrity(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'run.json';p.write_text(json.dumps(seal(run_value())))
            self.assertEqual(read_result(p),run_value())
            value=json.loads(p.read_text());value['completed']=False;p.write_text(json.dumps(value))
            with self.assertRaises(ValueError):read_result(p)

    def test_store_alias_fingerprints_real_interpreter(self):
        with patch.object(Path,'read_bytes',side_effect=[OSError('app alias'),b'actual interpreter']):
            e=environment()
        self.assertEqual(len(e['executable_sha256']),64)
        self.assertIn('fingerprinted_executable',e)


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.repo=self.root/'git';self.repo.mkdir()
        self.git('init');self.git('config','user.name','Eval');self.git('config','user.email','eval@example.invalid')
        (self.repo/'onecrew').mkdir();(self.repo/'onecrew/__init__.py').write_text('VALUE=0')
        self.git('add','onecrew');self.git('commit','-m','before')
        self.before=revision(self.repo,'HEAD')
        (self.repo/'onecrew/__init__.py').write_text('VALUE=1')
        self.git('add','onecrew');self.git('commit','-m','after')
        self.harness=self.root/'harness';(self.harness/'onecrew').mkdir(parents=True)
        src=Path(__file__).resolve().parents[1]/'onecrew/eval_probe.py'
        (self.harness/'onecrew/eval_probe.py').write_bytes(src.read_bytes())
        (self.harness/'tests').mkdir();(self.harness/'tests/__init__.py').write_text('')
        (self.harness/'tests/probe.py').write_text('import unittest,onecrew\nclass C(unittest.TestCase):\n def test_behavior(self): self.assertEqual(onecrew.VALUE,1)\n')

    def git(self,*args):
        return subprocess.check_output(['git','-C',str(self.repo),*args],stderr=subprocess.DEVNULL)

    def test_same_frozen_harness_observes_behavioral_before_after_without_checkout_mutation(self):
        marker=self.repo/'user.txt';marker.write_text('keep')
        dirty=self.git('status','--porcelain')
        for ref,expected in [(self.before,'assertion_failed'),('HEAD','passed')]:
            dest=self.root/expected;archive(self.repo,revision(self.repo,ref),dest)
            result=execute_probe(dest,self.harness,'tests.probe.C.test_behavior',self.root/(expected+'.json'),10)
            self.assertEqual(result['status'],expected,result)
        self.assertEqual(self.git('status','--porcelain'),dirty)
        self.assertEqual(marker.read_text(),'keep')

    def test_missing_capability_is_not_behavioral_failure(self):
        (self.harness/'tests/probe.py').write_text('from onecrew.no_such_module import implementation\n')
        runtime=self.root/'runtime';archive(self.repo,self.before,runtime)
        r=execute_probe(runtime,self.harness,'tests.probe.C.test_behavior',self.root/'r.json',10)
        self.assertEqual(r['status'],'capability_unavailable')

    def test_timeout_is_bounded(self):
        (self.harness/'tests/probe.py').write_text('import time\ntime.sleep(20)\n')
        runtime=self.root/'runtime';archive(self.repo,self.before,runtime)
        r=execute_probe(runtime,self.harness,'tests.probe.C.test_behavior',self.root/'r.json',1)
        self.assertEqual(r['status'],'timed_out')

    def test_expected_failure_unexpected_success_and_skip_never_pass(self):
        for i,(decorator,body) in enumerate([('expectedFailure','self.fail()'),('expectedFailure','pass'),("skip('not run')",'pass')]):
            (self.harness/'tests/probe.py').write_text('import unittest\nclass C(unittest.TestCase):\n @unittest.'+decorator+'\n def test_behavior(self): '+body+'\n')
            runtime=self.root/('runtime'+str(i));archive(self.repo,self.before,runtime)
            r=execute_probe(runtime,self.harness,'tests.probe.C.test_behavior',self.root/('r'+str(i)+'.json'),10)
            self.assertNotEqual(r['status'],'passed',r)

    def test_missing_external_fixture_dependency_is_harness_error(self):
        (self.harness/'tests/probe.py').write_text('import missing_eval_fixture_dependency\n')
        runtime=self.root/'runtime';archive(self.repo,self.before,runtime)
        r=execute_probe(runtime,self.harness,'tests.probe.C.test_behavior',self.root/'r.json',10)
        self.assertEqual(r['status'],'harness_error')

    def test_runtime_cannot_fall_back_to_harness_package(self):
        (self.harness/'onecrew/__init__.py').write_text('VALUE=1')
        runtime=self.root/'empty';runtime.mkdir()
        r=execute_probe(runtime,self.harness,'tests.probe.C.test_behavior',self.root/'r.json',10)
        self.assertEqual(r['status'],'capability_unavailable')

    def test_hash_changes_when_oracle_changes(self):
        a=tree_hash(self.harness,['tests']);(self.harness/'tests/probe.py').write_text('changed')
        self.assertNotEqual(a,tree_hash(self.harness,['tests']))

    def test_child_profile_and_temp_stay_inside_disposable_fixture(self):
        env=clean_environment(self.root/'env')
        for key in ('USERPROFILE','TEMP','TMP','LOCALAPPDATA','APPDATA','ONECREW_DESKTOP_HOME'):
            self.assertTrue(Path(env[key]).is_relative_to(self.root))
        self.assertNotIn('ANTHROPIC_API_KEY',env)
        (self.harness/'tests/probe.py').write_text('import unittest\nfrom pathlib import Path\nclass C(unittest.TestCase):\n def test_behavior(self): self.assertIn("env",Path.home().parts)\n')
        runtime=self.root/'runtime';archive(self.repo,self.before,runtime)
        r=execute_probe(runtime,self.harness,'tests.probe.C.test_behavior',self.root/'r.json',10)
        if __import__('os').name=='nt':self.assertEqual(r['status'],'passed',r)


class ObservationTests(unittest.TestCase):
    task='TASK-'+'1'*32

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.db=self.root/'ledger.sqlite3'
        self.c=sqlite3.connect(self.db);self.addCleanup(self.c.close)
        self.c.executescript('CREATE TABLE tasks(id TEXT, project_id TEXT); CREATE TABLE events(seq INTEGER PRIMARY KEY, task_id TEXT, kind TEXT, payload TEXT, created_at TEXT); CREATE TABLE requests(id TEXT,revision TEXT,task_id TEXT,state TEXT);')
        self.c.execute('INSERT INTO tasks VALUES (?,?)',(self.task,'project'))
        self.s={'phase':'completed','snapshot':'snapshot','verification':'passed','acceptance':'not_requested',
                'native_change':{'review_accepted':True,'timeout_checkpoints':[{'id':1}]},
                'tests':[{'passed':True,'evidence':{'snapshot':'snapshot','exit_code':0,'stdout':'PRIVATE_SENTINEL'}}],
                'workspace_applied':True,'outputs':[{'report':'PRIVATE_SENTINEL'}]}
        env=patch.dict('os.environ',{'ONECREW_DESKTOP_HOME':str(self.root/'desktop')})
        env.start();self.addCleanup(env.stop)

    def event(self,kind,value):
        self.c.execute('INSERT INTO events(task_id,kind,payload,created_at) VALUES (?,?,?,?)',(self.task,kind,json.dumps(value),'2026-10-12T00:00:00Z'));self.c.commit()

    def test_completed_unknown_assistance_does_not_mean_autonomous_or_device_tested(self):
        self.event('workflow.checkpoint',self.s)
        before=self.db.read_bytes();r=observe(self.root,[self.task]);t=r['tasks'][0]
        self.assertEqual(t['gates']['tests'],'recorded_pass');self.assertIn('device',t['gaps'])
        self.assertEqual(t['assistance'],'unknown');self.assertIsNone(r['product_autonomy_rate'])
        self.assertEqual(before,self.db.read_bytes());self.assertNotIn('PRIVATE_SENTINEL',json.dumps(r))

    def test_past_assistance_survives_new_completed_state_and_entry_device_not_worker(self):
        old=dict(self.s,phase='blocked',assistance='entry-runtime-repair',entry_repairs=[{'commit':'a'}])
        self.event('workflow.checkpoint',old);self.event('workflow.checkpoint',old)
        self.event('workflow.checkpoint',self.s)
        self.event('entry.physical_a54_verification',{'secret':'PRIVATE_SENTINEL'})
        self.event('learning.outcome',{'phase':'completed','snapshot':'snapshot','managed_calls':5})
        r=observe(self.root,[self.task]);t=r['tasks'][0]
        self.assertEqual(t['metrics']['entry_repairs'],1);self.assertEqual(t['metrics']['managed_calls'],5)
        self.assertEqual(t['gates']['device'],'entry_evidence_only')
        self.assertEqual(len(t['phase_episodes']),2);self.assertEqual(t['assistance'],'recorded')
        self.assertNotIn('PRIVATE_SENTINEL',json.dumps(r))

    def test_parent_counts_child_calls_and_intervention_not_only_root(self):
        child='TASK-'+'2'*32
        self.c.executescript('CREATE TABLE delivery_children(task_id TEXT,root TEXT); CREATE TABLE executions(task_id TEXT,used_calls INTEGER);')
        self.c.execute('INSERT INTO delivery_children VALUES (?,?)',(child,self.task))
        self.c.executemany('INSERT INTO executions VALUES (?,?)',[(child,4),(self.task,1)]);self.c.commit()
        self.event('workflow.checkpoint',self.s)
        self.c.execute('INSERT INTO events(task_id,kind,payload,created_at) VALUES (?,?,?,?)',
                       (child,'eval.assistance',json.dumps({'actor':'codex','category':'build','checkpoint':1,'reason':'PRIVATE_SENTINEL'}),'2026-10-12T00:00:00Z'));self.c.commit()
        t=observe(self.root,[self.task])['tasks'][0]
        self.assertEqual(t['metrics']['managed_calls'],5)
        self.assertEqual(t['assistance'],'recorded')
        self.assertEqual(t['recorded_interventions'][0]['actor'],'codex')
        self.assertNotIn('PRIVATE_SENTINEL',json.dumps(t))

    def test_stale_outcome_and_test_receipt_not_counted(self):
        self.s['tests'][0]['evidence']['snapshot']='old'
        self.event('workflow.checkpoint',self.s)
        self.event('learning.outcome',{'phase':'blocked','snapshot':'old','managed_calls':3})
        t=observe(self.root,[self.task])['tasks'][0]
        self.assertIsNone(t['metrics']['managed_calls']);self.assertEqual(t['gates']['tests'],'unverified')

    def test_one_passed_parent_node_does_not_hide_another_missing_node(self):
        s={'plan':{'nodes':[{'id':'a','kind':'regression'},{'id':'b','kind':'regression'}]},
           'delivery':{'source':{'hash':'current'},'nodes':{'a':{'phase':'passed','receipt':{
               'passed':True,'source':'current','counts':{'passed':3,'failed':0,'skipped':0}}}}}}
        gates,metrics=project_state(s)
        self.assertEqual(gates['tests'],'unverified');self.assertIsNone(metrics['test_cases_passed'])

    def test_duplicate_unknown_or_missing_task_rejected(self):
        for ids in ([self.task,self.task],['../bad'],['TASK-'+'2'*32]):
            with self.assertRaises(ValueError):observe(self.root,ids)
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaises(sqlite3.OperationalError):observe(empty,[self.task])
            self.assertFalse((Path(empty)/'ledger.sqlite3').exists())

    def test_stale_blocker_notice_never_counts_for_current_completion(self):
        self.event('workflow.checkpoint',dict(self.s,phase='blocked'))
        self.event('workflow.checkpoint',self.s)
        from onecrew.desktop_notifications import directory
        from types import SimpleNamespace
        folder=directory(SimpleNamespace(state_root=self.root));folder.mkdir(parents=True)
        key=content_hash({'task':self.task,'outcome':{'phase':'blocked','first':1}})[:32]
        (folder/(key+'.json')).write_text(json.dumps({'id':key,'task':self.task,'phase':'blocked','status':'shown'}))
        t=observe(self.root,[self.task])['tasks'][0]
        self.assertIsNone(t['windows']);self.assertEqual(t['gates']['notification'],'unverified')

    def test_current_window_is_delivery_not_product_or_user_acceptance(self):
        self.event('workflow.checkpoint',self.s)
        from onecrew.desktop_notifications import directory
        from types import SimpleNamespace
        folder=directory(SimpleNamespace(state_root=self.root));folder.mkdir(parents=True)
        key=content_hash({'task':self.task,'outcome':{'phase':'completed','first':1}})[:32]
        (folder/(key+'.json')).write_text(json.dumps({'id':key,'task':self.task,'phase':'completed','status':'shown'}))
        t=observe(self.root,[self.task])['tasks'][0]
        self.assertEqual(t['gates']['notification'],'recorded_shown');self.assertIn('device',t['gaps'])
        self.assertEqual(t['acceptance'],'not_requested')


class AssistanceTests(unittest.TestCase):
    def test_note_is_idempotent_scoped_and_does_not_execute_or_change_checkpoint(self):
        from tests.test_owned import OwnedTests
        f=OwnedTests();f.setUp();self.addCleanup(f.doCleanups)
        runtime,task,worker=f.runtime([])
        before=runtime.state(task);budget=runtime.control.status(task)['budget']
        a=assistance_note(f.ledger,task,'repair-1','codex','environment','Restored approved dependency cache.')
        self.assertEqual(assistance_note(f.ledger,task,'repair-1','codex','environment','Restored approved dependency cache.'),a)
        with self.assertRaises(ValueError):assistance_note(f.ledger,task,'repair-1','codex','build','Different action.')
        self.assertEqual(before,runtime.state(task));self.assertEqual(budget,runtime.control.status(task)['budget'])
        self.assertEqual(worker.calls,[])
        r=observe(f.ledger.state_root,[task])
        self.assertEqual(len(r['tasks'][0]['recorded_interventions']),1)


if __name__=='__main__': unittest.main()
