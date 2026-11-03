"""OBS-1 from the INSTALLED wheel, outside the checkout: a fresh venv under TEMP, a scenario run with -I from a neutral folder, the real
engine -> NativeExecutor -> ClaudeArtifact -> Supervisor path with the FAKE `claude` console script (tests/v24_fake_claude.py: a real OS
process, no model) producing a real root/node/attempt in a temporary ledger; then `onecrew track list --json`, `track show --json`, the
detached `track serve` process and its page (a headless browser when one is here). The modules that answered come from the installed
distribution. The fake worker is a test double: this proves the tracking path on a real task flow, not that a model did useful work.
"""
import json
import subprocess
import sys
import time
import unittest
import urllib.request
from pathlib import Path

from tests import v23_harness as hx
from tests import wf_wheel as wh
from tests.test_obs1_web import badge, dump_dom, find_browser, screenshot
from tests.test_v24_a_installed import build_fake_wheel
from tests.test_v2_l1 import plan_json
from tests.test_wf_engine import node
from tests.wf_env import owner_terminal

BODY = r'''
import json, subprocess, sys, time
from pathlib import Path
from onecrew.ledger import Ledger
from onecrew.common_executor import NativeExecutor
from onecrew.v2 import plan, engine, internal_plan, tracking
work = Path(WORK)
root = work / 'project with space'; root.mkdir()
def git(*args): return subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True,text=True).stdout.strip()
git('init','-q'); git('config','user.name','fixture'); git('config','user.email','fixture@localhost')
(root/'a.txt').write_text('base\n'); (root/'out.txt').write_text('base\n'); (root/'.gitignore').write_text('.onecrew/\n')
git('add','.'); git('commit','-qm','base')
ledger = Ledger(root, work/'state with space')
plan.propose(ledger, 'P1', json.loads(CONTRACT), 'codex', workflow=True, capabilities=['namespaced-storage','root-budget','internal-plan','sequential-engine'])
before = tracking.overview(ledger.state_root)['projects'][0]['tasks'][0]
plan.approve(ledger, 'P1', 'owner', 'temporary fixture only')
internal_plan.revise(ledger, 'P1', json.loads(DEFINITION), reason='Installed tracking fixture', evidence=['a.txt:1'])
idle = tracking.overview(ledger.state_root)['projects'][0]['tasks'][0]
step = engine.step(ledger, 'P1', NativeExecutor(ledger))          # real worker process: the fake claude.exe on PATH
after = tracking.overview(ledger.state_root)['projects'][0]['tasks'][0]
detail = tracking.detail(ledger.state_root, 'P1')
out = {'before': before['status'], 'before_needs': [n['kind'] for n in before['needs_user']], 'idle': idle['status'], 'step': step['state'],
       'after': after['status'], 'after_level': after['level'], 'nodes': {k: (v['phase'], v['state'], v['generation']) for k, v in detail['nodes'].items()},
       'attempts': [a['status'] for a in detail['attempts']], 'measure': detail['measure'].get('attempts_wall_seconds'),
       'timeline_kinds': [e['kind'] for e in detail['timeline']], 'evidence_keys': len(detail['evidence_keys']),
       'origins': {name: getattr(sys.modules.get(name), '__file__', None) for name in ('onecrew.v2.tracking', 'onecrew.v2.engine', 'onecrew.common_executor')},
       'state_root': str(ledger.state_root), 'project': str(root)}
Path(OUT).write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
'''


