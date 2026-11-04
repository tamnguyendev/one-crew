"""Installed W24 delivery shares v1 stores and never launches a real window."""
import json
import shutil
import unittest

from tests import wf_wheel as wh
from tests.test_v2_l1 import plan_json
from onecrew.v2 import boundary


class InstalledNotifications(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = wh._runs()
        cls.wheel, _, (modules, packages) = wh.build_wheel(cls.runs)
        cls.python = wh.make_venv(cls.runs)
        wh.install(cls.python, cls.wheel)
        cls.ctx = wh.build_ctx(cls.python, modules, packages)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.runs, ignore_errors=True)

    def test_installed_cli_question_pull_ack_desktop_retry_and_answer(self):
        contract = plan_json()
        contract['understanding']['target']['ref'] = 'snapshot'
        contract['understanding']['target']['paths'] = ['a.md']
        contract['preconditions'][0]['args']['path'] = 'a.md'
        contract['scope']['owned'] = ['a.md']
        contract['milestones'][0]['verifier'] = {'type': 'doc', 'config': {'docs': ['a.md']}}
        body = '''
import contextlib, io, json, os, tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from onecrew import desktop_core, notification_core
from onecrew.ledger import Ledger
from onecrew.v2 import cli, plan, notification_window
for name in ('ONECREW_ACTOR','CLAUDECODE','CLAUDE_CODE_CHILD_SESSION'): os.environ.pop(name,None)
with tempfile.TemporaryDirectory() as temp:
    root=Path(temp)/'project'; root.mkdir(); (root/'a.md').write_text('Document output.\\n')
    state=Path(temp)/'state'; os.environ['ONECREW_DESKTOP_HOME']=str(Path(temp)/'desktop')
    contract=Path(temp)/'contract.json'; contract.write_text(CONTRACT,encoding='utf-8')
    ledger=Ledger(root,state)
    def command(*args):
        stream=io.StringIO()
        with contextlib.redirect_stdout(stream):
            code=cli.main(['--project',str(root),'--state-root',str(state),*args])
        assert code==0,(args,stream.getvalue())
        return json.loads(stream.getvalue())
    command('plan','propose','P1','--file',str(contract),'--author','fixture')
    command('plan','approve','P1','--by','owner','--reference','authorized temporary fixture')
    task=plan.show(ledger,'P1')['anchor_task']
    q={'schema_version':1,'question':'Allow this scoped write?','reason':'M1 needs write access.',
       'impact':'M1 waits.','options':[{'id':'yes','label':'Allow'},{'id':'no','label':'Keep blocked'}],
       'recommendation':'no','action':{'type':'authorize','parameters':{'class':'U2'}}}
    req=ledger.create_request(task,'write',q)
    first=command('notifications','pull','--consumer','plan-fixture')
    assert [n['status'] for n in first['notifications']]==['blocker'],first
    assert first['notifications'][0]['target']['revision']==req['revision']
    assert command('notifications','pull','--consumer','plan-fixture')['id']==first['id']
    command('notifications','ack','--consumer','plan-fixture','--batch',first['id'])
    assert ledger.request(req['id'])['state']=='pending'
    assert notification_core.location(ledger,'plan-fixture',False).exists()
    command('desktop','enable')
    with patch.object(desktop_core,'launch',side_effect=OSError('fixture transport failure')):
        command('desktop','show','--task',task)
    records=command('desktop','status')['records']; assert len(records)==1,records
    assert records[0]['status']=='pending'
    with patch.object(desktop_core,'launch') as launcher:
        command('desktop','retry','--id',records[0]['id'])
        assert launcher.call_count==1
    command('question','answer',req['id'],'--revision',req['revision'],'--choice','no','--reference','authorized temporary fixture')
    events=ledger.events(task)
    contents=[]
    class Widget:
        def __init__(self,*a,**kw): pass
        def pack(self,**kw): pass
        def insert(self,position,text): contents.append(text)
        def configure(self,**kw): pass
    class Window(Widget):
        def title(self,*a): pass
        def geometry(self,*a): pass
        def attributes(self,*a): pass
        def after(self,*a): pass
        def destroy(self): pass
        def winfo_ismapped(self): return True
        def protocol(self,n,cb): self.close=cb
        def bind(self,n,cb): self.map=cb
        def mainloop(self):
            self.map(SimpleNamespace(widget=self)); self.close()
    with patch.dict('sys.modules',{'tkinter':SimpleNamespace(Tk=Window,Label=Widget,Frame=Widget,Button=Widget),
                                 'tkinter.scrolledtext':SimpleNamespace(ScrolledText=Widget)}):
        notification_window.show(desktop_core.directory(ledger),records[0]['id'])
    assert 'đã giải' in contents[0],contents
    record=command('desktop','status')['records'][0]
    assert record['status']=='closed' and record['answers_recorded'] is False
    assert record['user_attention_verified'] is False
    assert ledger.events(task)==events
    assert plan.show(ledger,'P1')['status']=='approved'
'''.replace('CONTRACT', repr(json.dumps(contract)))
        dump, tail = wh.run_case(self.python, body, cwd=self.runs)
        self.assertIsNotNone(dump, tail)
        self.assertEqual(boundary.violations(dump['end'], self.ctx), [], tail)

    def test_installed_opt_in_verifier_binding_stales_and_rechecks_changed_input(self):
        contract = plan_json()
        contract['understanding']['target'] = {'repo': '.', 'ref': 'snapshot', 'paths': ['guide.md']}
        contract['preconditions'][0]['args']['path'] = 'guide.md'
        contract['scope']['owned'] = ['guide.md']
        contract['milestones'][0]['verifier'] = {'type': 'doc', 'config': {'docs': ['guide.md']}}
        body = '''
import contextlib, io, json, os, tempfile
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew.snapshots import Snapshots
from onecrew.v2 import cli, namespaces
for name in ('ONECREW_ACTOR','CLAUDECODE','CLAUDE_CODE_CHILD_SESSION'): os.environ.pop(name,None)
with tempfile.TemporaryDirectory() as temp:
    root=Path(temp)/'project'; root.mkdir(); (root/'guide.md').write_text('# Guide\\n')
    state=Path(temp)/'state'
    cfile=Path(temp)/'contract.json'; cfile.write_text(CONTRACT,encoding='utf-8')
    def command(*args):
        stream=io.StringIO()
        with contextlib.redirect_stdout(stream):
            code=cli.main(['--project',str(root),'--state-root',str(state),*args])
        assert code==0,(args,stream.getvalue())
        return json.loads(stream.getvalue())
    caps=[arg for cap in sorted(namespaces.CAPABILITIES) for arg in ('--capability',cap)]
    command('plan','propose','P1','--file',str(cfile),'--author','fixture','--workflow',*caps)
    command('plan','approve','P1','--by','owner','--reference','temporary fixture')
    first=command('verdict','run','--plan','P1','--milestone','M1')
    assert first['milestones'][0]['state']=='passed',first
    receipt=first['milestones'][0]['last_verdict']['receipt']
    saved=Snapshots(state).read_blob(receipt)
    proof=json.loads(saved)['evidence_binding']; assert set(proof['inputs'])=={'guide.md'}
    (root/'guide.md').write_text('# New interface\\n')
    stale=command('plan','show','P1')['milestones'][0]
    assert stale['stale'] and 'input changed: guide.md' in stale['stale_reasons'],stale
    second=command('verdict','run','--plan','P1','--milestone','M1')
    assert second['milestones'][0]['state']=='passed',second
    assert second['milestones'][0]['last_verdict']['receipt']!=receipt
    assert Snapshots(state).read_blob(receipt)==saved
    store=Snapshots(state)
    latest=json.loads(store.read_blob(second['milestones'][0]['last_verdict']['receipt']))
    manifest=store.load(latest['artifact_sha'])
    (store.root/'blobs'/manifest['files']['guide.md']['working']).write_bytes(b'corrupted retained proof')
    damaged=command('plan','show','P1')['milestones'][0]
    assert damaged['stale'] and 'hash' in '; '.join(damaged['stale_reasons']).lower(),damaged
'''.replace('CONTRACT', repr(json.dumps(contract)))
        dump, tail = wh.run_case(self.python, body, cwd=self.runs)
        self.assertIsNotNone(dump, tail)
        self.assertEqual(boundary.violations(dump['end'], self.ctx), [], tail)
