"""2.4-B, Codex review round 1, finding F3 (P2; D:/OneCrewRuns/v24/codex-r1/plan.md): the dependency walk of working_context.decide
stopped at a fixed depth and published what it had not explored. A result that depends directly or transitively on withdrawn or changed
knowledge (or on an input whose dependency check cannot be completed) must never be published or verified as current, whatever the
length of the chain, the order of the questions or a restart; an independent branch keeps going.

Integration tests: real engine + ledger in a temp dir, fake worker (no model call), built on tests.test_v24_b_context.BFixture like
Codex's chain_integration probe. Unit tests: the walk alone with the ledger reads patched (like Codex's depth_probe), for shapes a real
engine never writes (a cycle, a missing start record, the walk guard).
"""
import json
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

from onecrew.ledger import Ledger, LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import knowledge
from tests.test_v24_b_context import BFixture, auto, wc
from tests.test_wf_engine import EngineFixture, node


class Chains(BFixture):
    def chain(self, names, head=('a.txt',), after=None):
        """Nodes names[0] -> names[1] -> ...; the head reads and writes `head`, the others report on b.txt; each needs the previous verified."""
        items, prev = [], after
        for i, n in enumerate(names):
            item = self.item(n, read=head if i == 0 and after is None else ('b.txt',), write=head if i == 0 and after is None else ())
            if prev: item['depends'] = [{'node': prev, 'requires': 'verified'}]
            items.append(item); prev = n
        return items

    def run_all(self, items, open_=()):
        """Produce every item (dependency order chosen by the engine); verify all but `open_`."""
        self.values += [auto] * len(items)
        for _ in items:
            r = self.step()
            self.assertEqual(r['state'], 'produced', r)
            if r['node'] not in open_: self.check(r['node'])

    def attempts(self, ledger=None):
        return {p['node']: p['attempt'] for k, p in self.events() if k == 'node.started'}

    def decision(self, n, memo=None, ledger=None):
        ledger = ledger or self.ledger
        record = self.engine.state(ledger, 'P1')['nodes'][n]
        return wc().decide(ledger, Snapshots(ledger.state_root), 'P1', n, self.attempts()[n], receipt_key=record.get('receipt'), memo=memo)

    def actions(self, names, memo=None):
        return {n: self.decision(n, memo)['action'] for n in names}

    def refused(self, n, ledger=None):
        """engine.verify(n) is refused, writes no verification of n, makes no model call, resets no budget; returns the error text."""
        ledger = ledger or self.ledger
        before = len(self.calls)
        with self.assertRaisesRegex(LedgerError, 'knowledge') as caught:
            self.engine.verify(ledger, 'P1', n, self.checker)
        self.assertEqual(len(self.calls), before)
        self.assertNotIn(n, [p['node'] for k, p in self.events() if k == 'node.verification'])
        self.assertFalse([p for k, p in self.events() if k == 'node.resumed' and p.get('budget_reset')])
        record = self.engine.state(ledger, 'P1')['nodes'][n]
        self.assertNotEqual(record.get('state'), 'verified')
        return str(caught.exception)


