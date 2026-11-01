"""2.4-B (ROADMAP-DESIGN §2.4b, MEM-03 of §2.4d, the 2.4-B row of §7; map-ab §4): working context per consumer.

What 2.3 delivers to a native attempt (the knowledge package, tests/test_v23_a1_knowledge) is now identified per attempt and generation
(`knowledge.delivered`, class A, written before launch). A withdrawal, a supersession, a changed source or a new mandatory entry acts only
on the consumers that received what changed (and on what consumed their artifacts): a running consumer gets the delta at its next safe
point (a continuation or a resumed generation), and a candidate is rechecked before it is published or verified - never published as
current on withdrawn knowledge, also after a crash and a rebuild. Independent branches run on. No new store: the ledger and the package
blobs only. Nothing here claims that a model understood or forgot anything.

Checkout tests on real git repositories and ledgers; the worker is a fixture (no model call). The installed-wheel case is
tests/test_v24_b_installed.py.
"""
import copy
import json
import os
from unittest.mock import patch

from onecrew.common_executor import NativeExecutor
from onecrew.ledger import LedgerError, canonical
from onecrew.v2 import compat, knowledge, plan as plans
from tests.test_v23_a1_knowledge import KnowledgeFixture, PIN
from tests.test_v24_a_sources import WorkerMixin, SourceFixture, ask, body_of
from tests.test_v2_l1 import plan_json
from tests.test_wf_engine import node


def wc():
    from onecrew.v2 import working_context
    return working_context


def auto(prompt, schema):
    """Answer any node: a write node writes its first file, a report node reports; nothing else."""
    item = body_of(prompt)['node']
    if item['write']:
        return {'summary': 'done', 'files': [{'path': item['write'][0], 'content': item['id'] + ' done\n'}], 'backlog': []}
    return {'summary': 'reported', 'evidence': []}


def partial(path='a.txt', used=()):
    return {'summary': 'part', 'files': [{'path': path, 'content': 'partial\n'}], 'backlog': [],
            'continuation': {'remaining': 'finish the file'}, 'knowledge': {'used': list(used)}}


class Crash(BaseException):
    """The controller dies (os._exit in a real run)."""


class AllEvents:
    def events(self, name='P1'):                                                    # every event of the root (ledger.events pages 200)
        with self.ledger.transaction() as conn:
            task = plans.derive(self.ledger, conn, name)['task_id']
            return [(r['kind'], json.loads(r['payload'])) for r in conn.execute('SELECT kind,payload FROM events WHERE task_id=? ORDER BY seq', (task,))]


class BFixture(AllEvents, WorkerMixin, KnowledgeFixture):
    managed = False

    def setUp(self):
        super().setUp()
        self.start_worker()

    def factory(self, control, provider):
        worker = super().factory(control, provider)
        if not self.managed: return worker
        case, real = self, worker
        class Managed:                                # what a contained Supervisor run leaves, so the managed rebuild path accepts it
            def capability(self): return real.capability()
            def run(self, attempt, prompt, schema, profile):
                case.calls.append({'prompt': prompt, 'schema': schema, 'attempt': attempt['id'], 'provider': provider})
                control.launched(attempt['id'], attempt['generation'], {'fixture': True, 'job_contained': True})
                control.finish(attempt['id'], attempt['generation'], {'exit_code': 0, 'tree_stopped': True, 'stdout': 'out', 'stderr': 'err',
                                                                      'seconds': 0.1})
            def result(self, attempt): return real.result(attempt)
        return Managed()

    def last_event(self):
        with self.ledger.transaction() as conn:
            return conn.execute("SELECT MAX(e.seq) FROM events e JOIN tasks t ON t.id=e.task_id WHERE t.project_id=?",
                                (self.ledger.project_id,)).fetchone()[0]

    def fact(self, text, must=False, applies=('a.txt',), plan='P1'):
        return knowledge.record(self.ledger, plan, kind='decision', text=text, applies_to=list(applies), must=must,
                                evidence={'status': 'verified', 'property': 'decided in review',
                                          'sources': [{'type': 'event', 'id': self.last_event()}]})['id']

    def withdraw(self, ident, plan='P1'):
        knowledge.withdraw(self.ledger, plan, ident, reason='no longer true', evidence={'sources': [{'type': 'event', 'id': self.last_event()}]})

    def integration(self, depends):
        return dict(node('I', list(depends), integration=True, write=()), executor=dict(PIN))

    def plan(self, *items, name='P1'):
        return self.ip.revise(self.ledger, name, [*items, self.integration([i['id'] for i in items])],
                              reason='Working context fixture', evidence=['a.txt:1'])

    def step(self, adapter=None, name='P1'):
        return self.engine.step(self.ledger, name, adapter or self.adapter)

    def delivered(self, name='P1'):
        return [p for k, p in self.events(name) if k == 'knowledge.delivered']

    def package(self, call=-1):
        return body_of(self.calls[call]['prompt']).get('knowledge') or {}

    def ids(self, pkg):
        return [e['id'] for e in pkg.get('entries', []) + pkg.get('requested', [])]

    def receipt(self, key):
        return json.loads(self.store.read_blob(key))

    def check(self, nid, name='P1'):
        return self.engine.verify(self.ledger, name, nid, self.checker)


