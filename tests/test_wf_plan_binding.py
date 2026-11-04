"""W12b dispatch binding: actual submit, solution gate, reserve and extension.

All roots, task grants and execution counters live in temporary ledger state.
The legacy root is created by the unmodified pre-namespace archived CLI.
"""
import datetime as dt
import json
from pathlib import Path
import tempfile

from onecrew import budget, solution_gate
from onecrew.control import Control, migrate
from onecrew.ledger import Ledger, LedgerError
from onecrew.owned_intake import submit
from onecrew.v2 import gate, plan as plans, plan_binding
from tests.test_v2_l1 import Fixture, plan_json
from tests import wf_oldversion as ov

REPO = Path(__file__).resolve().parents[1]


class PlanBindingTests(Fixture):
    @classmethod
    def setUpClass(cls):
        cls.archive_temp = tempfile.TemporaryDirectory(prefix='ocbind-old-')
        cls.old = ov.OldVersion(ov.archive('d3120c6', REPO, cls.archive_temp.name))

    @classmethod
    def tearDownClass(cls):
        cls.archive_temp.cleanup()

    def legacy(self, name='dual'):
        path = Path(self.temp.name) / 'legacy-contract.json'
        path.write_text(json.dumps(ov.contract('Legacy root')), encoding='utf-8')
        code, output = self.old.run(self.root, self.ledger.state_root, 'plan', 'propose', name,
                                    '--file', str(path), '--author', 'codex')
        self.assertEqual(code, 0, output)
        return plans.approve(self.ledger, 'plan:' + name, 'owner', 'fixture legacy approval')

    def dual(self, value=None, approve_new=True):
        legacy = self.legacy()
        newer = plans.propose(self.ledger, 'dual', value or plan_json(), 'codex')
        if approve_new:
            newer = plans.approve(self.ledger, 'plan-ns:dual', 'owner', 'fixture namespaced approval')
        return legacy, newer

    def job(self, key='job', selector='plan-ns:dual', **options):
        return submit(self.ledger, 'Inspect the approved document', key, provider='codex', model='gpt-6.1-sol',
                      max_calls=20, max_seconds=600, plan_selector=selector, **options)

    def payload(self, task):
        with self.ledger.transaction() as conn:
            return json.loads(self.ledger._task(conn, task['id'])['payload'])

    def execution(self, task):
        migrate(self.ledger)
        control = Control(self.ledger)
        execution = control.configure(task['id'], task['revision'], {'mode': 'test'})
        return control, execution

    def test_dual_roots_require_explicit_binding_and_different_approvals_do_not_leak(self):
        legacy, newer = self.dual(approve_new=False)
        gate.set_enforced(self.ledger, True, 'owner', 'fixture enforcement')
        bare = submit(self.ledger, 'Inspect the document', 'dual', max_calls=20, max_seconds=600)
        with self.assertRaisesRegex(LedgerError, 'ambiguous'):
            solution_gate.check(self.ledger, bare['id'])
        with self.assertRaisesRegex(LedgerError, 'approved'):
            self.job('new-unapproved')
        old_job = self.job('old-job', selector='plan:dual')
        self.assertIsNone(solution_gate.check(self.ledger, old_job['id']))
        plans.approve(self.ledger, 'plan-ns:dual', 'owner', 'fixture namespaced approval')
        new_job = self.job('new-job')
        self.assertIsNone(solution_gate.check(self.ledger, new_job['id']))
        self.assertEqual(self.payload(old_job)['plan_binding']['root_task_id'], legacy['anchor_task'])
        self.assertEqual(self.payload(new_job)['plan_binding']['root_task_id'], newer['anchor_task'])
        with self.ledger.transaction() as conn:
            self.assertEqual(self.ledger._task(conn, new_job['id'])['request_key'], 'new-job')
        self.assertNotEqual(new_job['id'], newer['anchor_task'])

    def test_invalid_selector_revision_or_foreign_root_cannot_submit_task(self):
        self.dual()
        other = Ledger(ov.git_project(self.temp.name, 'foreign'), self.ledger.state_root)
        plans.propose(other, 'foreign-only', plan_json(), 'codex')
        plans.approve(other, 'foreign-only', 'owner', 'fixture foreign approval')
        for selector, revision in (('dual', None), ('plan-ns:missing', None), ('plan-ns:foreign-only', None),
                                   ('plan-ns:dual', 2), ('plan-ns:dual', True), ('plan-ns:../x', None)):
            with self.subTest(selector=selector, revision=revision):
                with self.ledger.transaction() as conn:
                    before = conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
                with self.assertRaises(LedgerError):
                    self.job(selector=selector, plan_revision=revision)
                with self.ledger.transaction() as conn:
                    self.assertEqual(conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], before)

    def test_binding_is_sealed_and_replay_does_not_reset_calls_or_deadline(self):
        self.dual()
        task = self.job(plan_revision=1)
        control, execution = self.execution(task)
        attempt = control.reserve(task['id'], execution['revision'], 'one', {'stage': 'fixture', 'item': 'I1'})
        control.launched(attempt['id'], attempt['generation'], {'fixture': 1})
        control.finish(attempt['id'], attempt['generation'], {'verified': True})
        replay = self.job(plan_revision=1)
        self.assertEqual((replay['id'], replay['revision'], replay['deadline']), (task['id'], task['revision'], task['deadline']))
        self.assertEqual(control.status(task['id'])['used_calls'], 1)
        self.assertEqual(self.payload(replay)['plan_binding'], self.payload(task)['plan_binding'])
        with self.assertRaisesRegex(LedgerError, 'sealed plan binding'):
            self.job(selector='plan:dual')
        with self.ledger.transaction(write=True) as conn:
            payload = self.payload(task)
            payload['plan_binding']['root_task_id'] = 'TASK-forged'
            conn.execute('UPDATE tasks SET payload=? WHERE id=?', (json.dumps(payload), task['id']))
        with self.assertRaisesRegex(LedgerError, 'sealed submission|task revision'):
            solution_gate.check(self.ledger, task['id'])
        with self.ledger.transaction(write=True) as conn:
            payload.pop('plan_binding')
            conn.execute('UPDATE tasks SET payload=? WHERE id=?', (json.dumps(payload), task['id']))
        with self.assertRaisesRegex(LedgerError, 'sealed submission'):
            solution_gate.check(self.ledger, task['id'])

    def test_changed_approved_revision_refuses_original_binding_in_gate_extension_and_items(self):
        self.dual()
        task = self.job()
        changed = plan_json(title='Owner approved a different revision')
        plans.amend(self.ledger, 'plan-ns:dual', changed, 'Owner changed the contract', 'codex')
        plans.approve(self.ledger, 'plan-ns:dual', 'owner', 'fixture revision two approval')
        with self.assertRaisesRegex(LedgerError, 'revision'):
            solution_gate.check(self.ledger, task['id'])
        with self.ledger.transaction() as conn:
            raw = self.ledger._task(conn, task['id'])
            with self.assertRaisesRegex(LedgerError, 'revision'):
                gate.check_extension(self.ledger, conn, raw, 30, 1200)
            from onecrew.v2.items import check_operation
            with self.assertRaisesRegex(LedgerError, 'revision'):
                check_operation(self.ledger, conn, raw, {'item': 'I1'})

    def test_actual_budget_extension_and_item_reserve_use_bound_root_not_same_name_legacy(self):
        value = plan_json(budget={'max_calls': 40, 'time': 30}, items=[
            {'id': 'I1', 'title': 'Optional document detail', 'tier': 'should', 'milestone': 'M1'},
            {'id': 'I2', 'title': 'Required document work', 'tier': 'must', 'milestone': 'M1'}])
        self.dual(value)
        task = self.job()
        control, execution = self.execution(task)
        current = self.ledger.task(task['id'])['budget']
        end = dt.datetime.fromisoformat(task['created_at']) + dt.timedelta(minutes=20)
        with self.assertRaisesRegex(LedgerError, 'approved plan budget of 40'):
            budget.extend(control, task['id'], current['revision'], 'too-many', 70, end.isoformat(), 'fixture extension')
        result = budget.extend(control, task['id'], current['revision'], 'within-root', 30, end.isoformat(), 'fixture extension')
        self.assertEqual(result['budget']['limits']['max_calls'], 30)
        with self.assertRaisesRegex(LedgerError, 'did not tick'):
            control.reserve(task['id'], execution['revision'], 'optional', {'stage': 'fixture', 'item': 'I1'})
        old = self.job('legacy-job', selector='plan:dual')
        old_control, old_execution = self.execution(old)
        attempt = old_control.reserve(old['id'], old_execution['revision'], 'required', {'stage': 'fixture', 'item': 'I1'})
        self.assertEqual(attempt['status'], 'reserved')

    def test_explicit_binding_still_obeys_root_authority_and_v1_solution_approval(self):
        self.dual(plan_json(authority={'edit': False, 'commands': False}))
        work = {'schema_version': 1, 'goal': 'Edit the document', 'acceptance': ['Document is corrected'],
                'preserve': ['Other files'], 'authority': {'edit': True},
                'scope': {'repository': '', 'paths': ['a.txt']}, 'authorized_by': {'source': 'user', 'reference': 'fixture'}}
        task = submit(self.ledger, None, 'writer', mode='work', provider='codex', model='gpt-6.1-sol', contract=work,
                      max_calls=20, max_seconds=600, plan_selector='plan-ns:dual')
        with self.assertRaisesRegex(LedgerError, 'exceeds the authority'):
            solution_gate.check(self.ledger, task['id'])
        with self.assertRaises(LedgerError):
            self.job('missing-solution', solution_id='SOL-missing', solution_revision='missing')

    def test_legacy_job_without_binding_keeps_existing_opt_in_behavior(self):
        self.legacy('legacy-job')
        task = submit(self.ledger, 'Inspect the legacy document', 'legacy-job', max_calls=20, max_seconds=600)
        self.assertNotIn('plan_binding', self.payload(task))
        self.assertIsNone(solution_gate.check(self.ledger, task['id']))
        gate.set_enforced(self.ledger, True, 'owner', 'fixture enforcement')
        self.assertIsNone(solution_gate.check(self.ledger, task['id']))
