import json
import subprocess
import sys
import unittest
from unittest.mock import patch
from tests import test_owned as fixtures
from onecrew.mcp_entry import Server
from onecrew.ledger import LedgerError


class EntryMCPTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.OwnedTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.run,self.task,self.worker=self.f.runtime([])

    def test_read_only_default_cannot_submit_cancel_or_reply(self):
        server=Server(self.f.ledger)
        self.assertEqual({t['name'] for t in server.tools()},{'status','outputs','inbox'})
        for name in ('submit','cancel','reply'):
            with self.assertRaises(LedgerError): server.call(name,{})
        self.assertEqual(server.call('status',{'task':self.task})['task']['id'],self.task)
        self.assertEqual(self.worker.calls,[])

    def test_cross_entry_revision_checked_reply_not_authority_upgrade(self):
        args=dict(question='Version?',reason='Required',options=[{'id':'a','label':'A'},{'id':'b','label':'B'}],recommendation='a')
        state=self.run.state(self.task)[1];profile=self.run.control.status(self.task)['configuration']['profile']
        req=self.run._tool(self.task,state,'ask',args,profile)
        server=Server(self.f.ledger,True,'claude-entry')
        q=server.call('inbox',{'task':self.task})[0]
        with self.assertRaises(LedgerError): server.call('reply',dict(request=q['id'],revision='stale',choice='a',reference='user message'))
        receipt=server.call('reply',dict(request=q['id'],revision=q['revision'],choice='a',reference='actual user message'))
        self.assertFalse(receipt['action_applied']);self.assertEqual(receipt['provenance']['source'],'claude-entry')
        self.assertEqual(self.worker.calls,[])

    def test_schema_rejects_extra_scope_and_boolean_limits(self):
        server=Server(self.f.ledger,True)
        with self.assertRaises(LedgerError): server.call('status',{'task':self.task,'project':'elsewhere'})
        with self.assertRaises(LedgerError): server.call('submit',dict(goal='test',request_key='x',provider='codex',model='x',max_calls=True,max_seconds=30))

    def test_failed_launch_keeps_task_id_and_replay_does_not_duplicate(self):
        from onecrew.owned import Owned
        server=Server(self.f.ledger,True)
        args=dict(goal='Inspect only',request_key='launch-failure',provider='codex',model='fixture',max_calls=4,max_seconds=60)
        with patch.object(Owned,'enable'),patch('onecrew.runner.start',side_effect=OSError('launch interrupted')):
            first=server.call('submit',args);second=server.call('submit',args)
        self.assertEqual(first['id'],second['id'])
        self.assertEqual(first['runner']['status'],'unconfirmed')
        self.assertEqual(self.f.ledger.task(first['id'])['id'],first['id'])

    def test_submit_omitted_budget_uses_same_policy_as_cli(self):
        from onecrew.owned import Owned
        server=Server(self.f.ledger,True)
        with patch.object(Owned,'enable'),patch('onecrew.runner.start',return_value={'status':'fixture'}):
            result=server.call('submit',dict(goal='Inspect source',request_key='default-budget'))
        self.assertEqual(result['budget']['limits'],{'max_calls':100,'max_seconds':7200})

    def test_stdio_protocol_exits_on_eof_and_never_launches_worker(self):
        messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05'}},
            {'jsonrpc':'2.0','method':'notifications/initialized'},
            {'jsonrpc':'2.0','id':2,'method':'tools/list'},
            {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'status','arguments':{'task':self.task}}}]
        result=subprocess.run([sys.executable,'-X','utf8','-m','onecrew.mcp_entry','--project',str(self.f.root),
            '--state-root',str(self.f.ledger.state_root)],input='\n'.join(map(json.dumps,messages))+'\n',capture_output=True,text=True,encoding='utf-8',timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        rows=[json.loads(x) for x in result.stdout.splitlines()]
        self.assertEqual([x['id'] for x in rows],[1,2,3]);self.assertFalse(rows[-1]['result']['isError'])

if __name__=='__main__': unittest.main()
