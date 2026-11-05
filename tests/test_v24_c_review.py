"""2.4-C review fixes (D:/OneCrewRuns/v24/review-c/review-c.md, C-R01..C-R18): every probe of the review as a test, plus the missing
§7 2.4-C cases (two concurrent tools runs, exclusive resource across step+batch and tools+worker, tools on a moved generation, the
CapacityWait branch at reserve time, raising/dropping an unknown in a later check, the budget against 2.3, session evidence across attempts).
Fixtures only: they prove the rules, records and fences, not a real model or provider."""
import contextlib
import copy
import io
import json
import os
import threading
from unittest.mock import patch

from onecrew.control_core import Control, migrate
from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, engine_cli, execution_mode, executors, internal_plan, plan as plans, proposal, step0, survey
from tests.test_v2_l1 import Fixture, milestone, plan_json
from tests.test_v24_c_execution_mode import BASE_CAPS, OWNED, ModeFixture, integration, worker
from tests.test_v24_c_step0_card import BLOCKING, INVESTIGATION, CardFixture, card_sample, codes
from tests.test_wf_r01_step0_survey import Clock


# ---- C-R01 / C-R02 / C-R16: the step-0 stop point holds -----------------------------------------------------------------------

class StopPoint(CardFixture):
    def spend_cap(self):
        value = card_sample(unknowns=[BLOCKING], investigation=INVESTIGATION); value['preferred'] = None
        self.review(value)
        opened = survey.show(self.ledger, 'P1')['surveys']
        clock = Clock()
        def slow(context):
            clock.advance(4 * 60 + 1); context.read('x/y.py')
        survey.run(self.ledger, 'P1', opened[0]['id'], slow, clock=clock)
        self.assertIn('investigation_cap_spent', codes(self.review(value)))
        return value

    def refused_everywhere(self, out, code):
        self.assertFalse(out['ok']); self.assertIn(code, codes(out))
        self.assertFalse(out['card']['enough']); self.assertIn(code, out['card']['not_enough'])
        self.assertIn('U1', [u['id'] for u in out['card']['unknowns_open']])
        with self.assertRaises(LedgerError) as caught: plans.approve(self.ledger, 'P1', 'owner', 'said yes')
        self.assertIn('proposal_refused', str(caught.exception))

    def test_r01_a_later_check_cannot_close_the_unknown_without_evidence(self):
        self.spend_cap()
        out = self.review(card_sample(unknowns=[dict(BLOCKING, status='closed')], investigation=INVESTIGATION))
        self.refused_everywhere(out, 'unknown_dropped_without_evidence')

    def test_r01_a_later_check_cannot_drop_the_unknown_without_evidence(self):
        self.spend_cap()
        out = self.review(card_sample(investigation=INVESTIGATION))
        self.refused_everywhere(out, 'unknown_dropped_without_evidence')
        dropped = card_sample(investigation=INVESTIGATION)
        history = step0.proposal_history(self.ledger, 'P1', REQ_SHA(self))
        self.assertTrue(proposal.check(self.ledger, REQUIREMENT_OF(self), dropped, history=history,
                                       rules=tuple(r for r in proposal.RULES if r is not proposal.rule_unknown_dropped))['ok'])   # counter-proof

    def test_r01_closing_evidence_in_the_ledger_lets_it_close(self):
        self.spend_cap()
        from onecrew.v2 import decisions
        with patch.dict(os.environ, {'ONECREW_ACTOR': 'user'}):
            decisions.record(self.ledger, plans.show(self.ledger, 'P1')['anchor_task'], subject={'component': 'owner', 'model': 'human'},
                             authority={'grant_id': 'owner-chat-0111', 'revision': 'r1'}, evidence=[{'statement': 'U1: not used by another job'}],
                             basis='the owner knows the old report data is not used elsewhere', scope='unknown:U1', by='owner')
        out = self.review(card_sample(unknowns=[dict(BLOCKING, status='closed')], investigation=INVESTIGATION))
        self.assertTrue(out['ok'], out['reasons'])

    def test_r02_a_later_check_cannot_raise_the_cap_and_a_refused_cap_is_never_used(self):
        value = self.spend_cap()
        bigger = copy.deepcopy(value); bigger['investigation'] = dict(INVESTIGATION, cap={'minutes': 120, 'calls': 50})
        out = self.review(bigger)
        self.assertIn('investigation_widened', codes(out))
        self.assertEqual(len(survey.show(self.ledger, 'P1')['surveys']), 1)                    # no survey after the stop
        lower = copy.deepcopy(value); lower['investigation'] = dict(INVESTIGATION, cap={'minutes': 3, 'calls': 2})
        self.assertNotIn('investigation_widened', codes(self.review(lower)))
        with self.ledger.transaction() as conn:
            self.assertEqual(survey.investigation_of(conn, plans.show(self.ledger, 'P1')['anchor_task'])['cap'], {'minutes': 3, 'calls': 2})

    def test_r02_r16_an_out_of_bounds_cap_or_whole_project_paths_are_recorded_refusals_never_used(self):
        for bad in (dict(INVESTIGATION, cap={'minutes': 999, 'calls': 999}), dict(INVESTIGATION, paths=['.'])):
            value = card_sample(unknowns=[BLOCKING], investigation=bad); value['preferred'] = None
            out = self.review(value)                                                          # recorded, not raised
            self.assertFalse(out['ok'])
            self.assertTrue({'investigation_cap', 'investigation_unscoped'} & set(codes(out)))
            with self.ledger.transaction() as conn:
                self.assertIsNone(survey.investigation_of(conn, plans.show(self.ledger, 'P1')['anchor_task']))
            self.assertEqual(survey.show(self.ledger, 'P1')['surveys'], [])                  # no survey of the whole project


