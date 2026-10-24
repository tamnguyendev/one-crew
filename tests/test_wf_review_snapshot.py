"""W15 / T04b, T01: a review runs on a FIXED snapshot while the code node moves on.

Node C writes a.txt; node R reviews C (depends on C `produced`, writes nothing) and I integrates. The review
checker is a fixture that records exactly which artifact it was handed: it proves the engine interface,
not a real reviewer. A repair of C (new generation A2) must invalidate R's old result and require a new
review of A2; a repair that lands while R's checker is running must not let the old review publish.
"""
from onecrew.ledger import LedgerError
from onecrew.v2 import repair_tasks
from tests.test_wf_engine import EngineFixture, node


class ReviewSnapshotTests(EngineFixture):
    def setUp(self):
        super().setUp()
        review = node('R', ['C'], requires='produced', write=())
        review['depends'][0]['advance'] = {'limit': 2, 'discard_on_failure': True}
        self.revise([node('C'), review, node('I', ['C', 'R'], integration=True, write=())])
        self.reviewed = []

    def execute(self, ledger, control, task, item, attempt):
        # each generation of C yields a different snapshot (the fixture executor of EngineFixture is deterministic per node)
        control.launched(attempt['id'], attempt['generation'], {'fixture': True})
        artifact = self.store.blob(('artifact-' + item['id'] + '-' + attempt['id']).encode())
        receipt = self.store.blob(('executor-' + item['id'] + '-' + attempt['id']).encode())
        control.finish(attempt['id'], attempt['generation'], {'fixture': True, 'artifact': artifact})
        return {'artifact': artifact, 'receipt': receipt}

    def reviewer(self, item, artifact):
        self.reviewed.append(artifact)
        return self.checker(item, artifact)

    def produce_and_review(self):
        self.step()                                     # C -> A1
        view = self.engine.state(self.ledger, 'P1')
        a1 = view['nodes']['C']['artifact']
        self.assertEqual(self.step()['node'], 'R')     # R runs on the snapshot A1 (bounded advance on a produced C)
        self.verify('R', self.reviewer)
        return a1

    def test_review_receipt_binds_the_snapshot_it_was_given_and_a_new_generation_needs_a_new_review(self):
        a1 = self.produce_and_review()
        view = self.engine.state(self.ledger, 'P1')
        self.assertEqual(view['nodes']['R']['inputs']['C']['artifact'], a1)           # [E2] R is bound to A1
        self.assertEqual(self.reviewed, [view['nodes']['R']['artifact']])
        self.assertEqual(view['nodes']['R']['state'], 'verified')
        first_receipt = view['nodes']['R']['verification_receipt']
        # C moves on: a repair reissues C (generation +1). R depends on C, so its review of A1 no longer applies.
        self.verify('C', lambda item, artifact: {'artifact': artifact, 'checks': [
            {'id': c['id'], 'result': 'fail', 'evidence': self.store.blob(b'actual C check failed')} for c in item['checks']]})
        receipt = self.engine.state(self.ledger, 'P1')['nodes']['C']['verification_receipt']
        plan = repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='Repair C after its failed check', evidence=[receipt])
        self.assertIn('R', plan['affected_nodes'])
        after = self.engine.state(self.ledger, 'P1')
        self.assertEqual(after['nodes']['R']['generation'], view['nodes']['R']['generation'] + 1)
        self.assertEqual((after['nodes']['R']['phase'], after['nodes']['R']['state']), ('pending', None))       # [E3] A2 needs a new review
        self.assertIsNone(after['nodes']['R'].get('verification_receipt'))
        self.assertFalse(self.engine.root_ready(self.ledger, 'P1'))
        # C produces A2, R reviews A2: the new receipt binds A2, the old one is history (T01: results keyed by artifact+generation).
        self.assertEqual(self.step()['node'], 'C'); self.verify('C')
        a2 = self.engine.state(self.ledger, 'P1')['nodes']['C']['artifact']
        self.assertNotEqual(a2, a1)
        self.assertEqual(self.step()['node'], 'R')
        self.verify('R', self.reviewer)
        final = self.engine.state(self.ledger, 'P1')
        self.assertEqual(final['nodes']['R']['inputs']['C']['artifact'], a2)          # [E5]/[E6] the review of A2 saw A2
        self.assertNotEqual(final['nodes']['R']['verification_receipt'], first_receipt)
        self.assertEqual(len(self.reviewed), 2)

    def test_review_in_flight_when_code_moves_on_is_retained_not_published(self):
        self.step()
        self.assertEqual(self.step()['node'], 'R')
        def late_review(item, artifact):
            # while the review of A1 runs, C is repaired to a new generation
            self.verify('C', lambda i, a: {'artifact': a, 'checks': [
                {'id': c['id'], 'result': 'fail', 'evidence': self.store.blob(b'actual C check failed')} for c in i['checks']]})
            receipt = self.engine.state(self.ledger, 'P1')['nodes']['C']['verification_receipt']
            repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='Repair C while R reviews A1', evidence=[receipt])
            return self.reviewer(item, artifact)
        with self.assertRaisesRegex(LedgerError, 'retained without verification'):
            self.verify('R', late_review)
        view = self.engine.state(self.ledger, 'P1')
        self.assertEqual((view['nodes']['R']['phase'], view['nodes']['R']['state']), ('pending', None))
        self.assertIn('node.result_retained', self.kinds())
        self.assertFalse(self.engine.verification_ready(self.ledger, 'P1'))
