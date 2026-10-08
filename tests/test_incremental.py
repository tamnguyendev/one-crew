import contextlib
import copy
import io
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest.mock import patch
from onecrew.incremental import IncrementalRunner
from onecrew.incremental_profile import MODULES,validate_plan
from onecrew.runtime import ProviderFailure,Halt
from onecrew.cv_gate import DockerGate

ROOT=Path(__file__).resolve().parents[1]
def plan():
    ids={p:'task-'+str(i) for i,p in enumerate(MODULES)}
    return {'title':'Incremental fixture','brief':'Local fixture','non_goals':['No deployment'],
            'tasks':[{'id':ids[p],'file':p,'title':p,'depends_on':[ids[d] for d in u['deps']]} for p,u in MODULES.items()]}

class IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.parent=ROOT/'.onecrew'/'incremental-tests';self.parent.mkdir(parents=True,exist_ok=True)
        self.temp=Path(tempfile.mkdtemp(dir=self.parent));self.calls=[]
    def tearDown(self):
        def retry(fn,p,exc):
            self.assertTrue(Path(p).resolve().is_relative_to(self.temp.resolve()))
            if not isinstance(exc[1],PermissionError):raise exc[1]
            os.chmod(p,stat.S_IREAD|stat.S_IWRITE);fn(p)
        self.assertTrue(self.temp.resolve().is_relative_to(self.parent.resolve()))
        shutil.rmtree(self.temp,onerror=retry)
    def provider(self,stage,prompt,schema,selection):
        self.calls.append(stage)
        if stage=='plan':return plan()
        if stage=='review':return {'summary':'Fixture review','findings':[]}
        if stage=='repair-triage':return {'files':[{'path':'public/app.js','reason':'Fix fixture failure'}]}
        path=stage.removeprefix('file:')
        if path.endswith(('.mjs','.js')):
            return '\n'.join('export const '+name+' = {};' for name in MODULES[path]['exports']) or ('export {}; // repair' if 'FAILURES TO FIX (data)\n[{' in prompt else 'export {};')
        return 'Fixture document'
    def runner(self,provider=None):
        return IncrementalRunner(self.temp,self.temp/'product','Synthetic brief',{'seconds':120,'calls':24,'repairs':3,'step_seconds':5},provider=provider or self.provider)
    def execute(self,r,results=None):
        with patch.object(DockerGate,'preflight',lambda s:None),patch.object(DockerGate,'verify',side_effect=results or [{'passed':True,'checks':['fixture'],'failures':[]}]),contextlib.redirect_stdout(io.StringIO()):
            return r.execute()
    def test_file_dag_requires_complete_ownership_and_dependencies(self):
        self.assertEqual(len(validate_plan(plan())),10)
        for mutation in ('missing','duplicate','deps'):
            p=plan()
            if mutation=='missing':p['tasks'].pop()
            if mutation=='duplicate':p['tasks'][1]['file']=p['tasks'][0]['file']
            if mutation=='deps':p['tasks'][1]['depends_on']=[]
            with self.assertRaises(ValueError):validate_plan(p)
    def test_full_controller_delivers_ten_independent_checkpoints(self):
        r=self.runner();s=self.execute(r)
        self.assertEqual(s['status'],'ready_for_review');self.assertEqual(s['calls'],12)
        self.assertEqual(len(s['completed_tasks']),10);self.assertEqual(len(s['checkpoints']),10)
        self.assertEqual(s['acceptance'],'pending_user_review');self.assertTrue((r.root/'delivery.json').exists())
        from onecrew.preview import verified_output
        self.assertEqual(verified_output(self.temp,r.id)[1],r.output)
        (r.output/'server.mjs').write_text('modified')
        with self.assertRaises(ValueError):verified_output(self.temp,r.id)
    def test_provider_timeout_retries_only_failed_unit(self):
        hits=0
        def provider(stage,*args):
            nonlocal hits
            if stage=='file:lib/storage.mjs':
                hits+=1
                if hits==1:raise ProviderFailure('failed','Process timeout after 5s')
            return self.provider(stage,*args)
        r=self.runner(provider);s=self.execute(r)
        self.assertEqual(s['status'],'ready_for_review');self.assertEqual(s['calls'],13)
        self.assertEqual(self.calls.count('file:lib/common.mjs'),1);self.assertEqual(hits,2)
    def test_syntax_error_is_repaired_before_unit_completion(self):
        hits=0
        def provider(stage,*args):
            nonlocal hits
            if stage=='file:public/app.js':
                hits+=1
                if hits==1:return 'const = ;'
            return self.provider(stage,*args)
        r=self.runner(provider);s=self.execute(r)
        self.assertEqual(s['status'],'ready_for_review');self.assertEqual(hits,2)
        self.assertEqual(len(s['checkpoints']),10)
        checks=[json.loads(p.read_text())['passed'] for p in r.root.glob('syntax-*.json')]
        self.assertIn(False,checks);self.assertIn(True,checks)
    def test_permanent_failure_keeps_completed_work_and_stops(self):
        hits=0
        def provider(stage,*args):
            nonlocal hits
            if stage=='file:lib/storage.mjs':hits+=1;raise ProviderFailure('failed','timeout')
            return self.provider(stage,*args)
        r=self.runner(provider);s=self.execute(r)
        self.assertEqual(s['status'],'failed');self.assertEqual(hits,2)
        self.assertEqual(len(s['completed_tasks']),1);self.assertTrue((r.output/'lib/common.mjs').exists())
        self.assertFalse((r.root/'delivery.json').exists())
    def test_cancel_is_never_retried(self):
        def provider(stage,*args):
            if stage.startswith('file:'):raise Halt('cancelled','cancelled by user')
            return self.provider(stage,*args)
        r=self.runner(provider);s=self.execute(r)
        self.assertEqual(s['status'],'cancelled');self.assertEqual(s['calls'],2)
    def test_gate_failure_uses_targeted_repair_and_reverification(self):
        r=self.runner();s=self.execute(r,[{'passed':False,'checks':[],'failures':[{'requirement':'CV-UI','error':'fixture interaction failure'}]}, {'passed':True,'checks':['reverified'],'failures':[]}])
        self.assertEqual(s['status'],'ready_for_review');self.assertEqual(s['repairs'],1);self.assertEqual(s['calls'],14)
        self.assertEqual(self.calls.count('file:public/app.js'),2);self.assertEqual(self.calls.count('file:lib/commit.mjs'),1)
    def test_repair_no_change_rejected_before_checkpoint(self):
        r=self.runner()
        with contextlib.redirect_stdout(io.StringIO()):r.accept_file('public/app.js','export {};','build:public/app.js')
        with self.assertRaisesRegex(ValueError,'no source change'):
            r.accept_file('public/app.js','export {};','repair-1:public/app.js')
        self.assertEqual(len(r.state['checkpoints']),1)
    def test_task_routing_and_retry_escalation(self):
        r=self.runner()
        self.assertEqual(r.select_model('file:public/styles.css','medium')['tier'],'builder')
        self.assertEqual(r.select_model('file:lib/sessions.mjs','medium')['tier'],'engineer')
        self.assertEqual(r.select_model('repair-triage','medium')['tier'],'engineer')
        self.assertEqual(r.select_model('review','medium')['tier'],'reviewer')
        r.unit_retry=1
        self.assertEqual(r.select_model('file:public/styles.css','medium')['tier'],'engineer')
    def test_file_size_limit_blocks_before_write(self):
        r=self.runner()
        with self.assertRaises(ValueError):r.accept_file('public/app.js','x'*24001,'too-large')
        self.assertFalse((r.output/'public/app.js').exists())
    def test_raw_cli_output_is_accepted_without_schema_flag(self):
        r=self.runner();r.provider=None
        def command(args,**kwargs):
            self.assertNotIn('--output-schema',args)
            self.assertTrue(any(str(a).startswith('model_instructions_file=') for a in args))
            Path(args[args.index('-o')+1]).write_text('export {};',encoding='utf-8')
            return 0,json.dumps({'type':'turn.completed','usage':{'input_tokens':8,'output_tokens':3}}),''
        with patch.object(r,'command',side_effect=command),contextlib.redirect_stdout(io.StringIO()):
            result=r.produce('file:public/app.js','synthetic')
        self.assertEqual(result,'export {};');self.assertEqual(r.state['usage']['output_tokens'],3)
    def test_bad_repair_candidate_does_not_clobber_valid_file(self):
        r=self.runner()
        with contextlib.redirect_stdout(io.StringIO()):r.accept_file('public/app.js','export {};','valid')
        with self.assertRaises(ValueError):r.accept_file('public/app.js','I cannot write in read only mode.','bad')
        self.assertEqual((r.output/'public/app.js').read_text().strip(),'export {};')
        self.assertEqual(len(r.state['checkpoints']),1)

if __name__=='__main__':unittest.main()
