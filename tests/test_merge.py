import json
import os
import shutil
import subprocess
import unittest
from unittest.mock import patch

import test_workflow as fixtures
from onecrew.integration import Integration
from onecrew.ledger import LedgerError
from onecrew.merge import merge
from onecrew.workflow import verify


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.WorkflowTests()
        self.f.setUp()
        self.git('init')
        self.git('config','user.name','Fixture')
        self.git('config','user.email','fixture@example.invalid')
        self.git('config','core.autocrlf','false')
        (self.f.project/'README.txt').write_bytes(b'base\n')
        (self.f.project/'contract.txt').write_bytes(b'v1')
        self.git('add','.')
        self.git('commit','-m','base')
        (self.f.project/'README.txt').write_bytes(b'user staged\n')
        self.git('add','README.txt')
        (self.f.project/'README.txt').write_bytes(b'user unstaged\n')
        profile = fixtures.profile()
        profile['context'].append('contract.txt')
        profile['checks'].append({'id':'contract','acceptance':['AC-DOC'],'kind':'text_equal','path':'contract.txt','expected':'v1'})
        self.f.workflow.enable(self.f.task['id'],self.f.task['revision'],profile)
        self.state = self.f.workflow.run(self.f.task['id'])
        self.integration = Integration(self.f.workflow)
        self.target = 'refs/heads/integration-target'
        self.head = self.git('rev-parse','HEAD').decode().strip()
        self.expected = self.target_commit({'outside-scope.txt':b'keep target work'})
        self.integration.git('update-ref',self.target,self.expected)

    def tearDown(self):
        self.assertTrue(self.f.base.is_relative_to(fixtures.TEMP.resolve()))
        def writable(function,path,error):
            os.chmod(path,0o700)
            function(path)
        shutil.rmtree(self.f.base,onexc=writable)

    def git(self,*args):
        return subprocess.check_output(['git','-C',str(self.f.project),*args],stderr=subprocess.DEVNULL)

    def target_commit(self,changes,parent=None):
        index = self.f.base/'target-index'
        self.integration.git('read-tree',parent or self.head,index=index)
        for path,data in changes.items():
            blob = self.integration.git('hash-object','-w','--stdin',stdin=data).decode().strip()
            self.integration.git('update-index','--add','--cacheinfo','100644',blob,path,index=index)
        tree = self.integration.git('write-tree',index=index).decode().strip()
        return self.integration.git('commit-tree',tree,'-p',parent or self.head,'-m','target fixture').decode().strip()

    def run_merge(self):
        return merge(self.f.workflow,self.f.task['id'],self.state['snapshot'],self.target,self.expected)

    def test_verified_merge_preserves_target_changes_and_user_checkout_index(self):
        index = (self.f.project/'.git/index').read_bytes()
        result = self.run_merge()
        self.assertEqual(result['receipt']['status'],'verified')
        commit = result['receipt']['result']['commit']
        self.assertEqual(self.git('show',commit+':outside-scope.txt'),b'keep target work')
        self.assertEqual(json.loads(self.git('show',commit+':settings.json')),{'enabled':True,'workers':2})
        self.assertEqual(self.git('rev-parse',commit+'^1').decode().strip(),self.expected)
        self.assertEqual(self.git('rev-parse','HEAD').decode().strip(),self.head)
        self.assertEqual((self.f.project/'.git/index').read_bytes(),index)
        self.assertEqual((self.f.project/'README.txt').read_bytes(),b'user unstaged\n')
        self.assertEqual(self.run_merge()['receipt'],result['receipt'])

    def test_whole_file_conflict_records_paths_without_modifying_target(self):
        self.expected = self.target_commit({'README.txt':b'different target instructions'})
        self.integration.git('update-ref',self.target,self.expected)
        with self.assertRaisesRegex(LedgerError,'Both sides changed'):
            self.run_merge()
        self.assertEqual(self.git('rev-parse',self.target).decode().strip(),self.expected)
        with self.f.ledger.transaction() as conn:
            evidence = json.loads(conn.execute("SELECT payload FROM events WHERE kind='integration.conflict'").fetchone()[0])
        self.assertEqual(evidence['paths'],['README.txt'])

    def test_merged_candidate_fails_real_gate_even_when_source_passed(self):
        self.expected = self.target_commit({'contract.txt':b'v2'})
        self.integration.git('update-ref',self.target,self.expected)
        self.assertEqual(self.state['verification'],'passed')
        with self.assertRaisesRegex(LedgerError,'Merged Git candidate failed'):
            self.run_merge()
        with self.f.ledger.transaction() as conn:
            evidence = json.loads(conn.execute("SELECT payload FROM events WHERE kind='integration.failed'").fetchone()[0])
        self.assertEqual(self.f.workflow.store.context(evidence['gate_snapshot'])['contract.txt'],'v2')
        self.assertFalse(evidence['checks']['passed'])
        outputs = self.f.workflow.outputs(self.f.task['id'])
        self.assertEqual(outputs['integration_issues'][0]['kind'],'integration.failed')
        self.assertEqual(outputs['deliveries'],[])
        self.assertEqual(self.git('rev-parse',self.target).decode().strip(),self.expected)

    def test_target_race_after_gate_rejects_update_and_checked_out_target_rejected(self):
        moved = self.target_commit({'outside-scope.txt':b'new target work'},self.expected)
        def race(*args,**kwargs):
            value = verify(*args,**kwargs)
            self.integration.git('update-ref',self.target,moved,self.expected)
            return value
        with patch('onecrew.merge.verify',side_effect=race):
            with self.assertRaisesRegex(LedgerError,'Target base changed'):
                self.run_merge()
        self.assertEqual(self.git('rev-parse',self.target).decode().strip(),moved)
        current = self.git('symbolic-ref','HEAD').decode().strip()
        with self.assertRaisesRegex(LedgerError,'checked out'):
            merge(self.f.workflow,self.f.task['id'],self.state['snapshot'],current,self.head)

    def test_lost_ack_reconciles_exact_commit_without_reapplying(self):
        original = Integration.git
        updates = []
        def lost(instance,*args,**kwargs):
            value = original(instance,*args,**kwargs)
            if args[0] == 'update-ref':
                updates.append(args)
                raise OSError('lost acknowledgment')
            return value
        with patch.object(Integration,'git',lost):
            first = self.run_merge()
        self.assertEqual(first['receipt']['status'],'unknown')
        self.assertEqual(self.run_merge()['receipt']['status'],'verified')
        self.assertEqual(len(updates),1)

    def test_cancelled_candidate_cannot_publish_branch_or_merge(self):
        self.f.workflow.control.cancel(self.f.task['id'])
        with self.assertRaises(LedgerError):
            self.run_merge()
        with self.assertRaisesRegex(LedgerError,'Cancelled'):
            self.integration.branch(self.f.task['id'],self.state['snapshot'],'must-not-publish')

    def test_source_edit_after_action_authorization_prevents_ref_update(self):
        original = self.f.workflow.control.authorize_action
        def edit_after_authorize(*args):
            original(*args)
            (self.f.project/'README.txt').write_bytes(b'new user edit')
        with patch.object(self.f.workflow.control,'authorize_action',side_effect=edit_after_authorize):
            result = self.run_merge()
        self.assertEqual(result['receipt']['status'],'unknown')
        self.assertEqual(self.git('rev-parse',self.target).decode().strip(),self.expected)
        self.assertEqual((self.f.project/'README.txt').read_bytes(),b'new user edit')


if __name__ == '__main__':
    unittest.main()
