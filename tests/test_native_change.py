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
        (root/'.dart_tool/package_graph.json').write_text(json.dumps({'configVersion':1,'roots':['app'],'packages':[{'name':'app','version':'1.0.0','dependencies':[]}]}))
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

    def test_content_rejection_repairs_without_installing_or_leaking_value(self):
        candidate=self.candidate()
        candidate['files'][1]['text']="password = 'long-fixture-value';"
        self.worker.responses=[candidate,self.candidate()]
        state=self.run.run(self.task,steps=1)
        native=state['native_change']
        self.assertEqual(native['stage'],'work');self.assertEqual(native['repairs'],1)
        self.assertNotIn('result_pending',native)
        self.assertNotIn('long-fixture-value',native['feedback'])
        self.assertIn('app/test/main_test.dart',native['feedback'])
        self.assertEqual(native['checks'],[])
        self.assertIn('a-b',(Path(native['workspace'])/'app/lib/main.dart').read_text())
        state=self.run.run(self.task,steps=1)
        self.assertEqual(state['native_change']['stage'],'verify')
        self.assertIn('a-b',(self.f.root/'app/lib/main.dart').read_text())

    def test_repeated_content_rejection_is_bounded_and_never_applied(self):
        candidate=self.candidate();candidate['files'][0]['text']="password = 'long-fixture-value';"
        self.worker.responses=[candidate]*3
        for _ in range(3): state=self.run.run(self.task,steps=1)
        self.assertEqual(state['phase'],'blocked')
        self.assertEqual(state['native_change']['repairs'],2)
        self.assertEqual(len(state['native_change']['rejected_candidates']),3)
        self.assertEqual(state['native_change']['checks'],[])
        self.assertEqual(len(self.worker.calls),3)
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

    def test_offline_graph_recovery_validates_source_and_never_calls_worker(self):
        from onecrew.native_change import prepare_test_environment
        from onecrew.sandbox_gate import GateUnavailable
        state=self.run.state(self.task)[1];workspace=Path(state['native_change']['workspace'])
        target=workspace/'app/.dart_tool/package_graph.json'
        self.assertFalse(target.exists())
        evidence=prepare_test_environment(self.run,state,self.recipe)
        self.assertTrue(target.exists());self.assertEqual(evidence['package_count'],1)
        self.assertFalse(evidence['pub_get_ran']);self.assertFalse(self.worker.calls)
        self.assertEqual(prepare_test_environment(self.run,state,self.recipe),evidence)
        source=self.f.root/'app/.dart_tool/package_config.json'
        data=json.loads(source.read_text());data['packages'][0]['languageVersion']='99.0'
        source.write_text(json.dumps(data))
        with self.assertRaises(GateUnavailable): prepare_test_environment(self.run,state,self.recipe)

    def test_missing_metadata_is_environment_failure_without_code_repairs(self):
        self.worker.responses=[self.candidate()]
        state=self.run.run(self.task,steps=1)
        result={'passed':False,'detail':'missing graph','failure_kind':'environment',
                'evidence':{'snapshot':state['snapshot'],'exit_code':1}}
        with patch('onecrew.native_change.verify',return_value=result):state=self.run.run(self.task,steps=1)
        self.assertEqual(state['phase'],'blocked');self.assertEqual(state['recovery']['kind'],'environment')
        self.assertEqual(state['native_change']['repairs'],0)
        self.assertEqual(state['native_change']['stage'],'verify')
        self.assertEqual(len(self.worker.calls),1)

    def test_missing_dependency_cache_blocks_before_compiler_and_preserves_candidate(self):
        from onecrew.native_change import prepare_test_environment
        from onecrew.sandbox_gate import GateUnavailable
        state=self.run.state(self.task)[1];workspace=Path(state['native_change']['workspace'])
        dependency=Path(self.f.temp.name)/'cache/test_api-1.0.0'
        for path in (self.f.root/'app/.dart_tool/package_config.json',workspace/'app/.dart_tool/package_config.json'):
            config=json.loads(path.read_text())
            config['packages'].append({'name':'test_api','rootUri':dependency.as_uri()+'/'})
            path.write_text(json.dumps(config))
        graph=self.f.root/'app/.dart_tool/package_graph.json'
        value=json.loads(graph.read_text());value['packages'].append({'name':'test_api','version':'1.0.0','dependencies':[]})
        graph.write_text(json.dumps(value))
        with self.assertRaisesRegex(GateUnavailable,'cache incomplete.*test_api'):
            prepare_test_environment(self.run,state,self.recipe)
        self.assertFalse(self.worker.calls);self.assertEqual(state['native_change']['repairs'],0)
        dependency.mkdir(parents=True)
        with self.assertRaises(GateUnavailable):prepare_test_environment(self.run,state,self.recipe)
        (dependency/'pubspec.yaml').write_text('name: test_api\n')
        self.assertEqual(prepare_test_environment(self.run,state,self.recipe)['package_count'],2)

    def test_compiler_only_inputs_are_separate_hash_pinned_and_block_changed_source(self):
        from onecrew.native_change import prepare_test_environment
        from onecrew.native_test_workspace import prepare,check_workspace
        from onecrew.sandbox_gate import GateUnavailable
        state=self.run.state(self.task)[1];install_candidate(self.run,state,self.candidate(),self.recipe)
        original=self.f.root/'app/lib/token_manager.dart'
        original.write_text("const password = 'synthetic-local-fixture';\n")
        worker=Path(state['native_change']['workspace'])
        prepare_test_environment(self.run,state,self.recipe)
        gate,receipt=prepare(self.run,state,self.recipe)
        self.assertEqual(receipt['local_only_source_count'],1)
        self.assertFalse((worker/'app/lib/token_manager.dart').exists())
        self.assertEqual((gate/'app/lib/token_manager.dart').read_bytes(),original.read_bytes())
        self.assertIn('a+b',(gate/'app/lib/main.dart').read_text())
        self.assertIn('a-b',(self.f.root/'app/lib/main.dart').read_text())
        check_workspace(state)
        (gate/'app/lib/main.dart').write_text('tampered')
        with self.assertRaises(GateUnavailable):check_workspace(state)
        original.write_text('changed by user')
        with self.assertRaises(GateUnavailable):prepare(self.run,state,self.recipe)
        with self.assertRaises(GateUnavailable):apply(self.run,state)
        self.assertIn('a-b',(self.f.root/'app/lib/main.dart').read_text())

    def test_compiler_only_input_links_cannot_escape_source_root(self):
        from onecrew.native_change import prepare_test_environment
        from onecrew.native_test_workspace import prepare
        state=self.run.state(self.task)[1]
        outside=Path(self.f.temp.name)/'outside.dart';outside.write_text('outside')
        link=self.f.root/'app/lib/token_link.dart'
        try:link.symlink_to(outside)
        except OSError:self.skipTest('Symlink creation unavailable')
        prepare_test_environment(self.run,state,self.recipe)
        with self.assertRaises(LedgerError):prepare(self.run,state,self.recipe)

    def test_environment_preflight_exception_preserves_candidate_and_repair_count(self):
        from onecrew.sandbox_gate import GateUnavailable
        self.worker.responses=[self.candidate()]
        state=self.run.run(self.task,steps=1);snapshot=state['snapshot']
        with patch('onecrew.native_change.verify',side_effect=GateUnavailable('Offline metadata missing')):
            state=self.run.run(self.task,steps=1)
        self.assertEqual(state['recovery']['kind'],'environment')
        self.assertEqual(state['snapshot'],snapshot)
        self.assertEqual(state['native_change']['repairs'],0)
        self.assertEqual(state['native_change']['stage'],'verify')

    def test_rejected_tool_receipt_can_recover_without_second_model_call(self):
        from onecrew.native_audit import NativeClaude
        from tests.test_native_tool_receipts import denied_events
        self.worker.responses=[self.candidate()]
        with patch.object(self.worker,'result',side_effect=LedgerError('Old parser rejects attempted Edit')):
            state=self.run.run(self.task,steps=1)
        self.assertEqual(state['phase'],'blocked');self.assertIsNotNone(state['pending'])
        events=denied_events()+[{'type':'result','subtype':'success','is_error':False,
            'structured_output':self.candidate()}]
        class Recorded:
            def stdout(self,attempt):return '\n'.join(json.dumps(e) for e in events)
        def recovered(attempt):
            return NativeClaude.result(Recorded(),dict(attempt,result=json.dumps({'stdout':'fixture.jsonl'})))
        self.run.resume(self.task)
        with patch.object(self.worker,'result',side_effect=recovered):state=self.run.run(self.task,steps=1)
        self.assertEqual(state['native_change']['stage'],'verify')
        self.assertEqual(len(self.worker.calls),1)
        self.assertEqual(self.run.control.status(self.task)['used_calls'],1)
        self.assertEqual(state['native_change']['attempts'][0]['denied_tool_calls'][0]['name'],'Edit')
        self.assertIn('a-b',(self.f.root/'app/lib/main.dart').read_text())

    def test_snapshot_mutation_is_detected_before_patch_can_mask_it(self):
        state=self.run.state(self.task)[1]
        target=Path(state['native_change']['workspace'])/'app/lib/main.dart'
        target.write_text('unauthorized change')
        self.worker.responses=[self.candidate()]
        state=self.run.run(self.task,steps=1)
        self.assertEqual(state['phase'],'blocked')
        self.assertIn('Captured source changed',state['message'])
        self.assertEqual(target.read_text(),'unauthorized change')
        self.assertFalse(state.get('workspace_applied'))

    def test_explicit_resume_after_block_resets_idle_warning_not_calls_or_pending_question(self):
        import datetime as dt
        seq,state=self.run.state(self.task)
        state.update(phase='blocked')
        state['effort_watch']['started_at']=(self.run.control.clock()-dt.timedelta(hours=2)).isoformat()
        self.run.persist(self.task,seq,state)
        before=self.run.control.status(self.task)
        self.run.resume(self.task)
        state=self.run.state(self.task)[1]
        self.assertEqual(state['effort_watch']['round'],1)
        self.assertEqual(self.run.control.status(self.task)['budget'],before['budget'])
        from onecrew.effort_watch import check
        seq,state=self.run.state(self.task)
        self.assertFalse(check(self.run,self.task,seq,state)[1])
        state['effort_watch']['started_at']=(self.run.control.clock()-dt.timedelta(hours=2)).isoformat()
        seq=self.run.persist(self.task,seq,state)
        self.assertTrue(check(self.run,self.task,seq,state)[1])
        request=self.f.ledger.requests(self.task,pending=True)[0]
        seq,state=self.run.state(self.task);state['phase']='blocked';self.run.persist(self.task,seq,state)
        self.run.resume(self.task)
        self.assertEqual(self.run.state(self.task)[1]['effort_watch']['round'],1)
        self.assertEqual(self.f.ledger.requests(self.task,pending=True)[0]['id'],request['id'])
        self.run.run(self.task,steps=1)
        self.assertEqual(self.worker.calls,[])

    def test_repair_limit_preserves_session_and_never_applies(self):
        self.worker.responses=[self.candidate()]*3
        sessions=[]
        for _ in range(3):
            state=self.run.run(self.task,steps=1);sessions.append(state['native_change']['worker_session'])
            result={'passed':False,'detail':'assertion failed','evidence':{'snapshot':state['snapshot'],'exit_code':1}}
            with patch('onecrew.native_change.verify',return_value=result): state=self.run.run(self.task,steps=1)
        self.assertEqual(state['phase'],'blocked');self.assertEqual(len(set(sessions)),1)
        self.assertIn('a-b',(self.f.root/'app/lib/main.dart').read_text())

    def test_explicit_resume_reuses_review_feedback_after_legacy_content_repairs(self):
        seq,state=self.run.state(self.task)
        native=state['native_change'];native.update(stage='review',repairs=2,
            rejected_candidates=[{'digest':'first'},{'digest':'second'}])
        state.update(phase='blocked',message='Native change repair limit reached; evidence preserved.',
                     reviews=[{'accepted':False,'feedback':'Preserve original credential precedence.'}])
        self.run.persist(self.task,seq,state)
        before=self.run.control.status(self.task)
        self.run.resume(self.task);state=self.run.run(self.task,steps=1)
        self.assertEqual(state['native_change']['stage'],'work')
        self.assertEqual(state['native_change']['feedback'],'Preserve original credential precedence.')
        self.assertEqual(state['native_change']['repairs'],3)
        self.assertEqual(state['native_change']['repair_counts'],{'content':2,'product':1})
        self.assertEqual(self.run.control.status(self.task)['used_calls'],before['used_calls'])
        self.assertFalse(self.worker.calls)

    def test_separate_repair_caps_preserve_cumulative_history_and_still_stop(self):
        from onecrew.native_change import repair
        state=self.run.state(self.task)[1]
        for kind in ('content','content','product','product'):repair(state,'failure',kind)
        self.assertEqual(state['native_change']['repairs'],4)
        for kind in ('content','product'):
            repair(state,'still fails',kind)
            self.assertEqual(state['phase'],'blocked')
            self.assertEqual(state['native_change']['repairs'],4)
            self.assertEqual(state['native_change']['pending_repair']['kind'],kind)

    def test_operator_recipe_requires_explicit_authority_and_private_hash(self):
        with self.assertRaises(LedgerError): validate(dict(self.recipe,trusted_native=False))
        with self.assertRaises(LedgerError): validate(dict(self.recipe,owned=['app/lib/app_secrets.dart',*self.recipe['owned']]))


if __name__=='__main__': unittest.main()
