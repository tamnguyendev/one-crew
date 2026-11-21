import datetime as dt
from unittest.mock import patch

from onecrew.v2 import executors, plan, report
from tests.test_obs1_tracking import QUESTION
from tests.v2_fixture import Fixture, plan_json


class BudgetTime(Fixture):
    start = dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc)

    def setUp(self):
        super().setUp()
        self.minute = 0
        clock = patch('onecrew.ledger.utcnow', side_effect=lambda: self.at(self.minute).isoformat())
        clock.start()
        self.addCleanup(clock.stop)
        self.value = plan_json(budget={'time': 10, 'max_calls': 100})
        self.task = self.propose(value=self.value)['anchor_task']

    def at(self, minute):
        return self.start + dt.timedelta(minutes=minute)

    def approve(self, minute=0):
        self.minute = minute
        plan.approve(self.ledger, 'P1', 'owner', 'fixture')

    def section(self, minute):
        text = report.render_report(self.ledger.state_root, 'P1', now=self.at(minute))
        return text.split('3. Phút so ngân sách\n')[1].split('4. Lần chặn')[0]

    def test_report_propose_advice_approve_delay_alone_never_exceeds_budget(self):
        self.minute = 25
        with self.ledger.transaction(write=True) as conn:
            state = plan.derive(self.ledger, conn, 'P1')
            plan.emit(self.ledger, conn, self.task, 'plan.advised', dict(revision=1, sha=state['revisions'][1]['sha'],
                      usable=True, answers=[], model='fixture', independence='independent'))
        self.assertIn('Phút tính ngân sách: 0 phút', self.section(30))
        self.approve(50)
        text = self.section(52)
        self.assertIn('Chờ chủ: 50 phút', text)
        self.assertIn('Phút tính ngân sách: 2 phút', text)
        self.assertNotIn('VƯỢT', text)

    def test_pending_reapproval_excludes_owner_wait_from_budget(self):
        self.approve(5)
        self.minute = 9
        self.value['milestones'][0]['title'] = 'Changed acceptance'
        plan.amend(self.ledger, 'P1', self.value, 'fixture changed milestone', 'claude')
        self.assertIn('Phút tính ngân sách: 4 phút', self.section(39))
        self.approve(40)
        text = self.section(44)
        self.assertIn('Chờ chủ: 36 phút', text)
        self.assertIn('Phút tính ngân sách: 8 phút', text)

    def test_unaffected_work_stays_chargeable_during_amendment(self):
        self.approve()
        self.minute = 2
        plan.amend(self.ledger, 'P1', dict(self.value, title='New title only'), 'fixture clarification', 'claude')
        self.assertIn('Phút tính ngân sách: 8 phút', self.section(8))

    def test_open_and_overlapping_owner_questions_count_wait_once(self):
        self.approve(3)
        self.minute = 7
        first = self.ledger.create_request(self.task, 'first', QUESTION)
        self.minute = 12
        self.ledger.create_request(self.task, 'second', QUESTION)
        self.minute = 14
        self.ledger.reply(first['id'], first['revision'], 'seven', 'owner-terminal', 'fixture')
        text = self.section(20)
        self.assertIn('Chờ chủ: 16 phút', text)
        self.assertIn('Phút tính ngân sách: 4 phút', text)

    def test_elapsed_chargeable_and_measured_command_minutes_are_labelled(self):
        self.approve(10)
        text = self.section(13)
        for line in ('Thời gian lịch: 13 phút', 'Chờ chủ: 10 phút', 'Phút tính ngân sách: 3 phút',
                     'Tổng thời gian lệnh đã đo: chưa đo'):
            self.assertIn(line, text)

    def test_parallel_attempt_durations_do_not_multiply_elapsed_or_chargeable_time(self):
        self.approve(5)
        adapter = executors.Declaration('parallel-fixture', 'managed', ('measure',), ('time',))
        for key in ('a', 'b'):
            for what, minute in [('start', 5), ('end', 10)]:
                executors.observe(self.ledger, 'P1', adapter, key, what, source='executor_clock',
                                  ref=f'{key}-{what}', at=self.at(minute).isoformat())
        text = self.section(10)
        self.assertIn('Thời gian lịch: 10 phút', text)
        self.assertIn('Phút tính ngân sách: 5 phút', text)
        self.assertIn('Tổng thời gian lệnh đã đo: 10 phút', text)

    def test_at_limit_and_over_limit_use_only_chargeable_minutes(self):
        self.approve(90)
        self.assertNotIn('VƯỢT', self.section(100))
        self.assertIn('VƯỢT', self.section(101))

    def test_local_hold_without_root_wait_evidence_keeps_elapsed_only(self):
        self.approve()
        self.minute = 2
        question = dict(QUESTION, action={'type':'v2.item_budget', 'parameters':{'item':'I1'}})
        self.ledger.create_request(self.task, 'item-budget', question)
        text = self.section(25)
        self.assertIn('Thời gian lịch: 25 phút', text)
        self.assertIn('Phút tính ngân sách: chưa đo', text)
        self.assertNotIn('VƯỢT', text)

    def test_incomplete_legacy_timeline_reports_unknown_without_overrun(self):
        self.approve(1)
        # An old ledger lacks the chronology of the first approval. Exercise the report's
        # budget section directly: other plan projections need an intact proposal to load.
        facts = report._gather(self.ledger.state_root, report._anchors(self.ledger.state_root)[0][0])
        facts['events'] = [e for e in facts['events'] if e[0] != 'plan.proposed']
        text = '\n'.join(report._minutes(facts))
        self.assertIn('Phút tính ngân sách: chưa đo', text)
        self.assertNotIn('VƯỢT', text)