class RecordTests(BFixture):
    def test_sb01_delivery_record_names_attempt_generation_entries_and_blobs(self):
        rule = self.fact('Keep a.txt to one line', must=True)
        self.plan(self.item('C'))
        self.values.append(auto)
        produced = self.step()
        self.assertEqual(produced['state'], 'produced', produced)
        rows = self.delivered()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        started = next(p for k, p in self.events() if k == 'node.started')
        receipt = self.receipt(produced['receipt'])
        self.assertEqual((row['node'], row['generation'], row['attempt'], row['task']), ('C', 0, started['attempt'], started['child']))
        self.assertEqual((row['package'], row['revision']), (receipt['knowledge']['package'], receipt['knowledge']['revision']))
        entry = next(e for e in row['entries'] if e['id'] == rule)
        self.assertEqual((entry['use'], entry['must']), ('fact', True))
        self.assertIsInstance(entry['event'], int)
        self.assertEqual([s['path'] for s in entry['sources']], ['a.txt'])
        self.assertRegex(entry['sources'][0]['blob'], r'^[0-9a-f]{40}$')
        self.assertEqual(row['consumer_paths'], ['a.txt'])
        self.assertEqual(compat.event_class('knowledge.delivered'), 'A')
        seq = wc().row_for_attempt(self.ledger, 'P1', row['attempt'])['event']
        self.assertEqual(wc().record_delivery(self.ledger, 'P1', self.ip.current(self.ledger, 'P1')['definition']['nodes'][0],
                                              {'id': row['attempt']}, {'id': row['task']}, receipt['knowledge'], None), seq)
        self.assertEqual(len(self.delivered()), 1)                                 # idempotent per attempt

    def test_sb01b_a_root_without_knowledge_writes_no_record(self):
        self.plan(self.item('C'))
        self.values.append(auto)
        self.assertEqual(self.step()['state'], 'produced')
        self.assertEqual(self.delivered(), [])


