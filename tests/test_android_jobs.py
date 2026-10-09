import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import time
import unittest
from unittest.mock import Mock, patch

import tests.test_android_build as fixtures
from onecrew import android_jobs as jobs
from onecrew.android_build import AndroidBuild
from onecrew.ledger import LedgerError
from onecrew.supervisor import identity, native_python, probe
from onecrew.workflow import task_lock


class BackgroundBuildTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.AndroidTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.f=self.fixture;self.ledger=self.f.f.ledger;self.task=self.f.task

    def submit(self,key='background',**options):
        return jobs.dispatch(self.ledger,self.task,key,self.f.flutter,self.f.sdk,
                             native_authorized=True,**options)

    def wait_stopped(self,key):
        end=time.monotonic()+10
        while time.monotonic()<end:
            value=jobs.status(self.ledger,self.task,key)
            if value['runner']=='dead': return value
            time.sleep(.05)
        self.fail('Fixture build runner failed to exit')

    def stop(self,key):
        jobs.cancel(self.ledger,self.task,key);return self.wait_stopped(key)

    def test_detached_queue_survives_launcher_duplicate_cancel_and_foreground_share_slot(self):
        args=[native_python(),'-X','utf8','-m','onecrew','--project',str(self.ledger.project),
              '--state-root',str(self.ledger.state_root),'android','build','--from-task',self.task,
              '--key','native','--flutter-root',str(self.f.flutter),'--android-sdk',str(self.f.sdk),
              '--allow-trusted-native-build']
        with task_lock(self.ledger,'android.capacity'):
            before=time.monotonic()
            launch=subprocess.run(args,capture_output=True,timeout=12)
            self.assertEqual(launch.returncode,0,launch.stderr.decode()+launch.stdout.decode())
            value=json.loads(launch.stdout);self.addCleanup(self.stop,'native')
            self.assertLess(time.monotonic()-before,10)
            self.assertEqual(value['runner'],'alive');self.assertEqual(value['status'],'queued')
            again=subprocess.run(args,capture_output=True,timeout=12)
            self.assertEqual(json.loads(again.stdout)['identity'],value['identity'])
            with self.assertRaises(LedgerError): self.f.build(Mock(),'foreground')
            with self.assertRaises(LedgerError): self.f.build(Mock(),'native')
            self.assertFalse((jobs.paths(self.ledger,self.task,'native')[0]/'receipt.json').exists())
            self.assertEqual(self.f.run.control.status(self.task)['used_calls'],0)
            stopped=self.stop('native');self.assertEqual(stopped['status'],'cancelled')
            self.assertEqual(self.submit('native')['status'],'cancelled')

    def test_queue_deadline_and_required_question_never_launch(self):
        from tests.test_ledger import QUESTION
        request=self.ledger.create_request(self.task,'question',QUESTION)
        value=self.submit('wait',queue_seconds=1);self.addCleanup(self.stop,'wait')
        end=self.wait_stopped('wait')
        self.assertEqual(end['status'],'blocked');self.assertIn('Queue deadline',end['error'])
        self.assertEqual(self.ledger.request(request['id'])['state'],'pending')
        self.assertFalse((jobs.paths(self.ledger,self.task,'wait')[0]/'receipt.json').exists())

    def test_killed_queue_reports_interrupted_never_replays(self):
        with task_lock(self.ledger,'android.capacity'):
            value=self.submit('killed');self.addCleanup(self.stop,'killed')
            self.assertEqual(probe(value['identity']),'alive')
            subprocess.run(['taskkill','/PID',str(value['identity']['pid']),'/F'],capture_output=True,check=True)
            end=self.wait_stopped('killed');self.assertEqual(end['status'],'interrupted')
            from onecrew.notifications import pull
            batch=pull(self.ledger,'lost-build')
            notices=[n for n in batch['notifications'] if n.get('build_key')=='killed']
            self.assertEqual(len(notices),1);self.assertEqual(notices[0]['status'],'interrupted')
            with patch('onecrew.android_jobs.subprocess.Popen') as spawn:
                self.assertEqual(self.submit('killed')['status'],'interrupted');spawn.assert_not_called()

    def test_configuration_conflict_and_spawn_failure_persist(self):
        with patch('onecrew.android_jobs.subprocess.Popen',side_effect=OSError('spawn denied')):
            self.assertEqual(self.submit('failed')['status'],'blocked')
        with self.assertRaises(LedgerError): self.submit('failed',max_seconds=60)
        self.assertEqual(self.submit('failed')['status'],'blocked')
        with self.assertRaises(LedgerError): self.submit('bad',queue_seconds=0)

    def test_native_failure_is_reported_after_dispatch_and_other_project_shares_capacity(self):
        from onecrew.ledger import Ledger
        other=self.f.f.root.parent/'other';other.mkdir()
        other_ledger=Ledger(other,self.ledger.state_root)
        with task_lock(other_ledger,'android.capacity'):
            result=jobs.dispatch(self.ledger,self.task,'missing-sdk',self.f.flutter/'absent',self.f.sdk,native_authorized=True)
            self.addCleanup(self.stop,'missing-sdk')
            self.assertEqual(result['status'],'queued')
        result=self.wait_stopped('missing-sdk')
        self.assertEqual(result['status'],'blocked')
        self.assertIn('SDK unavailable',result['error'])
        self.assertEqual(result['build']['status'],'blocked')

    def test_worker_runs_under_capacity_and_releases_slot_after_failure(self):
        root,path=jobs.paths(self.ledger,self.task,'local')
        now=dt.datetime.now(dt.timezone.utc)
        record=dict(request=dict(task=self.task,key='local',flutter_root=str(self.f.flutter),
                    android_sdk=str(self.f.sdk),native_authorized=True),status='queued',
                    identity=identity(os.getpid()),queue_deadline=(now+dt.timedelta(seconds=30)).isoformat())
        jobs.save(self.ledger,self.task,path,record)
        def execute(**kwargs):
            with self.assertRaises(LedgerError):
                with task_lock(self.ledger,'android.capacity'): pass
            kwargs['external_guard']()
            return {'status':'blocked','error':'fixture failure'}
        value=jobs.run(self.ledger,self.task,'local',builder=Mock(_build=Mock(side_effect=execute)))
        self.assertEqual(value['status'],'blocked')
        with task_lock(self.ledger,'android.capacity'): pass

    def test_background_receipt_directory_is_compatible_with_build_and_guard_cancels(self):
        root,path=jobs.paths(self.ledger,self.task,'guard');root.mkdir(parents=True)
        call=Mock()
        with task_lock(self.ledger,'android.capacity'):
            result=AndroidBuild(self.ledger,call)._build(self.task,'guard',self.f.flutter,self.f.sdk,
                native_authorized=True,external_guard=Mock(side_effect=LedgerError('cancelled by user')))
        self.assertEqual(result['status'],'blocked');call.assert_not_called()
        from tests.test_ledger import QUESTION
        self.ledger.create_request(self.task,'foreground-question',QUESTION)
        result=AndroidBuild(self.ledger,call).build(self.task,'question-guard',self.f.flutter,self.f.sdk,native_authorized=True)
        self.assertEqual(result['status'],'blocked');self.assertIn('input is pending',result['error'])
        call.assert_not_called()

    def test_successful_background_recipe_receipt_and_duplicate_verify_artifact(self):
        import zipfile
        root,path=jobs.paths(self.ledger,self.task,'artifact')
        now=dt.datetime.now(dt.timezone.utc)
        record=dict(request=dict(task=self.task,key='artifact',flutter_root=str(self.f.flutter),
                    android_sdk=str(self.f.sdk),native_authorized=True,max_seconds=1200,
                    dependency_policy='as-of',dependency_root=None),status='queued',queue_seconds=1800,
                    identity=identity(os.getpid()),queue_deadline=(now+dt.timedelta(seconds=30)).isoformat())
        jobs.save(self.ledger,self.task,path,record)
        def execute(argv,directory,timeout,guard,**kwargs):
            guard();apk=directory/'build/app/outputs/flutter-apk/app-debug.apk';apk.parent.mkdir(parents=True)
            with zipfile.ZipFile(apk,'w') as z:
                z.writestr('AndroidManifest.xml','fixture');z.writestr('classes.dex','fixture')
            return 0,'fixture successful',''
        result=jobs.run(self.ledger,self.task,'artifact',builder=AndroidBuild(self.ledger,execute))
        self.assertEqual(result['status'],'succeeded')
        with patch('onecrew.android_jobs.subprocess.Popen') as spawn:
            self.assertEqual(self.submit('artifact')['status'],'succeeded');spawn.assert_not_called()
        Path(result['apk']['path']).write_bytes(b'changed')
        with self.assertRaises((LedgerError,zipfile.BadZipFile)): self.submit('artifact')


if __name__=='__main__': unittest.main()
