"""Kill the real coordinator process mid-node, restart it, and check it continues from the checkpoint.

The coordinator runs onecrew.runner.loop in a separate Python process. Native nodes are fixture functions
that journal every execution; the first process is TerminateProcess-killed while a node is running."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

from onecrew.ledger import Ledger
from onecrew.solution_delivery import Delivery, submit
from tests.test_solution_delivery import plan
from tests.test_solution_gate import approve_fixture

SCRIPT = textwrap.dedent('''
    import json, os, sys, time
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    from onecrew import delivery_steps, runner
    from onecrew.ledger import Ledger
    project, state, task, journal, barrier, marker = sys.argv[2:8]
    try:  # absent before the autopilot runtime; the probe then measures the old behaviour
        from onecrew import delivery_recovery
        delivery_recovery.BACKOFF = (0, 0, 0)
    except ImportError:
        pass
    def execute(runtime, task_id, s, node, row):
        with open(journal, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'node': node['id'], 'generation': row['generation'], 'pid': os.getpid()}) + '\\n')
        if node['id'] == 'build' and Path(barrier).exists():
            Path(marker).write_text('reached')
            time.sleep(600)
        if node['kind'] == 'handover':
            return real(runtime, task_id, s, node, row)
        if node['kind'] == 'build':
            return {'passed': True, 'source': s['delivery']['source']['hash'], 'apk': 'fixture.apk', 'sha256': '0' * 64}
        return {'passed': True, 'source': s['delivery']['source']['hash'], 'counts': {'passed': 1, 'failed': 0, 'skipped': 0}, 'red': [{'test': 'x'}]}
    real = delivery_steps.execute
    delivery_steps.execute = execute
    print(runner.loop(Ledger(project, state), task, interval=.05), flush=True)
''')


@unittest.skipUnless(os.name == 'nt', 'TerminateProcess semantics of the Windows coordinator')
class CoordinatorRestartTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name); self.root = base / 'project'; (self.root / 'app/test').mkdir(parents=True)
        (self.root / 'app/main.dart').write_text('void main() {}')
        (self.root / 'app/test/test_test.dart').write_text('// immutable suite fixture')
        (self.root / 'app/.dart_tool').mkdir()
        (self.root / 'app/.dart_tool/package_config.json').write_text(json.dumps({'packages': [{'name': 'app', 'rootUri': '../'}]}))
        from onecrew.delivery_steps import dart_argv
        for p in map(Path, (lambda a: (a[0], a[1][11:], a[2]))(dart_argv(self.root / 'sdk'))):
            p.parent.mkdir(parents=True, exist_ok=True); p.write_text('fixture tool, never executed')
        self.state = base / 'state'; self.ledger = Ledger(self.root, self.state)
        (base / 'android').mkdir()
        value = plan(self.root)
        # A build writes only into a fresh capture, so an interrupted build is replay-safe (356fb82 left it 'uncertain').
        value['nodes'].insert(2, {'id': 'build', 'kind': 'build', 'depends': ['review'], 'config': {
            'package': 'app', 'flutter_root': str(self.root / 'sdk'), 'android_sdk': str(base / 'android'), 'variant': 'debug',
            'config_reference': None, 'config_version': 'none', 'signer_sha256': 'a' * 64, 'timeout_seconds': 600}})
        value['nodes'][-1]['depends'].append('build')
        value['acceptance'].append({'id': 'AC2', 'text': 'Debug APK builds', 'nodes': ['build']})
        self.task = submit(self.ledger, 'Deliver fixture', 'root', value, **approve_fixture(self.ledger), provider='claude', model='sonnet')['id']
        Delivery(self.ledger).enable(self.task)
        self.script = base / 'coordinator.py'; self.script.write_text(SCRIPT, encoding='utf-8')
        self.journal = base / 'journal.jsonl'; self.barrier = base / 'barrier'; self.marker = base / 'marker'
        self.env = dict(os.environ, ONECREW_DELIVERY_ROOT=str(base / 'ocd'), ONECREW_DESKTOP_HOME=str(base / 'desktop'))

    def coordinator(self):
        repo = str(Path(__file__).resolve().parents[1])
        return subprocess.Popen([sys.executable, '-X', 'utf8', str(self.script), repo, str(self.root), str(self.state), self.task,
                                 str(self.journal), str(self.barrier), str(self.marker)], env=self.env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def events(self, kind):
        return [e for e in self.ledger.events(self.task) if e['kind'] == kind]

    def test_kill_mid_node_then_restart_continues_from_checkpoint(self):
        self.barrier.write_text('hold')
        first = self.coordinator()
        try:
            deadline = time.monotonic() + 60
            while not self.marker.exists():
                self.assertIsNone(first.poll(), first.communicate()[1].decode(errors='replace')[-2000:] if first.poll() is not None else '')
                self.assertLess(time.monotonic(), deadline, 'coordinator never reached the node'); time.sleep(.05)
        finally:
            first.kill(); first.communicate(timeout=30)
        seq, before = Delivery(self.ledger).state(self.task)
        self.assertEqual(before['delivery']['nodes']['build']['phase'], 'running')
        self.assertEqual(self.events('runner.stopped'), [])  # A hard kill runs no finalizer.
        budget = Delivery(self.ledger).control.status(self.task)['used_calls']
        self.barrier.unlink()
        second = self.coordinator()
        out, err = second.communicate(timeout=120)
        self.assertEqual(second.returncode, 0, err.decode(errors='replace')[-3000:])
        self.assertEqual(out.decode().strip().splitlines()[-1], 'completed')
        _, after = Delivery(self.ledger).state(self.task)
        runs = [json.loads(line) for line in self.journal.read_text(encoding='utf-8').splitlines()]
        self.assertEqual([r['node'] for r in runs], ['tests', 'review', 'build', 'build', 'handover'])
        self.assertEqual(len({r['pid'] for r in runs}), 2)
        self.assertEqual([x['action'] for x in after['delivery'].get('recoveries', [])], ['replay'])
        self.assertEqual(next(iter(after['delivery']['failures'].values()))['class'], 'interrupted')
        self.assertEqual(after['delivery']['source'], before['delivery']['source'])
        self.assertEqual(Delivery(self.ledger).control.status(self.task)['used_calls'], budget)
        self.assertEqual(after['phase'], 'completed'); self.assertEqual(after['delivery']['criteria'], {'AC1': 'passed', 'AC2': 'passed'})
        self.assertEqual(len(self.events('runner.started')), 2)
        self.assertGreater(seq, 0)


if __name__ == '__main__': unittest.main()
