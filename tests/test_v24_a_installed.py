"""2.4-A from the INSTALLED wheel (sa12): a fresh venv outside the checkout (under TEMP), a scenario interpreter run with -I from a folder
outside the checkout, the real engine -> NativeExecutor -> ClaudeArtifact -> Supervisor path with the FAKE `claude` console script
(tests/v24_fake_claude.py; a real OS process, no model). A node with `sources` reads a file that is not in its `read` list by request
on the pinned tree and writes the value it found. The modules that ran come from the installed distribution (paging and source_tools
included, listed in its RECORD), no v1 runtime module (worker_tools, owned) is loaded, and the install boundary holds."""
import base64
import hashlib
import json
import unittest
import zipfile
from pathlib import Path

from onecrew.v2 import boundary
from tests import v23_harness as hx
from tests import wf_wheel as wh
from tests.test_v2_l1 import plan_json
from tests.test_wf_engine import node
from tests.wf_env import owner_terminal

HERE = Path(__file__).resolve().parent
FAKE = 'onecrew_fake_claude_v24'

BODY = r'''
import json, subprocess, sys
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew.snapshots import Snapshots
from onecrew.common_executor import NativeExecutor
from onecrew.v2 import plan, engine, internal_plan
work = Path(WORK)
root = work / 'project with space'; root.mkdir()
def git(*args): return subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True,text=True).stdout.strip()
git('init','-q'); git('config','user.name','fixture'); git('config','user.email','fixture@localhost')
(root/'a.txt').write_text('base\n'); (root/'out.txt').write_text('base\n'); (root/'.gitignore').write_text('.onecrew/\n')
(root/'src'/'lib').mkdir(parents=True)
(root/'src'/'main.py').write_text('from lib import value\n')
(root/'src'/'lib'/'value.txt').write_text('The configured VALUE: green\n')
(root/'src'/'.env.local').write_text('TOKEN=never-shown\n')
git('add','.'); git('commit','-qm','base')
ledger = Ledger(root, work/'state with space')
plan.propose(ledger, 'P1', json.loads(CONTRACT), 'codex', workflow=True, capabilities=['namespaced-storage','root-budget','internal-plan','sequential-engine'])
plan.approve(ledger, 'P1', 'owner', 'temporary fixture only')
internal_plan.revise(ledger, 'P1', json.loads(DEFINITION), reason='Installed source-reading fixture', evidence=['a.txt:1'])
executor = NativeExecutor(ledger)                      # real make_worker -> ClaudeArtifact -> Supervisor -> the fake claude.exe
steps = [engine.step(ledger, 'P1', executor)]
while steps[-1]['state'] == 'continuing' and len(steps) < 5:
    steps.append(engine.step(ledger, 'P1', executor))
store = Snapshots(ledger.state_root)
receipt = json.loads(store.read_blob(steps[-1]['receipt'])) if steps[-1].get('receipt') else {}
log = [json.loads(line) for line in Path(LOG).read_text(encoding='utf-8').splitlines()]
out = {'states': [s['state'] for s in steps], 'fake': log, 'source': receipt.get('source'),
       'candidate': store.context(steps[-1]['artifact'])['out.txt'] if steps[-1].get('artifact') else None,
       'worktree': (root/'out.txt').read_text(),
       'origins': {name: getattr(sys.modules.get(name), '__file__', None) for name in
                   ('onecrew.paging', 'onecrew.v2.source_tools', 'onecrew.common_executor', 'onecrew.v2.engine')},
       'v1': sorted(n for n in sys.modules if n.startswith(('onecrew.worker_tools', 'onecrew.owned')))}
Path(OUT).write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
'''


