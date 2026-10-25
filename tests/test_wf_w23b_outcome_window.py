"""W23b (T46): v2 root outcomes must not push v1 outcomes out of the v1 consumers' windows.

Counter-example: three verified v1 outcomes of one goal give task_intake.recommend 'repeated_verified' {45 calls, 1350 s}. Then more than the
200-row window of learning.outcome events is written on a v2 plan anchor (mode 'plan', source 'v2-plan'). Before the fix the shared window held
only the v2 rows and the same v1 goal got 'insufficient_history' {100, 7200}; skills.latest lost the v1 rows the same way. v2 rows stay visible.
Real temporary ledger (tests.test_v2_l1.Fixture); nothing runs a model.
"""
from onecrew import budget_policy, skills, task_intake
from onecrew.ledger import content_hash
from onecrew.v2 import plan as plans
from tests.test_v2_l1 import Fixture

GOAL = 'Add the export button to the report page'


class OutcomeWindowTests(Fixture):
    def v1_outcomes(self):
        tasks = []
        for index in range(3):
            task = task_intake.submit(self.ledger, GOAL, f'v1-goal-{index}', mode='audit')['id']
            data = {'version': 1, 'task': task, 'task_revision': 1, 'spec_revision': content_hash(GOAL), 'phase': 'completed', 'mode': 'audit',
                    'provider': 'codex', 'model': 'gpt-x', 'snapshot': 's' * 40, 'verification': 'passed', 'acceptance': 'accepted',
                    'managed_calls': 28 + index, 'timing': {'wall_seconds': 898 + index}, 'signature': {'mode': 'audit', 'words': ['export']}}
            with self.ledger.transaction(write=True) as conn:
                self.ledger._event(conn, task, 'learning.outcome', dict(data, id=content_hash(data)))
            tasks.append(task)
        return tasks

    def v2_outcomes(self, count):
        self.approved()
        anchor = plans.show(self.ledger, 'P1')['anchor_task']
        with self.ledger.transaction(write=True) as conn:
            for index in range(count):
                data = {'version': 1, 'task': anchor, 'task_revision': 1, 'spec_revision': 'c' * 64, 'phase': 'completed', 'mode': 'plan',
                        'provider': None, 'model': None, 'verification': 'passed', 'acceptance': 'accepted', 'managed_calls': None,
                        'timing': {'wall_seconds': 10}, 'signature': None, 'source': 'v2-plan', 'plan': 'P1', 'plan_anchor': 'plan:P1',
                        'plan_revision': index + 1, 'end': 'accepted', 'end_event': index}
                self.ledger._event(conn, anchor, 'learning.outcome', dict(data, id=content_hash(data)))
        return anchor

    def views(self, tasks):
        with self.ledger.transaction() as conn:
            latest = skills.latest(self.ledger, conn)
        rows = task_intake.outcomes(self.ledger, 200)
        return {'recommend': task_intake.recommend(self.ledger, GOAL, 'audit', 'codex', 'gpt-x'),
                'budget_policy': budget_policy.recommend(self.ledger, GOAL, 'audit', 'codex', 'gpt-x'),
                'outcomes_v1': sorted(r['task'] for r in rows if r['task'] in tasks),
                'latest_v1': sorted(r['task'] for r in latest if r['task'] in tasks),
                'latest_good_v1': sorted(r['task'] for r in latest if r['task'] in tasks and skills.good(r)),
                'rows': rows, 'latest': latest}

    def test_w23b_more_than_limit_v2_outcomes_keep_v1_recommendation_exact(self):
        tasks = self.v1_outcomes()
        before = self.views(tasks)
        self.assertEqual(before['recommend']['classification'], 'repeated_verified')
        self.assertEqual(before['recommend']['recommended'], {'max_calls': 45, 'max_seconds': 1350})
        anchor = self.v2_outcomes(201)                                                         # more than the 200-row window
        after = self.views(tasks)
        for key in ('recommend', 'budget_policy', 'outcomes_v1', 'latest_v1', 'latest_good_v1'):
            self.assertEqual(after[key], before[key], key)                                    # was insufficient_history {100, 7200}
        self.assertEqual(after['outcomes_v1'], sorted(tasks))
        self.assertIn(anchor, {r['task'] for r in after['rows']})                             # v2 rows are still readable by v1 readers
        self.assertIn(anchor, {r['task'] for r in after['latest']})
        self.assertEqual(sum(r['task'] == anchor for r in after['rows']), 200)                 # each partition keeps its own window
        self.assertEqual([r['event'] for r in after['rows']], sorted((r['event'] for r in after['rows']), reverse=True))

    def test_w23b_v1_window_still_honours_its_limit(self):
        tasks = self.v1_outcomes()
        self.assertEqual(len(task_intake.outcomes(self.ledger, 2)), 2)
        self.assertEqual({r['task'] for r in task_intake.outcomes(self.ledger, 2)}, set(tasks[1:]))   # newest first, v1 semantics
