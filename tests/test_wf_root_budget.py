"""W10 budget subset of T03/T32, through actual Control reserve/launch/settle.

Temporary Git/state only; no real executor or provider. Internal plan subdivision
and acceptance mappings belong to W04 and are not claimed by these tests.
"""
import datetime as dt
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from onecrew import budget_core, solution_gate
from onecrew.control import Control, migrate
from onecrew.ledger import Ledger, LedgerError, content_hash
from onecrew.task_intake import submit
from onecrew.v2 import namespaces, plan as plans
from tests.test_v2_l1 import Fixture, plan_json

REPO = Path(__file__).resolve().parents[1]


class RootBudgetTests(Fixture):
    def make_root(self, calls=100, minutes=30, workflow=True):
        value = plan_json(budget={'max_calls': calls, 'time': minutes})
        self.root_view = plans.propose(self.ledger, 'P1', value, 'codex', workflow=workflow)
        self.root_view = plans.approve(self.ledger, 'P1', 'owner', 'fixture root budget approval')
        return self.root_view

    def job(self, key, **options):
        return submit(self.ledger, 'Inspect the document', key, plan_selector='plan-ns:P1',
                      provider='codex', model='gpt-6.1-sol', **options)

    def configured(self, task, ledger=None):
        ledger = ledger or self.ledger
        migrate(ledger)
        control = Control(ledger)
        execution = control.configure(task['id'], task['revision'], {'mode': 'test'})
        return control, execution

    def spend(self, control, task, execution, key):
        attempt = control.reserve(task['id'], execution['revision'], key, {'stage': 'fixture'})
        control.launched(attempt['id'], attempt['generation'], {'fixture': True})
        control.finish(attempt['id'], attempt['generation'], {'verified': True})
        return attempt

    def root_group(self):
        with self.ledger.transaction() as conn:
            result = budget_core.group(conn, self.root_view['anchor_task'])
        self.assertIsNotNone(result, 'approved root-budget capability must retain its shared budget')
        return result

    def test_actual_approval_seals_budget_before_any_children_and_starts_first_deadline(self):
        root = self.make_root(calls=3)
        group = self.root_group()
        first = next(payload for kind, payload in self.events() if kind == 'plan.approved')
        expected = (dt.datetime.fromisoformat(first['at']) + dt.timedelta(minutes=30)).isoformat()
        self.assertEqual((group['owner_task_id'], group['max_calls'], group['used_calls'], group['reserved_calls']),
                         (root['anchor_task'], 3, 0, 0))
        self.assertEqual(group['deadline'], expected)
        self.assertEqual(self.kinds().count('budget.group'), 1)
        task = self.job('default-child')
        self.assertEqual(task['budget']['limits'], {'max_calls': 3, 'max_seconds': 1800})
        self.assertEqual(task['deadline'], expected)
        self.assertEqual(task['root_task_id'], root['anchor_task'])

    def test_sixty_spent_new_child_keys_retry_unknown_and_process_restart_keep_forty(self):
        self.make_root()
        original = self.job('original')
        control, execution = self.configured(original)
        for number in range(60):
            self.spend(control, original, execution, 'spent-' + str(number))
        before = self.root_group()
        self.assertEqual((before['used_calls'], before['remaining_calls']), (60, 40))
        children = [self.job('child-one'), self.job('child-two')]
        for child in children:
            self.assertEqual(child['budget']['goal']['remaining_calls'], 40)
            self.assertEqual(child['deadline'], before['deadline'])
        definite, definite_execution = self.configured(children[1])
        not_started = definite.reserve(children[1]['id'], definite_execution['revision'], 'not-started-retry', {'stage': 'fixture'})
        definite.finish(not_started['id'], not_started['generation'], {'not_started': True}, not_started=True)
        self.assertEqual(self.root_group()['remaining_calls'], 40)
        child_control, child_execution = self.configured(children[0])
        attempt = child_control.reserve(children[0]['id'], child_execution['revision'], 'retry', {'stage': 'fixture'})
        child_control.unknown(attempt['id'], 'injected uncertain launch; no executor was started')
        restarted = Ledger(self.root, self.ledger.state_root)
        resumed = Control(restarted)
        duplicate = resumed.reserve(children[0]['id'], child_execution['revision'], 'retry', {'stage': 'fixture'})
        self.assertEqual(duplicate['id'], attempt['id'])
        held = self.root_group()
        self.assertEqual((held['used_calls'], held['reserved_calls'], held['remaining_calls'], held['unknown_attempts']), (60, 1, 39, 1))
        script = '''import json, sys
from onecrew.ledger import Ledger
ledger = Ledger(sys.argv[1], sys.argv[2])
print(json.dumps(ledger.task(sys.argv[3])['budget']['goal'], sort_keys=True))
'''
        done = subprocess.run([sys.executable, '-c', script, str(self.root), str(self.ledger.state_root), self.root_view['anchor_task']],
                              cwd=REPO, capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        observed = json.loads(done.stdout)
        self.assertEqual((observed['used_calls'], observed['reserved_calls'], observed['remaining_calls'], observed['deadline']),
                         (60, 1, 39, before['deadline']))
        with self.assertRaisesRegex(LedgerError, 'Cannot refund a launched or ambiguous attempt'):
            resumed.finish(attempt['id'], attempt['generation'], {'not_started': True}, not_started=True)
        self.assertEqual(self.root_group()['remaining_calls'], 39)
        self.assertEqual(self.kinds().count('budget.group'), 1)

    def test_new_job_keys_cannot_reset_exhausted_root(self):
        self.make_root(calls=3)
        first, second = self.job('first'), self.job('second')
        a, ax = self.configured(first)
        b, bx = self.configured(second)
        self.spend(a, first, ax, 'one')
        self.spend(b, second, bx, 'two')
        self.spend(a, first, ax, 'three')
        self.assertEqual(self.root_group()['remaining_calls'], 0)
        fresh = self.job('different-key')
        c, cx = self.configured(fresh)
        self.assertIn('goal', fresh['budget'], 'a different child key must still be attached to the root')
        self.assertEqual(fresh['budget']['goal']['used_calls'], 3)
        with self.assertRaisesRegex(LedgerError, 'Shared goal call budget exhausted'):
            c.reserve(fresh['id'], cx['revision'], 'four', {'stage': 'fixture'})
        replay = self.job('first')
        self.assertEqual((replay['id'], replay['deadline']), (first['id'], first['deadline']))
        self.assertEqual(self.root_group()['remaining_calls'], 0)

    def test_two_children_reserve_atomically_against_one_remaining_call(self):
        self.make_root(calls=1)
        children = [self.job('parallel-one'), self.job('parallel-two')]
        workers = [self.configured(child) for child in children]

        def reserve(index):
            control, execution = workers[index]
            try:
                return control.reserve(children[index]['id'], execution['revision'], 'one', {'stage': 'fixture'})
            except LedgerError as error:
                return str(error)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, (0, 1)))
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1, results)
        self.assertEqual(sum(isinstance(result, str) and 'Shared goal call budget exhausted' in result for result in results), 1, results)
        group = self.root_group()
        self.assertEqual((group['reserved_calls'], group['remaining_calls']), (1, 0))

    def test_child_cannot_enlarge_root_calls_time_or_create_a_separate_grant(self):
        self.make_root(calls=3)
        for options in ({'max_calls': 4}, {'max_calls': 100}, {'max_seconds': 1801}):
            with self.subTest(options=options):
                with self.assertRaisesRegex(LedgerError, 'exceeds the shared workflow root budget'):
                    self.job('over-grant', **options)
        self.assertEqual(self.root_group()['max_calls'], 3)
        self.assertEqual(self.root_group()['members'], [{'task_id': self.root_view['anchor_task']}])

    def test_new_approval_revision_cannot_reset_spend_or_automatically_increase_budget(self):
        self.make_root(calls=3)
        task = self.job('before-amend')
        control, execution = self.configured(task)
        self.spend(control, task, execution, 'one')
        self.spend(control, task, execution, 'two')
        deadline = self.root_group()['deadline']
        changed = plan_json(title='Owner clarified the document', budget={'max_calls': 8, 'time': 60})
        plans.amend(self.ledger, 'P1', changed, 'Owner changed the contract', 'codex')
        plans.approve(self.ledger, 'P1', 'owner', 'fixture revision two approval')
        group = self.root_group()
        self.assertEqual((group['max_calls'], group['used_calls'], group['remaining_calls'], group['deadline']), (3, 2, 1, deadline))
        new = self.job('after-amend')
        worker, configured = self.configured(new)
        self.spend(worker, new, configured, 'three')
        self.assertEqual(self.root_group()['remaining_calls'], 0)
        with self.assertRaisesRegex(LedgerError, 'revision'):
            solution_gate.check(self.ledger, task['id'])
        self.assertEqual(self.kinds().count('budget.group'), 1)

    def test_first_deadline_limits_late_children_and_expired_dispatch(self):
        self.make_root(calls=3)
        deadline = self.root_group()['deadline']
        first = next(payload for kind, payload in self.events() if kind == 'plan.approved')
        later = dt.datetime.fromisoformat(first['at']) + dt.timedelta(seconds=10)
        with patch('onecrew.task_intake.utcnow', return_value=later.isoformat()):
            child = self.job('late-child')
        self.assertEqual(child['deadline'], deadline)
        after = dt.datetime.fromisoformat(deadline) + dt.timedelta(seconds=1)
        with patch('onecrew.task_intake.utcnow', return_value=after.isoformat()):
            with self.assertRaisesRegex(LedgerError, 'root deadline is exhausted'):
                self.job('expired-child')
        migrate(self.ledger)
        control = Control(self.ledger, clock=lambda: after)
        execution = control.configure(child['id'], child['revision'], {'mode': 'test'})
        with self.assertRaisesRegex(LedgerError, 'deadline exhausted'):
            control.reserve(child['id'], execution['revision'], 'too-late', {'stage': 'fixture'})

    def test_implicit_matching_job_is_sealed_only_for_opted_in_workflow(self):
        self.make_root(calls=3)
        task = submit(self.ledger, 'Inspect the document', 'P1')
        self.assertEqual(task['budget']['goal']['owner_task_id'], self.root_view['anchor_task'])
        with self.ledger.transaction() as conn:
            binding = json.loads(self.ledger._task(conn, task['id'])['payload'])['plan_binding']
        self.assertEqual(binding['selector'], 'plan-ns:P1')

    def test_default_schema2_and_preexisting_storage_only_workflow_keep_old_budget_semantics(self):
        for name, workflow in (('schema2', False), ('old-storage', True)):
            with patch.object(namespaces, 'CAPABILITIES', ('namespaced-storage',)):
                plans.propose(self.ledger, name, plan_json(budget={'max_calls': 3, 'time': 30}), 'codex', workflow=workflow)
            plans.approve(self.ledger, name, 'owner', 'fixture unchanged semantics')
            task = submit(self.ledger, 'Inspect a document', name + '-job', plan_selector='plan-ns:' + name,
                          max_calls=3, max_seconds=1800)
            self.assertNotIn('goal', task['budget'])
            with self.ledger.transaction() as conn:
                state = plans.derive(self.ledger, conn, name)
                self.assertFalse(namespaces.has_capability(state, 'root-budget'))
                self.assertFalse(conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind='budget.group'", (state['task_id'],)).fetchone())

    def test_preexisting_goal_constraint_is_not_bypassed_by_workflow_root(self):
        self.make_root(calls=100)
        first, second = self.job('first'), self.job('second')
        a, ax = self.configured(first)
        b, bx = self.configured(second)
        # A historical existing goal-group receipt: same format read by v1's
        # public goal_budget.create. This checks constraint composition only.
        payload = {'owner_task_id': first['id'], 'members': [{'task_id': first['id']}, {'task_id': second['id']}],
                   'max_calls': 1, 'deadline': self.root_group()['deadline'], 'authority': 'local_operator'}
        payload['revision'] = content_hash(payload)
        with self.ledger.transaction(write=True) as conn:
            self.ledger._event(conn, first['id'], 'budget.group', payload)
        self.spend(a, first, ax, 'one')
        self.assertEqual(self.root_group()['remaining_calls'], 99)
        with self.assertRaisesRegex(LedgerError, 'Shared goal call budget exhausted'):
            b.reserve(second['id'], bx['revision'], 'two', {'stage': 'fixture'})
