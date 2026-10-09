import json
import os
import shutil
import subprocess
import unittest
from unittest.mock import patch

import test_workflow as fixtures
from onecrew.integration import Integration
from onecrew.ledger import LedgerError


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.WorkflowTests()
        self.f.setUp()
        self.git('init')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'core.autocrlf', 'false')
        (self.f.project/'README.txt').write_bytes(b'base\n')
        self.git('add', '.')
        self.git('commit', '-m', 'base')
        (self.f.project/'README.txt').write_bytes(b'user staged\n')
        self.git('add', 'README.txt')
        (self.f.project/'README.txt').write_bytes(b'user unstaged\n')
        self.f.enable()
        self.state = self.f.workflow.run(self.f.task['id'])
        self.integration = Integration(self.f.workflow)

    def tearDown(self):
        self.assertTrue(self.f.base.is_relative_to(fixtures.TEMP.resolve()))
        def writable(function,path,error):
            os.chmod(path,0o700)
            function(path)
        shutil.rmtree(self.f.base,onexc=writable)

    def git(self,*args):
        return subprocess.check_output(['git','-C',str(self.f.project),*args],stderr=subprocess.DEVNULL)

    def branch(self,name='review'):
        return self.integration.branch(self.f.task['id'],self.state['snapshot'],name)

    def test_review_branch_verifies_actual_tree_and_preserves_checkout_index(self):
        hook=self.f.project/'.git/hooks/reference-transaction'
        hook.write_text('#!/bin/sh\nprintf touched > hook-ran\n',encoding='utf-8')
        os.chmod(hook,0o700)
        head=self.git('rev-parse','HEAD')
        index=(self.f.project/'.git/index').read_bytes()
        result=self.branch()
        self.assertEqual(result['receipt']['status'],'verified')
        commit=result['receipt']['result']['commit']
        self.assertEqual(json.loads(self.git('show',commit+':settings.json')),{'enabled':True,'workers':2})
        self.assertEqual(self.git('show',commit+'^:README.txt'),b'user unstaged\n')
        self.assertEqual(self.git('rev-parse','HEAD'),head)
        self.assertEqual((self.f.project/'.git/index').read_bytes(),index)
        self.assertEqual((self.f.project/'README.txt').read_bytes(),b'user unstaged\n')
        self.assertFalse((self.f.project/'hook-ran').exists())
        self.assertEqual(self.branch()['receipt'],result['receipt'])

    def test_source_changed_or_existing_branch_does_not_overwrite(self):
        (self.f.project/'README.txt').write_text('new user edit')
        with self.assertRaises(LedgerError): self.branch()
        self.assertIsNone(self.integration.git('show-ref','--verify','refs/heads/onecrew/review',allow_failure=True))
        (self.f.project/'README.txt').write_bytes(b'user unstaged\n')
        self.git('branch','onecrew/review')
        with self.assertRaises(LedgerError): self.branch()

    def test_gate_runs_on_git_candidate_and_failure_never_publishes_branch(self):
        with patch('onecrew.integration.verify',return_value={'passed':False}):
            with self.assertRaises(LedgerError): self.branch()
        self.assertIsNone(self.integration.git('show-ref','--verify','refs/heads/onecrew/review',allow_failure=True))

    def test_lost_ack_after_ref_update_is_reconciled_without_replay(self):
        original=self.integration.git
        calls=[]
        def lost(*args,**kwargs):
            value=original(*args,**kwargs)
            if args[0]=='update-ref':
                calls.append(args)
                raise OSError('ack lost after update')
            return value
        with patch.object(self.integration,'git',side_effect=lost):
            result=self.branch()
        self.assertEqual(result['receipt']['status'],'unknown')
        self.assertEqual(self.branch()['receipt']['status'],'verified')
        self.assertEqual(len(calls),1)


if __name__=='__main__':
    unittest.main()
