import io
import tarfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import tests.test_owned as fixtures
from onecrew.android_build import AndroidBuild, dependency_paths, extract_archive
from onecrew.git_history import History
from onecrew.ledger import LedgerError


class AndroidTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.OwnedTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        home=patch('onecrew.android_build.Path.home',return_value=self.f.root.parent/'home')
        home.start();self.addCleanup(home.stop)
        self.f.setup_git()
        (self.f.root/'pubspec.yaml').write_text('name: example\n')
        (self.f.root/'android').mkdir();(self.f.root/'android/build.gradle').write_text('// fixture\n')
        self.f.git('add','pubspec.yaml','android');self.f.git('commit','-m','Android baseline')
        self.base=self.f.git('rev-parse','HEAD').decode().strip()
        (self.f.root/'screen.dart').write_text('// new UI\n')
        self.f.git('add','screen.dart');self.f.git('commit','-m','UI')
        change=self.f.git('rev-parse','HEAD').decode().strip()
        self.run,self.task,_=self.f.runtime([],mode='branch',branch='onecrew/pre-ui')
        profile=self.run.control.status(self.task)['configuration']['profile']
        receipt=History(self.run,self.task,profile,'').branch_before(change,change,'baseline')
        seq,state=self.run.state(self.task);state.update(phase='completed',branches=[receipt]);self.run.persist(self.task,seq,state)
        self.sdk=self.f.root.parent/'sdk';self.sdk.mkdir()
        self.flutter=self.f.root.parent/'flutter'
        for name in ('bin/cache/dart-sdk/bin/dart.exe','bin/cache/flutter_tools.snapshot','packages/flutter_tools/.dart_tool/package_config.json'):
            path=self.flutter/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture')

    def build(self, callback, key='build'):
        return AndroidBuild(self.f.ledger,callback).build(self.task,key,self.flutter,self.sdk,native_authorized=True)

    def test_verified_commit_export_success_and_duplicate_does_not_execute(self):
        before=(self.f.root/'.git/index').read_bytes()
        def execute(argv,directory,timeout,guard,**kwargs):
            self.assertNotEqual(directory,self.f.root)
            self.assertFalse((directory/'screen.dart').exists())
            self.assertEqual(argv[-3:],['build','apk','--debug']);guard()
            path=directory/'build/app/outputs/flutter-apk/app-debug.apk';path.parent.mkdir(parents=True)
            with zipfile.ZipFile(path,'w') as archive:
                archive.writestr('AndroidManifest.xml','manifest');archive.writestr('classes.dex','dex')
            return 0,'ok',''
        call=Mock(side_effect=execute)
        result=self.build(call);again=self.build(call)
        self.assertEqual(result['status'],'succeeded');self.assertEqual(result['apk'],again['apk'])
        self.assertEqual(result['repositories'][0]['commit'],self.base)
        self.assertEqual(call.call_count,1);self.assertEqual(before,(self.f.root/'.git/index').read_bytes())
        self.assertFalse((self.f.root/'android/local.properties').exists())
        Path(result['apk']['path']).write_bytes(b'broken')
        with self.assertRaises((LedgerError,zipfile.BadZipFile)): self.build(call)

    def test_build_failure_and_missing_artifact_never_pass(self):
        failed=self.build(lambda *a,**k:(1,'dependency error',''),'failed')
        self.assertEqual(failed['status'],'blocked');self.assertEqual(failed['exit_code'],1)
        missing=self.build(lambda *a,**k:(0,'success claimed',''),'missing')
        self.assertEqual(missing['status'],'blocked');self.assertIsNone(missing['apk'])
        self.assertTrue((Path(failed['logs'])/'stdout.log').exists())

    def test_missing_authority_or_moved_ref_prevents_native_execution(self):
        call=Mock()
        with self.assertRaises(LedgerError): AndroidBuild(self.f.ledger,call).build(self.task,'denied',self.flutter,self.sdk)
        self.f.git('update-ref','refs/heads/onecrew/pre-ui','HEAD')
        with self.assertRaises(LedgerError): self.build(call)
        call.assert_not_called()

    def test_export_rejects_traversal_and_links(self):
        for name,kind in (('../escape',tarfile.REGTYPE),('symlink',tarfile.SYMTYPE)):
            data=io.BytesIO()
            with tarfile.open(fileobj=data,mode='w') as archive:
                member=tarfile.TarInfo(name);member.type=kind;member.linkname='../outside';archive.addfile(member)
            with self.assertRaises(LedgerError): extract_archive(data.getvalue(),self.f.root/'export')

    def test_dependency_path_policy(self):
        self.assertEqual(dependency_paths('dependencies:\n  base:\n    path: ../base # shared\n'),['../base'])
        for text in ('dependencies:\n  base: {path: ../base}', 'dependencies:\n  base:\n    path: C:\\base'):
            with self.assertRaises(LedgerError): dependency_paths(text)

    def test_dependency_pin_and_escape_boundary(self):
        builder=AndroidBuild(self.f.ledger)
        from onecrew.integration import Integration
        from types import SimpleNamespace
        dep=self.f.root.parent/'base';dep.mkdir()
        git=Integration(SimpleNamespace(ledger=SimpleNamespace(project=dep,state_root=self.f.ledger.state_root),store=None)).git
        git('init');(dep/'pubspec.yaml').write_text('name: base\n');git('add','pubspec.yaml');git('commit','-m','base')
        sha=git('rev-parse','HEAD').decode().strip()
        (self.f.root/'pubspec.yaml').write_text('name: example\ndependencies:\n  base:\n    path: ../base\n')
        self.f.git('add','pubspec.yaml');self.f.git('commit','-m','Add path dependency')
        commit=self.f.git('rev-parse','HEAD').decode().strip()
        receipt={'repositories':[]}
        directory=builder.prepare(self.f.root.parent/'deps',self.f.root,commit,'as-of',lambda:None,receipt)
        self.assertEqual(receipt['repositories'][1]['commit'],sha)
        self.assertTrue((directory.parent/'base/pubspec.yaml').exists())
        (self.f.root/'pubspec.yaml').write_text('name: example\ndependencies:\n  base:\n    path: ../../outside\n')
        self.f.git('add','pubspec.yaml');self.f.git('commit','-m','Outside dependency')
        commit=self.f.git('rev-parse','HEAD').decode().strip()
        with self.assertRaises(LedgerError):
            builder.prepare(self.f.root.parent/'escape',self.f.root,commit,'as-of',lambda:None,{'repositories':[]})

    def test_unpinned_git_uses_matching_historical_local_repo_and_keeps_original(self):
        builder=AndroidBuild(self.f.ledger)
        from onecrew.integration import Integration
        from types import SimpleNamespace
        dep=self.f.root.parent/'shared';dep.mkdir()
        git=Integration(SimpleNamespace(ledger=SimpleNamespace(project=dep,state_root=self.f.ledger.state_root),store=None)).git
        git('init');git('remote','add','origin','git@github.com:example/shared.git')
        (dep/'pubspec.yaml').write_text('name: shared\nversion: 1.0.0\n');git('add','pubspec.yaml');git('commit','-m','shared')
        old=git('rev-parse','HEAD').decode().strip()
        (dep/'README.md').write_text('new compatible revision');git('add','README.md');git('commit','-m','new revision')
        sha=git('rev-parse','HEAD').decode().strip()
        (self.f.root/'pubspec.yaml').write_text('name: example\ndependencies:\n  shared:\n    git:\n      url: https://github.com/example/shared.git\n      ref: main\n    version: 1.0.0\ndependency_overrides:\n  printing: ^5.14.0\n')
        self.f.git('add','pubspec.yaml');self.f.git('commit','-m','dependency')
        commit=self.f.git('rev-parse','HEAD').decode().strip();receipt={'repositories':[]}
        export=builder.prepare(self.f.root.parent/'gitdeps',self.f.root,commit,'as-of',lambda:None,receipt)
        (export/'pubspec.lock').write_text('packages:\n  shared:\n    description:\n      url: https://github.com/example/shared.git\n      resolved-ref: '+old+'\n    source: git\n')
        builder.pin_git_dependencies(export,self.f.root,commit,self.f.root.parent,lambda:None,receipt)
        self.assertEqual(receipt['git_dependency_pins']['shared']['ref'],sha)
        self.assertIn('printing: ^5.14.0',(export/'pubspec_overrides.yaml').read_text())
        self.assertFalse((self.f.root/'pubspec_overrides.yaml').exists())
        (export/'pubspec.lock').unlink()
        with self.assertRaises(LedgerError):
            builder.pin_git_dependencies(export,self.f.root,commit,None,lambda:None,{})


if __name__=='__main__': unittest.main()
