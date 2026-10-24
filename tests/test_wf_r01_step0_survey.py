"""T27 (W31a) - a step-0 survey/PoC that ends correctly: a cap, an end condition, a read-only scope. Fake worker, fake clock: this proves the
interface and the rules that end a survey, not the quality of a real answer (a real worker is a later release).

A survey is opened for an unknown that carries `affected` and `required_by` from the moment it is proposed. It ends in exactly one of two
ways: an answer WITH evidence (success, even when the hypothesis is refuted), or a blocker WITH evidence (the cap was reached, the scope was
violated, nothing was found). It never runs past its cap, never writes, and a survey that closes with neither is impossible.
"""
import hashlib
import json
import os
import unittest
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import compat, plan as plans, step0, survey
from tests.test_v2_l3 import Step0, step0_json

SPEC = {'hypothesis': 'The old report data is not used by another job', 'cap': {'minutes': 3, 'calls': 5},
        'end_condition': 'an answer that cites file:line, or the cap', 'scope': {'mode': 'read_only', 'paths': ['x', 'onecrew']}}


class Clock:
    """A fake clock: seconds since 0; the worker advances it, never real time."""
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now
    def advance(self, seconds): self.now += seconds


def scoped_plan(**unknown):
    value = step0_json(size='S', unknowns=['U1'])
    value['understanding']['unknowns'][0].update(dict({'affected': ['O1'], 'required_by': 'option_choice'}, **unknown))
    return value


def tree_hash(root):
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob('*') if p.is_file() and '.git' not in p.parts):
        digest.update(str(path.relative_to(root)).encode()); digest.update(path.read_bytes())
    return digest.hexdigest()


