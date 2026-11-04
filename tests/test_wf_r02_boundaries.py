"""R02 namespace, common-merge and privacy boundaries beyond the source snapshot."""
import contextlib
import io
import unittest
from unittest.mock import patch

from onecrew import contract_diff, outcome_core
from onecrew.ledger import LedgerError
from onecrew.v2 import context, outcome, plan as plans, report, resume_pack, verdict
from tests import test_learning
from tests.wf_r02 import BAD, Sandbox, approved, anchor, count_kind, events, milestone, pass_all, plan_json, tree


class Boundaries(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox(); self.addCleanup(self.sb.close)
        self.p1 = self.sb.project('P1', {'a.txt': 'one\n', 'internal/private.py': 'secret = 1\n'})
        self.p2 = self.sb.project('P2')
        self.state = self.sb.state('shared')
        self.l1 = self.sb.ledger(self.p1, self.state)
        self.l2 = self.sb.ledger(self.p2, self.state)
        approved(self.l1, 'same', plan_json())
        approved(self.l2, 'same', plan_json())

    def test_same_name_projects_keep_context_and_resume_pack_separate(self):
        for ledger, text in ((self.l1, 'project one fact'), (self.l2, 'project two fact')):
            source = {'type': 'event', 'id': events(ledger, 'same')[0][0]}
            context.add(ledger, 'same', kind='note', label='observed', text=text, source=source)
        self.assertEqual([e['text'] for e in context.for_pack(self.l1, 'same')], ['project one fact'])
        self.assertEqual([e['text'] for e in context.for_pack(self.l2, 'same')], ['project two fact'])
        self.assertEqual(resume_pack.build(self.l1, 'same')['anchor_task'], anchor(self.l1, 'same'))
        self.assertEqual(resume_pack.build(self.l2, 'same')['anchor_task'], anchor(self.l2, 'same'))

    def test_foreign_event_is_not_a_source_for_private_or_general_publication(self):
        source = {'type': 'event', 'id': events(self.l2, 'same')[0][0]}
        for scope in ('project', 'general'):
            with self.subTest(scope=scope), self.assertRaises(LedgerError):
                context.add(self.l1, 'same', kind='note', label='observed', text='A generic looking statement', source=source,
                            scope=scope, conditions=['Python'] if scope == 'general' else None)

    def test_generalisation_does_not_publish_a_private_basename(self):
        with self.assertRaisesRegex(LedgerError, 'private detail'):
            context.add(self.l1, 'same', kind='note', label='observed', text='The file private.py carries the credentials',
                        source={'type': 'event', 'id': events(self.l1, 'same')[0][0]}, scope='general', conditions=['Python'])

    def test_bare_and_explicit_selector_share_one_context_identity(self):
        source = {'type': 'event', 'id': events(self.l1, 'same')[0][0]}
        kw = dict(kind='note', label='observed', text='same source fact', source=source)
        first = context.add(self.l1, 'same', **kw)
        again = context.add(self.l1, 'plan-ns:same', **kw)
        self.assertTrue(first['recorded']); self.assertFalse(again['recorded'])
        self.assertEqual(first['id'], again['id'])

    def test_reconcile_repairs_a_terminal_gap_without_duplicate_outcome_or_request(self):
        pass_all(self.l1, 'same', self.p1)
        requests = len(self.l1.requests())
        with patch.object(outcome, 'build_payload', side_effect=OSError('injected outcome publication failure')):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(plans.accept(self.l1, 'same', 'owner', 'fixture acceptance', tree(self.p1))['status'], 'accepted')
        self.assertEqual(len(outcome.missing(self.l1)), 1)
        self.assertEqual(outcome.reconcile(self.l1)['missing'], [])
        self.assertEqual(outcome.reconcile(self.l1)['results'], [])
        self.assertEqual(len(outcome.outcomes(self.l1, 'same')), 1)
        self.assertEqual(len(self.l1.requests()), requests)

    def test_reconcile_preserves_missing_stop_revision_before_later_acceptance(self):
        approved(self.l1, 'history', plan_json(milestones=[milestone(argv=BAD, max_repairs=0)]))
        with patch.object(outcome, 'note'):
            verdict.run(self.l1, 'history', 'M1', self.p1)
        stopped = next(p for _, kind, p in events(self.l1, 'history') if kind == 'verdict.recorded')
        self.assertEqual(outcome.outcomes(self.l1, 'history'), [])
        plans.amend(self.l1, 'history', plan_json(), 'repair the failed check', 'claude')
        plans.approve(self.l1, 'history', 'owner', 'approve revision two')
        pass_all(self.l1, 'history', self.p1)
        plans.accept(self.l1, 'history', 'owner', 'accept revision two', tree(self.p1))
        outcome.record(self.l1, 'history')
        self.assertEqual({(r['plan_revision'], r['end']) for r in outcome.outcomes(self.l1, 'history')}, {(2, 'accepted')})
        gap = [r for r in outcome.missing(self.l1) if r['plan'] == 'history']
        self.assertEqual([(r['revision'], r['end']) for r in gap], [(1, 'stopped_with_report')])
        self.assertEqual(outcome.reconcile(self.l1)['missing'], [])
        rows = outcome.outcomes(self.l1, 'history')
        self.assertEqual({(r['plan_revision'], r['end']) for r in rows}, {(1, 'stopped_with_report'), (2, 'accepted')})
        previous = next(r for r in rows if r['plan_revision'] == 1)
        self.assertEqual(previous['snapshot'], stopped['artifact_sha'])
        self.assertEqual(previous['repair_rounds'], 1)


class V1MergePreservation(unittest.TestCase):
    def test_v1_writer_calls_the_same_merge_function_as_plan_outcomes(self):
        fixture = test_learning.LearningTests(); fixture.setUp()
        try:
            with patch.object(outcome_core, 'append_outcome', wraps=outcome_core.append_outcome) as append:
                fixture.finish(); fixture.finish()
            self.assertEqual(append.call_count, 2)
            from onecrew.learning import outcomes
            self.assertEqual(len(outcomes(fixture.f.ledger)), 1)
        finally:
            fixture.doCleanups()


class SharedContractDiff(unittest.TestCase):
    def test_full_text_and_id_list_reorder_use_one_comparison(self):
        text = 'Long acceptance text ' * 100
        old = {'items': [{'id': 'A', 'title': text}, {'id': 'B', 'title': 'second'}]}
        new = {'items': [{'id': 'B', 'title': 'second'}, {'id': 'A', 'title': text + 'changed tail'}]}
        with patch.object(contract_diff, 'diff', wraps=contract_diff.diff) as shared:
            tuples = report._diff(old, new)
            count = shared.call_count
            structured = resume_pack.changes_vs_approved(old, new)
            self.assertGreater(count, 0)
            self.assertGreater(shared.call_count, count)
        self.assertIn(('items', 'đổi thứ tự', old['items'], new['items']), tuples)
        changed = next(c for c in structured if c['path'] == 'items[A].title')
        self.assertEqual(changed['before'], text)
        self.assertEqual(changed['after'], text + 'changed tail')
        self.assertEqual(next(c for c in structured if c['change'] == 'reordered')['before'], old['items'])
