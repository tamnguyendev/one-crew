import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from onecrew.workspace_cache import restore
from onecrew.sandbox_gate import GateUnavailable


class WorkspaceCacheTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.package=self.root/'app';(self.package/'.dart_tool').mkdir(parents=True)
        self.cache=self.root/'cache';self.dep=self.cache/'hosted/pub.dev/example-1.2.3'
        (self.package/'.dart_tool/package_config.json').write_text(json.dumps({'packages':[{'name':'example','rootUri':self.dep.as_uri()+'/'}]}))
        self.lock=self.package/'pubspec.lock'
        self.lock.write_text('packages:\n  example:\n    description:\n      sha256: "'+'a'*64+'"\n      url: "https://pub.dev"\n    source: hosted\n    version: "1.2.3"\nsdks:\n  dart: ">=3"\n')
        self.runtime=SimpleNamespace(ledger=SimpleNamespace(project=self.root,state_root=self.root/'state'),control=None)
        self.state={'native_change':{}};self.recipe={'package':'app','restore_cache':True,'flutter_root':str(self.root/'flutter')}

    def materialize(self,digest):
        self.dep.mkdir(parents=True,exist_ok=True);(self.dep/'pubspec.yaml').write_text('name: example')
        hashfile=self.cache/'hosted-hashes/pub.dev/example-1.2.3.sha256'
        hashfile.parent.mkdir(parents=True,exist_ok=True);hashfile.write_text(digest)

    def test_restores_exact_version_and_hash_without_resolving(self):
        def run(argv,*args):
            self.assertEqual(argv[-5:],['cache','add','example','--version','1.2.3'])
            self.materialize('a'*64);return 0,'',''
        with patch('onecrew.workspace_cache.task_guard',return_value=lambda:None),patch('onecrew.workspace_cache.command',side_effect=run) as command:
            result=restore(self.runtime,'TASK',self.state,self.recipe)
            self.assertEqual(result[0]['version'],'1.2.3');self.assertEqual(command.call_count,1)
            self.assertEqual(restore(self.runtime,'TASK',self.state,self.recipe),[])

    def test_mismatch_stays_blocked_on_retry_instead_of_trusting_created_directory(self):
        def run(*args):self.materialize('b'*64);return 0,'',''
        with patch('onecrew.workspace_cache.task_guard',return_value=lambda:None),patch('onecrew.workspace_cache.command',side_effect=run):
            with self.assertRaisesRegex(GateUnavailable,'failed'):restore(self.runtime,'TASK',self.state,self.recipe)
            with self.assertRaisesRegex(GateUnavailable,'hash'):restore(self.runtime,'TASK',self.state,self.recipe)

    def test_unauthorized_private_and_unlocked_paths_do_not_download(self):
        with patch('onecrew.workspace_cache.command') as command:
            with self.assertRaises(GateUnavailable):restore(self.runtime,'TASK',self.state,dict(self.recipe,restore_cache=False))
            self.lock.write_text(self.lock.read_text().replace('https://pub.dev','https://private.invalid'))
            with self.assertRaisesRegex(GateUnavailable,'explicit recovery'):restore(self.runtime,'TASK',self.state,self.recipe)
            command.assert_not_called()