def build_fake_wheel(into):
    """A wheel holding tests/v24_fake_claude.py as module onecrew_fake_claude_v24 with console script `claude`."""
    source = (HERE / 'v24_fake_claude.py').read_bytes()
    info = f'{FAKE}-0.1.dist-info'
    files = {f'{FAKE}.py': source,
             f'{info}/METADATA': b'Metadata-Version: 2.1\nName: onecrew-fake-claude-v24\nVersion: 0.1\nSummary: test double of the claude CLI\n',
             f'{info}/WHEEL': b'Wheel-Version: 1.0\nGenerator: test_v24_a_installed\nRoot-Is-Purelib: true\nTag: py3-none-any\n',
             f'{info}/entry_points.txt': f'[console_scripts]\nclaude = {FAKE}:main\n'.encode()}
    record = []
    for name, data in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')
        record.append(f'{name},sha256={digest},{len(data)}')
    files[f'{info}/RECORD'] = ('\n'.join(record + [f'{info}/RECORD,,']) + '\n').encode()
    path = Path(into) / f'{FAKE}-0.1-py3-none-any.whl'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return path


class InstalledSources(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = Path(wh._runs())                     # under TEMP: outside the checkout
        cls.wheel, _, (modules, packages) = wh.build_wheel(cls.runs)
        spaced = cls.runs / 'v24a run with space'; spaced.mkdir()
        cls.python = wh.make_venv(spaced)
        wh.install(cls.python, cls.wheel)
        wh.install(cls.python, build_fake_wheel(cls.runs))
        cls.ctx = wh.build_ctx(cls.python, modules, packages)

    @classmethod
    def tearDownClass(cls):
        hx.cleanup(cls.runs)

    def setUp(self):
        owner_terminal(self)

    def test_sa12_wheel_runs_source_tools_without_checkout(self):
        work = self.runs / 'work dir'; work.mkdir()
        policy = work / 'policy.json'; policy.write_text(json.dumps({'read': 'value.txt'}))
        log, out = work / 'fake.jsonl', work / 'out.json'
        item = node('C', write=('out.txt',))
        item['read'] = ['src/main.py']
        item['checks'] = [{'id': 'M1', 'spec': 'out.txt holds the configured value.'}]
        item['executor'] = {'role': 'worker', 'provider': 'claude', 'model': 'claude-haiku-5-5'}
        item['sources'] = {'read': ['src/'], 'max_rounds': 2, 'max_chars_per_round': 8000}
        integration = node('I', ['C'], integration=True, write=())
        integration['checks'] = [{'id': 'M1', 'spec': 'Integration keeps out.txt.'}]
        integration['executor'] = dict(item['executor'])
        contract = plan_json(scope={'owned': ['a.txt', 'out.txt']},
                             authority={'edit': True, 'commands': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12'],
                                        'read': ['src/**']})
        body = (BODY.replace('WORK', repr(str(work))).replace('LOG', repr(str(log))).replace('OUT', repr(str(out)))
                .replace('CONTRACT', repr(json.dumps(contract))).replace('DEFINITION', repr(json.dumps([item, integration]))))
        dump, tail = wh.run_case(self.python, body, env_extra=hx.scenario_env(self.python, work, policy=policy, log=log), cwd=work)
        self.assertIsNotNone(dump, tail)
        self.assertEqual(boundary.violations(dump['end'], self.ctx), [], tail)
        result = json.loads(out.read_text(encoding='utf-8'))
        self.assertEqual(result['states'], ['continuing', 'produced'], result)
        self.assertEqual([(r['how'], r.get('value')) for r in result['fake']], [('ask', None), ('read', 'green')])
        self.assertEqual(result['fake'][1]['from'], 'src/lib/value.txt')                  # not in node.read: read by request
        self.assertEqual(result['candidate'], 'green\n'); self.assertEqual(result['worktree'], 'base\n')
        self.assertEqual(result['source']['capability'], 'git-tree')
        self.assertEqual(result['source']['rounds_used'], 1)
        self.assertEqual(result['v1'], [])
        venv = str(Path(self.python).parent.parent).casefold()
        record = {f.casefold() for f in wh.installed_record(self.python)['files']}
        for name, origin in result['origins'].items():
            self.assertTrue(origin and origin.casefold().startswith(venv), (name, origin))
            self.assertIn(str(Path(origin).resolve()).casefold(), record, name)
        self.assertNotIn(str(wh.REPO).casefold(), json.dumps(result['origins']).casefold())


if __name__ == '__main__':
    unittest.main()