def REQUIREMENT_OF(case):
    from tests.test_wf_r01_step0_proposal import REQUIREMENT
    return REQUIREMENT


def REQ_SHA(case):
    from onecrew.ledger import content_hash
    return content_hash(proposal.validate_requirement(REQUIREMENT_OF(case)))


# ---- C-R03 / C-R04 / C-R07..R11: tools ----------------------------------------------------------------------------------------

class Free:
    model_free = True

    def __init__(self, case, gate=None):
        self.case, self.gate, self.calls = case, gate, []

    def __call__(self, item, artifact):
        self.calls.append(item['id'])
        if self.gate is not None:
            try: self.gate.wait(3)
            except threading.BrokenBarrierError: pass
        return self.case.checker(item, artifact)


class Tools(ModeFixture):
    def test_r03_two_concurrent_tools_runs_verify_once(self):
        self.revise([worker('A', ['a.txt']), worker('B', ['b.txt']), integration(['A', 'B'])])
        self.step()
        checker = Free(self, threading.Barrier(2))
        results = []
        def run(entry):
            try:
                if entry == 'step': results.append(engine.step(self.ledger, 'P1', self.isolated(), checker=checker, _target='A'))
                else: results.append(engine.run_batch(self.ledger, 'P1', self.isolated(), slots=2, checker=checker))
            except Exception as error:
                results.append({'error': repr(error)})
        threads = [threading.Thread(target=run, args=(entry,)) for entry in ('step', 'batch')]
        for t in threads: t.start()
        for t in threads: t.join(30)
        self.assertEqual(checker.calls, ['A'])
        self.assertEqual(len([p for p in self.payloads('node.verification') if p['node'] == 'A']), 1)
        self.assertFalse([r for r in results if 'error' in r], results)

    def test_r03_two_concurrent_step_checks_on_one_node_verify_once(self):
        self.revise([worker('A', ['a.txt']), integration(['A'])])
        self.step()
        checker = Free(self, threading.Barrier(2))
        results = []
        threads = [threading.Thread(target=lambda: results.append(engine.step(self.ledger, 'P1', self.isolated(), checker=checker)))
                   for _ in range(2)]
        for t in threads: t.start()
        for t in threads: t.join(30)
        self.assertEqual(checker.calls, ['A'])
        self.assertEqual(len([p for p in self.payloads('node.verification') if p['node'] == 'A']), 1)
        self.assertEqual(sorted(r['state'] for r in results), ['verified', 'waiting'])
        loser = next(r for r in results if r['state'] == 'waiting')
        self.assertIn('tools_in_progress', json.dumps(loser))

    def held_by_running(self, resources_a, resources_b, read_b=None):
        self.revise([worker('A', ['a.txt'], resources=resources_a), worker('B', ['b.txt'], read=read_b, resources=resources_b),
                     integration(['A', 'B'])])
        self.step()                                                                           # A produced
        started, release, out = threading.Event(), threading.Event(), {}
        def hold(ledger, control, task, item, attempt):
            control.launched(attempt['id'], attempt['generation'], {'fixture': True}); started.set()
            release.wait(10)
            r = {'artifact': self.store.blob(b'B out'), 'receipt': self.store.blob(b'B receipt')}
            control.finish(attempt['id'], attempt['generation'], r); return r
        thread = threading.Thread(target=lambda: out.update(engine.step(self.ledger, 'P1', self.isolated(hold), _target='B', slots=2)))
        thread.start(); self.addCleanup(lambda: (release.set(), thread.join(10)))
        self.assertTrue(started.wait(5))
        return release, thread, out

    def test_r04_tools_waits_for_a_running_worker_holding_the_same_resource(self):
        release, thread, out = self.held_by_running(['db:dev'], ['db:dev'])
        checker = Free(self)
        result = engine.step(self.ledger, 'P1', self.isolated(), checker=checker, slots=2)
        self.assertEqual((result['state'], result['mode']), ('waiting', 'wait'))
        self.assertTrue(any(r.startswith('exclusive_resource:B:shared_resource:db:dev') for r in result['reasons']), result)
        self.assertEqual(checker.calls, [])
        release.set(); thread.join(10)
        self.assertEqual(engine.step(self.ledger, 'P1', self.isolated(), checker=checker)['mode'], 'tools')
        self.assertEqual(checker.calls, ['A'])

    def test_r04_tools_waits_for_a_running_worker_that_writes_what_it_reads(self):
        release, thread, out = self.held_by_running([], [], read_b=['b.txt', 'a.txt'])
        result = engine.step(self.ledger, 'P1', self.isolated(), checker=Free(self), slots=2)
        self.assertEqual(result['mode'], 'wait'); self.assertTrue(any('read_write' in r for r in result['reasons']), result)

    def test_r04_an_open_tools_run_holds_a_worker_sharing_its_resource(self):
        self.revise([worker('A', ['a.txt'], resources=['db:dev']), worker('C', ['c.txt']), worker('B', ['b.txt'], depends=['C'], resources=['db:dev']),
                     integration(['A', 'B', 'C'])])
        self.step(); self.step(); self.verify('C')                                             # A produced, C verified, B ready
        entered, release = threading.Event(), threading.Event()
        case = self
        class Slow(Free):
            def __call__(self, item, artifact):
                entered.set(); release.wait(10); return case.checker(item, artifact)
        thread = threading.Thread(target=lambda: engine.step(self.ledger, 'P1', self.isolated(), checker=Slow(self)))
        thread.start()
        try:
            self.assertTrue(entered.wait(5))
            self.assertEqual([c['id'] for c in engine.ready(self.ledger, 'P1', slots=2)], [])    # B waits for A's checks (db:dev)
            waiting = engine.run_batch(self.ledger, 'P1', self.isolated(), slots=2)
            self.assertNotIn('B', [p['node'] for p in self.started()])
        finally:
            release.set(); thread.join(10)
        self.assertEqual(engine.step(self.ledger, 'P1', self.isolated(), slots=2)['node'], 'B')

    def test_r04_two_produced_nodes_sharing_a_label_get_one_checker_per_batch(self):
        self.revise([worker('A', ['a.txt'], resources=['db:dev']), worker('B', ['b.txt'], resources=['db:dev']), integration(['A', 'B'])])
        self.step(); self.step()
        checker = Free(self)
        engine.run_batch(self.ledger, 'P1', self.isolated(), slots=2, checker=checker)
        self.assertEqual(len(checker.calls), 1)

    def test_r07_only_command_or_model_free_adapter_checks_are_tools(self):
        self.revise([worker('A', ['a.txt']), integration(['A'])])
        self.step()
        view = engine.state(self.ledger, 'P1'); a = view['definition']['nodes'][0]
        for kind, expected in (('command', 'tools'), ('adapter', 'tools'), ('owner-manual', 'wait'), ('reviewer', 'wait'), ('adapter_metered', 'wait')):
            out = execution_mode.choose(a, view, slots=1, checker=Free(self), check_types={'check-A': kind})
            self.assertEqual(out['mode'], expected, kind)
        self.assertIn('not_model_free:check-A=owner-manual', execution_mode.choose(a, view, slots=1, checker=Free(self),
                                                                                    check_types={'check-A': 'owner-manual'})['reasons'])
        contract = {'milestones': [{'id': 'check-A', 'verifier': {'type': 'owner-manual', 'config': {}}}]}
        self.assertEqual(execution_mode.check_types(contract, a), {'check-A': 'owner-manual'})

    def test_r08_r09_a_failing_tools_try_is_retried_a_bounded_number_of_times_and_never_breaks_the_batch(self):
        self.revise([worker('A', ['a.txt']), worker('B', ['b.txt']), integration(['A', 'B'])])
        self.step()
        calls = []
        class Broken(Free):
            def __call__(self, item, artifact):
                calls.append(item['id']); raise OSError('checker host gone')
        for _ in range(4):
            out = engine.run_batch(self.ledger, 'P1', self.isolated(), slots=2, checker=Broken(self))      # never raises
            self.assertIn('results', out)
        # 2.5-B RV-T3 changed this from TOOLS_TRIES calls: the exception left the outcome unknown, so the check is held, not replayed;
        # the automatic tries stay bounded and `engine verify` explains what to do. A refusal before any verifier ran can still be tried again.
        self.assertEqual(calls.count('A'), 1)
        self.assertLessEqual(calls.count('B'), execution_mode.TOOLS_TRIES)

        self.assertEqual(engine.verify(self.ledger, 'P1', 'A', Broken(self))['status'], 'held')
        self.assertEqual(calls.count('A'), 1)
        tried = [p for k, p in self.events() if k == 'workflow.mode' and p.get('phase') == 'released' and p.get('node') == 'A']
        self.assertEqual(len(tried), execution_mode.TOOLS_TRIES)
        self.assertEqual(engine.state(self.ledger, 'P1')['nodes']['B']['state'], 'produced')   # the worker side ran

    def test_r10_tools_do_not_run_on_a_stale_internal_definition(self):
        self.revise([worker('A', ['a.txt']), integration(['A'])])
        self.step()
        view = engine.state(self.ledger, 'P1'); view['definition_contract_sha'] = 'stale'
        self.assertEqual(engine._tool_choices(self.ledger, view, Free(self))[0], [])

    def test_tools_on_a_moved_generation_publish_nothing(self):
        self.revise([worker('A', ['a.txt']), integration(['A'])])
        self.step()
        definition = copy.deepcopy(internal_plan.current(self.ledger, 'P1')['definition']['nodes'])
        case = self
        class Moving(Free):
            def __call__(self, item, artifact):
                moved = copy.deepcopy(definition); moved[0]['goal'] += ' (narrowed while checking)'
                case.revise(moved)                                                             # A gets a new generation
                return case.checker(item, artifact)
        result = engine.step(self.ledger, 'P1', self.isolated(), checker=Moving(self))
        self.assertEqual((result['state'], result['mode']), ('waiting', 'tools'))
        self.assertEqual([p for p in self.payloads('node.verification')], [])
        self.assertIn('node.result_retained', self.kinds())
        self.assertEqual(engine.state(self.ledger, 'P1')['nodes']['A']['generation'], 1)


