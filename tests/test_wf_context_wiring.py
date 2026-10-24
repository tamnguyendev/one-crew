"""W48a (T51a, "thu bằng mã"): the context is written by the code paths themselves, not only by a worker calling `context observe`.

Engine fixture (tests/test_wf_engine): the HD-05 decisions of the engine (Q2 eligibility, Q9 verification) and a verified node each leave one
`context.entry` whose source is the decision event / the published verifier receipt. Counter-rules: no entry per ordinary event (the entry count
stays far below the event count), a repeated decision adds nothing, and a context failure never undoes the decision record.
"""
from onecrew.v2 import context
from tests.test_wf_engine import EngineFixture, node


class ContextWiringTests(EngineFixture):
    def entries(self):
        return [p for k, p in self.events() if k == 'context.entry']

    def test_decisions_and_a_verified_node_write_sourced_entries_without_a_model(self):
        self.revise([node('C'), node('I', ['C'], integration=True, write=())])
        self.step()
        before = self.entries()
        self.assertTrue(before, 'the Q2 eligibility decision of the step left a decision entry')
        self.assertEqual({p['kind'] for p in before}, {'decision'})
        decision_ids = [p['source']['id'] for p in before]
        with self.ledger.transaction() as conn:
            kinds = [conn.execute('SELECT kind FROM events WHERE seq=?', (i,)).fetchone()['kind'] for i in decision_ids]
        self.assertEqual(set(kinds), {'decision.recorded'})                                        # source = the decision event itself
        self.verify('C')
        after = self.entries()
        done = [p for p in after if p['kind'] == 'task_done']
        self.assertEqual(len(done), 1)
        verification = [p for k, p in self.events() if k == 'node.verification'][-1]
        self.assertEqual(done[0]['source'], {'type': 'receipt', 'key': verification['receipt']})   # cites the published receipt
        self.assertEqual(done[0]['label'], 'verified'); self.assertIn('Node C', done[0]['text'])
        self.assertTrue(any(p['kind'] == 'decision' and 'Q9' in p['text'] for p in after))
        self.assertLess(len(after), len(self.events()) / 2, 'not one entry per event')             # T51a E1 counter-rule

    def test_a_repeated_decision_adds_no_entry_and_a_failed_verification_is_not_a_finished_task(self):
        self.revise([node('C'), node('I', ['C'], integration=True, write=())])
        self.step()
        self.verify('C')
        count = len(self.entries())
        from onecrew.v2 import internal_plan as ip
        with self.ledger.transaction() as conn:
            root, contract, sha = ip.context(self.ledger, conn, 'P1', 'sequential-engine')
            ctx = ip.ceilings(self.ledger, conn, root)
        ip.decide(self.ledger, root, contract, sha, {'kind': 'decision', 'q': 'Q12', 'nodes': ['C'], 'node_state': 'verified'}, ctx, 'onecrew.engine')
        first = len(self.entries())
        self.assertEqual(first, count + 1)
        ip.decide(self.ledger, root, contract, sha, {'kind': 'decision', 'q': 'Q12', 'nodes': ['C'], 'node_state': 'verified'}, ctx, 'onecrew.engine')
        self.assertEqual(len(self.entries()), first, 'same decision again: deduplicated by content')
        self.step()
        def red(item, artifact):
            return {'artifact': artifact, 'checks': [{'id': c['id'], 'result': 'fail', 'evidence': self.store.blob(b'fixture check failed')} for c in item['checks']]}
        self.verify('I', red)
        self.assertEqual(len([p for p in self.entries() if p['kind'] == 'task_done']), 1, 'a failed node is not a finished task')

    def test_the_context_write_never_undoes_the_decision_record(self):
        self.revise([node('C'), node('I', ['C'], integration=True, write=())])
        from unittest.mock import patch
        from onecrew.ledger import LedgerError
        decisions_before = len([1 for k, _ in self.events() if k == 'decision.recorded'])
        entries_before = self.entries()                                                              # the revision's own Q1 decision entry
        with patch.object(context, 'observe', side_effect=LedgerError('context unavailable')):
            self.step()
        self.assertGreater(len([1 for k, _ in self.events() if k == 'decision.recorded']), decisions_before)
        self.assertEqual(self.entries(), entries_before)
