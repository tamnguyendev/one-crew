"""Round 7 / T35a (W23b, R02) — E14 with a REAL mutant of the dedupe key; E19 with a REAL "nối sai" mutant of the intervention writer.

tests.test_wf_r02_outcome.test_e14_counter_key_by_plan_only_collapses_the_two_rows only states that the two rows of `two` share one plan; it
never runs a writer keyed by plan alone. 05 T35 [E14] evidence: "bản phản chứng (khoá chỉ theo plan) làm test đỏ". Here the writer's dedupe
step is wrapped so that it refuses a second outcome of the SAME PLAN whatever its revision and end (the plan-only key), the stop-then-accept
root is built through the real v2 functions, and the E14 check (one row per (plan, revision, end), two rows for the stop-then-accept root) goes
red on it; with the real writer the same check is green, and the second write of every root still adds nothing.

E19 evidence: "bộ đếm lời gọi interventions.record >= 1; bản 'nối sai' (module mới tự ghi sự kiện, không gọi hàm v1) làm test đỏ". The mutant
replaces the v1 module seen by onecrew.v2.outcome with a writer that appends the same control.intervention row itself (idempotent by key, so
only the wiring differs); the E19 integration check goes red on it and is green on the real code.
"""
import json
import types
import unittest
from unittest.mock import patch

from onecrew import interventions
from onecrew.v2 import outcome, plan as plans, verdict
from tests.test_wf_r02_outcome import OutcomeTestCase, outcomes_of
from wf_r02 import BAD, OK, approved, count_kind, events, milestone, pass_all, plan_json, tree


def build_stop_then_accept(ledger, root):
    approved(ledger, 'two', plan_json(milestones=[milestone(argv=BAD, max_repairs=0)], title='Stop then accept'))
    verdict.run(ledger, 'two', 'M1', root)
    plans.amend(ledger, 'two', plan_json(title='Stop then accept, fixed', milestones=[milestone(argv=OK)]), 'the milestone command was wrong', 'claude')
    plans.approve(ledger, 'two', 'owner', 'second approval')
    pass_all(ledger, 'two', root)
    plans.accept(ledger, 'two', 'owner', 'ok', tree(root))


def e14_problems(ledger):
    """The E14 check, from the ledger events: each (plan, revision, end) once; stop at 1 + accept at 2 = two rows."""
    rows = [(p['plan'], p['plan_revision'], p['end']) for _, _, p in outcomes_of(ledger, 'two')]
    problems = []
    if len(rows) != len(set(rows)): problems.append(f'duplicate key in {rows}')
    if set(rows) != {('two', 1, 'stopped_with_report'), ('two', 2, 'accepted')}: problems.append(f'rows {sorted(rows)} are not one per end')
    return problems


class DedupeKeyMutantTests(OutcomeTestCase):
    def test_e14_real_writer_keeps_one_row_per_end(self):
        ledger = self.sandbox.ledger(self.root, self.sandbox.state('K-real'))
        build_stop_then_accept(ledger, self.root)
        self.assertEqual(e14_problems(ledger), [])
        before = count_kind(ledger, 'learning.outcome')
        self.assertFalse(outcome.record(ledger, 'two')['recorded'])
        self.assertEqual(count_kind(ledger, 'learning.outcome'), before)

    def test_e14_counter_a_plan_only_key_is_red(self):
        ledger = self.sandbox.ledger(self.root, self.sandbox.state('K-plan'))
        real = outcome._record_found

        def plan_only(l, name, found):
            if outcomes_of(l, name): return {'plan': name, 'recorded': False, 'reason': 'already_recorded_for_this_plan'}
            return real(l, name, found)
        with patch.object(outcome, '_record_found', plan_only):
            build_stop_then_accept(ledger, self.root)
        self.assertGreaterEqual(count_kind(ledger, 'learning.outcome'), 1, 'the mutant still writes the first end')
        problems = e14_problems(ledger)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn('not one per end', problems[0])


def e19_problems(ledger, name):
    """The E19 integration check: two writes with the same key -> one control.intervention on the root with actor, kind, reason, and the v1
    function interventions.record was called."""
    calls = []
    real = interventions.record

    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)
    with patch.object(interventions, 'record', spy):
        for _ in range(2):
            outcome.intervene(ledger, name, 'state.fix', 'repaired a stuck state by hand', actor='claude', key='fix-r7')
    problems = []
    if not calls: problems.append('interventions.record (v1) was not called')
    rows = [p for _, _, p in events(ledger, name, 'control.intervention') if p.get('key') == 'fix-r7']
    if len(rows) != 1: problems.append(f'{len(rows)} control.intervention rows for one key')
    elif (rows[0].get('actor'), rows[0].get('reason'), (rows[0].get('details') or {}).get('kind')) != ('claude', 'repaired a stuck state by hand', 'state.fix'):
        problems.append(f'row fields {rows[0]}')
    return problems


class InterventionWiringMutantTests(OutcomeTestCase):
    def test_e19_real_writer_goes_through_interventions_record(self):
        ledger = self.sandbox.ledger(self.root, self.sandbox.state('I-real'))
        approved(ledger, 'iv', plan_json())
        self.assertEqual(e19_problems(ledger, 'iv'), [])

    def test_e19_counter_a_module_that_writes_the_event_itself_is_red(self):
        ledger = self.sandbox.ledger(self.root, self.sandbox.state('I-self'))
        approved(ledger, 'iv', plan_json())

        def own_writer(led, task_id, command, *, actor=None, channel='cli', reason=None, details=None, key=None):
            with led.transaction(write=True) as conn:
                old = conn.execute("SELECT payload FROM events WHERE task_id=? AND kind='control.intervention' AND json_extract(payload,'$.key')=?",
                                   (task_id, key)).fetchone()
                if old: return json.loads(old['payload'])
                payload = {'actor': actor, 'channel': channel, 'command': command, 'reason': reason, 'details': details, 'key': key}
                led._event(conn, task_id, 'control.intervention', payload)
                return payload
        with patch.object(outcome, 'interventions', types.SimpleNamespace(record=own_writer)):
            problems = e19_problems(ledger, 'iv')
        self.assertEqual(problems, ['interventions.record (v1) was not called'])
        self.assertEqual(len([p for _, _, p in events(ledger, 'iv', 'control.intervention')]), 1)


if __name__ == '__main__':
    unittest.main()
