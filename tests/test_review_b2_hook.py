"""2.5-B cycle 2: the Stop hook is a reminder door. It sees the running check of the shared lifecycle and never dispatches one."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))          # test_v2_l2 imports test_v2_l1 by its plain name
from test_v2_l2 import HookFixture, owned_plan                      # noqa: E402

from onecrew.common_handoff import handoff                          # noqa: E402
from onecrew.common_verification import CandidateChecker            # noqa: E402
from onecrew.control_core import Control, migrate                   # noqa: E402
from onecrew.ledger import canonical                                # noqa: E402
from onecrew.snapshots import Snapshots                             # noqa: E402
from onecrew.v2 import active_plan, engine, internal_plan, plan as plans, review_dispatch   # noqa: E402
from onecrew.v2.verifiers import command                            # noqa: E402
from tests.test_v2_l1 import milestone, plan_json                   # noqa: E402
from tests.test_wf_engine import node                               # noqa: E402


class StopSeesRunningChecks(HookFixture):
    def setUp(self):
        super().setUp()
        self.enforce(value=owned_plan(milestones=[milestone('M1')]))

    def stop(self, session):
        return self.run_hook('stop', {'session_id': session, 'cwd': str(self.root), 'hook_event_name': 'Stop', 'stop_hook_active': False})

    def test_a_running_check_of_another_door_lets_the_session_go_and_is_named(self):
        request = review_dispatch.milestone_request(self.ledger, 'P1', 'M1', command.artifact_sha(self.root))
        claim = review_dispatch.claim_check(self.ledger, 'P1', request, door='candidate', subject={'milestone': 'M1'})
        code, out, _ = self.stop('s-running')
        self.assertEqual((code, out.strip()), (0, ''))
        last = self.violations()[-1]
        self.assertEqual((last['event'], last['rule']), ('logged', 'stop_waiting'))
        self.assertIn(claim['run_id'], last['reason'])
        self.assertIn('candidate', last['reason'])
        anchor = plans.show(self.ledger, 'P1')['anchor_task']
        started = [e for e in self.ledger.events(anchor) if e['kind'].endswith('run_started')]
        self.assertEqual(len(started), 1, 'the hook never starts a check')
        with self.ledger.transaction(write=True) as conn:
            review_dispatch.finish_check(self.ledger, conn, anchor, claim['run_id'], outcome='not_dispatched')
        code, out, _ = self.stop('s-finished')
        self.assertEqual(json.loads(out)['decision'], 'block')


class WorkflowRootStop(HookFixture):
    """On a workflow root the engine owns execution and the owner accepts the handoff; a milestone verdict does not count there. The reminder must
    not send the session to `verdict run`, a second dispatch of the same checks."""

    def setUp(self):
        super().setUp()
        (self.root / 'b.txt').write_text('two\n', encoding='utf-8')
        self.git('add', '.'); self.git('commit', '-qm', 'second file')
        check = [sys.executable, '-c', 'from pathlib import Path; assert Path("a.txt").read_text()=="candidate\\n"; print("candidate tested")']
        value = plan_json(milestones=[milestone('M1', argv=check)], scope={'owned': ['a.txt', 'b.txt']}, authority={
            'edit': True, 'commands': True, 'apply_to_project': True, 'unconfined_commands': True, 'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q9', 'Q12']})
        plans.propose(self.ledger, 'P1', value, 'codex', workflow=True,
                      capabilities=['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine'])
        plans.approve(self.ledger, 'P1', 'owner', 'fixture approval on a temporary ledger')
        os.environ['ONECREW_ACTOR'] = 'codex'
        self.store = Snapshots(self.ledger.state_root); migrate(self.ledger); self.control = Control(self.ledger)
        nodes = [node('C'), node('I', ['C'], integration=True, write=())]
        for item in nodes: item['checks'] = [{'id': 'M1', 'spec': 'The approved command'}]
        internal_plan.revise(self.ledger, 'P1', nodes, reason='Split work inside the approved scope', evidence=['a.txt:1'])
        active_plan.set_mode(self.ledger, 'enforce'); active_plan.export(self.ledger, 'P1')

    def execute(self, ledger, control, task, item, attempt):
        control.launched(attempt['id'], attempt['generation'], {'fixture': True})
        artifact = self.store.overlay(self.store.capture(self.root, ['a.txt']), {'a.txt': b'candidate\n'}, ['a.txt'])
        receipt = self.store.blob(canonical({'kind': 'fixture-producer', 'artifact': artifact}).encode())
        control.finish(attempt['id'], attempt['generation'], {'artifact': artifact})
        return {'artifact': artifact, 'receipt': receipt}

    def stop(self, session):
        return self.run_hook('stop', {'session_id': session, 'cwd': str(self.root), 'hook_event_name': 'Stop', 'stop_hook_active': False})

    def test_the_reminder_names_the_engine_step_not_a_second_verdict_dispatch(self):
        engine.step(self.ledger, 'P1', self.execute, control=self.control)
        code, out, _ = self.stop('s-produced')
        reason = json.loads(out)['reason']
        self.assertEqual(code, 0)
        self.assertIn('engine verify', reason); self.assertIn('C', reason)
        self.assertNotIn('verdict run', reason)
        self.assertIn('Do not say it is done', reason)

    def test_after_delivery_the_session_is_told_the_owner_accepts(self):
        checker = CandidateChecker(self.ledger, 'P1')
        engine.step(self.ledger, 'P1', self.execute, control=self.control); engine.verify(self.ledger, 'P1', 'C', checker)
        engine.step(self.ledger, 'P1', self.execute, control=self.control); engine.verify(self.ledger, 'P1', 'I', checker)
        self.assertEqual(handoff(self.ledger, 'P1')['state'], 'delivered')
        active_plan.export(self.ledger, 'P1')
        code, out, _ = self.stop('s-delivered')
        self.assertEqual(code, 0)
        reason = json.loads(out)['reason']
        self.assertIn('owner', reason)
        self.assertNotIn('verdict run', reason)
        code, out, _ = self.stop('s-delivered')                      # said once, then the session may stop: it cannot move this
        self.assertEqual((code, out.strip()), (0, ''))
