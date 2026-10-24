"""T35d (W23c, R03) - efficiency figures read from the ledger, classified by the v1 evaluation functions through an adapter.

Fixture: a temporary ledger with THREE finished roots built through the real plan / verdict / request code under a fake clock (the receipts are
fabricated blobs with chosen `seconds`; the owner's verbs are run with ONECREW_ACTOR=user on test data, nothing real). The expected figures below
are worked out by hand from this timeline, not by the code under test:

  P1  09:00 propose   09:02 approve   09:10 verdict FAIL (60 s)   09:20 verdict PASS (30 s)   09:22 accept
  P2  10:00 propose   10:01 approve   10:05 verdict PASS (20 s)   10:06 accept
  P3  11:00 propose   11:01 approve   11:05 FAIL (10 s)   11:10 FAIL (10 s) -> stopped, owner question opened 11:10
      11:40 owner answers (30 minutes of waiting)   11:45 amend   11:46 approve rev 2   11:50 PASS (5 s)   11:52 accept
"""
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v2_l1 import Fixture, OK, milestone, plan_json          # noqa: E402

from onecrew.ledger import canonical                              # noqa: E402
from onecrew.snapshots import Snapshots                           # noqa: E402
from onecrew.v2 import metrics, plan as plans, verdict           # noqa: E402

UNKNOWN = metrics.UNKNOWN


class Clock:
    now = '2026-10-24T08:00:00+00:00'

    def at(self, hhmm):
        self.now = f'2026-10-24T{hhmm}:00+00:00'

    def __call__(self):
        return self.now


class Counting:
    """The v1 evaluation functions, each call counted (the proof that the adapter calls them instead of re-implementing them)."""

    def __init__(self):
        self.calls = {}
        real = metrics.v1_evaluator()
        for name in metrics.V1_FUNCTIONS:
            setattr(self, name, self._wrap(name, getattr(real, name)))

    def _wrap(self, name, function):
        def call(*args, **kwargs):
            self.calls[name] = self.calls.get(name, 0) + 1
            return function(*args, **kwargs)
        return call

    @property
    def total(self):
        return sum(self.calls.values())


class ThreeRoots(Fixture):
    def setUp(self):
        super().setUp()
        self.clock = Clock()
        for target in ('onecrew.ledger.utcnow', 'onecrew.v2.plan.utcnow'):
            patcher = patch(target, self.clock); patcher.start(); self.addCleanup(patcher.stop)
        owner = patch.dict(os.environ, {'ONECREW_ACTOR': 'user'}); owner.start(); self.addCleanup(owner.stop)
        self.build()

    # ---- the fixture -------------------------------------------------------------------------------------------------
    def verdict(self, name, result, seconds, revision=1):
        with self.ledger.transaction() as conn:
            sha = plans.derive(self.ledger, conn, name)['revisions'][revision]['sha']
        body = {'kind': 'command-receipt', 'plan': name, 'revision': revision, 'milestone': 'M1', 'argv': OK, 'exit_code': 0 if result == 'pass' else 3,
                'timed_out': False, 'error': None, 'artifact_sha': self.tree(), 'artifact_sha_after': self.tree(), 'plan_sha': sha, 'seconds': seconds}
        blob = Snapshots(self.ledger.state_root).blob(canonical(body).encode('utf-8'))
        with self.ledger.transaction(write=True) as conn:
            plans.emit(self.ledger, conn, plans.derive(self.ledger, conn, name)['task_id'], 'verdict.receipt_issued',
                       {'plan': name, 'revision': revision, 'milestone': 'M1', 'receipt': blob})
        return verdict.record(self.ledger, name, 'M1', result, 'command', blob, self.tree())

    def build(self):
        c = self.clock
        for name, title in (('P1', 'First'), ('P2', 'Second'), ('P3', 'Third')): setattr(self, 'title_' + name, title)
        c.at('09:00'); self.propose('P1', plan_json(title='First'))
        c.at('09:02'); plans.approve(self.ledger, 'P1', 'owner', 'fixture: owner said yes')
        c.at('09:10'); self.verdict('P1', 'fail', 60)
        c.at('09:20'); self.verdict('P1', 'pass', 30)
        c.at('09:22'); plans.accept(self.ledger, 'P1', 'owner', 'fixture: accepted', self.tree())
        c.at('10:00'); self.propose('P2', plan_json(title='Second'))
        c.at('10:01'); plans.approve(self.ledger, 'P2', 'owner', 'fixture: owner said yes')
        c.at('10:05'); self.verdict('P2', 'pass', 20)
        c.at('10:06'); plans.accept(self.ledger, 'P2', 'owner', 'fixture: accepted', self.tree())
        c.at('11:00'); self.propose('P3', plan_json(title='Third'))
        c.at('11:01'); plans.approve(self.ledger, 'P3', 'owner', 'fixture: owner said yes')
        c.at('11:05'); self.verdict('P3', 'fail', 10)
        c.at('11:10'); out = self.verdict('P3', 'fail', 10)
        self.assertEqual(out['stopped']['question'], 'created')
        request = self.ledger.requests(out['anchor_task'])[0]
        c.at('11:40'); self.ledger.reply(request['id'], request['revision'], 'amend_plan', source='fixture', reference='fixture owner answer', decided_by='user', by='user')
        c.at('11:45'); plans.amend(self.ledger, 'P3', plan_json(title='Third, again'), 'fixture: continue after the stop', 'claude')
        c.at('11:46'); plans.approve(self.ledger, 'P3', 'owner', 'fixture: owner said yes again')
        c.at('11:50'); self.verdict('P3', 'pass', 5, revision=2)
        c.at('11:52'); plans.accept(self.ledger, 'P3', 'owner', 'fixture: accepted', self.tree())

    def measure(self, name, evaluator=None):
        return metrics.measure(self.ledger, name, evaluator or metrics.v1_evaluator())