class LongChainTests(Chains):
    NAMES = 'ABCDEFG'                                                               # 7 nodes, the head 6 inputs away from the leaf

    def test_f3_a_long_chain_withdrawn_at_the_head_is_never_published_or_verified(self):
        rule = self.fact('Keep a.txt to one line', must=True)
        self.plan(*self.chain(self.NAMES))
        self.run_all(self.chain(self.NAMES), open_=('G',))
        self.withdraw(rule)
        self.assertEqual(self.actions(self.NAMES), dict(A='recheck', **{n: 'input_changed' for n in self.NAMES[1:]}))
        leaf = self.decision('G')
        self.assertEqual([(u['node'], u['ids']) for u in leaf['upstream']], [('F', [rule])])
        text = self.refused('G')
        self.assertIn('F', text)
        held = self.engine.state(self.ledger, 'P1')['nodes']['G']
        self.assertEqual((held['phase'], held.get('classification')), ('held', 'input_changed'))

    def test_f3_b_any_order_or_prewarmed_memo_gives_the_same_answers(self):
        rule = self.fact('Keep a.txt to one line', must=True)
        self.plan(*self.chain(self.NAMES))
        self.run_all(self.chain(self.NAMES), open_=('G',))
        self.withdraw(rule)
        expected = dict(A='recheck', **{n: 'input_changed' for n in self.NAMES[1:]})
        fresh = self.actions(self.NAMES)                                             # a new memo per question
        forward, backward, warm = {}, {}, {}
        shared_f = {n: self.decision(n, forward)['action'] for n in self.NAMES}
        shared_b = {n: self.decision(n, backward)['action'] for n in reversed(self.NAMES)}
        self.decision('C', warm); self.decision('E', warm)                          # a memo pre-warmed in the middle of the chain
        shared_w = {n: self.decision(n, warm)['action'] for n in ('G', 'B', 'F', 'A', 'D')}
        for got in (fresh, shared_f, shared_b):
            self.assertEqual(got, expected)
        self.assertEqual(shared_w, {n: expected[n] for n in shared_w})
        ids = {n: sorted(i for u in self.decision(n, backward)['upstream'] for i in u['ids']) for n in self.NAMES[1:]}
        self.assertEqual(ids, {n: [rule] for n in self.NAMES[1:]})

    def test_f3_c_a_restart_between_withdrawal_and_verify_rederives_the_hold_from_the_ledger(self):
        rule = self.fact('Keep a.txt to one line', must=True)
        self.plan(*self.chain(self.NAMES))
        self.run_all(self.chain(self.NAMES), open_=('G',))
        self.withdraw(rule)
        restarted = Ledger(self.root, self.ledger.state_root)                       # a new controller: nothing kept in memory
        self.assertEqual(self.decision('G', ledger=restarted)['action'], 'input_changed')
        self.refused('G', ledger=restarted)

    def test_f3_d_a_newer_version_of_a_mandatory_entry_propagates_transitively(self):
        first = knowledge.record(self.ledger, 'P1', kind='decision', text='Keep a.txt to one line', applies_to=['a.txt'], must=True,
                                 key='one-line', evidence={'status': 'verified', 'property': 'decided in review',
                                                           'sources': [{'type': 'event', 'id': self.last_event()}]})
        self.plan(*self.chain(self.NAMES))
        self.run_all(self.chain(self.NAMES), open_=('G',))
        second = knowledge.record(self.ledger, 'P1', kind='decision', text='Keep a.txt to one line without tabs', applies_to=['a.txt'],
                                  must=True, key='one-line', base=first['version'],
                                  evidence={'status': 'verified', 'property': 'decided in review again',
                                            'sources': [{'type': 'event', 'id': self.last_event()}]})
        self.assertEqual(second['id'], first['id'])                                  # the same entry, a new version (not withdrawn)
        head = self.decision('A')
        self.assertEqual(head['action'], 'recheck')
        self.assertEqual([(c['id'], c['reason']) for c in head['critical']], [(first['id'], 'a newer version')])
        self.assertEqual(self.actions(self.NAMES[1:]), {n: 'input_changed' for n in self.NAMES[1:]})
        self.refused('G')


