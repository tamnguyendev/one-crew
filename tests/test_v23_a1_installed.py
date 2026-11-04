"""2.3-A1 from the INSTALLED wheel (KP-01, KP-02; KA-16 through a real process): a fresh venv under a path with spaces, a scenario
interpreter run with -I from a folder outside the checkout, the real NativeExecutor -> ClaudeArtifact -> Supervisor path with the FAKE
`claude` console script (tests/v23_fake_claude.py; a real OS process, no model). The wiki page says which value the file must hold;
the node's real command check judges the candidate. The modules that ran are checked against the installed distribution (no import
from the checkout), and the installed `onecrew` executable prints wiki data in Vietnamese under a cp1252 console."""
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
import json, os, subprocess, sys
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew.snapshots import Snapshots
from onecrew.common_executor import NativeExecutor
from onecrew.common_verification import CandidateChecker
from onecrew.v2 import plan, engine, internal_plan, knowledge, wiki, context
work = Path(WORK)
root = work / 'project with space'; root.mkdir()
def git(*args): return subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True,text=True).stdout.strip()
git('init','-q'); git('config','user.name','fixture'); git('config','user.email','fixture@localhost')
(root/'a.txt').write_text('base\n'); (root/'.gitignore').write_text('.onecrew/\n')
git('add','.'); git('commit','-qm','base'); head = git('rev-parse','HEAD')
(root/'docs'/'wiki').mkdir(parents=True)
meta = {'id': 'a-value', 'kind': 'constraint', 'label': 'verified', 'must': True, 'applies_to': ['a.txt'],
        'sources': [{'type': 'file', 'path': 'a.txt', 'revision': head}]}
page = ('# Quy ước\n\n## Giá trị của a.txt\n```onecrew\n' + json.dumps(meta) + '\n```\n'
        'a.txt phải chứa đúng VALUE: right — không phải giá trị mặc định.\n\n## Lịch họp\nHọp nhóm thứ hai hằng tuần ở phòng lớn.\n')
(root/'docs'/'wiki'/'rules.md').write_text(page, encoding='utf-8')
git('add','.'); git('commit','-qm','wiki')
ledger = Ledger(root, work/'state with space')
contract = json.loads(CONTRACT)
contract['milestones'][0]['verifier']['config']['argv'] = [sys.executable, '-c', 'from pathlib import Path; assert Path("a.txt").read_text().strip()=="right", Path("a.txt").read_text(); print("value verified")']
plan.propose(ledger, 'P1', contract, 'codex', workflow=True, capabilities=['namespaced-storage','root-budget','internal-plan','sequential-engine'])
plan.approve(ledger, 'P1', 'owner', 'temporary fixture only')
internal_plan.revise(ledger, 'P1', json.loads(DEFINITION), reason='Scoped installed wiki fixture', evidence=['a.txt:1'])
executor = NativeExecutor(ledger)                      # real make_worker -> ClaudeArtifact -> Supervisor -> the fake claude.exe
produced = engine.step(ledger, 'P1', executor)
assert produced['state'] == 'produced', produced
verdict = engine.verify(ledger, 'P1', 'C', CandidateChecker(ledger, 'P1'))
store = Snapshots(ledger.state_root)
receipt = json.loads(store.read_blob(produced['receipt']))
view = json.loads(store.read_blob(receipt['knowledge']['package']))
log = [json.loads(line) for line in Path(LOG).read_text(encoding='utf-8').splitlines()]
out = {'verdict': verdict['result'], 'delivered': receipt['knowledge']['delivered'], 'use': receipt['knowledge_use'],
       'fake': log, 'must': [e['id'] for e in view['entries'] if e['must']], 'omitted': view['omitted'],
       'origins': {name: getattr(sys.modules[name], '__file__', None) for name in
                   ('onecrew.v2.knowledge', 'onecrew.v2.wiki', 'onecrew.v2.context', 'onecrew.common_executor', 'onecrew.artifact_provider_core')},
       'page_unchanged': (root/'docs'/'wiki'/'rules.md').read_text(encoding='utf-8') == page,
       'candidate': store.context(produced['artifact'])['a.txt'], 'worktree': (root/'a.txt').read_text()}