class FiguresTests(ThreeRoots):
    # [E1] each figure is taken from the ledger and equals the hand-worked value
    def test_e1_time_to_usable_output(self):
        for name, wall, to_acceptance, inside in (('P1', 18.0, 20.0, 0.0), ('P2', 4.0, 5.0, 0.0), ('P3', 49.0, 51.0, 31.0)):
            t = self.measure(name)['time_to_output']
            self.assertEqual((t['wall_minutes'], t['to_acceptance_minutes'], t['owner_wait_inside_minutes']), (wall, to_acceptance, inside), name)
            self.assertEqual(t['excluding_owner_wait_minutes'], wall - inside, name)

    def test_e1_rework(self):
        got = {n: self.measure(n)['rework'] for n in ('P1', 'P2', 'P3')}
        self.assertEqual([(got[n]['repair_rounds'], got[n]['amends']) for n in ('P1', 'P2', 'P3')], [(1, 0), (0, 0), (2, 1)])
        self.assertEqual(got['P3']['by_milestone'], {'M1': 2})
        for n in got:                                                                 # the cause of an amend and a late defect are not in the ledger: unknown, not 0
            self.assertEqual((got[n]['amend_causes'], got[n]['late_defects']), (UNKNOWN, UNKNOWN))

    def test_e1_check_cost(self):
        got = {n: self.measure(n)['check_cost'] for n in ('P1', 'P2', 'P3')}
        self.assertEqual([(got[n]['seconds'], got[n]['runs'], got[n]['unknown_runs']) for n in ('P1', 'P2', 'P3')], [(90, 2, 0), (20, 1, 0), (25, 3, 0)])

    def test_e1_owner_decisions_by_verb_and_by_request(self):
        got = {n: self.measure(n)['owner_decisions'] for n in ('P1', 'P2', 'P3')}
        self.assertEqual([got[n]['by_verb'] for n in ('P1', 'P2', 'P3')],
                         [{'approve': 1, 'accept': 1, 'record': 0, 'answer': 0}, {'approve': 1, 'accept': 1, 'record': 0, 'answer': 0},
                          {'approve': 2, 'accept': 1, 'record': 0, 'answer': 1}])
        self.assertEqual([got[n]['total'] for n in ('P1', 'P2', 'P3')], [2, 2, 4])
        request = got['P3']['by_request']
        self.assertEqual(len(request), 1)
        self.assertEqual((request[0]['type'], request[0]['choice'], request[0]['decided_by']), ('v2.plan_stopped', 'amend_plan', 'user'))
        self.assertEqual(got['P1']['by_request'], [])
        self.assertEqual(got['P3']['by_source'], {'user': 4, 'relayed': 0, 'entry': 0, 'unknown': 0})       # the owner ran every verb with ONECREW_ACTOR=user

    def test_e1_figures_with_no_source_in_the_ledger_are_unknown_and_say_why(self):
        m = self.measure('P1')
        self.assertEqual(m['status_queries'], {'value': UNKNOWN, 'why': m['status_queries']['why']})
        self.assertIn('read-only', m['status_queries']['why'])
        self.assertEqual((m['waits']['resource']['minutes'], m['waits']['external_service']['minutes']), (UNKNOWN, UNKNOWN))

    # [E2] a wait is not the owner's active minutes
    def test_e2_waiting_is_not_active_minutes(self):
        m = self.measure('P3')
        self.assertEqual(m['waits']['owner']['minutes'], 34.0)                              # approval 1 + approval 1 + the question 30 + acceptance 2
        request = [i for i in m['waits']['owner']['items'] if i['kind'] == 'request']
        self.assertEqual([(i['minutes'], i['from'][11:16], i['to'][11:16]) for i in request], [(30.0, '11:10', '11:40')])
        self.assertEqual(m['owner_active_minutes']['value'], UNKNOWN)                      # recorded by the owner (group B); never derived from the 30 minutes
        self.assertNotEqual(m['owner_active_minutes']['value'], 30.0)
        self.assertIn('owner', m['owner_active_minutes']['why'])
        self.assertEqual(self.measure('P1')['owner_active_minutes']['value'], UNKNOWN)      # nor 0
        self.assertEqual(self.measure('P3')['time_to_output']['excluding_owner_wait_minutes'], 18.0)     # the wait is taken OUT of the working time

    def test_an_open_question_is_an_open_wait_not_a_number(self):
        self.propose('P4', plan_json(title='Fourth'))
        self.clock.at('12:00'); plans.approve(self.ledger, 'P4', 'owner', 'fixture')
        anchor = plans.show(self.ledger, 'P4')['anchor_task']
        self.ledger.create_request(anchor, 'q-open', {'schema_version': 1, 'question': 'Which?', 'reason': 'r', 'impact': 'i',
                                                       'options': [{'id': 'a', 'label': 'A'}, {'id': 'b', 'label': 'B'}], 'recommendation': 'a',
                                                       'action': {'type': 'v2.plan_stopped', 'parameters': {'plan': 'P4', 'revision': 1, 'milestone': 'M1', 'key': 'q-open'}}})
        m = self.measure('P4')
        open_items = [i for i in m['waits']['owner']['items'] if i['kind'] == 'request']
        self.assertEqual([(i['minutes'], i['open']) for i in open_items], [(UNKNOWN, True)])
        self.assertEqual(m['time_to_output']['wall_minutes'], UNKNOWN)                      # not verified yet