class InvalidationTests(BFixture):
    def three(self):
        a = self.item('A')
        b = self.item('B', read=('a.txt',), write=())
        c = self.item('C2', read=('b.txt',), write=('b.txt',))
        self.plan(a, b, c)
        self.values += [auto] * 3
        for _ in range(3): self.assertEqual(self.step()['state'], 'produced')

    def test_sb02_withdraw_maps_to_affected_open_consumers_only(self):
        rule = self.fact('Keep a.txt to one line', must=True)
        self.three()
        received = {r['node'] for r in self.delivered() if rule in [e['id'] for e in r['entries']]}
        self.assertEqual(received, {'A', 'B'})
        self.withdraw(rule)
        affected = wc().affected_consumers(self.ledger, 'P1', [rule])
        self.assertEqual(sorted(a['node'] for a in affected), ['A', 'B'])
        self.assertTrue(all(a['ids'] == [rule] for a in affected))
        self.check('C2')                                                             # the independent branch is verified as before
        self.assertIn('node.verification', self.kinds())
        with self.assertRaisesRegex(LedgerError, 'knowledge'):
            self.check('A')
        resumed = [p for k, p in self.events() if k == 'node.resumed' and p['node'] == 'A']
        self.assertEqual(len(resumed), 1)
        self.assertFalse(resumed[0]['budget_reset'])
        self.assertEqual(resumed[0]['knowledge_changed']['critical'][0]['id'], rule)

    def test_sb08_multi_producer_consumer_delta_and_stale_delta_holds_only_affected_branch(self):
        rule = self.fact('Keep a.txt to one line', must=True)
        advance = {'limit': 1, 'discard_on_failure': True}
        p1, p2 = self.item('P1n'), self.item('P2n', read=('b.txt',), write=('b.txt',))
        k = self.item('K', read=('b.txt',), write=())
        k['depends'] = [{'node': 'P1n', 'requires': 'produced', 'advance': advance}, {'node': 'P2n', 'requires': 'produced', 'advance': advance}]
        self.plan(p1, p2, k)
        self.values += [auto] * 3
        for _ in range(3): self.assertEqual(self.step()['state'], 'produced')
        self.assertEqual({r['node'] for r in self.delivered() if rule in [e['id'] for e in r['entries']]}, {'P1n'})
        self.withdraw(rule)
        affected = {a['node']: a for a in wc().affected_consumers(self.ledger, 'P1', [rule])}
        self.assertEqual(sorted(affected), ['K', 'P1n'])
        self.assertEqual(affected['K']['via'], 'P1n')
        self.check('P2n')                                                            # the unaffected producer
        with self.assertRaisesRegex(LedgerError, 'knowledge'):
            self.check('K')                                                          # it consumed an artifact built on withdrawn knowledge
        with self.assertRaisesRegex(LedgerError, 'knowledge'):
            self.check('P1n')
        verified = [p['node'] for k_, p in self.events() if k_ == 'node.verification']
        self.assertEqual(verified, ['P2n'])

    def test_sb10_two_roots_regression(self):
        rule = self.fact('Keep a.txt to one line', must=True)
        value = plan_json(scope={'owned': ['a.txt', 'b.txt']}, authority={'edit': True, 'commands': True, 'edit_tests': True,
                                                                          'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']})
        plans.propose(self.ledger, 'P2', value, 'codex', workflow=True, capabilities=self.engine_caps)
        actor = os.environ.pop('ONECREW_ACTOR', None)                              # the fixture owner approves (as A2Fixture.root_b)
        try:
            plans.approve(self.ledger, 'P2', 'owner', 'fixture approval of root B')
        finally:
            if actor is not None: os.environ['ONECREW_ACTOR'] = actor
        self.plan(self.item('A1'), name='P1')                                       # root A has a consumer of its own
        self.plan(self.item('C'), name='P2')
        self.values += [lambda p, s: partial(used=[rule]), lambda p, s: partial(used=[rule]), auto]
        self.assertEqual(self.step(name='P1')['state'], 'continuing')
        self.assertEqual(self.step(name='P2')['state'], 'continuing')
        self.assertIn(rule, self.ids(self.package(1)))
        self.withdraw(rule, plan='P1')                                              # root A withdraws its project knowledge
        both = wc().affected_consumers(self.ledger, None, [rule])
        self.assertEqual(sorted((a['plan'], a['node']) for a in both), [('P1', 'A1'), ('P2', 'C')])
        self.assertEqual([(a['plan'], a['node']) for a in wc().affected_consumers(self.ledger, 'P2', [rule])], [('P2', 'C')])
        self.assertEqual([(a['plan'], a['node']) for a in wc().affected_consumers(self.ledger, 'P1', [rule])], [('P1', 'A1')])
        self.assertEqual([c['node'] for c in wc().consumers_report(self.ledger, 'P2')['consumers']], ['C'])
        restarted = NativeExecutor(self.ledger)
        self.assertEqual(self.step(restarted, name='P2')['state'], 'produced')
        pkg = self.package(2)
        self.assertNotIn(rule, self.ids(pkg))
        self.assertEqual([w['id'] for w in pkg['delta']['withdrawn']], [rule])


