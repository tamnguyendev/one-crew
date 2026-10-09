from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import test_workflow as fixtures
from onecrew.ledger import LedgerError, content_hash
from onecrew.specs import Project
from onecrew.workflow import Workflow, validate_profile


def response(action, argument='', path=None, content=None):
    return {'action': action, 'argument': argument,
            'artifact': {'summary': 'Bounded fixture operation', 'files': [] if path is None else [{'path':path,'content':content}], 'backlog':[]}}


class ToolsTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.WorkflowTests()
        self.f.setUp()
        (self.f.project/'settings.json').write_text('{"enabled":false}',encoding='utf-8')
        (self.f.project/'README.txt').write_text('Original instructions',encoding='utf-8')
        grant = {'schema_version':1,'permissions':['artifact.generate','tool.read','tool.check'],
                 'limits':{'max_calls':6,'max_seconds':300},'source':'Explicit fixture tool authority'}
        self.f.task = self.f.ledger.submit('SPEC-001',Project(self.f.project).find('SPEC-001').revision,'tool-fixture',grant)
        self.profile = dict(fixtures.profile(),tools={'allowed':['read_file','search','run_check'],'max_requests':4})
        self.prompts = []
        original = self.f.worker.run
        def run(attempt,prompt,schema,profile):
            self.prompts.append(prompt)
            return original(attempt,prompt,schema,profile)
        self.f.worker.run = run

    def tearDown(self):
        self.f.tearDown()

    def enable(self, responses):
        self.f.worker.responses = responses
        initial = self.f.workflow.enable(self.f.task['id'],self.f.task['revision'],self.profile)
        self.f.workflow.set_plan(self.f.task['id'],content_hash(initial),fixtures.plan())

    def final_responses(self):
        return [response('submit',path='settings.json',content='{"enabled":true,"workers":2}'),
                response('submit',path='README.txt',content='Start OneCrew.\n')]

    def test_read_search_candidate_check_then_submit_and_restart(self):
        self.enable([response('read_file','settings.json'),response('search','instructions'),
                     response('run_check','config','settings.json','{"enabled":false}'),*self.final_responses()])
        state = self.f.workflow.run(self.f.task['id'],steps=3)
        self.assertEqual(state['done'],[])
        self.assertFalse(state['tool_receipts'][-1]['result']['passed'])
        self.assertIn('Original instructions',state['tool_receipts'][1]['result']['matches'][0]['text'])
        self.assertEqual(self.f.workflow.store.context(state['snapshot'])['settings.json'],'{"enabled":false}')
        self.assertEqual(state['tool_requests'],3)
        self.f.workflow = Workflow(self.f.ledger,self.f.worker)
        state = self.f.workflow.run(self.f.task['id'])
        self.assertEqual(state['phase'],'completed')
        self.assertEqual(state['acceptance'],'pending')
        self.assertEqual(self.f.workflow.control.status(self.f.task['id'])['used_calls'],5)
        self.assertIn('RECENT TOOL RESULTS',self.prompts[-2])
        self.assertEqual((self.f.project/'settings.json').read_text(),'{"enabled":false}')
        self.assertEqual(self.f.workflow.outputs(self.f.task['id'])['tools']['used'],3)

    def test_explicit_permissions_and_profile_limits_required(self):
        for value in [dict(self.profile,parallel=True),dict(self.profile,tools={'allowed':['shell'],'max_requests':2}),
                      dict(self.profile,tools={'allowed':['read_file'],'max_requests':True})]:
            with self.assertRaises(LedgerError):
                validate_profile(value)
        grant = {'schema_version':1,'permissions':['artifact.generate'],'limits':{'max_calls':2,'max_seconds':60},'source':'No tool rights'}
        task = self.f.ledger.submit('SPEC-001',Project(self.f.project).find('SPEC-001').revision,'no-tools',grant)
        with self.assertRaisesRegex(LedgerError,'explicit tool'):
            self.f.workflow.enable(task['id'],task['revision'],self.profile)
        self.assertEqual(self.f.worker.calls,[])

    def test_escape_requests_block_before_tool_side_effect(self):
        bad = [response('read_file','../secret'),response('run_check','shell'),response('shell','whoami'),
               response('run_check','config','README.txt','Cannot write sibling'),
               response('search','x','settings.json','Cannot write while reading')]
        # Independent fixture per rejected protocol, retaining charged model attempts.
        for index,value in enumerate(bad):
            with self.subTest(value=value):
                if index:
                    self.tearDown(); self.setUp()
                self.enable([value])
                state = self.f.workflow.run(self.f.task['id'],steps=1)
                self.assertEqual(state['phase'],'blocked')
                self.assertEqual(state.get('tool_requests',0),0)
                self.assertEqual(self.f.workflow.control.status(self.f.task['id'])['used_calls'],1)
                self.assertEqual((self.f.project/'README.txt').read_text(),'Original instructions')

    def test_tool_cap_and_repeat_do_not_reset_on_resume(self):
        self.profile['tools']['max_requests'] = 1
        self.enable([response('read_file','settings.json'),response('search','instructions')])
        state = self.f.workflow.run(self.f.task['id'])
        self.assertEqual(state['phase'],'blocked')
        self.assertIn('budget exhausted',state['message'])
        self.assertEqual(state['tool_requests'],1)
        self.assertEqual(self.f.workflow.control.status(self.f.task['id'])['used_calls'],2)

    def test_identical_request_stops_without_reexecuting(self):
        self.enable([response('read_file','settings.json'),response('read_file','settings.json')])
        state = self.f.workflow.run(self.f.task['id'])
        self.assertEqual(state['phase'],'blocked')
        self.assertIn('no-progress',state['message'])
        self.assertEqual(state['tool_requests'],1)

    def test_lost_tool_receipt_recovers_without_another_model_call_or_cap_reset(self):
        self.enable([response('read_file','settings.json'),*self.final_responses()])
        original = self.f.workflow.persist
        def lose(task,seq,state,**kw):
            if state.get('tool_receipts'):
                raise OSError('disk failure at receipt checkpoint')
            return original(task,seq,state,**kw)
        with patch.object(self.f.workflow,'persist',side_effect=lose):
            state = self.f.workflow.run(self.f.task['id'],steps=1)
        self.assertEqual(state['phase'],'blocked')
        self.assertIsNotNone(state['tool_pending'])
        self.assertEqual(state['tool_requests'],1)
        with self.assertRaisesRegex(LedgerError,'Stop/reconcile'):
            self.f.workflow.switch(self.f.task['id'],content_hash(state),'codex','fixture')
        self.f.workflow.resume(self.f.task['id'])
        from onecrew.workflow import plan_revision
        _, resumed = self.f.workflow.state(self.f.task['id'])
        with self.assertRaisesRegex(LedgerError,'between work checkpoints'):
            self.f.workflow.reorder(self.f.task['id'],plan_revision(resumed),['config','doc'])
        state = self.f.workflow.run(self.f.task['id'],steps=1)
        self.assertEqual(len(self.f.worker.calls),1)
        self.assertEqual(state['tool_requests'],1)
        self.assertEqual(len(state['tool_receipts']),1)
        self.assertEqual(self.f.workflow.run(self.f.task['id'])['phase'],'completed')

    def test_cancel_during_check_never_publishes_tool_success(self):
        self.enable([response('run_check','config','settings.json','{"enabled":true,"workers":2}')])
        def cancel(*args,**kwargs):
            self.f.workflow.control.cancel(self.f.task['id'])
            return {'passed':True,'checks':[{'detail':'pass'}]}
        with patch('onecrew.workflow.verify',side_effect=cancel):
            state = self.f.workflow.run(self.f.task['id'])
        self.assertEqual(state.get('tool_receipts',[]),[])
        self.assertEqual(state['done'],[])
        self.assertEqual(self.f.workflow.control.status(self.f.task['id'])['status'],'cancelled')

    def test_result_truncation_is_explicit_and_amendment_cannot_expand_tools(self):
        (self.f.project/'README.txt').write_text('x'*7000,encoding='utf-8')
        self.enable([response('read_file','README.txt')])
        state = self.f.workflow.run(self.f.task['id'],steps=1)
        result = state['tool_receipts'][0]['result']
        self.assertTrue(result['truncated'])
        self.assertEqual(len(result['content']),6000)
        from onecrew.amendment import apply
        changed = deepcopy(self.profile)
        changed['tools']['max_requests'] = 5
        with self.assertRaisesRegex(LedgerError,'dedicated controls'):
            apply(self.f.workflow,self.f.task['id'],content_hash(state),self.f.task['spec_revision'],changed,['config'],'More tools')