class AdapterTests(ThreeRoots):
    # [E3] the classification is the v1 evaluation functions' own
    def test_e3_the_measure_calls_the_v1_functions(self):
        counter = Counting()
        m = self.measure('P3', counter)
        self.assertGreaterEqual(counter.total, 1)
        self.assertIn('signals', counter.calls)
        self.assertIn('decision_source', counter.calls)                                    # who decided each answer: v1's rule
        self.assertEqual(m['v1_calls'], counter.total)

    def test_e3_the_v1_view_keeps_unknown_unknown(self):
        view = self.measure('P1')['v1_view']
        self.assertEqual(view['completion_level'], 'complete')
        self.assertEqual(view['assistance_level'], 'unknown')                              # v2 records no runtime trace yet: not "autonomous"
        self.assertEqual(view['outcome'], 'unknown')
        self.assertIn('plan_provenance_unknown', view['assistance_reasons'])

    # [E10] a measure that classifies on its own does not call v1: the integration check sees it
    def test_e10_a_copied_classification_is_caught_by_the_call_counter(self):
        counter = Counting()
        own = {'runtime_revisions': None, 'coordinator_restarts': None, 'coordinator_restarts_by_initiator': None, 'child_starts_by_initiator': None,
               'interventions': None, 'decisions_answered': 1, 'decisions_by_source': {'user': 1, 'relayed': 0, 'entry': 0, 'unknown': 0}}      # what a copy would work out itself
        with patch.object(metrics, 'classify_decisions', lambda rows, root, evaluator: {k: own[k] for k in ('decisions_answered', 'decisions_by_source', 'interventions')} | {'signals': own}):
            self.measure('P3', counter)
        self.assertNotIn('signals', counter.calls)
        with self.assertRaises(AssertionError): self.assertIn('signals', counter.calls, 'a measure that re-implements the classification never calls v1')

    def test_e10_the_module_holds_no_copy_of_the_v1_classification(self):
        source = Path(metrics.__file__).read_text(encoding='utf-8')
        for forbidden in ('def decision_source', 'def role(', 'def signals', 'def assistance_level', 'def completion_level', 'DECISION_SOURCES', 'ENTRY_ACTORS', 'DECISIONS ='):
            self.assertNotIn(forbidden, source)
        self.assertNotRegex(source, r'(?m)^(from|import) \.{1,2}?(eval_|evaluation)', 'the v1 evaluation modules are reached by name at call time, not imported')

    def test_without_the_v1_functions_the_adapter_says_so(self):
        with patch.object(metrics, 'V1_MODULES', ('onecrew.not_here',)):
            with self.assertRaises(metrics.EvaluatorUnavailable) as caught: metrics.v1_evaluator()
        self.assertIn('unavailable', str(caught.exception))