class ShapeTests(Chains):
    def test_f3_e_fan_in_holds_the_join_and_the_independent_branch_goes_on(self):
        rule = self.fact('Keep a.txt to one line', must=True)
        one = self.chain(['A1', 'B1', 'C1', 'D1'])
        two = self.chain(['A2', 'B2', 'C2', 'D2'], head=('b.txt',))
        tail = self.chain(['X2'], after='D2')
        join = self.item('J', read=('b.txt',), write=())
        join['depends'] = [{'node': 'D1', 'requires': 'verified'}, {'node': 'D2', 'requires': 'verified'}]
        items = one + two + tail + [join]
        self.plan(*items)
        self.run_all(items, open_=('J', 'X2'))
        self.assertEqual({r['node'] for r in self.delivered() if rule in [e['id'] for e in r['entries']]}, {'A1'})
        self.withdraw(rule)
        self.assertEqual(self.actions(['A2', 'B2', 'C2', 'D2', 'X2']), {n: 'publish' for n in ['A2', 'B2', 'C2', 'D2', 'X2']})
        self.assertEqual(self.actions(['A1', 'D1', 'J']), {'A1': 'recheck', 'D1': 'input_changed', 'J': 'input_changed'})
        self.assertEqual([(u['node'], u['ids']) for u in self.decision('J')['upstream']], [('D1', [rule])])
        self.refused('J')
        self.check('X2')                                                             # the branch that does not depend on it is verified
        self.assertIn('X2', [p['node'] for k, p in self.events() if k == 'node.verification' and p['result'] == 'pass'])

    def test_f3_f_fan_out_holds_only_the_branch_built_on_the_withdrawn_entry(self):
        rule = self.fact('Keep a.txt to one line', must=True)
        head = self.chain(['H'], head=('b.txt',))
        one = self.chain(['K1'], after='H')
        one[0]['read'], one[0]['write'] = ['a.txt'], ['a.txt']                      # only this branch receives the rule
        one += self.chain(['L1', 'M1', 'N1', 'O1'], after='K1')
        two = self.chain(['K2', 'L2'], after='H')
        items = head + one + two
        self.plan(*items)
        self.run_all(items, open_=('O1', 'L2'))
        self.assertEqual({r['node'] for r in self.delivered() if rule in [e['id'] for e in r['entries']]}, {'K1'})
        self.withdraw(rule)
        self.assertEqual(self.actions(['H', 'K2', 'L2']), {'H': 'publish', 'K2': 'publish', 'L2': 'publish'})
        self.assertEqual(self.actions(['K1', 'L1', 'M1', 'N1', 'O1']),
                         {'K1': 'recheck', 'L1': 'input_changed', 'M1': 'input_changed', 'N1': 'input_changed', 'O1': 'input_changed'})
        self.refused('O1')
        self.check('L2')
        self.assertIn('L2', [p['node'] for k, p in self.events() if k == 'node.verification' and p['result'] == 'pass'])

    def test_f3_g_an_unreadable_input_receipt_is_not_published(self):
        items = self.chain(['A', 'B', 'C', 'D'])
        self.plan(*items)
        self.run_all(items, open_=('D',))
        receipt = self.engine.state(self.ledger, 'P1')['nodes']['A']['receipt']
        (self.store.root / 'blobs' / receipt).unlink()                               # the store lost the receipt of the head
        leaf = self.decision('D')
        self.assertEqual(leaf['action'], 'input_changed', leaf)
        why = ' '.join(x for u in leaf['upstream'] for x in [u['reason']] + u.get('unchecked', []))
        self.assertIn('could not be completed', why)
        self.assertIn('receipt of input A', why)
        self.assertIn('A', self.refused('D'))


class OpaqueReceiptTests(EngineFixture):
    def test_f3_l_an_opaque_receipt_of_another_executor_is_placed_by_the_ledger_and_walked_through(self):
        self.revise([node('A'), node('B', ['A'], write=('b.txt',)), node('C', ['B'], write=('b.txt',)),
                     node('I', ['A', 'B', 'C'], integration=True, write=())])
        for nid in 'AB':
            self.assertEqual(self.step()['node'], nid)
            self.engine.verify(self.ledger, 'P1', nid, self.checker)
        self.assertEqual(self.step()['state'], 'produced')
        view = self.engine.state(self.ledger, 'P1')
        self.assertEqual(self.store.read_blob(view['nodes']['B']['receipt']), b'executor-B')      # names no attempt
        memo = {}
        decision = wc().decide(self.ledger, self.store, 'P1', 'C', view['nodes']['C']['attempt'], receipt_key=view['nodes']['C']['receipt'],
                               memo=memo)
        self.assertEqual(decision['action'], 'publish', decision)
        walked = {k[1]: k[2] for k in memo if isinstance(k, tuple) and k[:1] == ('decision',)}
        self.assertEqual(walked, {'A': view['nodes']['A']['attempt'], 'B': view['nodes']['B']['attempt']})


# ---- the walk alone (ledger reads patched, as Codex's depth_probe) ------------------------------------------------------------------

