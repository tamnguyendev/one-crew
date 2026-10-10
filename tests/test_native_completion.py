import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tests import test_native_change as fixtures
from onecrew import native_completion as completion
from onecrew.ledger import LedgerError
from onecrew.native_change import validate


class CensusTests(unittest.TestCase):
    def test_project_wide_hits_boundaries_and_generated_exclusion(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name,text in {'base/a.dart':'cloudAuthFailureMessage(x);', 'other/b.dart':'cloudAuthFailureMessage(result);',
                              'other/c.dart':'cloudAuthFailureMessageSuffix(x);', 'build/old.dart':'cloudAuthFailureMessage(x);'}.items():
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
            value=completion.census(root,'cloudAuthFailureMessage')
            self.assertEqual(set(value['hits']),{'base/a.dart','other/b.dart'})
            self.assertEqual(value['dart_files'],3)
            self.assertIn('build',value['excluded'])


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.NativeChangeTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.runtime,self.task=self.fixture.run,self.fixture.task
        self.recipe=dict(self.fixture.recipe,caller_symbol='add',apk_build={
            'package':'app','base_package_name':'app','android_sdk':str(self.fixture.f.root/'android-sdk'),
            'max_seconds':30,'native_authorized':True})
        self.root=self.fixture.f.root
        self.seq,self.state=self.runtime.state(self.task)
        self.state['native_change']['caller_summary']=completion.collect(self.runtime,self.state,self.recipe)
        self.state['native_change']['stage']='build'
        self.artifact=self.root/'app/build/app/outputs/flutter-apk/app-debug.apk'
        self.real_task=self.runtime.ledger.task
        self.dir=tempfile.TemporaryDirectory();self.addCleanup(self.dir.cleanup)
        # Redirect the runtime artifact directory to a disposable test install.
        self.module_patch=patch.object(completion,'__file__',str(Path(self.dir.name)/'onecrew/native_completion.py'))
        self.module_patch.start();self.addCleanup(self.module_patch.stop)

    def grant(self,*args,**kwargs):
        task=self.real_task(*args,**kwargs)
        task['handoff']['grant']['permissions'].append('android.build')
        return task

    def apk(self):
        self.artifact.parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(self.artifact,'w') as output:
            output.writestr('AndroidManifest.xml','test');output.writestr('classes.dex','test')

    def run_build(self,command):
        with patch.object(self.runtime.ledger,'task',side_effect=self.grant),patch.object(completion,'command',side_effect=command):
            self.seq=completion.build(self.runtime,self.task,self.seq,self.state,self.recipe)

    def test_missing_authority_cannot_build(self):
        with patch.object(completion,'command') as command,self.assertRaises(LedgerError):
            completion.build(self.runtime,self.task,self.seq,self.state,self.recipe)
        command.assert_not_called()

    def test_fresh_valid_apk_has_archived_receipt_and_no_implicit_replay(self):
        def command(*args):
            self.assertEqual(self.runtime.state(self.task)[1]['native_change']['apk_build']['status'],'running')
            self.apk();return 0,'built',''
        self.run_build(command)
        receipt=self.state['native_change']['apk_build']
        self.assertEqual(receipt['status'],'passed')
        self.assertTrue(Path(receipt['artifact']['path']).exists())
        self.assertIn('--no-pub',receipt['argv'])
        with self.assertRaises(LedgerError):self.run_build(command)

    def test_stale_apk_cannot_turn_empty_success_into_completion(self):
        self.apk()
        self.run_build(lambda *args:(0,'no build output',''))
        self.assertEqual(self.state['phase'],'blocked')
        self.assertNotIn('artifact',self.state['native_change']['apk_build'])

    def test_failed_build_and_source_drift_preserve_blocked_evidence(self):
        def command(*args):
            self.apk();(self.root/'app/lib/main.dart').write_text('concurrent change');return 0,'built',''
        self.run_build(command)
        self.assertEqual(self.state['phase'],'blocked')
        self.assertIn('changed',self.state['message'])

    def test_build_exit_failure_never_passes(self):
        self.run_build(lambda *args:(1,'compiler error',''))
        self.assertEqual(self.state['native_change']['apk_build']['status'],'blocked')
        self.assertEqual(self.state['native_change']['apk_build']['exit_code'],1)

    def test_wrong_base_mapping_rejected_before_command(self):
        config=self.root/'app/.dart_tool/package_config.json'
        config.write_text(json.dumps({'packages':[{'name':'app','rootUri':'../../wrong/'}]}))
        with patch.object(completion,'command') as command,self.assertRaises(LedgerError):self.run_build(command)

    def test_census_detects_new_caller_before_apply(self):
        (self.root/'outside.dart').write_text('add(1,2);')
        with self.assertRaises(LedgerError):completion.check_census(self.runtime,self.state,self.recipe)
        with self.assertRaises(LedgerError):completion.collect(self.runtime,self.state,self.recipe)

    def test_invalid_recipe_never_grants_build(self):
        for changed in ({'native_authorized':False},{'package':'../escape'},{'max_seconds':0}):
            recipe=dict(self.recipe,apk_build=dict(self.recipe['apk_build'],**changed))
            with self.assertRaises(LedgerError):validate(recipe)

    def test_pipeline_does_not_complete_before_apk_and_reports_artifact(self):
        from onecrew.native_change import advance, install_candidate
        install_candidate(self.runtime,self.state,self.fixture.candidate(),self.recipe)
        native=self.state['native_change']
        native.update(stage='apply',review_accepted=True,checks=[{'passed':True,'evidence':{'snapshot':self.state['snapshot']}}])
        self.seq=self.runtime.persist(self.task,self.seq,self.state)
        profile={'native_change':self.recipe}
        advance(self.runtime,self.task,self.seq,self.state,profile)
        self.seq,self.state=self.runtime.state(self.task)
        self.assertEqual(self.state['native_change']['stage'],'build')
        self.assertNotEqual(self.state['phase'],'completed')
        self.assertIn('a+b',(self.root/'app/lib/main.dart').read_text())
        def command(*args):self.apk();return 0,'built',''
        with patch.object(self.runtime.ledger,'task',side_effect=self.grant),patch.object(completion,'command',side_effect=command):
            result=advance(self.runtime,self.task,self.seq,self.state,profile)
        self.assertEqual(result['phase'],'completed')
        self.assertEqual(result['outputs'][-1]['artifact']['sha256'],result['native_change']['apk_build']['artifact']['sha256'])
