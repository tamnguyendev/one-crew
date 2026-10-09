from copy import deepcopy
import json
import os
import shutil
import subprocess
import unittest
from unittest.mock import patch

import test_workflow as fixtures
from onecrew.goal_budget import create
from onecrew.integration import Integration
from onecrew.ledger import Ledger, LedgerError, content_hash
from onecrew.specs import Project
from onecrew.vector import verify_vector
from onecrew.workflow import Workflow


COMPAT = '''import json
from pathlib import Path
left = json.loads(Path('/work/left/settings.json').read_text())
right = json.loads(Path('/work/right/settings.json').read_text())
assert left['workers'] == right['workers'], 'worker contract mismatch'
print('cross-repo compatibility passed')
'''


class VectorTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.WorkflowTests()
        self.f.setUp()
        other = self.f.base/'other-project'
        (other/'specs').mkdir(parents=True)
        (other/'specs/SPEC-001-duyet-spec.md').write_text(fixtures.SAMPLE,encoding='utf-8')
        ledger = Ledger(other,self.f.ledger.state_root)
        spec=Project(other).find('SPEC-001')
        Project(other).decide(spec,spec.revision,'approved','fixture','Test operator approval')
        task = ledger.submit('SPEC-001',Project(other).find('SPEC-001').revision,'other',
            {'schema_version':1,'permissions':['artifact.generate'],'limits':{'max_calls':6,'max_seconds':300},'source':'fixture'})
        worker = fixtures.FixtureWorker(ledger,[fixtures.plan(),fixtures.artifact('settings.json','{"enabled":true,"workers":2}'),
                                               fixtures.artifact('README.txt','Start OneCrew.\n')])
        right_workers = getattr(self,'right_workers',2)
        worker.responses[1] = fixtures.artifact('settings.json',json.dumps({'enabled':True,'workers':right_workers}))
        self.items = [{'workflow':self.f.workflow,'task':self.f.task,'alias':'left'},
                      {'workflow':Workflow(ledger,worker),'task':task,'alias':'right'}]
        for item in self.items:
            w = item['workflow']
            (w.ledger.project/'compat.py').write_text(COMPAT,encoding='utf-8')
            def git(*args):
                subprocess.check_call(['git','-C',str(w.ledger.project),*args],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            git('init')
            git('config','user.name','Fixture')
            git('config','user.email','fixture@example.invalid')
            git('config','core.autocrlf','false')
            git('add','.')
            git('commit','-m','base')
            p = fixtures.profile()
            p['context'].append('compat.py')
            if item['alias'] == 'right':
                p['checks'][0]['expected']['workers'] = right_workers
            w.enable(item['task']['id'],item['task']['revision'],p)
        proposal = {'members':[{'task_id':item['task']['id'],'project':str(item['workflow'].ledger.project),
                               'workflow_revision':content_hash(item['workflow'].state(item['task']['id'])[1])} for item in self.items],
                    'max_calls':6,'deadline':self.f.task['deadline'],'reason':'Verify matching contracts across two repos.'}
        self.group = create(self.f.workflow,self.f.task['id'],proposal['members'][0]['workflow_revision'],proposal)
        members = []
        for item in self.items:
            w, task = item['workflow'],item['task']
            done = w.run(task['id'])
            result = Integration(w).branch(task['id'],done['snapshot'],'vector')
            delivery = result['receipt']['result']
            members.append({'task_id':task['id'],'project':str(w.ledger.project),'alias':item['alias'],
                            'snapshot':done['snapshot'],'ref':delivery['ref'],'commit':delivery['commit']})
        self.recipe = {'members':members,'check':{'id':'compat','acceptance':['AC-VECTOR'],'kind':'container_test',
            'path':'left/compat.py','expected':{'image':'sha256:'+'a'*64,
                'argv':['/usr/local/bin/python','/work/left/compat.py'],'timeout_seconds':30}}}

    def tearDown(self):
        self.assertTrue(self.f.base.is_relative_to(fixtures.TEMP.resolve()))
        def writable(function,path,error):
            os.chmod(path,0o700)
            function(path)
        shutil.rmtree(self.f.base,onexc=writable)

    def vector(self,recipe=None):
        return verify_vector(self.f.workflow,self.f.task['id'],self.group['revision'],recipe or self.recipe)

    def test_vector_binds_both_git_commits_and_cached_receipt_does_not_repeat_gate(self):
        with patch('onecrew.vector.verify',return_value={'passed':True,'checks':[]}) as gate:
            result = self.vector()
            self.assertEqual(self.vector(),result)
        self.assertEqual(gate.call_count,1)
        self.assertEqual(result['status'],'passed')
        self.assertEqual(len(result['commit_vector']),2)
        source = self.f.workflow.store.context(result['snapshot'])
        self.assertEqual(json.loads(source['left/settings.json']),json.loads(source['right/settings.json']))
        self.assertEqual(result['acceptance'],'pending')
        self.assertFalse(result['refs_updated'])
        self.assertFalse(result['atomic_cross_repo_commit'])
        self.assertEqual(self.f.workflow.control.status(self.f.task['id'])['budget']['goal']['used_calls'],6)

    def test_compatibility_failure_retained_even_when_individual_members_pass(self):
        with patch('onecrew.vector.verify',return_value={'passed':False,'checks':[{'id':'compat','passed':False}]}):
            failed = self.vector()
        self.assertEqual(failed['status'],'failed')
        self.assertTrue(all(item['workflow'].state(item['task']['id'])[1]['verification']=='passed' for item in self.items))
        with self.f.ledger.transaction() as conn:
            saved = json.loads(conn.execute("SELECT payload FROM events WHERE kind='integration.vector'").fetchone()[0])
        self.assertEqual(saved,failed)

    def test_ref_move_during_gate_never_emits_pass_receipt(self):
        def moved(*args,**kwargs):
            item = self.recipe['members'][1]
            integration = Integration(self.items[1]['workflow'])
            tree = integration.git('rev-parse',item['commit']+'^{tree}').decode().strip()
            commit = integration.git('commit-tree',tree,'-p',item['commit'],'-m','concurrent ref move').decode().strip()
            integration.git('update-ref',item['ref'],commit,item['commit'])
            return {'passed':True,'checks':[]}
        with patch('onecrew.vector.verify',side_effect=moved):
            with self.assertRaisesRegex(LedgerError,'stale'):
                self.vector()
        with self.f.ledger.transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM events WHERE kind='integration.vector'").fetchone()[0],0)

    def test_requires_complete_group_current_delivery_and_sealed_readonly_test(self):
        for change in ('snapshot','commit','owned-test','missing-member'):
            recipe = deepcopy(self.recipe)
            if change == 'snapshot': recipe['members'][0]['snapshot'] = '0'*64
            if change == 'commit': recipe['members'][0]['commit'] = '0'*40
            if change == 'owned-test': recipe['check']['path'] = 'left/README.txt'
            if change == 'missing-member': recipe['members'].pop()
            with self.subTest(change=change), self.assertRaises(LedgerError):
                self.vector(recipe)


if __name__ == '__main__':
    unittest.main()