Path(OUT).write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
'''


class InstalledA1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs, cls.python, cls.wheel, cls.ctx = hx.runtime('a1')

    @classmethod
    def tearDownClass(cls):
        hx.cleanup(cls.runs)

    def setUp(self):
        owner_terminal(self)

    def test_installed_wheel_delivers_the_wiki_rule_and_the_real_check_passes(self):
        work = self.runs / 'work dir'; work.mkdir()
        policy = work / 'policy.json'; policy.write_text(json.dumps({'target': 'a.txt', 'default': 'naive', 'careful': True}))
        log, out = work / 'fake.jsonl', work / 'out.json'
        item = node('C', write=('a.txt',))
        item['checks'] = [{'id': 'M1', 'spec': 'a.txt holds the value the project wiki requires.'}]
        item['executor'] = {'role': 'worker', 'provider': 'claude', 'model': 'claude-haiku-5-5'}
        integration = node('I', ['C'], integration=True, write=())
        integration['checks'] = [{'id': 'M1', 'spec': 'Integration keeps a.txt.'}]
        contract = plan_json(authority={'edit': True, 'commands': True, 'unconfined_commands': True,
                                        'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']})
        body = (BODY.replace('WORK', repr(str(work))).replace('LOG', repr(str(log))).replace('OUT', repr(str(out)))
                .replace('CONTRACT', repr(json.dumps(contract))).replace('DEFINITION', repr(json.dumps([item, integration]))))
        dump, tail = wh.run_case(self.python, body, env_extra=hx.scenario_env(self.python, work, policy=policy, log=log), cwd=work)
        self.assertIsNotNone(dump, tail)
        self.assertEqual(boundary.violations(dump['end'], self.ctx), [], tail)
        result = json.loads(out.read_text(encoding='utf-8'))
        self.assertEqual(result['verdict'], 'pass', result)
        self.assertEqual(result['must'], ['a-value'])
        self.assertIn('a-value', result['delivered'])
        self.assertEqual(result['use']['violations'], [])
        self.assertEqual(len(result['fake']), 1)                      # one real process run of the fake claude
        self.assertEqual((result['fake'][0]['how'], result['fake'][0]['value']), ('fact', 'right'))
        self.assertEqual(result['candidate'], 'right\n'); self.assertEqual(result['worktree'], 'base\n')   # candidate only, no project apply
        self.assertTrue(result['page_unchanged'])
        venv = str(Path(self.python).parent.parent).casefold()
        for name, origin in result['origins'].items():
            self.assertTrue(origin and origin.casefold().startswith(venv), (name, origin))
        self.assertGreater(result['omitted']['by_reason'].get('not_relevant', 0), 0)        # the meeting note was not delivered

    def test_cp1252_console_prints_the_wiki_report(self):
        work = self.runs / 'console'; work.mkdir()
        project = work / 'proj'; project.mkdir()
        run = lambda *a: subprocess.run(['git', '-C', str(project), *a], check=True, capture_output=True)
        run('init', '-q'); run('config', 'user.name', 'f'); run('config', 'user.email', 'f@localhost')
        (project / 'a.txt').write_text('x\n'); (project / 'docs' / 'wiki').mkdir(parents=True)
        (project / 'docs' / 'wiki' / 'n.md').write_text('## Ghi chú về a.txt\nTiếng Việt có dấu: ổn định.\n', encoding='utf-8')
        run('add', '.'); run('commit', '-qm', 'b')
        exe = Path(self.python).parent / 'onecrew.exe'
        env = dict(hx.clean_os_env(), PYTHONUTF8='0', PYTHONIOENCODING='cp1252', ONECREW_LANG='vi', **hx.scenario_env(self.python, work))
        done = subprocess.run([str(exe), '--project', str(project), '--state-root', str(work / 'state'), 'wiki', 'pages'],
                              capture_output=True, env=env, cwd=str(work))
        self.assertEqual(done.returncode, 0, done.stderr.decode('utf-8', 'replace'))
        report = json.loads(done.stdout.decode('utf-8'))
        self.assertEqual([e['id'] for e in report['pages'][0]['entries']], ['n-ghi-chu-ve-a-txt'])
        self.assertEqual(report['pages'][0]['entries'][0]['title'], 'Ghi chú về a.txt')