class SurveyTests(Step0):
    def setUp(self):
        super().setUp()
        self.propose('P1', scoped_plan())
        self.clock = Clock()

    def opened(self, **spec):
        return survey.open_survey(self.ledger, 'P1', 'U1', dict(SPEC, **spec))

    def finished(self):
        return [p for k, p in self.events('P1') if k == 'survey.finished']

    def run_survey(self, worker, **spec):
        view = self.opened(**spec)
        return survey.run(self.ledger, 'P1', view['id'], worker, clock=self.clock)

    # ---- the unknown is scoped from the moment it is proposed ----
    def test_an_unknown_carries_affected_and_required_by_from_the_proposal(self):
        view = plans.show(self.ledger, 'P1')
        unknown = view['contract']['understanding']['unknowns'][0]
        self.assertEqual((unknown['affected'], unknown['required_by']), (['O1'], 'option_choice'))
        for half in ({'affected': ['O1']}, {'required_by': 'option_choice'}, {'affected': [], 'required_by': 'option_choice'}, {'affected': ['O1'], 'required_by': 'someday'}):
            value = step0_json(size='S', unknowns=['U1']); value['understanding']['unknowns'][0].update(half)
            with self.assertRaises(LedgerError): plans.propose(self.ledger, 'P9', value, 'claude')
        plain = step0_json(size='S', unknowns=['U1'])                                     # a plan without the scope stays as it was
        self.assertNotIn('affected', plans.propose(self.ledger, 'P8', plain, 'claude')['contract']['understanding']['unknowns'][0])

    # ---- a survey without a cap, an end condition or a read-only scope is refused, and nothing is written ----
    def test_a_survey_needs_a_cap_an_end_condition_and_a_read_only_scope(self):
        bad = [dict(SPEC, cap=None), dict(SPEC, cap={'minutes': 3}), dict(SPEC, cap={'calls': 3}), dict(SPEC, cap={'minutes': 0, 'calls': 3}),
               dict(SPEC, cap={'minutes': 9999, 'calls': 3}), dict(SPEC, cap={'minutes': 3, 'calls': 9999}), dict(SPEC, end_condition=''),
               {k: v for k, v in SPEC.items() if k != 'end_condition'}, dict(SPEC, scope={'mode': 'read_write', 'paths': ['x']}),
               {k: v for k, v in SPEC.items() if k != 'scope'}, dict(SPEC, scope={'mode': 'read_only', 'paths': ['../outside']})]
        for spec in bad:
            with self.assertRaises(LedgerError, msg=spec): survey.open_survey(self.ledger, 'P1', 'U1', spec)
        self.assertNotIn('survey.opened', self.kinds('P1'))

    def test_a_survey_is_opened_only_for_a_scoped_open_unknown(self):
        self.propose('P2', step0_json(size='S', unknowns=['U1']))                          # the unknown has no affected / required_by
        with self.assertRaises(LedgerError) as caught: survey.open_survey(self.ledger, 'P2', 'U1', SPEC)
        self.assertIn('affected', str(caught.exception))
        with self.assertRaises(LedgerError): survey.open_survey(self.ledger, 'P1', 'U7', SPEC)
        opened = self.opened()
        payload = [p for k, p in self.events('P1') if k == 'survey.opened'][0]
        self.assertEqual((payload['affected'], payload['required_by'], payload['scope']['mode'], payload['cap']), (['O1'], 'option_choice', 'read_only', SPEC['cap']))
        self.assertEqual(self.opened()['id'], opened['id'])                                   # asking again returns the open survey
        self.assertEqual(self.kinds('P1').count('survey.opened'), 1)

    # ---- [E1] [E4] (a) answered, the hypothesis is refuted: a success with evidence ----
    def test_e1_an_answer_that_refutes_the_hypothesis_is_a_success_with_evidence(self):
        def worker(ctx):
            ctx.read('x/y.py'); self.clock.advance(30)
            return {'answer': 'Another job reads the data at x/y.py:2, so the hypothesis is wrong', 'evidence': 'x/y.py:2', 'hypothesis': 'refuted'}
        out = self.run_survey(worker)
        self.assertEqual(out['status'], 'answered'); self.assertNotIn(out['status'], ('failed', 'blocked'))    # [E4]
        self.assertEqual(out['hypothesis_result'], 'refuted'); self.assertTrue(out['answer'] and out['evidence'])
        event = self.finished()[0]
        self.assertEqual((event['status'], event['hypothesis_result'], event['evidence_kind']), ('answered', 'refuted', 'file_line'))
        self.assertIsNone(event.get('blocker'))
        view = plans.show(self.ledger, 'P1')                                                   # the answer closed the unknown with its evidence (by poc)
        unknown = view['contract']['understanding']['unknowns'][0]
        self.assertEqual((unknown['status'], unknown['closed_by'], unknown['evidence']), ('closed', 'poc', 'x/y.py:2'))
        self.assertEqual(plans.approve(self.ledger, 'P1', 'owner', 'said yes')['status'], 'approved')

    # ---- [E2] [E5] (b) no answer inside the cap: a blocker with evidence, stopped exactly at the cap ----
    def test_e2_no_answer_inside_the_time_cap_is_a_blocker_that_stops_at_the_cap(self):
        seen = []
        def worker(ctx):
            for _ in range(20):
                self.clock.advance(60); ctx.read('x/y.py'); seen.append(self.clock.now)
            return {'answer': 'too late', 'evidence': 'x/y.py:1'}
        out = self.run_survey(worker)
        self.assertEqual(out['status'], 'blocked'); self.assertEqual(out['blocker']['reason'], 'cap_reached')
        event = self.finished()[0]
        self.assertEqual(event['spent']['seconds'], 180)                                       # = the cap (3 minutes of the fake clock)
        self.assertEqual(seen, [60.0, 120.0])                                                   # the op that would pass the cap never ran
        ops = json.loads(Snapshots(self.ledger.state_root).read_blob(event['evidence']))['ops']
        self.assertTrue(ops and max(o['at'] for o in ops) <= 180)                             # [E5] nothing recorded after the cap
        self.assertEqual(plans.show(self.ledger, 'P1')['contract']['understanding']['unknowns'][0]['status'], 'open')    # a blocker closes nothing

    def test_e5_an_answer_that_arrives_after_the_cap_is_discarded(self):
        def worker(ctx):
            self.clock.advance(600)
            return {'answer': 'a late answer', 'evidence': 'x/y.py:1'}
        out = self.run_survey(worker)
        self.assertEqual((out['status'], out['blocker']['reason']), ('blocked', 'cap_reached')); self.assertIsNone(out.get('answer'))
        self.assertEqual(self.finished()[0]['spent']['seconds'], 180)                          # spent is clamped to the cap, never above it

    def test_the_budget_cap_stops_the_survey_too(self):
        def worker(ctx):
            for _ in range(10): ctx.tick('model call')
        out = self.run_survey(worker, cap={'minutes': 30, 'calls': 2})
        self.assertEqual(out['blocker']['reason'], 'cap_reached'); self.assertEqual(self.finished()[0]['spent']['calls'], 2)

    def test_a_worker_that_swallows_the_cap_cannot_go_on(self):
        count = []
        def worker(ctx):
            for _ in range(10):
                try: ctx.tick(); count.append(1)
                except survey.CapReached: pass
            return {'answer': 'x', 'evidence': 'x/y.py:1'}
        out = self.run_survey(worker, cap={'minutes': 30, 'calls': 3})
        self.assertEqual(len(count), 3); self.assertEqual(out['status'], 'blocked')

    # ---- [E3] (c) a write attempt is refused; the files do not change ----
    def test_e3_a_write_attempt_is_denied_with_the_read_only_reason(self):
        before = tree_hash(self.root)
        def worker(ctx):
            ctx.write('x/y.py', b'changed')
        out = self.run_survey(worker)
        self.assertEqual(tree_hash(self.root), before)
        self.assertEqual((out['status'], out['blocker']['reason']), ('blocked', 'scope_violation'))
        denied = [p for k, p in self.events('P1') if k == 'survey.denied']
        self.assertEqual(len(denied), 1); self.assertIn('read-only', denied[0]['reason']); self.assertEqual(denied[0]['path'], 'x/y.py')
        self.assertIn('read-only', out['blocker']['detail'])

    def test_a_read_outside_the_scope_is_denied(self):
        def worker(ctx):
            try: ctx.read('a.txt')                               # a file of the project but not on the survey's paths
            except survey.SurveyDenied: pass
            try: ctx.read('../outside.txt')
            except survey.SurveyDenied: pass
            return {'answer': 'found in x/y.py', 'evidence': 'x/y.py:1'}
        out = self.run_survey(worker)
        self.assertEqual(out['status'], 'answered')
        denied = [p['path'] for k, p in self.events('P1') if k == 'survey.denied' and p['op'] == 'read']
        self.assertEqual(denied, ['a.txt', '../outside.txt'])

    def test_a_write_made_behind_the_context_is_detected_and_blocks(self):
        def worker(ctx):
            (self.root / 'x' / 'y.py').write_text('tampered\n')
            return {'answer': 'done', 'evidence': 'x/y.py:1'}
        out = self.run_survey(worker)
        self.assertEqual((out['status'], out['blocker']['reason']), ('blocked', 'scope_violation')); self.assertIn('x/y.py', out['blocker']['detail'])
        self.assertEqual(plans.show(self.ledger, 'P1')['contract']['understanding']['unknowns'][0]['status'], 'open')

    # ---- [E6] a survey never closes with neither an answer nor a blocker ----
    def test_e6_every_closed_survey_has_an_answer_or_a_blocker_with_evidence(self):
        workers = [lambda ctx: None, lambda ctx: {'answer': 'no evidence'}, lambda ctx: {'answer': '', 'evidence': 'x/y.py:1'},
                   lambda ctx: {'answer': 'bad pointer', 'evidence': 'x/y.py:999'}, lambda ctx: (_ for _ in ()).throw(RuntimeError('boom')),
                   lambda ctx: {'blocked': 'the data lives in another repository'}]
        reasons = []
        for worker in workers:
            out = self.run_survey(worker)                         # a blocked survey leaves the unknown open: the next opening is a new survey
            reasons.append(out['blocker']['reason'])
            self.assertEqual(out['status'], 'blocked')
        self.assertEqual(reasons, ['no_answer', 'no_answer', 'no_answer', 'evidence_invalid', 'worker_error', 'worker_blocked'])
        for event in self.finished():
            self.assertTrue(event['status'] == 'answered' and event['answer'] and event['evidence'] or event['status'] == 'blocked' and event['blocker'] and event['evidence'])
        empty = [e for e in self.finished() if not (e.get('answer') or e.get('blocker'))]
        self.assertEqual(len(empty), 0)

    def test_a_finished_survey_is_not_run_again(self):
        calls = []
        def worker(ctx): calls.append(1); return {'answer': 'ok x/y.py:1', 'evidence': 'x/y.py:1'}
        view = self.opened()
        first = survey.run(self.ledger, 'P1', view['id'], worker, clock=self.clock)
        again = survey.run(self.ledger, 'P1', view['id'], worker, clock=self.clock)
        self.assertEqual(len(calls), 1); self.assertEqual(first['status'], again['status']); self.assertEqual(len(self.finished()), 1)
        with self.assertRaises(LedgerError): survey.run(self.ledger, 'P1', 'S-nope', worker, clock=self.clock)

    # ---- the step-0 flow: a blocking unknown opens a capped survey BEFORE the choice of an option ----
    def test_e6_of_t50a_the_capped_survey_stands_before_the_choice(self):
        requirement = {'acceptance': [{'id': 'A2', 'text': 'The old data is deleted'}]}
        unknown = {'id': 'U1', 'question': 'Is the old report data used by another job?', 'affected': ['A2', 'X4'], 'required_by': 'option_choice', 'status': 'open'}
        out = step0.review_proposal(self.ledger, 'P1', requirement, {'unknowns': [unknown]})
        self.assertEqual(out['result'], 'survey_first')
        kinds = self.kinds('P1')
        self.assertLess(kinds.index('survey.opened'), kinds.index('proposal.checked'))
        opened = [p for k, p in self.events('P1') if k == 'survey.opened'][0]
        self.assertEqual((opened['unknown'], opened['affected'], opened['required_by'], opened['scope']['mode']), ('U1', ['A2', 'X4'], 'option_choice', 'read_only'))
        self.assertTrue(opened['cap']['minutes'] and opened['cap']['calls'] and opened['end_condition'])
        self.assertNotIn('plan.approved', kinds); self.assertNotIn('ok', [p['result'] for k, p in self.events('P1') if k == 'proposal.checked'])
        step0.review_proposal(self.ledger, 'P1', requirement, {'unknowns': [unknown]})            # asking again does not open a second survey
        self.assertEqual(self.kinds('P1').count('survey.opened'), 1)

    def test_class_a_events(self):
        for kind in ('survey.opened', 'survey.finished', 'survey.denied'): self.assertEqual(compat.event_class(kind), 'A', kind)

    def test_cli_opens_and_shows_a_survey(self):
        path = self.root.parent / 'spec.json'
        path.write_text(json.dumps(SPEC), encoding='utf-8')
        code, out = self.cli('plan', 'survey', 'open', 'P1', 'U1', '--file', str(path))
        self.assertEqual(code, 0, out); self.assertEqual(json.loads(out)['unknown'], 'U1')
        code, out = self.cli('plan', 'survey', 'show', 'P1')
        self.assertEqual(code, 0, out); self.assertEqual(json.loads(out)['surveys'][0]['state'], 'open')
        path.write_text(json.dumps(dict(SPEC, cap=None)), encoding='utf-8')
        code, out = self.cli('plan', 'survey', 'open', 'P1', 'U1', '--file', str(path))
        self.assertEqual(code, 2)

    def test_enough_evidence_on_the_last_allowed_call_succeeds(self):
        def worker(ctx):
            ctx.read('x/y.py')
            return {'answer': 'the cited source answers the question', 'evidence': 'x/y.py:1', 'hypothesis': 'refuted'}
        out = self.run_survey(worker, cap={'minutes': 3, 'calls': 1})
        self.assertEqual(out['status'], 'answered')
        self.assertEqual(out['spent']['calls'], 1)

    def test_swallowing_a_write_refusal_does_not_turn_it_into_a_success(self):
        before = tree_hash(self.root)
        def worker(ctx):
            try: ctx.write('x/y.py', b'tamper')
            except survey.SurveyDenied: pass
            return {'answer': 'claim success anyway', 'evidence': 'x/y.py:1'}
        out = self.run_survey(worker)
        self.assertEqual(out['status'], 'blocked')
        self.assertEqual(out['blocker']['reason'], 'scope_violation')
        self.assertEqual(tree_hash(self.root), before)

    def test_a_large_file_write_behind_the_context_is_detected(self):
        path = self.root / 'large.bin'
        path.write_bytes(b'a' * (survey.MAX_FILE_BYTES + 1))
        def worker(ctx):
            with path.open('r+b') as stream:
                stream.seek(survey.MAX_FILE_BYTES); stream.write(b'b')
            return {'answer': 'claim success', 'evidence': 'x/y.py:1'}
        out = self.run_survey(worker)
        self.assertEqual(out['status'], 'blocked')
        self.assertIn('large.bin', out['blocker']['detail'])

    def test_incomplete_boundary_scan_blocks_before_calling_the_worker(self):
        calls = []
        with patch.object(survey, 'MAX_FILES', 1):
            out = self.run_survey(lambda ctx: calls.append(1))
        self.assertEqual(calls, [])
        self.assertEqual(out['status'], 'blocked')
        self.assertIn('entire read-only', out['blocker']['detail'])

    def test_a_result_for_changed_plan_input_does_not_close_the_unknown(self):
        def worker(ctx):
            with self.ledger.transaction() as conn:
                state = plans.anchor_events(self.ledger, conn, 'P1')
                value, _ = plans.load(self.ledger, state)
            value['understanding']['unknowns'][0]['question'] = 'A different question now?'
            plans.amend(self.ledger, 'P1', value, 'new input', 'claude')
            return {'answer': 'answer to the old question', 'evidence': 'x/y.py:1'}
        out = self.run_survey(worker)
        self.assertEqual((out['status'], out['blocker']['reason']), ('blocked', 'revision_changed'))
        unknown = plans.show(self.ledger, 'P1')['contract']['understanding']['unknowns'][0]
        self.assertEqual(unknown['status'], 'open')
        self.assertEqual(unknown['question'], 'A different question now?')

    def test_explicit_uncertainty_keeps_the_unknown_open_with_evidence(self):
        out = self.run_survey(lambda ctx: {'answer': 'The source is inconclusive', 'evidence': 'x/y.py:1', 'hypothesis': 'unknown'})
        self.assertEqual((out['status'], out['blocker']['reason']), ('blocked', 'uncertain_answer'))
        self.assertTrue(out['evidence'])
        log = json.loads(Snapshots(self.ledger.state_root).read_blob(out['evidence']))
        self.assertEqual(log['reported']['evidence'], 'x/y.py:1')
        shown = survey.show(self.ledger, 'P1')['surveys'][0]
        self.assertEqual(shown['evidence'], out['evidence'])
        self.assertEqual(plans.show(self.ledger, 'P1')['contract']['understanding']['unknowns'][0]['status'], 'open')


if __name__ == '__main__':
    unittest.main()