class SafePointTests(BFixture):
    def test_sb03_continuation_gets_delta_not_full_history(self):
        hint = self.fact('a.txt uses unix newlines')
        for i in range(5): self.fact(f'a.txt detail {i} that stays as it was')
        self.plan(self.item('C'))
        self.values += [lambda p, s: partial(used=[hint]), auto]
        self.assertEqual(self.step()['state'], 'continuing')
        self.withdraw(hint)
        rule = self.fact('a.txt must end with a newline', must=True)
        self.assertEqual(self.step()['state'], 'produced')
        pkg = self.package(1)
        self.assertEqual(pkg['delta']['withdrawn'], [{'id': hint, 'reason': 'withdrawn'}])
        self.assertEqual(pkg['delta']['added_mandatory'], [rule])
        self.assertNotIn(hint, self.ids(pkg))
        self.assertLess(len(canonical(pkg['delta'])), 600)                          # ids and reasons, not the history of the package
        self.assertNotIn('detail 0', canonical(pkg['delta']))
        rows = self.delivered()
        self.assertEqual(rows[-1]['delta']['withdrawn'][0]['id'], hint)
        self.assertEqual(self.receipt(self.engine.state(self.ledger, 'P1')['nodes']['C']['receipt'])['knowledge']['delta']['withdrawn'][0]['id'], hint)

    def test_sb06_partial_candidate_from_withdrawn_entry_is_rechecked_in_next_generation(self):
        hint = self.fact('a.txt holds the partial format')
        self.plan(self.item('C'))
        self.values += [lambda p, s: partial(used=[hint]), auto]
        self.assertEqual(self.step()['state'], 'continuing')
        self.withdraw(hint)
        produced = self.step()
        self.assertEqual(produced['state'], 'produced')
        delta = self.package(1)['delta']
        self.assertEqual(delta['withdrawn'][0]['id'], hint)
        self.assertTrue(delta['recheck_partial'])                                    # the candidate it continues was built with it
        self.assertNotIn(hint, self.ids(self.package(1)))


class GateTests(BFixture):
    def test_sb04_candidate_using_withdrawn_must_is_not_published_as_current(self):
        rule = self.fact('Keep a.txt to one line', must=True)
        self.plan(self.item('C'))
        def withdrawing(prompt, schema):
            self.assertIn(rule, self.ids(body_of(prompt)['knowledge']))
            self.withdraw(rule)                                                      # while the worker runs
            return auto(prompt, schema)
        self.values += [withdrawing, auto]
        first = self.step()
        self.assertEqual(first['state'], 'continuing', first)
        self.assertEqual(first['knowledge_changed']['critical'], [{'id': rule, 'reason': 'withdrawn', 'was': 'fact', 'must': True}])
        self.assertNotIn('node.produced', self.kinds())
        resumed = next(p for k, p in self.events() if k == 'node.resumed')
        self.assertFalse(resumed['budget_reset'])
        second = self.step()
        self.assertEqual(second['state'], 'produced')
        self.assertEqual(len(self.calls), 2)                                         # the run and one recheck
        pkg = self.package(1)
        self.assertNotIn(rule, self.ids(pkg))
        self.assertEqual(pkg['delta']['withdrawn'][0]['id'], rule)

    def test_sb04b_without_room_for_a_recheck_the_candidate_is_held(self):
        rule = self.fact('Keep a.txt to one line', must=True)
        self.plan(self.item('C'))
        def withdrawing(prompt, schema):
            self.withdraw(rule)
            return auto(prompt, schema)
        self.values.append(withdrawing)
        with patch.object(wc(), 'MAX_RECHECKS', 0):
            held = self.step()
        self.assertEqual(held['state'], 'held', held)
        event = next(p for k, p in self.events() if k == 'node.held')
        self.assertEqual(event['classification'], 'knowledge_changed')
        self.assertTrue(event['candidate']['artifact'])
        self.assertNotIn('node.produced', self.kinds())

    def test_sb05_restart_rebuild_after_withdraw_does_not_revive(self):
        from onecrew.v2 import managed_executor
        self.managed = True
        rule = self.fact('Keep a.txt to one line', must=True)
        self.plan(self.item('C'))
        adapter = managed_executor.ManagedExecutor(self.ledger)
        self.values += [auto, auto, auto]                                            # the run, its rebuild from the settled outputs, the recheck
        real = adapter._write
        def dying(attempt_id, phase, **facts):
            if phase == 'candidate': raise Crash()
            return real(attempt_id, phase, **facts)
        with patch.object(adapter, '_write', side_effect=dying):
            with self.assertRaises(Crash):
                self.step(adapter)
        attempt = next(p for k, p in self.events() if k == 'node.started')['attempt']
        self.withdraw(rule)
        restarted = managed_executor.ManagedExecutor(self.ledger)
        recovered = restarted.recover(attempt)
        self.assertEqual(recovered.get('rebuilt_from'), 'settled-process', recovered)
        adopted = self.step(restarted)
        self.assertEqual(adopted['state'], 'continuing', adopted)
        self.assertTrue(adopted.get('adopted_after_crash'))
        self.assertNotIn('node.produced', self.kinds())
        self.assertEqual(self.step(restarted)['state'], 'produced')
        pkg = self.package(-1)
        self.assertNotIn(rule, self.ids(pkg))
        self.assertEqual(pkg['requested'], [])

    def test_sb09_late_result_after_generation_move_never_published(self):
        rule = self.fact('Keep a.txt to one line', must=True)
        self.plan(self.item('C'))
        def late(prompt, schema):
            self.withdraw(rule)
            with self.ledger.transaction(write=True) as conn:            # another controller moved the generation while this one ran
                view = self.engine.state(self.ledger, 'P1', conn)
                self.engine._event(self.ledger, conn, view, 'C', 'node.resumed', reason='taken over by another controller', budget_reset=False)
            return auto(prompt, schema)
        self.values.append(late)
        result = self.step()
        self.assertEqual(result['state'], 'retained', result)
        self.assertNotIn('node.produced', self.kinds())
        self.assertFalse([p for k, p in self.events() if k == 'node.resumed' and p.get('knowledge_changed')])
        self.assertEqual(self.engine.state(self.ledger, 'P1')['nodes']['C']['generation'], 1)


