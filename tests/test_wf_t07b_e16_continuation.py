"""T07b [E16] (W36): a managed worker pauses at its next safe point; when the branch is released, work that is COMPLETE is adopted
(tests/test_wf_managed_hold) and work that is NOT complete continues with a NEW attempt from the partial candidate — budget spent stays
spent, nothing is replayed, the old attempt never executes again.

Fixture of tests/test_wf_managed_hold (real local process as the worker, real finding register, go-file safe point). The worker's first
run writes `part one` and declares a continuation; the second run (a new attempt, base = the partial candidate) writes the rest.
Counter-rules: the partial candidate is never published as the node's result; a late `finish` of the old attempt is fenced; the
continuation path also works without a pause (a worker that returns a partial result).
"""
import json as _json

from onecrew.budget_core import group
from onecrew.ledger import LedgerError
from onecrew.v2 import findings, verdict
import tests.test_wf_managed_hold as hold


class ContinuationTests(hold.ManagedHoldFixture):            # the fixture class carries no tests of its own
    def factory(self, control, provider):
        """Like the hold fixture's worker: the first launch stops after `part one` with work left; a later launch completes the file."""
        from onecrew.process_core import Supervisor, native_python
        from onecrew.subscription import environment
        case = self
        self.go = self.temp_path() / 'operation-go'
        self.prompts = getattr(self, 'prompts', [])
        class Worker:
            def capability(self): return {'provider': provider, 'mode': 'local-test-artifact-no-tools'}
            def run(self, attempt, prompt, schema, profile):
                case.launches.append(attempt['id']); case.prompts.append(prompt)
                directory = case.ledger.state_root / 'worker-io' / attempt['id']; directory.mkdir(parents=True)
                script = ('import pathlib,sys,time\n'
                          'pathlib.Path(sys.argv[1]).write_text("started")\n'
                          'until=time.monotonic()+float(sys.argv[3])\n'
                          'while not pathlib.Path(sys.argv[5]).exists() and time.monotonic()<until: time.sleep(0.05)\n'
                          'with pathlib.Path(sys.argv[2]).open("a") as out: out.write("operation completed\\n")\n'
                          'pathlib.Path("answer.json").write_text(sys.argv[4])\n')
                first = len(case.launches) == 1
                value = ({'summary': 'first half', 'files': [{'path': 'a.txt', 'content': 'part one\n'}], 'backlog': [], 'continuation': {'remaining': 'part two is not written yet'}}
                         if first else {'summary': 'second half', 'files': [{'path': 'a.txt', 'content': 'part one\npart two\n'}], 'backlog': []})
                return Supervisor(control).run(attempt, [native_python(), '-c', script, str(case.started), str(case.marker), '25', _json.dumps(value), str(case.go)],
                                               cwd=directory, timeout=min(30, profile['step_seconds']), env=environment())
            def result(self, attempt):
                return _json.loads((case.ledger.state_root / 'worker-io' / attempt['id'] / 'answer.json').read_text()), []
        return Worker()

    def test_e16_release_of_a_partial_candidate_continues_with_a_new_attempt_and_keeps_the_spent_budget(self):
        thread, result, attempt = self.run_in_background()
        ident = self.open_finding()                                                     # the finding arrives during the first operation
        self.go.write_text('go')                                                        # safe point
        thread.join(30); self.assertFalse(thread.is_alive()); self.assertNotIn('error', result)
        self.assertEqual(result['value']['state'], 'held'); self.assertEqual(result['value']['executor_state'], 'paused')
        paused = self.adapter.state(attempt)
        self.assertEqual(paused['state'], 'paused')
        partial = _json.loads(self.store.read_blob(paused['candidate']['receipt']))
        self.assertTrue(partial['partial']); self.assertEqual(partial['continuation'], {'remaining': 'part two is not written yet'})
        with self.ledger.transaction() as conn:
            spent_before = group(conn, self.root_view['anchor_task'])['used_calls']
        (self.root / 'a.txt').write_text('one\nrow1\nrow2\n')
        receipt = verdict.run(self.ledger, 'P1', 'M1')['milestones'][0]['last_verdict']['receipt']
        from onecrew.v2.verifiers import command
        findings.resolve(self.ledger, 'P1', ident, receipt, reason='rows restored', artifact_sha=command.artifact_sha(self.root))
        released = self.engine.step(self.ledger, 'P1', self.adapter)                   # the hold is clear: the retained partial candidate is released
        self.assertEqual((released['state'], released['continues_attempt'], released['generation']), ('continuing', attempt, 1))   # [E16] not adopted
        self.assertEqual(self.launches, [attempt], 'releasing starts nothing by itself')
        self.assertEqual(released['resume_artifact'], paused['candidate']['artifact'])
        resumed = [p for k, p in self.events() if k == 'node.resumed'][-1]
        self.assertEqual((resumed['continues_attempt'], resumed['budget_reset']), (attempt, False))
        self.assertNotIn('node.produced', self.kinds())                                 # the partial candidate was never published
        view = self.engine.state(self.ledger, 'P1')
        self.assertEqual((view['nodes']['C']['generation'], view['nodes']['C']['phase'], view['nodes']['C']['resume_artifact']), (1, 'pending', paused['candidate']['artifact']))
        second = self.engine.step(self.ledger, 'P1', self.adapter)                     # the NEW attempt
        self.assertEqual((second['node'], second['state']), ('C', 'produced'))
        self.assertEqual(len(self.launches), 2); self.assertNotEqual(self.launches[1], attempt)   # [E16] a new attempt, the old one is not reused
        self.assertIn('part one', self.prompts[1])                                        # it starts from the partial candidate
        self.assertEqual(self.store.context(second['artifact'])['a.txt'], 'part one\npart two\n')
        body = _json.loads(self.store.read_blob(second['receipt']))
        self.assertEqual((body['partial'], body['continues_attempt'], body['resume_artifact']), (False, attempt, paused['candidate']['artifact']))
        with self.ledger.transaction() as conn:
            self.assertEqual(group(conn, self.root_view['anchor_task'])['used_calls'], spent_before + 1)   # spent stays spent, one more call
        with self.assertRaises(LedgerError):
            old = self.adapter.control.attempt(attempt)
            self.adapter.control.finish(attempt, old['generation'], {'exit_code': 0})   # a late result of the old attempt is fenced
        self.assertEqual([k for k, p in self.events() if k == 'node.produced'], ['node.produced'])
        self.assertEqual((self.root / 'a.txt').read_text(), 'one\nrow1\nrow2\n')      # the project is untouched by all of it

    def test_a_partial_result_without_a_pause_also_continues_with_a_new_attempt(self):
        (self.temp_path() / 'operation-go').write_text('go')                           # no pause: the operation completes at once
        first = self.engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual(first['state'], 'continuing'); self.assertEqual(first['generation'], 1)
        self.assertIn('node.result_retained', self.kinds()); self.assertNotIn('node.produced', self.kinds())
        second = self.engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual(second['state'], 'produced'); self.assertEqual(len(self.launches), 2)
        self.assertEqual(self.store.context(second['artifact'])['a.txt'], 'part one\npart two\n')