def walk(parents, critical=(), missing_start=(), opaque=(), memo=None):
    """{node: action} of decide() for every node of `parents` ({node: [producer, ...]}); attempt id = node name, receipt key = node name."""
    from onecrew.v2 import working_context as w
    ledger = SimpleNamespace(transaction=lambda *a, **k: nullcontext(object()))
    store = SimpleNamespace(read_blob=lambda key: b'not a json receipt')
    def started(conn, root, attempt):
        return None if attempt in missing_start else {'inputs': {p: {'receipt': p} for p in parents[attempt]}}
    def own(l, s, c, p, n, a, row, st, receipt, memo_):
        return ([{'id': 'withdrawn-fact', 'reason': 'withdrawn', 'was': 'fact', 'must': True}] if n in critical else [], [])
    with patch.object(w.namespaces, 'resolve', return_value={'id': 'root', 'request_key': 'plan:P'}), \
         patch.object(w.namespaces, 'parse', return_value=('P', None)), patch.object(w, '_row', return_value=None), \
         patch.object(w, '_started', side_effect=started), \
         patch.object(w, '_receipt', side_effect=lambda s, k: None if k in opaque else {'attempt': k} if k else None), \
         patch.object(w, '_attempt_of', return_value=None, create=True), patch.object(w, '_own', side_effect=own):
        return {n: w.decide(ledger, store, 'P', n, n, receipt_key=n, memo=memo) for n in parents}


class WalkTests(unittest.TestCase):
    def test_f3_h_a_chain_of_forty_is_walked_to_the_head(self):
        names = ['N%02d' % i for i in range(40)]
        parents = {n: ([names[i - 1]] if i else []) for i, n in enumerate(names)}
        got = walk(parents, critical={'N00'})
        self.assertEqual(got['N00']['action'], 'recheck')
        self.assertEqual({n: got[n]['action'] for n in names[1:]}, {n: 'input_changed' for n in names[1:]})
        self.assertEqual(got['N39']['upstream'][0]['ids'], ['withdrawn-fact'])

    def test_f3_i_a_cycle_terminates_and_is_not_published(self):
        got = walk({'A': ['B'], 'B': ['A'], 'C': ['B']})
        self.assertEqual({n: d['action'] for n, d in got.items()}, {'A': 'input_changed', 'B': 'input_changed', 'C': 'input_changed'})
        self.assertTrue(all('cycle' in ' '.join(sum((u.get('unchecked', []) for u in d['upstream']), [])) for d in got.values()), got)

    def test_f3_j_a_missing_start_record_or_unknown_producer_is_not_published(self):
        got = walk({'A': [], 'B': ['A'], 'C': ['B'], 'D': ['C']}, missing_start={'B'})
        self.assertEqual(got['D']['action'], 'input_changed')
        self.assertIn('start record', ' '.join(sum((u.get('unchecked', []) for u in got['D']['upstream']), [])))
        self.assertEqual(got['A']['action'], 'publish')                              # what does not depend on it is untouched
        got = walk({'A': [], 'B': ['A'], 'C': ['B']}, opaque={'A'})                    # an opaque receipt the ledger cannot place
        self.assertEqual((got['B']['action'], got['C']['action']), ('input_changed', 'input_changed'))
        self.assertIn('attempt that produced input A', ' '.join(sum((u.get('unchecked', []) for u in got['C']['upstream']), [])))

    def test_f3_k_the_walk_guard_fails_closed(self):
        from onecrew.v2 import working_context as w
        names = ['N%d' % i for i in range(10)]
        parents = {n: ([names[i - 1]] if i else []) for i, n in enumerate(names)}
        with patch.object(w, 'MAX_WALK', 4):
            got = walk(parents)
        self.assertEqual(got['N0']['action'], 'publish')
        self.assertEqual(got['N9']['action'], 'input_changed')
        self.assertIn('more than 4', ' '.join(sum((u.get('unchecked', []) for u in got['N9']['upstream']), [])))
        self.assertEqual(walk(parents)['N9']['action'], 'publish')                   # nothing changed, nothing unreadable: published


if __name__ == '__main__':
    unittest.main()