class SourceChangeTests(AllEvents, SourceFixture):
    def test_sb07_source_change_marks_recheck_for_readers_of_that_file_only(self):
        reader = self.item('R1', patterns=('src/',))
        other = self.item('R2', read=('a.txt',), write=('a.txt',), patterns=('docs/',))
        self.plan(reader, other)
        rounds = {'R1': 0, 'R2': 0}
        def script(prompt, schema):
            nid = body_of(prompt)['node']['id']
            rounds[nid] += 1
            if rounds[nid] == 1:
                return ask({'op': 'read', 'path': 'src/lib/x.py' if nid == 'R1' else 'docs/guide.md'})
            if nid == 'R1' and rounds[nid] == 2:
                (self.root / 'src' / 'lib' / 'x.py').write_text('def helper():\n    return 43\n')     # changed while R1 worked on it
            target = body_of(prompt)['node']['write'][0]
            return {'summary': 'done', 'files': [{'path': target, 'content': nid + '\n'}], 'backlog': []}
        self.values += [script] * 6
        states = [self.step()['state'] for _ in range(5)]
        self.assertEqual(states[:2], ['continuing', 'continuing'])                     # R1 round 1, then R1 rechecked
        resumed = [p for k, p in self.events() if k == 'node.resumed' and p.get('knowledge_changed')]
        self.assertEqual([p['node'] for p in resumed], ['R1'])
        self.assertEqual(resumed[0]['knowledge_changed']['critical'][0]['reason'], 'source changed since it was read')
        self.assertEqual(resumed[0]['knowledge_changed']['critical'][0]['path'], 'src/lib/x.py')
        produced = [p['node'] for k, p in self.events() if k == 'node.produced']
        self.assertIn('R2', produced)                                                  # the reader of another file is published
        trees = [p['source_tree']['tree'] for k, p in self.events() if k == 'node.started' and p['node'] == 'R1']
        self.assertNotEqual(trees[0], trees[-1])                                       # the recheck reads a newly pinned tree


class CliTests(BFixture):
    def test_wiki_consumers_lists_delivery_and_delta_status(self):
        import contextlib
        import io
        from onecrew.v2 import cli
        rule = self.fact('Keep a.txt to one line', must=True)
        self.plan(self.item('C'))
        self.values.append(lambda p, s: partial(used=[rule]))
        self.step()
        def run():
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'wiki', 'consumers', '--plan', 'P1'])
            return code, json.loads(out.getvalue())
        code, before = run()
        self.assertEqual(code, 0, before)
        self.assertEqual([(c['node'], c['status']) for c in before['consumers']], [('C', 'none')])
        self.withdraw(rule)
        code, after = run()
        self.assertEqual(after['consumers'][0]['status'], 'withdrawn')
        self.assertEqual(after['consumers'][0]['delta']['withdrawn'][0]['id'], rule)
        self.assertTrue(after['data_not_authority'])