class ChecksFlagWithoutCapability(ModeFixture):
    mode = False

    def test_r11_checks_on_a_root_without_the_capability_runs_nothing(self):
        self.revise([worker('A', ['a.txt'], pin=True), integration(['A'], pin=True)])
        before = self.kinds()
        for verb in ('step', 'batch'):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = engine_cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'engine', verb, 'P1', '--checks'],
                                       native_executor=lambda ledger: self.fail('no worker may start'), checker=lambda ledger, plan: Free(self))
            self.assertEqual(code, 2, out.getvalue()); self.assertIn('execution-mode', out.getvalue())
        self.assertEqual(self.kinds(), before)


# ---- C-R05: the budget rule of 2.3 ------------------------------------------------------------------------------------------

class BudgetFixture(ModeFixture):
    def setUp(self):
        Fixture.setUp(self)
        self.engine, self.ip = engine, internal_plan
        for name in OWNED[1:]: (self.root / name).write_text(name + '\n')
        self.caps = BASE_CAPS + (['execution-mode'] if self.mode else [])
        raw = plan_json(scope={'owned': list(OWNED)}, budget={'max_calls': 5, 'time': 120},
                        authority={'edit': True, 'commands': True, 'edit_tests': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']})
        self.root_view = plans.propose(self.ledger, 'P1', raw, 'codex', workflow=True, capabilities=self.caps)
        plans.approve(self.ledger, 'P1', 'owner', 'fixture')
        os.environ['ONECREW_ACTOR'] = 'codex'
        self.store = Snapshots(self.ledger.state_root); migrate(self.ledger); self.control = Control(self.ledger)

    def scenario(self):
        a = worker('A', ['a.txt']); b = worker('B', ['b.txt'], depends=['A']); b['budget_calls'] = 3
        self.revise([a, b, integration(['A', 'B'])])
        count = []
        def partial(ledger, control, task, item, attempt):
            count.append(1); control.launched(attempt['id'], attempt['generation'], {'fixture': True})
            artifact = self.store.blob(('A-' + str(len(count))).encode()); control.finish(attempt['id'], attempt['generation'], {'fixture': True})
            more = len(count) <= 2
            return {'artifact': artifact, 'receipt': self.receipt(node=item['id'], partial=more, continuation={'remaining': 'r'} if more else None)}
        for _ in range(3): self.step(partial)
        self.verify('A')
        return self.step()


class BudgetWithMode(BudgetFixture):
    def test_r05_a_tight_budget_dispatches_like_2_3_and_says_so(self):
        out = self.scenario()
        self.assertEqual((out['node'], out['state']), ('B', 'produced'), out)
        self.assertIn('budget_tight', self.started('B')[0]['mode_reasons'])


class BudgetWithoutMode(BudgetFixture):
    mode = False

    def test_r05_the_2_3_path_on_the_same_scenario(self):
        out = self.scenario()
        self.assertEqual((out['node'], out['state']), ('B', 'produced'), out)


# ---- C-R06: session evidence across attempts --------------------------------------------------------------------------------

class SessionEvidence(ModeFixture):
    def test_r06_reuse_needs_the_previous_attempt_session_the_same_id_and_the_same_pin(self):
        self.revise([worker('A', ['a.txt'], pin=True), worker('C', ['c.txt'], pin=True), integration(['A', 'C'], pin=True)])
        seen = {'A': 0}
        def run(ledger, control, task, item, attempt):
            control.launched(attempt['id'], attempt['generation'], {'fixture': True, 'session_id': 'S-1'})
            control.finish(attempt['id'], attempt['generation'], {'fixture': True})
            more = item['id'] == 'A' and seen['A'] == 0
            if item['id'] == 'A': seen['A'] += 1
            return {'artifact': self.store.blob((item['id'] + str(seen.get(item['id'], 0))).encode()),
                    'receipt': self.receipt(node=item['id'], session_id='S-1', partial=more, continuation={'remaining': 'r'} if more else None)}
        executor = self.isolated(run, capabilities=('start', 'resume_session'), name='fixture-session-claim')
        for _ in range(3): engine.step(self.ledger, 'P1', executor)
        produced = {p['node']: p['session'] for p in self.payloads('node.produced')}
        self.assertFalse(produced['C']['reuse'])                                               # one attempt echoing its id is not reuse
        self.assertTrue(produced['A']['reuse'], produced['A'])                                 # continuation of S-1, launched and returned S-1
        decl = executor.declaration
        previous = {'session_id': 'S-1', 'pin': dict(worker('A', ['a.txt'], pin=True)['executor'])}
        pin = dict(previous['pin'])
        self.assertTrue(execution_mode.session(decl, 'S-1', 'S-1', previous=previous, pin=pin, role='worker')['reuse'])
        self.assertFalse(execution_mode.session(decl, 'S-1', 'S-1', previous=None, pin=pin, role='worker')['reuse'])
        self.assertFalse(execution_mode.session(decl, 'S-1', 'S-1', previous=previous, pin=dict(pin, model='other'), role='worker')['reuse'])
        self.assertFalse(execution_mode.session(decl, 'S-1', 'S-1', previous=previous, pin=pin, role='reviewer')['reuse'])
        self.assertFalse(execution_mode.session(decl, 'S-1', 'S-2', previous=previous, pin=pin, role='worker')['reuse'])
        self.assertFalse(execution_mode.session(decl, 'S-2', 'S-2', previous=previous, pin=pin, role='worker')['reuse'])


# ---- C-R12 / C-R13: the record says what happened ------------------------------------------------------------------------------

class Records(ModeFixture):
    def test_r12_overlap_is_corrected_when_the_partner_never_started(self):
        self.revise([worker('A', ['a.txt']), worker('B', ['b.txt']), integration(['A', 'B'])])
        original_choose = engine._choose
        def skip_b(ledger, view, item, executor, slots, ctx, peer):
            decision = original_choose(ledger, view, item, executor, slots, ctx, peer)
            if item['id'] == 'B': decision = execution_mode.rewrite(decision, 'run_now', decision['reasons'] + ['capacity_one_slot'])
            return decision
        with patch.object(engine, '_choose', skip_b):
            engine.run_batch(self.ledger, 'P1', self.isolated(), slots=2)
        a = self.started('A')[0]
        self.assertEqual(a['mode'], 'overlap')
        correction = [p for p in self.modes('A') if p.get('corrects')]
        self.assertEqual(correction[-1]['mode'], 'run_now'); self.assertIn('partner_skipped:B', correction[-1]['mode_reasons'])
        self.assertEqual(correction[-1]['corrects'], a['attempt'])
        report = execution_mode.measure(self.ledger, 'P1')
        self.assertEqual(next(x for x in report['attempts'] if x['node'] == 'A')['mode'], 'run_now')

    def test_r12_r13_the_capacity_wait_at_reserve_time_is_recorded_with_its_own_hash(self):
        self.revise([worker('A', ['a.txt'], pin=True), integration(['A'], pin=True)])
        from onecrew.task_intake import submit
        for index in range(2):
            task = submit(self.ledger, 'Other work holding a slot', f'other-{index}', plan_selector='plan-ns:P1', max_calls=2, max_seconds=60,
                          provider='codex', model='fixture-model')
            execution = self.control.configure(task['id'], task['revision'], {'mode': 'fixture-other'})
            self.control.reserve(task['id'], execution['revision'], 'other', {'unit': 'root'})
        real = execution_mode.facts
        def blind(ledger, conn, view, nid):
            out = real(ledger, conn, view, nid); out['capacity'] = {'active': 0, 'limit': 2}; return out    # filled after the choice
        used = self.used()
        with patch.object(execution_mode, 'facts', blind):
            result = engine.step(self.ledger, 'P1', self.isolated())
        self.assertEqual((result['state'], result['mode']), ('waiting', 'wait'))
        self.assertTrue(result['reasons'][0].startswith('capacity_full'))
        record = self.modes('A')[-1]
        self.assertEqual(record['mode'], 'wait')
        q2 = self.q2('A')[-1]
        self.assertNotEqual(q2['key'], 'mode-' + record['mode_inputs_sha'][:48])               # the hash covers the recorded wait
        body = dict(record['inputs'], mode='wait', reasons=record['mode_reasons'])
        from onecrew.ledger import content_hash
        self.assertEqual(record['mode_inputs_sha'], content_hash(body))
        self.assertEqual(self.started('A'), []); self.assertEqual(self.used(), used)

    def test_r12_a_continuation_that_does_not_take_the_second_slot_is_recorded_as_run_now(self):
        self.revise([worker('A', ['a.txt']), worker('U', ['c.txt']), worker('B', ['b.txt'], depends=['U']), integration(['A', 'U', 'B'])])
        view = engine.state(self.ledger, 'P1')
        b = next(n for n in view['definition']['nodes'] if n['id'] == 'B')
        view['nodes']['B'].update(resume_artifact='x' * 64, continues='ATT-x')
        view['nodes']['U'].update(artifact='y' * 64, state='verified', phase='complete')
        decl = self.isolated().declaration
        out = execution_mode.choose(b, view, slots=2, declaration=decl, peer=view['definition']['nodes'][0], filling=True,
                                    handover={'chars': 1, 'seconds': 'unknown', 'basis': 'x'})
        self.assertEqual(out['mode'], 'run_now'); self.assertIn('handover_unknown', out['reasons'])


# ---- C-R14 / C-R18: measurement ----------------------------------------------------------------------------------------------

class Measure(ModeFixture):
    def test_r14_r18_waits_close_when_the_data_is_there_and_overlap_is_a_union(self):
        self.revise([worker('U', ['c.txt']), worker('X', ['a.txt']), worker('B', ['b.txt'], depends=['U']), integration(['U', 'X', 'B'])])
        self.step(self.slow_prep(1.2, 60000)); self.verify('U')
        engine.run_batch(self.ledger, 'P1', self.isolated(), slots=2)                          # X runs, B skipped (handover > gain)
        engine.step(self.ledger, 'P1', self.isolated(), slots=2)                               # B now runs: its slot wait ends
        self.verify('X'); self.verify('B')
        report = execution_mode.measure(self.ledger, 'P1')
        b_wait = [w for w in report['waits'] if w['node'] == 'B']
        self.assertTrue(b_wait and isinstance(b_wait[0]['seconds'], float), report['waits'])
        self.assertEqual(self.step()['state'], 'produced')                                     # I
        self.verify('I'); self.assertEqual(self.step()['state'], 'waiting')                    # nothing pending: the final idle wait
        open_report = execution_mode.measure(self.ledger, 'P1')
        self.assertEqual(open_report['waits'][-1]['until'], 'unknown')                         # no later event yet: unknown, not 0
        with self.ledger.transaction(write=True) as conn:
            root = plans.anchor_events(self.ledger, conn, 'P1')
            plans.emit(self.ledger, conn, root['task_id'], 'plan.closed', {'revision': root['approved']['revision'], 'reason': 'fixture end'})
        report = execution_mode.measure(self.ledger, 'P1')
        self.assertIsInstance(report['waits'][-1]['seconds'], float)                           # closed at the root's last event
        self.assertIsInstance(report['wait_seconds'], float)

    def test_r18_overlapping_attempts_are_joined_not_summed(self):
        self.revise([worker('A', ['a.txt']), worker('B', ['b.txt']), integration(['A', 'B'])])
        barrier = threading.Barrier(2)
        def together(ledger, control, task, item, attempt):
            control.launched(attempt['id'], attempt['generation'], {'fixture': True})
            barrier.wait(5); import time; time.sleep(0.3)
            out = {'artifact': self.store.blob(('o-' + item['id']).encode()), 'receipt': self.store.blob(b'r')}
            control.finish(attempt['id'], attempt['generation'], out); return out
        engine.run_batch(self.ledger, 'P1', self.isolated(together), slots=2)
        report = execution_mode.measure(self.ledger, 'P1')
        import datetime as dt
        spans = [(dt.datetime.fromisoformat(a['reserved_at']), dt.datetime.fromisoformat(a['settled_at'])) for a in report['attempts']]
        self.assertEqual(report['attempts_wall_seconds'], round(executors.union_seconds(spans), 6))
        self.assertLess(report['attempts_wall_seconds'], sum(a['span_seconds'] for a in report['attempts']) - 0.2)


if __name__ == '__main__':
    import unittest
    unittest.main()
