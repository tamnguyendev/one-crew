"""W33b evidence for T15c E8: two nodes that write the same scope never run at the same time on an executor that does not declare
isolate (a plain callable executor, the sequential engine). Real engine, ledger and Control attempts on a temporary ledger; the executor
is a controllable fixture, so only the engine's admission rule is proved, not a real worker.
"""
import threading
import time

from onecrew.ledger import LedgerError
from tests.test_wf_engine import EngineFixture, node


class SameScopeSerialTests(EngineFixture):
    def setUp(self):
        super().setUp()
        self.revise([node('N1', write=('a.txt',)), node('N2', write=('a.txt',)), node('I', ['N1', 'N2'], integration=True, write=())])
        self.spans = {}
        self.guard = threading.Lock()
        self.inside = threading.Event()

    def slow(self, delay):
        def run(ledger, control, task, item, attempt):
            start = time.monotonic()
            self.inside.set()
            time.sleep(delay)
            result = self.execute(ledger, control, task, item, attempt)
            with self.guard:
                self.spans[item['id']] = (start, time.monotonic())
            return result
        return run

    def intervals(self):
        """Per node: (seq of node.started, seq of node.produced) from the ledger, in event order."""
        task = self.root_view['anchor_task']
        seqs = {}
        for event in self.ledger.events(task):
            if event['kind'] in ('node.started', 'node.produced'):
                seqs.setdefault(event['payload']['node'], {})[event['kind']] = event['seq']
        return {n: (v.get('node.started'), v.get('node.produced')) for n, v in seqs.items()}

    def assert_disjoint(self, a, b):
        (s1, e1), (s2, e2) = a, b
        self.assertTrue(e1 < s2 or e2 < s1, f'intervals intersect: {a} {b}')

    def test_t15c_e8_second_step_waits_while_the_first_same_scope_node_runs(self):
        """W33b / T15c E8: while N1 (write a.txt) is running, a concurrent step cannot start N2 (same write scope): it returns
        waiting, and the ledger shows N1 started..produced strictly before N2 started..produced."""
        outcomes = {}
        first = threading.Thread(target=lambda: outcomes.setdefault('first', self.step(self.slow(1.5))))
        first.start()
        self.assertTrue(self.inside.wait(30), 'the first executor never started')
        try:
            second = self.step(self.slow(0))                       # concurrent call while N1 is inside its executor
        except LedgerError as error:
            second = {'state': 'refused', 'reason': str(error)}
        first.join(60)
        self.assertEqual(outcomes['first']['node'], 'N1')
        self.assertIn(second['state'], ('waiting', 'refused'))
        self.assertNotEqual(second.get('node'), 'N2')
        started_early = [k for k, v in self.intervals().items() if k == 'N2']
        self.assertEqual(started_early, [], 'N2 started while N1 was running')
        self.verify('N1')
        ran = self.step(self.slow(0))                              # now the scope is free
        self.assertEqual(ran['node'], 'N2')
        spans = self.intervals()
        self.assertTrue(all(all(v) for v in spans.values()), spans)
        self.assert_disjoint(spans['N1'], spans['N2'])
        self.assertLess(spans['N1'][1], spans['N2'][0])

    def test_t15c_e8_simultaneous_steps_never_overlap_their_executions(self):
        """W33b / T15c E8: two steps released together by a barrier on a non-isolating executor: at most one executor body runs at
        a time (measured inside the executor), the loser is refused or told to wait, and the ledger intervals of the nodes do not intersect."""
        barrier = threading.Barrier(2)
        results = []

        def attempt():
            barrier.wait(30)
            try:
                results.append(self.step(self.slow(0.8)))
            except LedgerError as error:
                results.append({'state': 'refused', 'reason': str(error)})
        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(90)
        self.assertEqual(len(results), 2, results)
        ran = [r for r in results if r.get('state') == 'produced' and not r.get('already_adopted')]
        self.assertEqual(len(ran), 1, results)                    # one execution; the other call adopted it, waited or was refused
        for other_call in results:
            if other_call is not ran[0]:
                # the losing call of the race adopts the winner's result, waits, is refused, or finds its attempt already launched
                self.assertTrue(other_call.get('already_adopted') or other_call['state'] in ('waiting', 'refused', 'held'), results)
                self.assertNotEqual(other_call.get('node'), 'N2' if ran[0]['node'] == 'N1' else 'N1', results)
        self.assertEqual(len(self.spans), 1, self.spans)
        self.assertEqual(list(self.spans), [ran[0]['node']])
        self.assertEqual([k for k in self.intervals() if k != ran[0]['node']], [], 'the other same-scope node must not have started')
        winner = ran[0]['node']
        if any(r.get('state') == 'held' for r in results):
            return       # the losing call found its attempt already launched and held its own copy: the overlap rule above is what this test proves
        self.verify(winner)
        other = 'N2' if winner == 'N1' else 'N1'
        again = self.step(self.slow(0))
        self.assertEqual(again['node'], other)
        self.assertEqual(len(self.spans), 2)
        (a_start, a_end), (b_start, b_end) = self.spans[winner], self.spans[other]
        self.assertLessEqual(a_end, b_start)
        spans = self.intervals()
        self.assert_disjoint(spans[winner], spans[other])

    def test_t15c_e8_parallel_slots_are_refused_without_a_declared_isolate_capability(self):
        """W33b / T15c E8: asking the engine for two slots with an executor that declares no isolate is refused before any node starts."""
        with self.assertRaisesRegex(LedgerError, 'isolate'):
            self.engine.step(self.ledger, 'P1', self.slow(0), control=self.control, slots=2)
        self.assertEqual(self.intervals(), {})
