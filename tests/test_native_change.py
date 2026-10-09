import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_owned as fixtures
from onecrew.native_change import validate, install_candidate, apply, verify
from onecrew.ledger import LedgerError
from onecrew.snapshots import bytes_hash


class NativeChangeTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.OwnedTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        root=self.f.root/'app';(root/'lib').mkdir(parents=True);(root/'.dart_tool').mkdir()
        (root/'lib/main.dart').write_text('int add(int a,int b)=>a-b;\n')
        (root/'pubspec.yaml').write_text('name: app\n')
        (root/'.dart_tool/package_config.json').write_text(json.dumps({'configVersion':2,'packages':[{'name':'app','rootUri':'../','packageUri':'lib/'}]}))
        self.recipe=dict(source_roots=['app'],owned=['app/lib/main.dart','app/test/main_test.dart'],extra_sources={},
            package='app',flutter_root=str(Path(self.f.temp.name)/'flutter'),tests=['app/test/main_test.dart'],reference='User requested local fix',trusted_native=True)
        self.run,self.task,self.worker=self.f.runtime([],mode='change',provider='claude',model='sonnet',native_change=self.recipe)
        self.run.run(self.task,steps=1)

    def candidate(self):
        return {'report':'Fixed arithmetic and added regression coverage. Device unverified.','question':'','files':[
            {'path':'app/lib/main.dart','text':'int add(int a,int b)=>a+b;\n'},
            {'path':'app/test/main_test.dart','text':'// meaningful fixture test is simulated\n'}]}

    def test_complete_reviewed_apply_preserves_unrelated_dirty_source(self):
        untouched=self.f.root/'unrelated.txt';untouched.write_text('user dirty changes')
        self.worker.responses=[self.candidate(),{'accepted':True,'feedback':'Evidence checked'}]
        state=self.run.run(self.task,steps=1)
        baseline=(self.f.root/'app/lib/main.dart').read_text();self.assertIn('a-b',baseline)
        result={'passed':True,'detail':'All tests passed!','evidence':{'snapshot':state['snapshot'],'exit_code':0}}
        with patch('onecrew.native_change.verify',return_value=result): self.run.run(self.task,steps=1)
        self.run.run(self.task,steps=1);state=self.run.run(self.task,steps=1)
        self.assertEqual(state['phase'],'completed');self.assertTrue(state['workspace_applied'])
        self.assertIn('a+b',(self.f.root/'app/lib/main.dart').read_text())
        self.assertEqual(untouched.read_text(),'user dirty changes');self.assertEqual(len(self.worker.calls),2)

    def test_out_of_scope_and_duplicate_and_missing_test_rejected(self):
        state=self.run.state(self.task)[1]
        for files in ([{'path':'../outside.dart','text':'bad'}],self.candidate()['files']*2,[self.candidate()['files'][0]]):
            with self.assertRaises(LedgerError): install_candidate(self.run,state,dict(self.candidate(),files=files),self.recipe)
        self.assertIn('a-b',(self.f.root/'app/lib/main.dart').read_text())

    def test_conflict_preflight_writes_nothing_and_apply_recovery_is_idempotent(self):
        state=self.run.state(self.task)[1];install_candidate(self.run,state,self.candidate(),self.recipe)
        main=self.f.root/'app/lib/main.dart';main.write_text('user concurrent change')
        with self.assertRaises(LedgerError): apply(self.run,state)
        self.assertFalse((self.f.root/'app/test/main_test.dart').exists())
        main.write_bytes(self.run.store.read_blob(state['native_change']['originals']['app/lib/main.dart']))
        apply(self.run,state);apply(self.run,state)
        self.assertIn('a+b',main.read_text())

    def test_crash_after_result_does_not_repeat_model(self):
        self.worker.responses=[self.candidate()];persist=self.run.persist
        def crash(task,seq,state,**kw):
            saved=persist(task,seq,state,**kw)
            if state.get('native_change',{}).get('result_pending'): raise RuntimeError('crash')
            return saved
        with patch.object(self.run,'persist',side_effect=crash):
            with self.assertRaises(RuntimeError): self.run.run(self.task,steps=1)
        state=self.run.run(self.task,steps=1)
        self.assertEqual(state['native_change']['stage'],'verify');self.assertEqual(len(self.worker.calls),1)

    def test_fixed_recipe_never_trusts_reported_test_success(self):
        state=self.run.state(self.task)[1];install_candidate(self.run,state,self.candidate(),self.recipe)
        sdk=Path(self.recipe['flutter_root'])
        for name in ('bin/cache/dart-sdk/bin/dart.exe','bin/cache/flutter_tools.snapshot','packages/flutter_tools/.dart_tool/package_config.json'):
            p=sdk/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('fixture')
        with patch('onecrew.native_change.command',return_value=(1,'All tests passed!','compiler failure')) as call:
            result=verify(self.run,self.task,state,self.recipe)
        self.assertFalse(result['passed']);self.assertIn('--no-pub',call.call_args.args[0])
        self.assertEqual(result['evidence']['snapshot'],state['snapshot'])

    def test_repair_limit_preserves_session_and_never_applies(self):
        self.worker.responses=[self.candidate()]*3
        sessions=[]
        for _ in range(3):
            state=self.run.run(self.task,steps=1);sessions.append(state['native_change']['worker_session'])
            result={'passed':False,'detail':'assertion failed','evidence':{'snapshot':state['snapshot'],'exit_code':1}}
            with patch('onecrew.native_change.verify',return_value=result): state=self.run.run(self.task,steps=1)
        self.assertEqual(state['phase'],'blocked');self.assertEqual(len(set(sessions)),1)
        self.assertIn('a-b',(self.f.root/'app/lib/main.dart').read_text())

    def test_operator_recipe_requires_explicit_authority_and_private_hash(self):
        with self.assertRaises(LedgerError): validate(dict(self.recipe,trusted_native=False))
        with self.assertRaises(LedgerError): validate(dict(self.recipe,owned=['app/lib/app_secrets.dart',*self.recipe['owned']]))


if __name__=='__main__': unittest.main()
