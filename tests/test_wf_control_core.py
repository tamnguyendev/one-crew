"""The installed execution core requires root authority; legacy APIs share its accounting."""
from onecrew.control_core import Control
from onecrew.ledger import LedgerError
from onecrew.v2 import plan
from tests.test_wf_engine import EngineFixture, node


class CorePolicyTests(EngineFixture):
    def setUp(self):
        super().setUp()
        self.control = Control(self.ledger)

    def test_bound_engine_executes_with_core_and_charges_the_existing_counters(self):
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        result = self.step()
        self.assertEqual(result['state'], 'produced')
        view = self.engine.state(self.ledger, 'P1')
        status = self.control.status(view['nodes']['A']['child'])
        self.assertEqual((status['used_calls'], status['reserved_calls']), (1, 0))
        self.verify('A')

    def test_core_cannot_configure_an_unbound_task_or_implicitly_use_legacy_policy(self):
        task = self.ledger.task(self.root_view['anchor_task'])
        with self.assertRaisesRegex(LedgerError, 'namespaced root binding'):
            self.control.configure(task['id'], task['revision'], {'mode': 'fixture'})
        with self.ledger.transaction() as conn:
            self.assertIsNone(conn.execute('SELECT 1 FROM executions WHERE task_id=?', (task['id'],)).fetchone())

    def test_closed_root_cannot_launch_an_admitted_child(self):
        self.revise([node('A'), node('I', ['A'], integration=True, write=())])
        def close_before_launch(ledger, control, task, item, attempt):
            with ledger.transaction(write=True) as conn:
                root = plan.anchor_events(ledger, conn, 'P1')
                plan.emit(ledger, conn, root['task_id'], 'plan.closed',
                          {'revision': root['approved']['revision'], 'reason': 'fixture stop'})
            with self.assertRaises(LedgerError):
                control.launched(attempt['id'], attempt['generation'], {'fixture': True})
            raise LedgerError('fixture launch correctly refused')
        result = self.step(close_before_launch)
        self.assertEqual(result['state'], 'held')
        view = self.engine.state(self.ledger, 'P1')
        status = self.control.status(view['nodes']['A']['child'])
        self.assertEqual((status['used_calls'], status['reserved_calls']), (0, 1))
        self.assertNotIn('node.produced', self.kinds())
