"""W49b evidence for T52b E7, E11, E12 (same real world as tests/test_wf_r06_learning: real verifier runs with a scripted reviewer,
one incident, one mid-root project lesson, then a general candidate and a withdrawal).

E7  the withdrawal is a recorded event carrying its reason; retrieval no longer returns the lesson (project and general scope).
E11 `learning.record` is never called and no outcome / `completed` event exists anywhere while the root is open, including after the
    candidate and the withdrawal; the check goes red when a fake completed outcome is written.
E12 the contract hash, the gate list (milestones), the authority and the review policy are identical before and after the lesson is
    recorded, after the general candidate and after the withdrawal; no approval/amendment/acceptance event appears.
"""
import json
from unittest.mock import patch

from onecrew import learning
from onecrew.ledger import LedgerError
from onecrew.v2 import context, lessons, plan as plans
from tests.test_wf_r06_learning import LearningWorld

TEXT = 'Preserve all rows when collecting an iterator.'
STRUCTURAL = ('plan.proposed', 'plan.amended', 'plan.approved', 'plan.accepted', 'plan.revoked', 'milestone.stopped')


class T52bEvidence(LearningWorld):
    def returned(self, scope=None):
        kwargs = {'plan': 'R'} if scope is None else {'plan': 'R', 'scope': scope}
        return [e.get('lesson') for e in context.retrieve(self.ledger, **kwargs)['entries']]

    def governance(self):
        """What a lesson must never change: the sealed contract, its gates (milestones), authority and review policy."""
        shown = plans.show(self.ledger, 'R')
        contract = shown['contract']
        with self.ledger.transaction() as conn:
            root = plans.anchor_events(self.ledger, conn, 'R')
            structural = [(r['kind']) for r in conn.execute('SELECT kind FROM events WHERE task_id=? ORDER BY seq', (root['task_id'],))
                          if r['kind'] in STRUCTURAL]
        return {'sha': shown['sha'], 'approved_revision': shown['approved_revision'], 'revisions': shown['revisions'],
                'gates': json.dumps(contract['milestones'], sort_keys=True), 'authority': json.dumps(contract.get('authority'), sort_keys=True),
                'review_policy': json.dumps(contract.get('review_policy'), sort_keys=True), 'scope': json.dumps(contract['scope'], sort_keys=True),
                'stop': json.dumps(shown['stop'].get('max_repairs', None) if isinstance(shown['stop'], dict) else None),
                'structural_events': structural}

    def test_t52b_e7_withdrawal_event_carries_its_reason_and_retrieval_drops_the_lesson(self):
        """W49b / T52b E7: withdrawing a wrong lesson writes a learning.lesson event (status withdrawn, the reason, link to the original
        event); retrieval no longer returns it (project scope, and the general candidate made from it); the same call twice is one record;
        a withdrawal without a reason is refused and writes nothing."""
        self.prepare_repair()
        lesson = self.lesson['lesson']
        shared = lessons.propose_general(self.ledger, 'R', lesson, text=TEXT, conditions=['Python'])
        self.assertIn(lesson, self.returned())
        count = len(self.root_events('learning.lesson'))
        with self.assertRaises(LedgerError):
            lessons.withdraw(self.ledger, 'R', lesson, reason='')
        self.assertEqual(len(self.root_events('learning.lesson')), count)
        reason = 'The lesson was generalised from a one-off environment fault.'
        done = lessons.withdraw(self.ledger, 'R', lesson, reason=reason)
        self.assertTrue(done['recorded'])
        events = self.root_events('learning.lesson')
        self.assertEqual(len(events), count + 1)
        seq, _, payload = events[-1]
        self.assertEqual((payload['lesson'], payload['status']), (lesson, 'withdrawn'))
        self.assertEqual(payload['withdrawal_reason'], reason)
        self.assertEqual(payload['previous_event'], self.lesson['event'])
        self.assertGreater(seq, self.lesson['event'])
        self.assertNotIn(lesson, self.returned())
        self.assertNotIn(shared['lesson'], self.returned('general'))
        again = lessons.withdraw(self.ledger, 'R', lesson, reason=reason)
        self.assertFalse(again['recorded'])
        self.assertEqual(len(self.root_events('learning.lesson')), count + 1)

    def fake_outcome_violations(self, calls):
        """The T52b E11 check: learning.record calls, plus any outcome / `completed` event on any task of the ledger."""
        bad = []
        if calls:
            bad.append(f'learning.record called {calls} time(s)')
        with self.ledger.transaction() as conn:
            for row in conn.execute("SELECT kind, payload FROM events WHERE kind IN ('learning.outcome') OR payload LIKE '%\"completed\"%'"):
                try:
                    phase = json.loads(row['payload']).get('phase')
                except ValueError:
                    phase = None
                if row['kind'] == 'learning.outcome' or phase == 'completed':
                    bad.append(f'{row["kind"]} with phase {phase!r}')
        return bad

    def test_t52b_e11_no_learning_record_and_no_completed_outcome_for_the_whole_open_root(self):
        """W49b / T52b E11: across the three attempts, the automatic lesson, the general candidate and the withdrawal the counter of
        learning.record is 0 and no outcome / completed event exists; the same check is red when a fake completed outcome is written."""
        with patch.object(learning, 'record', wraps=learning.record) as counter:
            self.prepare_repair()
            lessons.propose_general(self.ledger, 'R', self.lesson['lesson'], text=TEXT, conditions=['Python'])
            lessons.withdraw(self.ledger, 'R', self.lesson['lesson'], reason='superseded by a narrower lesson')
            self.assertEqual(self.fake_outcome_violations(counter.call_count), [])
            self.assertEqual(counter.call_count, 0)
        self.assertEqual(self.root_events('learning.outcome'), [])
        self.assertEqual(plans.show(self.ledger, 'R')['status'], 'approved')
        with self.ledger.transaction(write=True) as conn:                     # counter-example: a fake completed outcome written mid-root
            root = plans.anchor_events(self.ledger, conn, 'R')
            plans.emit(self.ledger, conn, root['task_id'], 'learning.outcome', {'version': 1, 'task': root['task_id'], 'phase': 'completed'})
        self.assertTrue(any('completed' in v for v in self.fake_outcome_violations(0)))
        self.assertTrue(self.fake_outcome_violations(1))

    def test_t52b_e12_recording_and_withdrawing_a_lesson_changes_no_contract_gate_or_authority(self):
        """W49b / T52b E12: contract hash, gate list (milestones), authority, review policy, scope and the approval/amendment events
        are identical before the repair, after the lesson was recorded, after the general candidate and after the withdrawal."""
        before = self.governance()
        self.assertTrue(before['gates'])
        self.prepare_repair()
        self.assertEqual(len(self.root_events('learning.lesson')), 1)
        after_record = self.governance()
        shared = lessons.propose_general(self.ledger, 'R', self.lesson['lesson'], text=TEXT, conditions=['Python'])
        self.assertEqual(shared['status'], 'proposed')
        after_candidate = self.governance()
        lessons.withdraw(self.ledger, 'R', self.lesson['lesson'], reason='too broad')
        after_withdraw = self.governance()
        self.assertEqual(before, after_record)
        self.assertEqual(before, after_candidate)
        self.assertEqual(before, after_withdraw)
        self.assertEqual(plans.show(self.ledger, 'R')['status'], 'approved')
        self.assertFalse(self.lesson['automatic_promotion'])
        self.assertFalse(self.lesson['automatic_injection'])
