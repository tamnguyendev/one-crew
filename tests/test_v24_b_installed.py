"""2.4-B from the INSTALLED wheel: the sb04 scenario (a mandatory fact withdrawn while the worker runs) in a fresh venv outside the checkout,
a scenario interpreter run with -I from a folder outside the checkout, the real engine -> NativeExecutor -> ClaudeArtifact -> Supervisor
path with the FAKE `claude` console script (tests/v23_fake_claude.py; a real OS process, no model). The withdrawal is written by the
scenario between the settled run and the receipt (a concurrent writer); the candidate built on the withdrawn fact is not published, the
next generation receives the delta, and the installed `onecrew wiki consumers` shows the delivery and its status. Module origins come from
the installed distribution and the install boundary holds."""
import json
import subprocess
import unittest
from pathlib import Path

from onecrew.v2 import boundary
from tests import v23_harness as hx
from tests import wf_wheel as wh
from tests.test_v2_l1 import plan_json
from tests.test_wf_engine import node
from tests.wf_env import owner_terminal

BODY = r'''
import json, subprocess, sys
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew.snapshots import Snapshots
from onecrew.common_executor import NativeExecutor
from onecrew.v2 import plan, engine, internal_plan, knowledge
work = Path(WORK)
root = work / 'project with space'; root.mkdir()
def git(*args): return subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True,text=True).stdout.strip()
git('init','-q'); git('config','user.name','fixture'); git('config','user.email','fixture@localhost')
(root/'a.txt').write_text('base\n'); (root/'.gitignore').write_text('.onecrew/\n')
git('add','.'); git('commit','-qm','base')
ledger = Ledger(root, work/'state with space')
plan.propose(ledger, 'P1', json.loads(CONTRACT), 'codex', workflow=True, capabilities=['namespaced-storage','root-budget','internal-plan','sequential-engine'])
plan.approve(ledger, 'P1', 'owner', 'temporary fixture only')
with ledger.transaction() as conn:
    event = conn.execute('SELECT MAX(seq) FROM events').fetchone()[0]
rule = knowledge.record(ledger, 'P1', kind='decision', text='a.txt must hold VALUE: right', applies_to=['a.txt'], must=True,
                        evidence={'status': 'verified', 'property': 'decided in review', 'sources': [{'type': 'event', 'id': event}]})['id']
internal_plan.revise(ledger, 'P1', json.loads(DEFINITION), reason='Installed working-context fixture', evidence=['a.txt:1'])
class Concurrent(NativeExecutor):
    withdrawn = False
    def finish(self, *args, **kwargs):
        if not Concurrent.withdrawn:                    # another writer withdraws the fact while this worker ran
            Concurrent.withdrawn = True
            knowledge.withdraw(ledger, 'P1', rule, reason='a.txt keeps its value now', evidence={'sources': [{'type': 'event', 'id': event}]})
        return super().finish(*args, **kwargs)
executor = Concurrent(ledger)                         # real make_worker -> ClaudeArtifact -> Supervisor -> the fake claude.exe
first = engine.step(ledger, 'P1', executor)
cli = subprocess.run([str(Path(sys.executable).parent / 'onecrew.exe'), '--project', str(root), '--state-root', str(ledger.state_root),
                      'wiki', 'consumers', '--plan', 'P1'], capture_output=True, cwd=str(work))
second = engine.step(ledger, 'P1', executor)
store = Snapshots(ledger.state_root)
with ledger.transaction() as conn:
    kinds = [r['kind'] for r in conn.execute('SELECT kind FROM events ORDER BY seq')]
    resumed = [json.loads(r['payload']) for r in conn.execute("SELECT payload FROM events WHERE kind='node.resumed'")]
receipt = json.loads(store.read_blob(second['receipt'])) if second.get('receipt') else {}
log = [json.loads(line) for line in Path(LOG).read_text(encoding='utf-8').splitlines()]
out = {'rule': rule, 'first': {k: first.get(k) for k in ('state', 'knowledge_changed')}, 'second': second['state'], 'fake': log,
       'cli': {'code': cli.returncode, 'out': json.loads(cli.stdout.decode('utf-8')) if cli.returncode == 0 else cli.stderr.decode('utf-8', 'replace')},
       'resumed': resumed, 'produced': kinds.count('node.produced'), 'delivered': kinds.count('knowledge.delivered'),
       'delta': receipt.get('knowledge', {}).get('delta'), 'candidate': store.context(second['artifact'])['a.txt'] if second.get('artifact') else None,
       'origins': {name: getattr(sys.modules.get(name), '__file__', None) for name in
                   ('onecrew.v2.working_context', 'onecrew.v2.knowledge', 'onecrew.common_executor', 'onecrew.v2.engine')}}
Path(OUT).write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
'''


class InstalledContext(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs, cls.python, cls.wheel, cls.ctx = hx.runtime('v24b')

    @classmethod
    def tearDownClass(cls):
        hx.cleanup(cls.runs)

    def setUp(self):
        owner_terminal(self)

    def test_sb04_installed_withdrawn_must_is_not_published_and_the_next_generation_gets_the_delta(self):
        work = self.runs / 'work dir'; work.mkdir()
        policy = work / 'policy.json'; policy.write_text(json.dumps({'target': 'a.txt', 'default': 'naive', 'careful': True}))
        log, out = work / 'fake.jsonl', work / 'out.json'
        item = node('C', write=('a.txt',))
        item['checks'] = [{'id': 'M1', 'spec': 'a.txt holds the value the project knowledge requires.'}]
        item['executor'] = {'role': 'worker', 'provider': 'claude', 'model': 'claude-haiku-5-5'}
        integration = node('I', ['C'], integration=True, write=())
        integration['checks'] = [{'id': 'M1', 'spec': 'Integration keeps a.txt.'}]
        integration['executor'] = dict(item['executor'])
        contract = plan_json(authority={'edit': True, 'commands': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']})
        body = (BODY.replace('WORK', repr(str(work))).replace('LOG', repr(str(log))).replace('OUT', repr(str(out)))
                .replace('CONTRACT', repr(json.dumps(contract))).replace('DEFINITION', repr(json.dumps([item, integration]))))
        dump, tail = wh.run_case(self.python, body, env_extra=hx.scenario_env(self.python, work, policy=policy, log=log), cwd=work)
        self.assertIsNotNone(dump, tail)
        self.assertEqual(boundary.violations(dump['end'], self.ctx), [], tail)
        result = json.loads(out.read_text(encoding='utf-8'))
        self.assertEqual(result['first']['state'], 'continuing', result)
        self.assertEqual(result['first']['knowledge_changed']['critical'][0]['id'], result['rule'])
        self.assertEqual([(r['how'], r['value']) for r in result['fake']], [('fact', 'right'), ('default', 'naive')])   # the fact was used, then not
        self.assertEqual(result['second'], 'produced')
        self.assertEqual(result['produced'], 1)                                    # only the rechecked candidate is published
        self.assertFalse(result['resumed'][0]['budget_reset'])
        self.assertEqual([w['id'] for w in result['delta']['withdrawn']], [result['rule']])
        self.assertEqual(result['candidate'], 'naive\n')
        self.assertEqual(result['cli']['code'], 0, result['cli'])
        self.assertEqual([(c['node'], c['status']) for c in result['cli']['out']['consumers']], [('C', 'withdrawn')])
        venv = str(Path(self.python).parent.parent).casefold()
        for name, origin in result['origins'].items():
            self.assertTrue(origin and origin.casefold().startswith(venv), (name, origin))


if __name__ == '__main__':
    unittest.main()
