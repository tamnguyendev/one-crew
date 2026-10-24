"""T52b (W49b) [E5], [E14]: a general candidate is conditional, sourced and free of private detail; no lesson is written once the root ended.

Same world as tests/test_wf_r06_learning (real verifier runs with a controlled reviewer answer, one incident, one project lesson).
[E5]  the general candidate carries `conditions` (non-empty) and its source (the incident / evidence event / source lesson), and a text that
      names a project path, the project name or a project symbol is refused (grep rule of context._private_reasons).
[E14] after the root is closed, `lessons.record` and `lessons.propose_general` are refused and write nothing: no learning.lesson is added.
"""
from onecrew.ledger import LedgerError
from onecrew.v2 import lessons, plan as plans
from tests.test_wf_r06_learning import LearningWorld


class LessonLimitsTests(LearningWorld):
    def lesson_events(self):
        return [p for _, k, p in self.root_events('learning.lesson')]

    def test_e5_general_candidate_has_conditions_and_source_and_no_private_detail(self):
        self.prepare_repair()
        shared = lessons.propose_general(self.ledger, 'R', self.lesson['lesson'], text='Preserve all rows when collecting an iterator.', conditions=['Python', 'sqlite'])
        self.assertEqual(shared['conditions'], ['Python', 'sqlite'])                                             # conditions
        self.assertEqual((shared['incident'], shared['evidence_event'], shared['source_lesson']), (self.incident['event'], self.incident['event'], self.lesson['lesson']))
        self.assertEqual(shared['scope'], 'general'); self.assertIsNone(shared['location']); self.assertIsNone(shared['snapshot'])
        text = (shared['text'] + ' ' + ' '.join(shared['conditions'])).casefold()
        for private in ('service.py', self.root.name.casefold(), 'export_records', str(self.root).casefold()):
            self.assertNotIn(private, text)                                                                       # no private path / project name / symbol
        for bad in ('Preserve rows in service.py.', f'In {self.root.name} keep every row.', 'export_records must copy the iterator.'):
            with self.subTest(bad=bad), self.assertRaises(LedgerError):
                lessons.propose_general(self.ledger, 'R', self.lesson['lesson'], text=bad, conditions=['Python'])
        with self.assertRaises(LedgerError):
            lessons.propose_general(self.ledger, 'R', self.lesson['lesson'], text='Preserve all rows when collecting an iterator.', conditions=[])
        again = lessons.propose_general(self.ledger, 'R', self.lesson['lesson'], text='Preserve all rows when collecting an iterator.', conditions=['Python', 'sqlite'])
        self.assertFalse(again['recorded'])                                                                       # the same candidate twice is one record

    def test_e14_no_lesson_after_the_root_ended(self):
        self.prepare_repair()
        count = len(self.lesson_events())
        with self.ledger.transaction(write=True) as conn:
            root = plans.anchor_events(self.ledger, conn, 'R')
            plans.emit(self.ledger, conn, root['task_id'], 'milestone.stopped', {'revision': root['approved']['revision'], 'milestone': 'M2', 'reason': 'max repairs reached in the fixture'})
        self.assertEqual(plans.show(self.ledger, 'R')['status'], 'stopped_with_report')
        with self.assertRaises(LedgerError) as refused:
            lessons.record(self.ledger, 'R', self.incident['event'], text='Collect the iterator once.', path='service.py', line=2,
                           revision=self.fixed, test='reviewer:R1')
        self.assertIn('before the root ends', str(refused.exception))
        with self.assertRaises(LedgerError):
            lessons.propose_general(self.ledger, 'R', self.lesson['lesson'], text='Preserve all rows when collecting an iterator.', conditions=['Python'])
        self.assertEqual(len(self.lesson_events()), count)                                                        # nothing written
