"""Installed T26 consumes existing SOL records without importing v1 engines."""
import json
import shutil
import unittest

from tests import wf_wheel as wh
from tests import test_wf_solution_link as fixtures
from onecrew.v2 import boundary


class InstalledSolutionLinkTests(unittest.TestCase):
    def test_installed_cli_linked_root_is_the_only_handoff_authority(self):
        fixture = fixtures.SolutionLinkTests()
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        runs = wh._runs(); self.addCleanup(shutil.rmtree, runs, ignore_errors=True)
        wheel, _, (modules, packages) = wh.build_wheel(runs)
        python = wh.make_venv(runs); wh.install(python, wheel)
        ctx = wh.build_ctx(python, modules, packages)
        body = '''
import contextlib, io, json, os
from pathlib import Path
from onecrew.ledger import Ledger, LedgerError, canonical, content_hash, utcnow
from onecrew.control_core import Control, migrate
from onecrew.task_intake import submit
from onecrew.v2 import cli, plan, solution_link, gate
for name in ('ONECREW_ACTOR','CLAUDECODE','CLAUDE_CODE_CHILD_SESSION'): os.environ.pop(name,None)
root=Path(ROOT); state=Path(STATE); ledger=Ledger(root,state)
path=root/'contract-fixture.json'; path.write_text(CONTRACT,encoding='utf-8')
def command(*args):
    stream=io.StringIO()
    with contextlib.redirect_stdout(stream):
        code=cli.main(['--project',str(root),'--state-root',str(state),*args])
    assert code==0,(args,stream.getvalue())
    return json.loads(stream.getvalue())
command('plan','propose','P1','--file',str(path),'--author','codex','--workflow')
with ledger.transaction() as conn:
    try: solution_link.intake_binding(ledger,conn,REF['id'],REF['revision'])
    except LedgerError: pass
    else: raise AssertionError('SOL approval must not grant authority before root approval')
command('plan','approve','P1','--by','owner','--reference','temporary installed fixture')
task=submit(ledger,'Inspect linked source','installed-read',plan_selector='plan-ns:P1',max_calls=1,max_seconds=60)
with ledger.transaction() as conn:
    raw=ledger._task(conn,task['id']); gate.require_plan(ledger,conn,raw)
    allowed=solution_link.check_task(ledger,conn,raw)
    current=plan.anchor_events(ledger,conn,'P1')
    assert allowed['authority']=='root' and allowed['solution_authority']=='none'
    assert allowed['root']['sha']==current['approved']['sha']
    assert allowed['solution_ref']==REF
migrate(ledger); control=Control(ledger)
execution=control.configure(task['id'],task['revision'],{'mode':'installed-local-fixture'})
attempt=control.reserve(task['id'],execution['revision'],'read',{'stage':'fixture'})
# Synthetic pending row models the existing v1 inbox; source tests use its real API.
with ledger.transaction(write=True) as conn:
    source=solution_link.source(ledger,conn,REF['id'],REF['revision'])
    payload={'affected_tasks':[task['id']],'question':'Fixture pending question'}
    conn.execute('INSERT INTO conversation_questions VALUES(?,?,?,?,?,?,?)',
        ('CREQ-fixture',source['conversation'],content_hash(payload),canonical(payload),'pending',None,utcnow()))
try: control.launched(attempt['id'],attempt['generation'],{'fixture':True})
except LedgerError as error: assert 'pending' in str(error),str(error)
else: raise AssertionError('Pending linked SOL question must block installed launch')
control.finish(attempt['id'],attempt['generation'],{'fixture':'never launched'},not_started=True)
with ledger.transaction(write=True) as conn:
    conn.execute("UPDATE conversation_questions SET state='answered' WHERE id='CREQ-fixture'")
    ledger._event(conn,task['id'],'solution.stopped',{'fixture':True})
try: control.configure(task['id'],task['revision'],{'mode':'installed-local-fixture'})
except LedgerError as error: assert 'stopped' in str(error),str(error)
else: raise AssertionError('Stopped linked task must not resume under installed policy')
assert 'onecrew.conversations' not in __import__('sys').modules
assert 'onecrew.solution_gate' not in __import__('sys').modules
'''.replace('ROOT', repr(str(fixture.root))).replace('STATE', repr(str(fixture.ledger.state_root))).replace('CONTRACT', repr(json.dumps(fixture.contract))).replace('REF', repr(fixture.ref))
        dump, tail = wh.run_case(python, body, cwd=runs)
        self.assertIsNotNone(dump, tail)
        self.assertEqual(boundary.violations(dump['end'], ctx), [], tail)
