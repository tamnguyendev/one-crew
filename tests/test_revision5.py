import json
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import test_owned as fixtures
from onecrew.ledger import LedgerError
from onecrew.progress import classify, observe
from onecrew.owned_recipes import validate, verify_completion
from onecrew.owned_verification import check_tests


class Revision5Tests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.OwnedTests();self.f.setUp();self.addCleanup(self.f.doCleanups)

    def config(self):
        return dict(flutter_root=str(self.f.root/'flutter'),android_sdk=str(self.f.root/'sdk'),
            dependency_root=None,dependency_policy='as-of',max_seconds=60,queue_seconds=30,native_authorized=True)

    def test_recipe_grant_validation_and_submission_identity(self):
        from onecrew.owned_intake import submit
        config=self.config()
        task=submit(self.f.ledger,'Build old UI','build',mode='branch',branch='onecrew/old',android_build=config)
        self.assertIn('android.build',self.f.ledger.task(task['id'],full=True)['handoff']['grant']['permissions'])
        config['max_seconds']=90
        with self.assertRaises(LedgerError):
            submit(self.f.ledger,'Build old UI','build',mode='branch',branch='onecrew/old',android_build=config)
        config['native_authorized']='true'
        with self.assertRaises(LedgerError): validate(config)

    def test_worker_and_reviewer_contract_excludes_ungranted_publication(self):
        from onecrew.owned import contract
        prompt,schema,delivery=contract({'mode':'change','branch':None,'remote':None})
        self.assertEqual(delivery,'isolated_candidate');self.assertNotIn('deliver',schema['properties']['action']['enum'])
        self.assertNotIn('\ndeliver:',prompt);self.assertIn('neither required nor authorized',prompt)
        run,task,_=self.f.runtime([],mode='change',image='sha256:'+'a'*64)
        with patch('onecrew.owned_git.GitDelivery') as git:
            with self.assertRaisesRegex(LedgerError,'not authorized'):
                run._tool(task,run.state(task)[1],'deliver',{'directory':''},run.control.status(task)['configuration']['profile'])
            git.assert_not_called()

    def test_worker_cannot_choose_build_command_or_sdk(self):
        run,task,_=self.f.runtime([],mode='branch',branch='onecrew/old',android_build=self.config())
        state=run.state(task)[1];state['branches']=[{'result':{}}]
        profile=run.control.status(task)['configuration']['profile']
        with patch('onecrew.android_jobs.dispatch') as launch:
            with self.assertRaises(LedgerError): run._tool(task,state,'android_build',{'flutter_root':'elsewhere'},profile)
            launch.assert_not_called()

    def test_waiting_build_restart_does_not_call_worker_and_verifies_artifact(self):
        run,task,worker=self.f.runtime([fixtures.action('android_build')],mode='branch',branch='onecrew/old',android_build=self.config())
        seq,state=run.state(task);state['branches']=[{'result':{}}];run.persist(task,seq,state)
        with patch('onecrew.android_jobs.dispatch',return_value={'status':'queued'}) as launch:
            state=run.run(task,steps=1)
        self.assertEqual(state['phase'],'waiting_operation');self.assertEqual(len(worker.calls),1)
        from onecrew.owned import Owned
        restored=Owned(self.f.ledger,worker)
        with patch('onecrew.android_jobs.reconcile'),patch('onecrew.android_jobs.status',return_value={'status':'running'}):
            for _ in range(3): self.assertEqual(restored.run(task,steps=1)['phase'],'waiting_operation')
        self.assertEqual(len(worker.calls),1)
        apk={'path':str(self.f.root/'app.apk'),'sha256':'fixture','bytes':12}
        with patch('onecrew.android_jobs.reconcile'),patch('onecrew.android_jobs.status',return_value={'status':'succeeded','apk':apk}),patch('onecrew.android_build.verify_apk',return_value=apk):
            state=restored.run(task,steps=1)
        self.assertEqual(state['phase'],'running');self.assertFalse(state['build_evidence']['device_tested'])
        self.assertEqual(len(worker.calls),1)
        with patch('onecrew.android_build.verify_apk',return_value=dict(apk,sha256='tampered')):
            with self.assertRaises(LedgerError): verify_completion(run,task,state,{'android_build':self.config()})

    def test_failed_build_blocks_without_repair_model(self):
        run,task,worker=self.f.runtime([])
        seq,state=run.state(task);state.update(phase='waiting_operation',operation={'key':'build'});run.persist(task,seq,state)
        with patch('onecrew.android_jobs.reconcile'),patch('onecrew.android_jobs.status',return_value={'status':'interrupted'}):
            state=run.run(task)
        self.assertEqual(state['phase'],'blocked');self.assertEqual(worker.calls,[])

    def test_equivalent_results_with_different_query_text_stop(self):
        state={'phase':'running','snapshot':None}
        # Repeated positive evidence remains a loop; different empty searches do not.
        for query in ('one','two','three'): observe(state,'search',{'query':query},{'matches':[{'path':'same.py','lines':[1]}]})
        self.assertEqual(state['phase'],'blocked')

    def test_exploration_limit_and_resume_does_not_reset_it(self):
        state={'phase':'running','snapshot':None}
        for i in range(16): observe(state,'git_log',{'cursor':i},{'commits':[i]})
        self.assertEqual(state['phase'],'blocked')
        state['phase']='running';observe(state,'git_log',{'cursor':17},{'commits':[17]})
        self.assertEqual(state['phase'],'blocked')

    def test_infrastructure_classification(self):
        from onecrew.sandbox_gate import GateUnavailable
        self.assertEqual(classify(GateUnavailable('Docker failed')),'environment')
        self.assertEqual(classify(ValueError('OAuth login required')),'auth')
        self.assertEqual(classify(ValueError('429 quota exceeded')),'quota')
        self.assertEqual(classify(ValueError('connection reset')),'transient')

    def test_known_auth_error_has_no_provider_retry(self):
        run,task,worker=self.f.runtime([fixtures.action('read',path='calc.py')])
        original=worker.result
        def fail(attempt): raise LedgerError('OAuth login required')
        with patch.object(worker,'result',side_effect=fail): state=run.run(task)
        self.assertEqual(state['phase'],'blocked');self.assertEqual(len(worker.calls),1)
        self.assertEqual(state['recovery']['kind'],'auth')

    def test_all_captured_tests_need_current_passing_receipts(self):
        state={'snapshot':'s2','files':{'test_a.py':'a','test_b.py':'b'},'original':{'test_a.py':'a','test_b.py':'b'},'tests':[]}
        def add(name,snapshot,passed): state['tests'].append({'test_path':name,'passed':passed,'evidence':{'snapshot':snapshot}})
        add('test_a.py','s2',True);add('test_b.py','s1',True)
        with self.assertRaises(LedgerError): check_tests(state)
        add('test_b.py','s2',False)
        with self.assertRaises(LedgerError): check_tests(state)
        add('test_b.py','s2',True)
        self.assertEqual(check_tests(state)['status'],'passed')

    def test_finish_cannot_omit_authorized_build(self):
        run,task,_=self.f.runtime([],mode='branch',branch='onecrew/old',android_build=self.config())
        with self.assertRaisesRegex(LedgerError,'no verified APK'):
            verify_completion(run,task,run.state(task)[1],run.control.status(task)['configuration']['profile'])

    def test_active_job_builds_without_fake_parent_completion_and_obeys_deadline(self):
        import zipfile
        import datetime as dt
        from tests.test_android_build import AndroidTests
        from onecrew.owned_intake import submit
        from onecrew.owned import Owned
        from onecrew.git_history import History
        from onecrew.android_build import AndroidBuild
        from tests.test_workflow import FixtureWorker
        fixture=AndroidTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        config=dict(flutter_root=str(fixture.flutter),android_sdk=str(fixture.sdk),dependency_root=None,
            dependency_policy='as-of',max_seconds=60,queue_seconds=30,native_authorized=True)
        task=submit(fixture.f.ledger,'Build old UI','active-build',mode='branch',branch='onecrew/active',android_build=config)['id']
        run=Owned(fixture.f.ledger,FixtureWorker(fixture.f.ledger,[]));run.enable(task)
        profile=run.control.status(task)['configuration']['profile']
        head=fixture.f.git('rev-parse','HEAD').decode().strip()
        receipt=History(run,task,profile,'').branch_before(head,head,'active')
        seq,state=run.state(task);state.update(phase='waiting_operation',branches=[receipt]);run.persist(task,seq,state)
        def command(argv,cwd,timeout,guard,**kwargs):
            guard();apk=cwd/'build/app/outputs/flutter-apk/app-debug.apk';apk.parent.mkdir(parents=True)
            with zipfile.ZipFile(apk,'w') as z:
                z.writestr('AndroidManifest.xml','manifest');z.writestr('classes.dex','dex')
            return 0,'built',''
        args={k:v for k,v in config.items() if k!='queue_seconds'}
        result=AndroidBuild(fixture.f.ledger,command).build(task,'active',**args)
        self.assertEqual(result['status'],'succeeded',result)
        self.assertEqual(run.state(task)[1]['phase'],'waiting_operation')
        with fixture.f.ledger.transaction(write=True) as conn:
            conn.execute('UPDATE tasks SET deadline=? WHERE id=?',((dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=1)).isoformat(),task))
        result=AndroidBuild(fixture.f.ledger,command).build(task,'expired',**args)
        self.assertEqual(result['status'],'blocked');self.assertIn('deadline',result['error'])

if __name__=='__main__': unittest.main()
