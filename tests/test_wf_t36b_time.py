"""T36b time semantics (R03 W32a/W33a; Codex finding P2-1): execution vs waiting vs time to the deadline, and the 70% budget warning.

Semantics under test (executors.summary / estimates.read):
  * an attempt's execution = (end - start) minus the UNION of its waits clipped to [start, end]; the same wait ref observed again counts once,
    two different overlapping waits count their union once; a wait wholly outside the attempt is waiting time but is not subtracted;
  * a wait whose start is unknown, or whose end is unknown while it began before the attempt ended, makes execution UNKNOWN (never 0, never a guess);
  * waiting = union of all observed waits (same merging), reported separately; unknown while any wait is open or unplaced;
  * wall_clock_remaining_seconds = deadline - now (injected `now`), a calendar figure that already includes waiting; it is not remaining
    execution work and not a calibrated ETA; after the deadline it is negative with deadline_passed=True (never clamped);
  * the 70% budget warning reuses the v1 policy (task_intake.POLICY warning_fraction via budget_policy.watch_policy) on the root's approved
    budget; it is one notice.exception (category budget_warning) per threshold crossing, never a request.

Fake clock: explicit ISO `at` / `until` / `now` strings; nothing sleeps. Real temporary ledger (tests.test_v2_l1.Fixture).
"""
import json

from onecrew import task_intake
from onecrew.v2 import estimates, executors, plan, report
from tests.test_v2_l1 import Fixture, plan_json

DEADLINE = '2026-10-25T18:00:00+07:00'
BASELINE = [21600, 28800]
MANAGED = executors.Declaration('fixture-managed', 'managed', ('measure',), ('time',))
COUNTING = executors.Declaration('fixture-counting', 'managed', ('measure',), ('time', 'calls'))
H = 3600


def t(hour, minute=0):
    return f'2026-10-25T{hour:02d}:{minute:02d}:00+07:00'