class InstalledTracking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = Path(wh._runs())
        cls.wheel, cls.version, (modules, packages) = wh.build_wheel(cls.runs)
        spaced = cls.runs / 'obs1 run with space'; spaced.mkdir()
        cls.python = wh.make_venv(spaced)
        wh.install(cls.python, cls.wheel)
        wh.install(cls.python, build_fake_wheel(cls.runs))

    @classmethod
    def tearDownClass(cls):
        hx.cleanup(cls.runs)

    def setUp(self):
        owner_terminal(self)

    def cli(self, env, work, *args):
        done = subprocess.run([str(self.python), '-I', '-m', 'onecrew.console', *args], capture_output=True, text=True, encoding='utf-8', errors='replace', env=env, cwd=str(work), timeout=300)
        return done.returncode, done.stdout, done.stderr

    def test_a_real_task_flow_from_the_wheel_shows_on_the_tracking_view_cli_and_page(self):
        work = self.runs / 'work dir'; work.mkdir()
        policy = work / 'policy.json'; policy.write_text(json.dumps({}))
        log, out = work / 'fake.jsonl', work / 'out.json'
        item = node('C', write=('out.txt',)); item['checks'] = [{'id': 'M1', 'spec': 'out.txt is written.'}]
        item['executor'] = {'role': 'worker', 'provider': 'claude', 'model': 'claude-haiku-5-5'}
        integration = node('I', ['C'], integration=True, write=()); integration['checks'] = [{'id': 'M1', 'spec': 'Integration keeps out.txt.'}]; integration['executor'] = dict(item['executor'])
        contract = plan_json(scope={'owned': ['a.txt', 'out.txt']}, authority={'edit': True, 'commands': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']})
        body = (BODY.replace('WORK', repr(str(work))).replace('OUT', repr(str(out))).replace('CONTRACT', repr(json.dumps(contract))).replace('DEFINITION', repr(json.dumps([item, integration]))))
        env = hx.scenario_env(self.python, work, policy=policy, log=log)
        dump, tail = wh.run_case(self.python, body, env_extra=env, cwd=work)
        self.assertIsNotNone(dump, tail)
        result = json.loads(out.read_text(encoding='utf-8'))
        self.assertEqual(result['before']['kind'], 'waiting'); self.assertEqual(result['before_needs'], ['approve'])
        self.assertEqual(result['idle']['kind'], 'waiting'); self.assertIn('chưa có worker', result['idle']['reason'])
        self.assertEqual(result['step'], 'produced')
        self.assertEqual(result['after']['kind'], 'waiting'); self.assertEqual(result['after_level']['kind'], 'produced')
        self.assertEqual(result['nodes']['C'], ['complete', 'produced', 0]); self.assertEqual(result['attempts'], ['settled'])
        self.assertIsInstance(result['measure'], float)
        for kind in ('plan.approved', 'node.started', 'attempt.launched', 'attempt.settled', 'node.produced'): self.assertIn(kind, result['timeline_kinds'])
        self.assertGreater(result['evidence_keys'], 0)
        venv = str(Path(self.python).parent.parent).casefold()
        for name, origin in result['origins'].items(): self.assertTrue(origin and origin.casefold().startswith(venv), (name, origin))
        self.assertNotIn(str(wh.REPO).casefold(), json.dumps(result['origins']).casefold())
        # the CLI of the installed package reads the same ledger
        full = {**hx.clean_os_env(), **env}
        code, text, err = self.cli(full, work, '--project', result['project'], '--state-root', result['state_root'], 'track', 'list', '--json')
        self.assertEqual(code, 0, (text + err)[-800:])
        listed = json.loads(text)
        self.assertEqual(listed['projects'][0]['tasks'][0]['status'], result['after'])
        code, text, err = self.cli(full, work, '--project', result['project'], '--state-root', result['state_root'], 'track', 'show', 'P1')
        self.assertEqual(code, 0, (text + err)[-800:]); self.assertIn('node C', text); self.assertIn('đã tạo đầu ra', text)
        code, text, err = self.cli(full, work, '--help')
        self.assertIn('track', text)
        # the detached server of `track open` (no browser launch) answers over HTTP from the installed modules; closing it leaves the ledger untouched
        marker = Path(result['state_root']) / 'tracking' / 'server.json'
        # `track open` opens the default browser: in this test the server is started through tracking_web.open_page with browser=False instead
        probe = ('import json, sys; from onecrew.v2 import tracking_web; print(json.dumps(tracking_web.open_page(sys.argv[1], interval=1.0, project=sys.argv[2], '
                 'explicit_state_root=sys.argv[1], idle_exit=120, browser=False)))')
        done = subprocess.run([str(self.python), '-I', '-c', probe, result['state_root'], result['project']], capture_output=True, text=True, encoding='utf-8', env=full, cwd=str(work), timeout=120)
        started = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertTrue(started.get('url'), started)
        try:
            with urllib.request.urlopen(started['url'] + 'api/overview', timeout=20) as r: value = json.loads(r.read().decode('utf-8'))
            self.assertEqual(value['projects'][0]['tasks'][0]['level']['kind'], 'produced')
            self.assertEqual(value['server']['pid'], started['pid'])
            with urllib.request.urlopen(started['url'] + 'api/task?plan=P1', timeout=20) as r: d = json.loads(r.read().decode('utf-8'))
            self.assertEqual(d['nodes']['C']['state'], 'produced')
            browser = find_browser(self.runs / 'browser profile')
            if browser:
                dom = dump_dom(browser, started['url'], self.runs / 'browser profile')
                cls, text = badge(dom)
                self.assertEqual(cls, 'ok', text); self.assertIn('P1', dom); self.assertIn('class="st waiting"', dom); self.assertIn('đang chờ</span>', dom)
                import os
                evidence = os.environ.get('OBS1_EVIDENCE_DIR')
                if evidence: screenshot(browser, started['url'], self.runs / 'browser profile', Path(evidence) / 'obs1-installed-page.png')
        finally:
            import signal, os
            try: os.kill(started['pid'], signal.SIGTERM)
            except OSError: pass
        time.sleep(0.5)
        code, text, err = self.cli(full, work, '--project', result['project'], '--state-root', result['state_root'], 'track', 'list', '--json')
        self.assertEqual(json.loads(text)['source']['last_seq'], listed['source']['last_seq'])     # the viewer wrote nothing


if __name__ == '__main__':
    unittest.main()
