"""W36/W18 (T07b [E16], T15c [E7], [E9]): a finding that holds a RUNNING managed node pauses it at its next safe point by itself.

Real local process (ManagedFixture worker) and the real finding register (data verifier on a.txt). The pause is only
requested by the engine; the acknowledgement comes from the Supervisor safe point. A non-managed attempt gets no pause.
"""
import os
import time

from onecrew.control_core import Control, migrate
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, findings, internal_plan, managed_executor, plan, verdict
from tests.test_v2_l1 import Fixture, milestone, plan_json
from tests.test_wf_engine import node
from tests.test_wf_managed_executor import ManagedFixture


class ManagedHoldFixture(ManagedFixture):
    def setUp(self):
        Fixture.setUp(self)
        self.engine, self.ip = engine, internal_plan
        check = milestone(); check['verifier'] = {'type': 'data', 'config': {'path': 'a.txt', 'columns': {'one': 'string'}, 'key': ['one'], 'row_count': 2}}
        raw = plan_json(milestones=[check], scope={'owned': ['a.txt', 'b.txt']},
                        authority={'edit': True, 'commands': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q8', 'Q9', 'Q12']})
        caps = ['namespaced-storage', 'finding-register', 'root-budget', 'internal-plan', 'sequential-engine']
        self.root_view = plan.propose(self.ledger, 'P1', raw, 'codex', workflow=True, capabilities=caps)
        plan.approve(self.ledger, 'P1', 'owner', 'temporary fixture grant')
        self.store = Snapshots(self.ledger.state_root); migrate(self.ledger); self.control = Control(self.ledger)
        os.environ['ONECREW_ACTOR'] = 'codex'
        previous = os.environ.get('ONECREW_HOST_HOME')
        os.environ['ONECREW_HOST_HOME'] = str(self.temp_path() / 'host-home')
        self.addCleanup(lambda: os.environ.__setitem__('ONECREW_HOST_HOME', previous) if previous is not None else os.environ.pop('ONECREW_HOST_HOME', None))
        self.marker = self.temp_path() / 'operations.txt'
        self.started = self.temp_path() / 'operation-started'
        self.delay = 0.0
        self.launches = []
        self.adapter = managed_executor.ManagedExecutor(self.ledger, worker_factory=self.factory)
        first = node('C'); first['executor'] = {'role': 'worker', 'provider': 'codex', 'model': 'fixture-model'}
        other = node('X', write=('b.txt',)); other['read'] = ['b.txt']
        integration = node('I', ['C', 'X'], integration=True, write=()); integration['read'] = []
        integration['executor'] = dict(first['executor'])
        self.revise([first, other, integration])

    def temp_path(self):
        from pathlib import Path
        return Path(self.temp.name)

    def factory(self, control, provider):
        """Like ManagedFixture's worker, but the bounded operation waits for a `go` file instead of a fixed sleep, so the test
        decides deterministically that the finding arrives WHILE the operation is in flight (a verdict run can take seconds)."""
        from onecrew.process_core import Supervisor, native_python
        from onecrew.subscription import environment
        import json as _json
        case = self
        self.go = self.temp_path() / 'operation-go'
        class LocalArtifactWorker:
            def capability(self):
                return {'provider': provider, 'mode': 'local-test-artifact-no-tools'}
            def run(self, attempt, prompt, schema, profile):
                case.launches.append(attempt['id'])
                directory = case.ledger.state_root / 'worker-io' / attempt['id']
                directory.mkdir(parents=True)
                script = ('import pathlib,sys,time\n'
                    'pathlib.Path(sys.argv[1]).write_text("started")\n'
                    'until=time.monotonic()+float(sys.argv[3])\n'
                    'while not pathlib.Path(sys.argv[5]).exists() and time.monotonic()<until: time.sleep(0.05)\n'
                    'with pathlib.Path(sys.argv[2]).open("a") as out: out.write("operation completed\\n")\n'
                    'pathlib.Path("answer.json").write_text(sys.argv[4])\n')
                value = {'summary': 'Local fixture candidate', 'files': [{'path': 'a.txt', 'content': 'isolated candidate\n'}], 'backlog': []}
                return Supervisor(control).run(attempt, [native_python(), '-c', script, str(case.started), str(case.marker), '25', _json.dumps(value), str(case.go)],
                    cwd=directory, timeout=min(30, profile['step_seconds']), env=environment())
            def result(self, attempt):
                directory = case.ledger.state_root / 'worker-io' / attempt['id']
                return _json.loads((directory / 'answer.json').read_text()), []
        return LocalArtifactWorker()

    def open_finding(self):
        verdict.run(self.ledger, 'P1', 'M1')          # a.txt has one row: the data check fails and a finding opens on M1
        rows = findings.list_findings(self.ledger, 'P1', open_only=True)
        self.assertEqual(len(rows), 1)
        return rows[0]['id']


class ManagedHoldTests(ManagedHoldFixture):
    def test_new_finding_pauses_the_running_managed_node_at_its_safe_point_and_release_reuses_the_candidate(self):
        thread, result, attempt = self.run_in_background()
        ident = self.open_finding()                     # while the operation of C is in flight
        history = self.adapter._history(attempt)
        requested = [p for p in history if p['phase'] == 'pause_requested']
        self.assertEqual(len(requested), 1, history)
        self.assertIn(ident, requested[0]['reason']); self.assertIn('C', requested[0]['reason'])
        self.assertFalse(self.marker.exists(), 'the current operation is not interrupted')
        self.assertEqual(self.adapter.state(attempt)['state'], 'pause_requested')
        self.go.write_text('go')                        # the bounded operation now completes: that is the safe point
        thread.join(30); self.assertFalse(thread.is_alive()); self.assertNotIn('error', result)
        self.assertEqual(result['value']['state'], 'held')
        self.assertEqual(result['value']['executor_state'], 'paused')
        paused = self.adapter.state(attempt)
        self.assertEqual((paused['state'], paused['text']), ('paused', 'đã dừng tại điểm an toàn'))
        self.assertEqual(self.marker.read_text().splitlines(), ['operation completed'])
        view = self.engine.state(self.ledger, 'P1')
        # the finding also blocks C's inputs, so the safe-point candidate is RETAINED (never published) and C stays on its attempt
        self.assertEqual(view['nodes']['C']['phase'], 'running')
        self.assertIsNone(view['nodes']['C']['artifact'])
        self.assertIn('node.result_retained', self.kinds())
        self.assertEqual((self.root / 'a.txt').read_text(), 'one\n')
        # a second register change does not repeat the request
        findings.update(self.ledger, 'P1', ident, reason='scope is a.txt only', read=['a.txt'], write=[])
        self.assertEqual(len([p for p in self.adapter._history(attempt) if p['phase'] == 'pause_requested']), 1)
        # resolve the finding with real passing evidence, then the retained candidate is released without another process
        (self.root / 'a.txt').write_text('one\nrow1\nrow2\n')
        shown = verdict.run(self.ledger, 'P1', 'M1')
        receipt = shown['milestones'][0]['last_verdict']['receipt']
        from onecrew.v2.verifiers import command
        findings.resolve(self.ledger, 'P1', ident, receipt, reason='rows restored', artifact_sha=command.artifact_sha(self.root))
        self.assertEqual(findings.list_findings(self.ledger, 'P1', open_only=True), [])
        released = self.engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual((released['node'], released['state']), ('C', 'produced')); self.assertTrue(released['released_retained'])
        self.assertEqual(self.launches, [attempt])
        self.assertEqual(released['artifact'], paused['candidate']['artifact'])
        self.assertEqual(self.store.context(released['artifact'])['a.txt'], 'isolated candidate\n')

    def test_hold_is_not_sent_to_an_attempt_without_a_managed_history(self):
        # a plain (hook-style) executor: Control attempt only, no executor.managed intent
        def external(ledger, control, task, item, attempt):
            control.launched(attempt['id'], attempt['generation'], {'fixture': True})
            self.open_finding()                           # the finding opens while this non-managed attempt runs
            requests = managed_executor.hold_for_findings(ledger, 'P1')
            self.assertEqual(requests, [])
            artifact = self.store.blob(b'external candidate'); receipt = self.store.blob(b'external receipt')
            control.finish(attempt['id'], attempt['generation'], {'fixture': True, 'artifact': artifact})
            return {'artifact': artifact, 'receipt': receipt}
        result = self.engine.step(self.ledger, 'P1', external, control=self.control)
        self.assertEqual(result['state'], 'retained')     # the finding arrived during execution: the result is retained, not published
        with self.ledger.transaction() as conn:
            rows = conn.execute("SELECT COUNT(*) FROM events WHERE kind=?", (managed_executor.KIND,)).fetchone()[0]
        self.assertEqual(rows, 0)