if __name__ == '__main__':
    import unittest
    unittest.main()


def claimed(text, path='a.txt', content='right\n', check='check-C'):
    claim = {'kind': 'finding', 'text': text, 'applies_to': [path], 'sources': [path], 'check': check}
    return {'summary': 'done', 'files': [{'path': path, 'content': content}], 'backlog': [],
            'knowledge': {'used': [], 'rejected': [], 'requests': [], 'new': [claim]}}


class ReviewBTests(BFixture):
    """The independent review of 26a86e7..58b863f (D:/OneCrewRuns/v24/review-b/review-b.md): its probes as tests."""

    def test_b_r01_a_consumer_of_a_verified_upstream_claim_is_published_at_once(self):
        c = self.item('C', read=('a.txt', 'b.txt'), write=('a.txt',))
        d = self.item('D', read=('a.txt', 'b.txt'), write=('b.txt',))
        d['depends'] = [{'node': 'C', 'requires': 'verified'}]
        self.plan(c, d)
        self.values.append(claimed('a.txt must hold VALUE: right'))
        self.assertEqual(self.step()['state'], 'produced')
        self.check('C')
        learned = [r['id'] for r in knowledge.records(self.ledger) if r['text'] == 'a.txt must hold VALUE: right' and r['visibility'] == 'project']
        self.assertTrue(learned)
        self.values += [auto] * 3
        before = len(self.calls)
        result = self.step()
        self.assertEqual((result.get('node'), result['state']), ('D', 'produced'), result)
        self.assertEqual(len(self.calls) - before, 1)
        row = next(r for r in self.delivered() if r['node'] == 'D')
        self.assertIn((learned[0], 'fact'), [(e['id'], e['use']) for e in row['entries']])

    def test_b_r02_a_withdrawal_while_the_checker_runs_is_not_verified(self):
        rule = self.fact('Keep a.txt to one line', must=True)
        self.plan(self.item('C'))
        self.values += [auto, auto]
        self.assertEqual(self.step()['state'], 'produced')
        def checker(item, artifact):
            self.withdraw(rule)
            return self.checker(item, artifact)
        with self.assertRaisesRegex(LedgerError, 'knowledge'):
            self.engine.verify(self.ledger, 'P1', 'C', checker)
        self.assertNotIn('node.verification', self.kinds())
        retained = [p for k, p in self.events() if k == 'node.result_retained' and p.get('receipt')]
        self.assertTrue(retained and 'checker ran' in retained[-1]['reason'], retained)
        self.assertNotEqual(self.engine.state(self.ledger, 'P1')['nodes']['C']['state'], 'verified')

    def test_b_r03_a_verified_producer_withdrawn_holds_the_dependent_without_a_model_call(self):
        rule = self.fact('Keep a.txt to one line', must=True)
        a = self.item('A')
        b = self.item('B', read=('b.txt',), write=('b.txt',))
        b['depends'] = [{'node': 'A', 'requires': 'verified'}]
        self.plan(a, b)
        self.values += [auto] * 4
        self.assertEqual(self.step()['state'], 'produced')
        self.check('A')
        self.withdraw(rule)
        before = len(self.calls)
        held = self.step()
        self.assertEqual((held.get('node'), held['state'], held.get('classification')), ('B', 'held', 'input_changed'), held)
        self.assertEqual(len(self.calls), before)                                   # no model call for a recheck that cannot help
        event = next(p for k, p in self.events() if k == 'node.held' and p['node'] == 'B')
        self.assertEqual(event['knowledge_changed']['critical'][0]['node'], 'A')
        self.assertEqual(event['knowledge_changed']['critical'][0]['ids'], [rule])
        self.assertEqual([(x['node'], x['via']) for x in wc().affected_consumers(self.ledger, 'P1', [rule])], [('B', 'A')])
        report = wc().consumers_report(self.ledger, 'P1')
        self.assertEqual([(c['node'], c['status']) for c in report['consumers']], [('B', 'input_changed')])

    def test_b_r04_a_new_mandatory_entry_reaches_a_node_without_a_record(self):
        self.plan(self.item('C'))
        def recording(prompt, schema):
            self.fact('a.txt must end with a newline', must=True)
            return auto(prompt, schema)
        self.values += [recording, auto]
        result = self.step()
        self.assertEqual(result['state'], 'continuing', result)
        self.assertEqual(result['knowledge_changed']['critical'][0]['reason'], 'a new mandatory entry concerns this node')
        self.assertEqual(self.step()['state'], 'produced')

    def test_b_r04b_a_node_that_receives_nothing_still_writes_no_record(self):
        self.plan(self.item('C'))
        self.values.append(auto)
        self.assertEqual(self.step()['state'], 'produced')
        self.assertEqual(self.delivered(), [])

    def test_b_r07_a_dependent_of_an_older_producer_generation_stays_listed(self):
        rule = self.fact('Keep a.txt to one line', must=True)
        advance = {'limit': 1, 'discard_on_failure': True}
        p1 = self.item('P1n')
        k = self.item('K', read=('b.txt',), write=())
        k['depends'] = [{'node': 'P1n', 'requires': 'produced', 'advance': advance}]
        self.plan(p1, k)
        self.values += [auto] * 4
        for _ in range(2): self.assertEqual(self.step()['state'], 'produced')
        self.withdraw(rule)
        with self.assertRaisesRegex(LedgerError, 'knowledge'):
            self.check('P1n')                                                        # P1n is rechecked ...
        self.assertEqual(self.step()['state'], 'produced')                           # ... into a clean generation
        listed = {(a['node'], a['via']) for a in wc().affected_consumers(self.ledger, 'P1', [rule])}
        self.assertIn(('K', 'P1n'), listed)                                          # K still holds the artifact built on the rule