class WholeLedgerTests(ThreeRoots):
    def test_all_roots_with_a_denominator_per_figure(self):
        report = metrics.measure_all(self.ledger, metrics.v1_evaluator())
        self.assertEqual(sorted(r['plan'] for r in report['roots']), ['P1', 'P2', 'P3'])
        cover = report['coverage']
        self.assertEqual(cover['time_to_output'], {'k': 3, 'n': 3, 'status': 'đủ', 'group': 'A'})
        self.assertEqual(cover['rework'], {'k': 3, 'n': 3, 'status': 'đủ', 'group': 'A'})
        self.assertEqual(cover['check_cost'], {'k': 3, 'n': 3, 'status': 'đủ', 'group': 'A'})
        self.assertEqual(cover['owner_decisions'], {'k': 3, 'n': 3, 'status': 'đủ', 'group': 'A'})
        self.assertEqual(cover['owner_active_minutes'], {'k': 0, 'n': 3, 'status': 'không có', 'group': 'B'})     # nobody wrote it down: no number, not 0
        self.assertEqual(cover['status_queries'], {'k': 0, 'n': 3, 'status': 'không có', 'group': 'C'})
        self.assertEqual(report['totals']['repair_rounds'], 3)
        self.assertEqual(report['totals']['check_seconds'], 135)
        self.assertEqual(report['totals']['owner_wait_minutes'], 2 + 2 + 1 + 1 + 34)
        self.assertNotIn('combined_score', json.dumps(report))
        self.assertNotIn('review', ' '.join(report['coverage']).lower())                  # the number of reviews is not the success measure

    def test_the_measure_writes_nothing(self):
        before = len(self.events('P1')) + len(self.events('P2')) + len(self.events('P3'))
        metrics.measure_all(self.ledger, metrics.v1_evaluator())
        self.assertEqual(len(self.events('P1')) + len(self.events('P2')) + len(self.events('P3')), before)


class CliTests(ThreeRoots):
    def test_the_checkout_command_prints_the_figures(self):
        import subprocess
        env = dict({k: v for k, v in os.environ.items() if k != 'CLAUDECODE'}, PYTHONUTF8='1')
        done = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'onecrew', '--project', str(self.root), '--state-root', str(self.ledger.state_root), 'eval', 'plan-metrics', '--json'],
                              cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=120, env=env)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        body = json.loads(done.stdout.decode('utf-8'))
        self.assertEqual(sorted(r['plan'] for r in body['roots']), ['P1', 'P2', 'P3'])
        self.assertEqual(body['coverage']['owner_active_minutes']['k'], 0)


if __name__ == '__main__':
    unittest.main()