class T36bTime(Fixture):
    def start(self, budget_minutes=1200, deadline=DEADLINE, max_calls=100):
        estimate = {'execution_seconds': BASELINE, 'evidence': ['fixture:task decomposition']}
        if deadline: estimate['deadline'] = deadline
        self.approved('P1', plan_json(budget={'max_calls': max_calls, 'time': budget_minutes}), estimate=estimate)

    def obs(self, attempt, what, at, until=None, ref=None, executor=MANAGED, measured=None):
        return executors.observe(self.ledger, 'P1', executor, attempt, what, source='executor_clock',
                                 ref=ref or f'clock:{attempt}:{what}:{at}', at=at, until=until,
                                 wait_reason='owner' if what == 'wait' else None, measured=measured)

    def attempt(self, name):
        return next(a for a in executors.summary(self.ledger, 'P1')['attempts'] if a['attempt'] == name)

    def warnings(self):
        return [p for k, p in self.events() if k == 'notice.exception' and p.get('category') == 'budget_warning']

    # 1. Codex P2-1: 08-12 attempt with a 09-11 owner wait inside it
    def test_p2_1_wait_inside_attempt_is_subtracted_from_execution(self):
        self.start()
        self.obs('m1', 'start', t(8))
        self.obs('m1', 'wait', t(9), until=t(11))
        self.obs('m1', 'end', t(12))
        a = self.attempt('m1')
        self.assertEqual((a['elapsed_seconds'], a['execution_seconds'], a['wait_seconds']), (4 * H, 2 * H, 2 * H))
        out = estimates.read(self.ledger, 'P1')
        self.assertEqual((out['execution_seconds'], out['waiting_seconds']), (2 * H, 2 * H))
        self.assertIn('Thực thi: 2 giờ; chờ: 2 giờ', report.render_report(self.ledger.state_root, 'P1'))
        self.assertNotIn('Thực thi: 4 giờ', report.render_present(self.ledger.state_root, 'P1'))

    # 2. overlapping waits count their union once; the same wait ref observed again counts once
    def test_overlapping_and_repeated_waits_are_merged(self):
        self.start()
        self.obs('m1', 'start', t(8))
        self.obs('m1', 'wait', t(9), ref='wait:A')                                   # open first ...
        self.obs('m1', 'wait', t(9), until=t(11), ref='wait:A')                      # ... then closed: the same wait, once
        self.obs('m1', 'wait', t(9), until=t(11), ref='wait:A')                      # an exact repeat writes nothing
        self.obs('m1', 'wait', t(9), until=t(11), ref='wait:A-copy')                 # the same interval under another ref
        self.obs('m1', 'wait', t(10), until=t(12), ref='wait:B')                     # overlaps A
        self.obs('m1', 'end', t(13))
        a = self.attempt('m1')
        self.assertEqual((a['elapsed_seconds'], a['wait_seconds'], a['execution_seconds']), (5 * H, 3 * H, 2 * H))
        out = estimates.read(self.ledger, 'P1')
        self.assertEqual((out['waiting_seconds'], out['execution_seconds']), (3 * H, 2 * H))

    # 3. a wait with an unknown end (or unknown start) makes execution unknown, never a number
    def test_wait_with_unknown_until_or_at_makes_execution_unknown(self):
        self.start()
        self.obs('m1', 'start', t(8))
        self.obs('m1', 'wait', t(9))                                                  # still open: nobody said when it ended
        self.obs('m1', 'end', t(12))
        a = self.attempt('m1')
        self.assertEqual((a['elapsed_seconds'], a['execution_seconds'], a['wait_seconds']), (4 * H, executors.UNKNOWN, executors.UNKNOWN))
        out = estimates.read(self.ledger, 'P1')
        self.assertEqual((out['execution_seconds'], out['waiting_seconds']), ('unknown', 'unknown'))
        text = report.render_report(self.ledger.state_root, 'P1')
        self.assertIn('Thực thi: chưa đo được; chờ: chưa đo được', text)
        self.assertNotIn('Thực thi: 0', text)
        # a wait whose start is unknown cannot be placed: unknown too
        self.obs('m2', 'start', t(13)); self.obs('m2', 'end', t(14))
        executors.observe(self.ledger, 'P1', MANAGED, 'm2', 'wait', source='executor_clock', ref='wait:m2', wait_reason='owner')
        self.assertEqual(self.attempt('m2')['execution_seconds'], executors.UNKNOWN)

    def test_open_wait_after_the_attempt_ended_does_not_hide_its_execution(self):
        self.start()
        self.obs('m1', 'start', t(8)); self.obs('m1', 'end', t(9))
        self.obs('m1', 'wait', t(10))                                                 # open, but it began after the attempt ended
        a = self.attempt('m1')
        self.assertEqual((a['execution_seconds'], a['wait_seconds']), (H, executors.UNKNOWN))
        self.assertEqual(estimates.read(self.ledger, 'P1')['waiting_seconds'], 'unknown')

    def test_unknown_start_or_end_stays_unknown_and_not_measured_stays_not_measured(self):
        self.start()
        self.obs('m1', 'start', t(8))
        self.assertEqual(self.attempt('m1')['execution_seconds'], executors.UNKNOWN)
        hook = executors.HookAdapter
        executors.observe(self.ledger, 'P1', hook, 'h1', 'start', source='tool_call', ref='toolu_1', at=t(8))
        executors.observe(self.ledger, 'P1', hook, 'h1', 'end', source='tool_call', ref='toolu_2', at=t(9))
        self.assertEqual(self.attempt('h1')['execution_seconds'], executors.NOT_MEASURED)
        self.assertEqual(estimates.read(self.ledger, 'P1')['execution_seconds'], 'unknown')

    def test_the_adapters_own_seconds_measurement_is_its_execution(self):
        self.start()
        self.obs('m1', 'start', t(8))
        self.obs('m1', 'wait', t(9), until=t(11))
        self.obs('m1', 'end', t(12), measured={'seconds': 5400})                    # the adapter's clock ran only while executing
        a = self.attempt('m1')
        self.assertEqual((a['execution_seconds'], a['execution_source'], a['wait_seconds']), (5400, 'adapter_measured', 2 * H))

    # 4. time to the deadline with an injected clock; distinct from remaining work and from an ETA
    def test_wall_clock_remaining_is_deadline_minus_now_and_not_remaining_work(self):
        self.start()
        estimates.reforecast(self.ledger, 'P1', 'm1-done', [10800, 14400], 'M1 completed with receipt', ['receipt:m1'])
        self.obs('m1', 'start', t(8)); self.obs('m1', 'wait', t(9), until=t(11)); self.obs('m1', 'end', t(12))
        out = estimates.read(self.ledger, 'P1', now=t(12))
        self.assertEqual(out['wall_clock_remaining_seconds'], 6 * H)
        self.assertEqual(out['wall_clock_kind'], 'time_to_deadline')
        self.assertFalse(out['deadline_passed'])
        self.assertEqual(out['remaining_seconds'], [10800, 14400])                  # remaining execution work is another figure
        self.assertNotEqual(out['wall_clock_remaining_seconds'], out['remaining_seconds'][0])
        self.assertNotEqual(out['wall_clock_remaining_seconds'], out['remaining_seconds'][1])
        self.assertEqual(out['remaining_kind'], 'execution_work')
        self.assertFalse(out['calibrated'])
        self.assertEqual((out['deadline'], out['baseline']['execution_seconds']), (DEADLINE, BASELINE))   # nothing extended or reset
        late = estimates.read(self.ledger, 'P1', now=t(19))
        self.assertEqual((late['wall_clock_remaining_seconds'], late['deadline_passed']), (-H, True))    # negative and flagged, never clamped
        self.assertEqual(late['deadline'], DEADLINE)
        text = report.render_present(self.ledger.state_root, 'P1')
        self.assertRegex(text, r'(giờ lịch tới deadline|Đã quá deadline)')        # the page reads this machine's clock
        self.assertIn('không phải công còn lại', text)

    def test_no_deadline_means_no_wall_clock_figure_with_a_reason(self):
        self.start(deadline=None)
        out = estimates.read(self.ledger, 'P1', now=t(12))
        self.assertIsNone(out['wall_clock_remaining_seconds'])
        self.assertIsNone(out['deadline_passed'])
        self.assertTrue(out['wall_clock_reason'])

    # [E15] second clause: an unmeasured / unobserved milestone 2 is never treated as "no progress" nor shown as 0
    def test_e15_unmeasured_milestone_is_unknown_and_never_a_no_progress_notice(self):
        from onecrew.v2 import exceptions
        self.start(budget_minutes=120)                                                # small budget: a 0-based guess would show up here
        self.obs('m1', 'start', t(8)); self.obs('m1', 'end', t(9))                    # milestone 1: measured, 1 h
        hook = executors.HookAdapter                                                 # milestone 2: an executor that does not measure time
        executors.observe(self.ledger, 'P1', hook, 'm2', 'start', source='tool_call', ref='toolu_m2_start', at=t(9))
        executors.observe(self.ledger, 'P1', hook, 'm2', 'end', source='tool_call', ref='toolu_m2_end', at=t(13))
        self.obs('m2b', 'start', t(13))                                              # and a measured attempt with no end observed
        exceptions.observe(self.ledger, 'P1', now=t(14))                             # give the notice writer its chance (before the deadline)
        self.assertEqual((self.attempt('m1')['execution_seconds'], self.attempt('m2')['execution_seconds'], self.attempt('m2b')['execution_seconds']),
                         (H, executors.NOT_MEASURED, executors.UNKNOWN))
        out = estimates.read(self.ledger, 'P1', now=t(14))
        self.assertEqual(out['execution_seconds'], 'unknown')                        # not 1 h (M2 as 0), not 0
        notices = [p for k, p in self.events() if k == 'notice.exception']
        self.assertEqual(notices, [])                                                # no no-progress, budget or other notice at all
        self.assertFalse([p for p in notices if 'm2' in json.dumps(p)])
        line = next(l for l in executors.render(executors.summary(self.ledger, 'P1')).splitlines() if '· m2 ·' in l)
        self.assertIn('thực thi (trừ chờ): không đo', line)
        self.assertNotRegex(line, r'thực thi \(trừ chờ\): 0')
        for render in (report.render_present, report.render_report):
            text = render(self.ledger.state_root, 'P1')
            self.assertIn('Thực thi: chưa đo được', text, render.__name__)
            for banned in ('không tiến triển', 'no progress', 'Thực thi: 0', ' 0 s', ' 0s'):
                self.assertNotIn(banned, text, (render.__name__, banned))
            self.assertNotRegex(text, r'(?<![\d.,])0 giờ', render.__name__)          # a standalone zero, not the "5.0 giờ" to the deadline

    # 5. the 70% budget warning: one in-authority notice per crossing, never a request
    def test_e17_seventy_percent_budget_warning_is_one_notice_not_a_request(self):
        self.start(budget_minutes=180)                                                # 10800 s; 70% = 7560 s
        self.obs('m1', 'start', t(8)); self.obs('m1', 'wait', t(8, 30), until=t(10, 30)); self.obs('m1', 'end', t(11))
        self.assertEqual(self.attempt('m1')['execution_seconds'], H)
        self.assertEqual(self.warnings(), [])                                        # 3 h elapsed, 1 h executed: waiting is not budget
        self.obs('m2', 'start', t(11)); self.obs('m2', 'end', t(13))                 # 3 h executed = 10800 >= 7560
        warnings = self.warnings()
        self.assertEqual(len(warnings), 1)
        w = warnings[0]
        self.assertEqual((w['category'], w['axis'], w['grants_authority'], w['user_action'], w['request']),
                         ('budget_warning', 'execution_seconds', False, None, None))
        self.assertEqual(w['policy']['fraction'], task_intake.POLICY['warning_fraction'])
        self.assertEqual((w['what_changed']['used'], w['what_changed']['limit'], w['what_changed']['threshold']), (3 * H, 10800, 7560))
        self.assertTrue(w['reason'].strip()); self.assertTrue(w['evidence'])
        self.obs('m3', 'start', t(13)); self.obs('m3', 'end', t(14))                 # still above: no second warning
        self.assertEqual(len(self.warnings()), 1)
        task = plan.show(self.ledger, 'P1')['anchor_task']
        self.assertEqual(self.ledger.requests(task), [])                             # [E17] no request for the owner
        out = estimates.read(self.ledger, 'P1')
        self.assertEqual(len(out['budget_warnings']), 1)
        for render in (report.render_present, report.render_report):
            text = render(self.ledger.state_root, 'P1')
            self.assertIn('Cảnh báo 70% ngân sách', text, render.__name__)
            self.assertIn('không cần bạn làm gì', text, render.__name__)

    def test_e17_calls_axis_and_unknown_never_triggers(self):
        self.start(max_calls=10)
        self.obs('c1', 'start', t(8), executor=COUNTING)
        self.obs('c1', 'end', t(8, 10), executor=COUNTING, measured={'calls': 6})
        self.assertEqual(self.warnings(), [])
        self.obs('c1', 'end', t(8, 20), ref='clock:c1:end:2', executor=COUNTING, measured={'calls': 1})   # 7 of 10 = 70%
        self.assertEqual([w['axis'] for w in self.warnings()], ['calls'])
        # an attempt with an unknown end adds no guessed time
        self.obs('u1', 'start', t(9))
        self.assertEqual([w['axis'] for w in self.warnings()], ['calls'])
