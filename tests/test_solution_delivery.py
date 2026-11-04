import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from onecrew.ledger import Ledger,LedgerError
from onecrew.solution_delivery import Delivery,submit
from onecrew.delivery_plan import validate
from onecrew.delivery_steps import parse_tests,fingerprint
from tests.test_solution_gate import approve_fixture


def plan(root):
    return {'version':1,'source_roots':['app'],'max_repairs':2,'acceptance':[{'id':'AC1','text':'Behavior passes','nodes':['tests']}],
        'nodes':[{'id':'tests','kind':'regression','depends':[],
            'config':{'package':'app','flutter_root':str(root/'sdk'),'tests':['test/test_test.dart'],'red':[]}},
            {'id':'review','kind':'review','depends':['tests'],'config':{}},
            {'id':'handover','kind':'handover','depends':['tests','review'],'config':{}}]}


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'project';(self.root/'app').mkdir(parents=True)
        (self.root/'app/main.dart').write_text('void main() {}')
        (self.root/'app/test').mkdir();(self.root/'app/test/test_test.dart').write_text('// immutable suite fixture')
        (self.root/'app/.dart_tool').mkdir()
        (self.root/'app/.dart_tool/package_config.json').write_text(json.dumps({'packages':[{'name':'app','rootUri':'../'}]}))
        from onecrew.delivery_steps import dart_argv
        args=dart_argv(self.root/'sdk')
        for p in (Path(args[0]),Path(args[1][11:]),Path(args[2])):p.parent.mkdir(parents=True,exist_ok=True);p.write_text('fixture tool, never executed')
        self.ledger=Ledger(self.root,Path(self.tmp.name)/'state');self.binding=approve_fixture(self.ledger)
        self.plan=plan(self.root)

    def create(self,**kw):
        t=submit(self.ledger,'Deliver fixture','root',self.plan,**self.binding,provider='claude',model='sonnet',**kw)
        r=Delivery(self.ledger);r.enable(t['id']);return r,t['id']

    def test_idempotent_submit_and_plan_sealed(self):
        r,t=self.create()
        self.assertEqual(submit(self.ledger,'Deliver fixture','root',self.plan,**self.binding,provider='claude',model='sonnet')['id'],t)
        bad=copy.deepcopy(self.plan);bad['max_repairs']=3
        with self.assertRaisesRegex(LedgerError,'already bound'):submit(self.ledger,'Deliver fixture','root',bad,**self.binding,provider='claude',model='sonnet')

    def test_approval_required(self):
        with self.assertRaises(LedgerError):submit(self.ledger,'x','bad',self.plan,'SOL-missing','hash',provider='claude',model='sonnet')

    def test_root_no_model_launch_on_enable_and_read(self):
        r,t=self.create();self.assertEqual(r.control.status(t)['used_calls'],0)
        self.assertEqual(r.card(t)['phase'],'running')
        self.assertEqual(r.state(t)[1]['delivery']['nodes']['tests']['phase'],'pending')
        self.assertNotIn('android.device',self.ledger.task(t,full=True)['handoff']['grant']['permissions'])
        from onecrew.delivery_steps import execute
        with self.assertRaisesRegex(LedgerError,'dispatch grant'):
            execute(r,t,r.state(t)[1],{'kind':'device'}, {})

    def test_delivery_receipt_does_not_imply_product_completion(self):
        r,t=self.create()
        seq,s=r.state(t);s['phase']='blocked';r.persist(t,seq,s)
        from onecrew.desktop_notifications import snapshots
        key=snapshots(self.ledger,task=t)[0]['id']
        for status,expected in [('launching','uncertain'),('shown','shown'),('closed','shown')]:
            with patch('onecrew.desktop_notifications.status',return_value={'config':{'enabled':True},'records':[
                {'id':key,'task':t,'status':status,'created_at':'2026-10-11T00:00:00Z'}]}):card=r.card(t)
            self.assertEqual(card['delivery']['delivery_status'],expected);self.assertEqual(card['phase'],'blocked')
        with patch('onecrew.desktop_notifications.status',return_value={'config':{'enabled':True},'records':[
            {'id':'old-episode','task':t,'status':'shown','created_at':'2026-10-11T00:00:00Z'}]}):
            self.assertEqual(r.card(t)['delivery']['delivery_status'],'pending')

    def test_restart_does_not_repeat_verified_nodes(self):
        r,t=self.create();r.run(t)
        with patch('onecrew.delivery_steps.execute',return_value={'passed':True,'source':r.state(t)[1]['delivery']['source']['hash'],'counts':{'passed':3,'skipped':0}}) as run:
            r.run(t);r=Delivery(Ledger(self.root,self.ledger.state_root));r.run(t)
            self.assertEqual(run.call_count,2)
        result=r.run(t)
        self.assertEqual(result['phase'],'completed');self.assertEqual(result['delivery']['criteria'],{'AC1':'passed'})
        self.assertTrue(Path(result['report_file']).is_file())
        with patch('onecrew.delivery_steps.execute') as run:r.run(t);run.assert_not_called()

    def test_missing_evidence_blocks_instead_of_complete(self):
        r,t=self.create();r.run(t)
        with patch('onecrew.delivery_steps.execute',return_value={'passed':False,'detail':'Required test skipped'}):s=r.run(t)
        self.assertEqual(s['phase'],'waiting');self.assertNotIn('report_file',s)
        self.assertEqual(s['delivery']['nodes']['tests']['phase'],'blocked')

    def test_source_drift_is_not_silently_accepted(self):
        r,t=self.create();r.run(t)
        (self.root/'app/main.dart').write_text('external edit')
        with patch('onecrew.delivery_steps.execute') as op:s=r.run(t);op.assert_not_called()
        self.assertEqual(s['phase'],'waiting');self.assertIn('drift',s['message'])
        self.assertEqual(s['delivery']['escalation']['class'],'drift')

    def test_root_budget_is_effective_in_core(self):
        r,t=self.create(max_calls=1)
        c=r.control.status(t)
        a=r.control.reserve(t,c['revision'],'attempt',{'stage':'test'})
        r.control.finish(a['id'],a['generation'],{'ok':True})
        with self.assertRaisesRegex(LedgerError,'budget'):r.control.reserve(t,c['revision'],'again',{'stage':'test'})
        self.assertEqual(r.control.status(t)['budget']['goal']['used_calls'],1)

    def test_cancel_is_terminal_without_budget_reset(self):
        r,t=self.create();r.control.cancel(t)
        with self.assertRaises(LedgerError):r.resume(t)

    def test_dependency_cycle_rejected(self):
        self.plan['nodes'][0]['depends']=['review']
        with self.assertRaises(LedgerError):validate(self.plan)

    def test_no_missing_final_node_dependencies(self):
        self.plan['nodes'][-1]['depends']=['review']
        with self.assertRaises(LedgerError):validate(self.plan)

    def test_build_without_review_dependency_rejected(self):
        self.plan['nodes'].insert(1,{'id':'build','kind':'build','depends':['tests'],'config':{
            'package':'app','flutter_root':str(self.root/'sdk'),'android_sdk':str(self.root/'android'),
            'variant':'debug','config_reference':None,'config_version':'none','signer_sha256':'a'*64,'timeout_seconds':30}})
        self.plan['nodes'][-1]['depends'].append('build')
        with self.assertRaisesRegex(LedgerError,'reviewed'):validate(self.plan)

    def test_child_notice_suppressed_standalone_unchanged(self):
        r,t=self.create()
        from onecrew import delivery_store as db
        from onecrew.owned_intake import submit as child_submit
        # Standalone audit task used only as a fixture for lineage filtering.
        child=child_submit(self.ledger,'audit','audit',provider='claude',model='sonnet')
        from tests.test_workflow import FixtureWorker
        from onecrew.owned import Owned
        cr=Owned(self.ledger,FixtureWorker(self.ledger,[]));cr.enable(child['id'])
        seq,s=cr.state(child['id']);s['phase']='completed';cr.persist(child['id'],seq,s)
        from onecrew.desktop_notifications import snapshots
        self.assertTrue(snapshots(self.ledger,task=child['id']))
        with self.ledger.transaction(write=True) as conn:conn.execute('INSERT INTO delivery_children VALUES(?,?,?,?)',(child['id'],t,'fixture',0))
        self.assertFalse(snapshots(self.ledger,task=child['id']))

    def test_test_counts_and_skip_gate(self):
        def stream(skip=False,success=True):return '\n'.join(json.dumps(v) for v in [
            {'type':'testStart','test':{'id':1,'name':'behavior'}},
            {'type':'testDone','testID':1,'result':'success','skipped':skip,'hidden':False},
            {'type':'done','success':success}])
        self.assertTrue(parse_tests(stream(),0)['passed'])
        self.assertFalse(parse_tests(stream(True),0)['passed'])
        self.assertFalse(parse_tests('All tests passed!',0)['passed'])
        self.assertFalse(parse_tests(stream(),1)['passed'])

    def change_plan(self):
        recipe=dict(source_roots=['app'],owned=['app/main.dart','app/test/new_test.dart'],extra_sources={},
            package='app',flutter_root=str(self.root/'sdk'),tests=['app/test/new_test.dart'],reference='Approved fixture',trusted_native=True)
        self.plan['nodes'].insert(0,{'id':'fix','kind':'change','depends':[], 'config':{'goal':'Fix behavior','recipe':recipe}})
        self.plan['nodes'][1]['depends']=['fix'];self.plan['nodes'][-1]['depends'].insert(0,'fix')
        return recipe

    def child(self,r,t,generation=0,enable=True):
        from onecrew.owned_intake import submit as child_submit
        from onecrew.owned import Owned
        from tests.test_workflow import FixtureWorker
        seq,s=r.state(t);node=self.plan['nodes'][0]
        s['delivery']['child_intent']={'node':'fix','generation':generation,'goal':'Fix behavior'};r.persist(t,seq,s)
        ct=child_submit(self.ledger,'Fix behavior','child-'+str(generation),mode='change',provider='claude',model='sonnet',
            native_change=node['config']['recipe'],max_calls=3,max_seconds=7200,**self.binding,
            _delivery_parent=t,_delivery_node='fix',_delivery_generation=generation)
        cr=Owned(self.ledger,FixtureWorker(self.ledger,[]))
        if enable:cr.enable(ct['id'])
        return cr,ct['id']

    def test_child_intent_replay_and_shared_calls(self):
        self.change_plan();r,t=self.create(max_calls=3);cr,child=self.child(r,t)
        self.assertEqual(self.child(r,t)[1],child)
        for runtime,task,key in ((r,t,'a'),(cr,child,'b'),(cr,child,'c')):
            c=runtime.control.status(task);a=runtime.control.reserve(task,c['revision'],key,{'stage':'fixture'})
            runtime.control.finish(a['id'],a['generation'],{'ok':True})
        self.assertEqual(cr.control.status(child)['budget']['goal']['used_calls'],3)
        with self.assertRaises(LedgerError):r.control.reserve(t,r.control.status(t)['revision'],'d',{'stage':'fixture'})
        with self.assertRaises(LedgerError):cr.control.reserve(child,cr.control.status(child)['revision'],'e',{'stage':'fixture'})

    def test_parent_stop_fences_child_and_cancel_handles_pre_enable_crash(self):
        self.change_plan();r,t=self.create(max_calls=3);cr,child=self.child(r,t,enable=False)
        r.control.cancel(t)
        with self.assertRaisesRegex(LedgerError,'root is stopped'):cr.enable(child)

    def test_parent_pause_fences_child_admission(self):
        self.change_plan();r,t=self.create(max_calls=3);cr,child=self.child(r,t)
        r.control.pause(t)
        with self.assertRaises(LedgerError):cr.control.reserve(child,cr.control.status(child)['revision'],'x',{'stage':'fixture'})

    def test_crash_in_build_replays_once_then_asks(self):
        # A build writes only into a fresh OneCrew capture, so one interrupted run replays; a second asks the user.
        r,t=self.create();r.run(t)
        seq,s=r.state(t)
        s['plan']['nodes'][0]['kind']='build';s['delivery']['nodes']['tests']['phase']='running';r.persist(t,seq,s)
        with patch('onecrew.delivery_steps.execute') as op:result=r.run(t);op.assert_not_called()
        self.assertEqual(result['delivery']['nodes']['tests']['phase'],'pending')
        self.assertEqual(result['phase'],'waiting_operation');self.assertEqual(result['delivery']['recoveries'][-1]['action'],'replay')
        seq,s=r.state(t);s['delivery']['nodes']['tests']['phase']='running';s['delivery']['retry_after']=None;r.persist(t,seq,s)
        with patch('onecrew.delivery_steps.execute') as op:result=r.run(t);op.assert_not_called()
        self.assertEqual(result['phase'],'waiting');self.assertTrue(self.ledger.requests(t,pending=True))
        self.assertEqual(result['delivery']['escalation']['class'],'interrupted')

    def test_stale_passed_receipt_cannot_finish(self):
        r,t=self.create();r.run(t);seq,s=r.state(t)
        for name in ('tests','review'):s['delivery']['nodes'][name].update(phase='passed',receipt={'passed':True,'source':'old'})
        r.persist(t,seq,s);result=r.run(t)
        # Stale evidence is a runtime defect: one question, never a completion.
        self.assertEqual(result['phase'],'waiting');self.assertNotIn('report_file',result)
        self.assertEqual(result['delivery']['escalation']['class'],'runtime_bug')

    def test_repair_retains_history_and_invalidates_downstream(self):
        self.change_plan();r,t=self.create();r.run(t);s=r.state(t)[1]
        for name,row in s['delivery']['nodes'].items():row.update(phase='passed',receipt={'passed':True,'source':'previous'})
        self.assertTrue(r._repair(s,s['plan']['nodes'][1],{'passed':False,'failure_kind':'test','detail':'assertion'}))
        self.assertTrue(all(v['phase']=='pending' for v in s['delivery']['nodes'].values()))
        self.assertEqual(s['delivery']['repairs'],1);self.assertGreater(len(s['delivery']['history']),1)
        s['delivery']['repairs']=2
        self.assertFalse(r._repair(s,s['plan']['nodes'][1],{'failure_kind':'test'}))

    def test_mcp_delivery_reads_never_start(self):
        from onecrew.mcp_entry import Server
        r,t=self.create()
        with patch('onecrew.runner.start') as start:
            self.assertEqual(Server(self.ledger).call('status',{'task':t})['task'],t)
            self.assertEqual(Server(self.ledger).call('outputs',{'task':t})['phase'],'running')
            start.assert_not_called()

    def test_capture_rebases_red_to_exact_overlay(self):
        from onecrew.delivery_steps import capture,rebase_packages
        import shutil
        (self.root/'app/.dart_tool').mkdir(exist_ok=True)
        (self.root/'app/.dart_tool/package_config.json').write_text(json.dumps({'packages':[{'name':'app','rootUri':'../'}]}))
        baseline=Path(self.tmp.name)/'baseline';red=Path(self.tmp.name)/'red'
        capture(self.root,fingerprint(self.root,['app']),baseline,['app']);shutil.copytree(baseline,red)
        rebase_packages(baseline,red,['app'])
        self.assertEqual(json.loads((red/'app/.dart_tool/package_config.json').read_text())['packages'][0]['rootUri'],(red/'app').as_uri()+'/')

    def test_shared_budget_concurrent_reservations_never_exceed_cap(self):
        from concurrent.futures import ThreadPoolExecutor
        self.change_plan();r,t=self.create(max_calls=3);cr,child=self.child(r,t)
        # Two remaining callers race for the last root reservation.
        for i in range(2):
            a=r.control.reserve(t,r.control.status(t)['revision'],'used'+str(i),{'stage':'fixture'})
            r.control.finish(a['id'],a['generation'],{'ok':True})
        def reserve(task):
            try:return r.control.reserve(task,r.control.status(task)['revision'],'race',{'stage':'fixture'})
            except LedgerError:return None
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(reserve,[t,child]))
        self.assertEqual(sum(x is not None for x in results),1)
        self.assertEqual(r.control.status(t)['budget']['goal']['remaining_calls'],0)

    def test_missing_dependency_blocks_preflight_without_worker(self):
        (self.root/'app/.dart_tool/package_config.json').write_text(json.dumps({'packages':[{'name':'missing','rootUri':'file:///no-such-onecrew-dependency'}]}))
        r,t=self.create();result=r.run(t)
        # Environment failures retry read-only with backoff, then ask once naming the missing item; no worker call.
        self.assertEqual(result['phase'],'waiting_operation');self.assertIn('environment',result['message'])
        for _ in range(3):
            seq,s=r.state(t);s['delivery']['retry_after']=None;r.persist(t,seq,s);result=r.run(t)
        self.assertEqual(result['phase'],'waiting')
        request=self.ledger.requests(t,pending=True)[0]
        self.assertIn('cache unavailable',request['question']['reason'])
        self.assertEqual(r.control.status(t)['used_calls'],0)
        self.assertEqual(len(self.ledger.requests(t,pending=True)),1)

    def test_child_wait_does_not_grow_checkpoints_or_embed_manifest(self):
        self.change_plan();r,t=self.create();r.run(t)
        seq,s=r.state(t)
        self.assertNotIn('files',s['delivery']['source'])
        with patch.object(r,'_child',return_value=None):
            r.run(t);first=r.state(t)[0]
            for _ in range(5):r.run(t)
        self.assertEqual(first,r.state(t)[0])

    def test_tool_drift_blocks_before_native_launch(self):
        r,t=self.create();r.run(t)
        path=next(iter(r.state(t)[1]['delivery']['preflight']['tools']));Path(path).write_text('changed tool')
        with patch('onecrew.delivery_steps.execute') as op:result=r.run(t);op.assert_not_called()
        self.assertIn('toolchain',result['message'])

    def test_private_build_values_and_raw_streams_not_in_evidence(self):
        from onecrew.delivery_steps import build,bounded
        import zipfile
        secret='fixture-sensitive-string-never-log';private=Path(self.tmp.name)/'private.json';private.write_text(json.dumps({'CREDENTIAL':secret}))
        r,t=self.create();r.run(t);s=r.state(t)[1]
        node={'id':'private-build','config':{'package':'app','flutter_root':str(self.root/'sdk'),'android_sdk':str(self.root/'sdk'),
            'variant':'release','config_reference':str(private),'config_version':'opaque-v1','timeout_seconds':60}}
        def fake_command(argv,directory,timeout,guard,env):
            (directory/'fixture.out').write_text(secret);(directory/'fixture.err').write_text(secret)
            apk=directory/'build/app/outputs/flutter-apk/app-release.apk';apk.parent.mkdir(parents=True)
            with zipfile.ZipFile(apk,'w') as z:z.writestr('AndroidManifest.xml','fixture');z.writestr('classes.dex','fixture')
            return 0,'echo '+secret,''
        with patch('onecrew.delivery_steps.command',side_effect=fake_command):result=build(r,t,s,node,{'generation':0})
        self.assertTrue(result['passed']);self.assertNotIn(secret,json.dumps(result))
        self.assertNotIn(secret,Path(result['log']).read_text())
        work=Path(result['apk']).parents[4]
        self.assertFalse(list(work.glob('fixture.*')))

    def test_review_conditional_acceptance_is_rejected(self):
        from onecrew.delivery_steps import review
        from onecrew.ledger import content_hash
        r,t=self.create();r.run(t);s=r.state(t)[1];s['delivery']['nodes']['tests'].update(phase='passed',receipt={'passed':True,'source':s['delivery']['source']['hash']})
        def capture(runtime,path,*a,**kw):path.mkdir(parents=True)
        digest=content_hash(s['delivery']['nodes']['tests']['receipt'])
        value={'verdict':'accept','feedback':'accept provided missing UI test is added','unresolved_required':['UI test'],
            'checks':[{'id':'AC1','status':'passed','evidence_refs':[digest]}]}
        with patch('onecrew.native_audit.capture',side_effect=capture),patch.object(r,'_invoke',return_value=(0,value)):
            result=review(r,t,s,s['plan']['nodes'][1],s['delivery']['nodes']['review'])
        self.assertFalse(result['passed'])

    def test_delivery_migration_backup_and_old_rows_preserved(self):
        r,t=self.create()
        self.assertTrue(list((self.ledger.state_root/'backups').glob('ledger-before-delivery-*.sqlite3')))
        with self.ledger.transaction() as c:
            self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],3)
            self.assertEqual(c.execute('SELECT count(*) FROM delivery_roots').fetchone()[0],1)

    def test_parent_drives_real_child_lifecycle_through_typed_fixture_handover(self):
        import zipfile
        from contextlib import ExitStack
        from onecrew.owned import Owned
        from onecrew.ledger import content_hash
        from onecrew.delivery_steps import file_hash
        from tests.test_workflow import FixtureWorker
        self.change_plan()
        (self.root/'app/pubspec.yaml').write_text('name: app\n')
        (self.root/'app/.dart_tool/package_graph.json').write_text(json.dumps({'configVersion':1,'roots':['app'],'packages':[{'name':'app','version':'1.0.0','dependencies':[]}]}))
        sdk=self.root/'android';sdk.mkdir();bt=sdk/'build-tools';bt.mkdir();(bt/'lib').mkdir()
        for name in ('lib/apksigner.jar','aapt2.exe','zipalign.exe'):(bt/name).write_text('fixture')
        java=self.root/'java.exe';java.write_text('fixture');adb=self.root/'adb.exe';adb.write_text('fixture')
        scenario=self.root/'scenario.json';scenario.write_text(json.dumps({'version':1,'activity':'.MainActivity',
            'steps':[{'id':'ready','operation':'assert_ui','arguments':{'selector':{'text':'READY'}}}], 'cleanup':[]}))
        additions=[{'id':'build','kind':'build','depends':['review'],'config':{
            'package':'app','flutter_root':str(self.root/'sdk'),'android_sdk':str(sdk),'variant':'release',
            'config_reference':None,'config_version':'fixture','signer_sha256':'a'*64,'timeout_seconds':60}},
            {'id':'audit','kind':'apk_audit','depends':['build'],'config':{'build_node':'build','build_tools':str(bt),
             'package_id':'example.app','signer_sha256':'a'*64,'require_16kb':True,'max_bytes':10000}},
            {'id':'device','kind':'device','depends':['audit'],'config':{'build_node':'build','adb':str(adb),'serial':'FIXTURE',
             'package_id':'example.app','scenario':str(scenario),'scenario_sha256':file_hash(scenario),
             'private_reference':None,'private_version':'fixture','timeout_seconds':60}}]
        self.plan['nodes'][-1:-1]=additions;self.plan['nodes'][-1]['depends']+=['build','audit','device']
        self.plan['acceptance'].append({'id':'AC2','text':'Verified fixture artifact installed and READY visible','nodes':['device']})
        r,t=self.create();workers={}
        def child_runtime(ledger):
            worker=FixtureWorker(ledger,[{'report':'Fixture patch changes behavior and adds an owned test. Device verification follows in the parent.','question':'','files':[
                {'path':'app/main.dart','text':'void main() { print(1); }'},
                {'path':'app/test/new_test.dart','text':'// fixture test'}]}, {'accepted':True,'feedback':'Fixture review'}])
            result=Owned(ledger,worker);workers['last']=result;return result
        def start(ledger,child):
            engine=workers['last']
            for _ in range(10):
                state=engine.run(child,steps=1)
                if state['phase'] in ('completed','blocked'):break
            self.assertEqual(state['phase'],'completed',state['message']);return {'status':'fixture'}
        def native_verify(runtime,task,state,recipe):return {'passed':True,'detail':'fixture','evidence':{'snapshot':state['snapshot'],'exit_code':0}}
        def invoke(task,seq,state,stage,prompt,schema,profile):
            refs=state['delivery']['nodes']['review']['review_context']['refs']
            return seq,{'verdict':'accept','feedback':'Fixture structured review','unresolved_required':[],
                'checks':[{'id':'AC1','status':'passed','evidence_refs':[refs['tests']]}]}
        def commands(runtime,task,argv,cwd,seconds,env=None):
            if 'test' in argv:return 0,'\n'.join(json.dumps(x) for x in [
                {'type':'testStart','test':{'id':1,'name':'behavior'}},
                {'type':'testDone','testID':1,'result':'success','hidden':False,'skipped':False},{'type':'done','success':True}]),''
            if 'build' in argv:
                apk=Path(cwd)/'build/app/outputs/flutter-apk/app-release.apk';apk.parent.mkdir(parents=True)
                with zipfile.ZipFile(apk,'w') as z:z.writestr('AndroidManifest.xml','fixture');z.writestr('classes.dex','fixture')
                return 0,'Built fixture',''
            if '-jar' in argv:return 0,'Signer #1 certificate SHA-256 digest: '+'a'*64,''
            if 'badging' in argv:return 0,"package: name='example.app'",''
            if '-s' in argv:
                self.assertEqual(argv[1:3],['-s','FIXTURE']);args=argv[3:]
                if args==['get-state']:return 0,'device',''
                if args==['shell','wm','size']:return 0,'Physical size: 1080x1920',''
                if args[0]=='install':return 0,'Success',''
                if args[:3]==['shell','pm','path']:return 0,'package:/data/app/base.apk',''
                if args[:2]==['shell','sha256sum']:return 0,r.state(t)[1]['delivery']['nodes']['build']['receipt']['sha256']+' /data/app/base.apk',''
                if args[0]=='exec-out':return 0,'<?xml version="1.0"?><hierarchy><node text="READY" package="example.app" bounds="[0,0][100,100]" enabled="true"/></hierarchy>',''
                if args[:2]==['shell','pidof']:return 0,'1234',''  # the launched app is running (round 2 checks it)
            return 0,'',''
        with ExitStack() as stack:
            stack.enter_context(patch('onecrew.solution_delivery.Owned',side_effect=child_runtime))
            stack.enter_context(patch('onecrew.runner.start',side_effect=start))
            stack.enter_context(patch('onecrew.runner.status',return_value={'status':'stopped'}))
            stack.enter_context(patch('onecrew.native_change.verify',side_effect=native_verify))
            stack.enter_context(patch.object(r,'_invoke',side_effect=invoke))
            stack.enter_context(patch('onecrew.delivery_steps.bounded',side_effect=commands))
            stack.enter_context(patch('onecrew.delivery_android.bounded',side_effect=commands))
            stack.enter_context(patch('onecrew.delivery_android.shutil.which',return_value=str(java)))
            for _ in range(15):
                state=r.run(t)
                if state['phase'] in ('blocked','completed'):break
        self.assertEqual(state['phase'],'completed',state['message'])
        self.assertEqual(state['delivery']['criteria'],{'AC1':'passed','AC2':'passed'})
        self.assertEqual(r.control.status(t)['budget']['goal']['used_calls'],2)  # Root reviewer is a test double.
        self.assertIn('print(1)',(self.root/'app/main.dart').read_text())
        self.assertTrue(Path(state['report_file']).is_file())


if __name__=='__main__':unittest.main()
