import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tests.test_routing import candidate,NOW
from tests.test_jev import Client,KEY
from onecrew.ledger import Ledger,LedgerError
from onecrew.owned_intake import submit
from onecrew.routing import choose
from onecrew.model_preferences import save,read
from onecrew.model_advisor import advise
from onecrew.jev import JevError


class ModelAdvisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'project';self.root.mkdir()
        self.ledger=Ledger(self.root,Path(self.tmp.name)/'state')
        self.work={'complexity':1,'risk':'low','allowed_providers':['claude','codex']}
        self.models=[candidate('cheap',1,1),candidate('claude-mid',2,4,'claude')]

    def response(self,choice='option1',confidence=.9):
        return {'model':'jev-1.13.0','answers':{'routing':{'type':'choice','choice':choice,'confidence':confidence,
            'probabilities':{k:confidence if k==choice else (1-confidence)/2 for k in ('option0','option1','abstain')}}},
            'usage':{'input_tokens':90,'output_tokens':8}}

    def test_preference_persists_for_new_jobs_and_replay_keeps_old_choice(self):
        before=submit(self.ledger,'Inspect source','old')
        save(self.ledger,'claude','sonnet','2026-10-09T23:00:00+07:00')
        task=submit(self.ledger,'Inspect source','new')
        self.assertEqual(self.ledger.task(task['id'],full=True)['handoff']['owned_execution']['provider'],'claude')
        self.assertEqual(submit(self.ledger,'Inspect source','old')['id'],before['id'])
        chosen=submit(self.ledger,'Inspect source','explicit',provider='codex')
        self.assertEqual(self.ledger.task(chosen['id'],full=True)['handoff']['owned_execution']['model'],'gpt-6-luna')
        self.assertEqual(read(Ledger(self.root,self.ledger.state_root))['model'],'sonnet')
        with self.assertRaises(LedgerError): save(self.ledger,'claude','sonnet','2026-10-09T23:00:00')

    def test_preference_never_overrides_quota_risk_or_capability(self):
        result=choose(self.work,self.models,NOW,'claude');self.assertEqual(result['selected']['id'],'claude-mid')
        self.models[1]['quota']=None
        self.assertEqual(choose(self.work,self.models,NOW,'claude')['selected']['id'],'cheap')
        self.work['risk']='high';self.assertEqual(choose(self.work,self.models,NOW,'claude')['status'],'blocked')

    def test_jev_proposal_never_applies_or_dispatches_and_receives_only_eligible(self):
        bad=candidate('unavailable',1,0,'claude');bad['quota']=None;self.models.append(bad)
        result=choose(self.work,self.models,NOW,'claude');client=Client(self.response())
        with patch.object(client,'open',wraps=client.open) as opened:
            value=advise('Fix an isolated arithmetic function',self.work,self.models,result,'claude',key=KEY,opener=client)
            body=opened.call_args.args[0].data.decode()
        self.assertNotIn('unavailable',body);self.assertNotIn('quota',json.dumps(json.loads(body)['state']['workload']))
        self.assertEqual(client.calls,1);self.assertEqual(value['selected'],'claude-mid')
        self.assertFalse(value['automatic_application']);self.assertFalse(value['quality_calibrated'])
        self.assertEqual(result['selected']['id'],'claude-mid');self.assertNotIn(KEY,json.dumps(value))

    def test_invalid_response_and_errors_are_redacted_without_retry(self):
        result=choose(self.work,self.models,NOW)
        for field,value in [('choice','invented'),('confidence',float('nan')),('confidence',True),('probabilities',{'option1':1})]:
            response=self.response();response['answers']['routing'][field]=value
            client=Client(response)
            with self.assertRaises(JevError): advise('Audit a small function',self.work,self.models,result,key=KEY,opener=client)
            self.assertEqual(client.calls,1)
        client=Client(self.response())
        with patch.object(client,'open',side_effect=RuntimeError(KEY)) as call:
            with self.assertRaises(JevError) as error: advise('Audit',self.work,self.models,result,key=KEY,opener=client)
            self.assertNotIn(KEY,str(error.exception));self.assertEqual(call.call_count,1)

    def test_abstain_low_confidence_and_zero_calls_for_blocked_or_single(self):
        result=choose(self.work,self.models,NOW)
        for choice,confidence in [('abstain',.9),('option1',.6)]:
            value=advise('Audit',self.work,self.models,result,key=KEY,opener=Client(self.response(choice,confidence)))
            self.assertTrue(value['requires_review'])
        with patch('onecrew.model_advisor.load_key') as load:
            for subset in ([],self.models[:1]):
                rec=choose(self.work,subset or [dict(self.models[0],quota=None)],NOW)
                value=advise('Audit',self.work,subset,rec)
                self.assertEqual(value['calls'],0)
            load.assert_not_called()

    def test_cli_preference_and_jev_failure_receipt(self):
        from onecrew.cli import main
        from onecrew.provider_cli import main as provider_main
        args=['--project',str(self.root),'--state-root',str(self.ledger.state_root)]
        with patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(main(args+['provider','prefer','claude','--model','sonnet']),0)
        path=Path(self.tmp.name)/'routing.json';path.write_text(json.dumps({'workload':self.work,'candidates':self.models}))
        fixed=choose(self.work,self.models,NOW,'claude')
        with patch('onecrew.provider_cli.choose',return_value=fixed),patch('onecrew.model_advisor.advise',side_effect=JevError(KEY)),patch('sys.stdout',new_callable=io.StringIO) as stdout:
            self.assertEqual(provider_main(args+['choose','--file',str(path),'--jev','--brief','Synthetic audit']),0)
        value=json.loads(stdout.getvalue());self.assertEqual(value['jev']['status'],'unavailable')
        self.assertEqual(value['selected']['id'],'claude-mid');self.assertNotIn(KEY,stdout.getvalue())
        self.assertTrue(Path(value['receipt']).exists())

if __name__=='__main__': unittest.main()