class ReviewBSourceTests(AllEvents, SourceFixture):
    def run_nodes(self, script, steps):
        self.values += [script] * (steps + 2)
        return [self.step() for _ in range(steps)]

    def test_b_r05_a_changed_search_hit_rechecks_the_reader(self):
        self.plan(self.item('R1', patterns=('src/',)))
        rounds = {'n': 0}
        def script(prompt, schema):
            rounds['n'] += 1
            if rounds['n'] == 1: return ask({'op': 'search', 'query': 'helper', 'path': 'src'})
            if rounds['n'] == 2: (self.root / 'src' / 'lib' / 'x.py').write_text('def helper():\n    return 43\n')
            return {'summary': 'done', 'files': [{'path': 'out.txt', 'content': 'R1\n'}], 'backlog': []}
        states = [r['state'] for r in self.run_nodes(script, 2)]
        self.assertEqual(states, ['continuing', 'continuing'])
        resumed = [p for k, p in self.events() if k == 'node.resumed' and p.get('knowledge_changed')]
        self.assertEqual(resumed[0]['knowledge_changed']['critical'][0]['path'], 'src/lib/x.py')

    def test_b_r06_a_source_recheck_carries_the_candidate_and_may_read_again(self):
        self.plan(self.item('R1', patterns=('src/',), rounds=1))
        rounds = {'n': 0}
        def script(prompt, schema):
            rounds['n'] += 1
            results = body_of(prompt)['source_tools']['results']
            if rounds['n'] == 1: return ask({'op': 'read', 'path': 'src/lib/x.py'})
            if rounds['n'] == 2:
                (self.root / 'src' / 'lib' / 'x.py').write_text('def helper():\n    return 43\n')
                return {'summary': 'done', 'files': [{'path': 'out.txt', 'content': 'saw 42\n'}], 'backlog': []}
            if rounds['n'] == 3: return ask({'op': 'read', 'path': 'src/lib/x.py'})
            seen = [r['result'].get('text') for r in results if r['action'] == 'read']
            return {'summary': 'done', 'files': [{'path': 'out.txt', 'content': 'saw ' + ('43' if '43' in str(seen) else '?') + '\n'}], 'backlog': []}
        results = self.run_nodes(script, 4)
        self.assertEqual([r['state'] for r in results], ['continuing', 'continuing', 'continuing', 'produced'], results)
        resumed = next(p for k, p in self.events() if k == 'node.resumed' and p.get('knowledge_changed'))
        self.assertTrue(resumed.get('resume_artifact'))                              # the candidate is carried
        self.assertEqual(self.store.context(results[-1]['artifact'])['out.txt'], 'saw 43\n')
        receipt = self.receipt(results[-1]['receipt'])
        self.assertEqual(receipt['source']['rounds_total'], 2)                       # the receipts still show the total
