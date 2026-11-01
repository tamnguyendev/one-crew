"""Verifier provider calls share native task budgets and never blindly retry uncertainty."""
import json
import datetime as dt
import os
import sys
import time
from unittest.mock import patch

from onecrew import budget_core
from onecrew.ledger import LedgerError
from onecrew.v2 import internal_plan, plan, verdict
from onecrew.v2.metered_verifier import ProviderCall
from onecrew.v2.verifiers import reviewer
from tests.test_v2_l1 import Fixture, plan_json, milestone
from tests.test_v2_reviewer import reviewer_milestone, answer, row


class MeteredVerifierTests(Fixture):
    def approved_root(self, calls=1):
        plan.propose(self.ledger, 'P1', plan_json(milestones=[reviewer_milestone()],
            budget={'max_calls': calls, 'time': 1}), 'codex', workflow=True)
        plan.approve(self.ledger, 'P1', 'owner', 'bounded temporary fixture')
        os.environ['ONECREW_ACTOR'] = 'codex'

    def counters(self):
        with self.ledger.transaction() as conn:
            root = plan.anchor_events(self.ledger, conn, 'P1')
            return budget_core.group(conn, root['task_id'])

    def test_actual_root_reviewer_charges_shared_budget_and_bounds_time(self):
        self.approved_root()
        (self.root / 'a.txt').write_text('two\n')
        calls = []
        def fake(prompt, config, env, scratch, limit):
            calls.append(limit)
            return answer(row('R1'), row('R2')), {}, None, False, b'fixture'
        with patch.object(reviewer, 'call', side_effect=fake):
            result = verdict.run(self.ledger, 'P1', 'M1')
            self.assertEqual(result['milestones'][0]['state'], 'passed')
            (self.root / 'a.txt').write_text('three\n')
            with self.assertRaisesRegex(LedgerError, 'shared root budget'):
                verdict.run(self.ledger, 'P1', 'M1')
        self.assertEqual(len(calls), 1); self.assertLessEqual(calls[0], 1)
        self.assertEqual((self.counters()['used_calls'], self.counters()['remaining_calls']), (1, 0))

    def test_unknown_call_blocks_same_retry_without_refunding_or_second_dispatch(self):
        self.approved_root(3)
        calls = []
        def crash(*args):
            calls.append(1)
            raise OSError('fixture lost acknowledgement')
        config = {'provider': 'codex', 'model': 'fixture'}
        for _ in range(2):
            call = ProviderCall(self.ledger, 'P1', 'M1', call=crash)
            with self.assertRaises((OSError, LedgerError)):
                call('same prompt', config, {}, self.root.parent, 1)
        self.assertEqual(len(calls), 1)
        budget = self.counters()
        self.assertEqual((budget['used_calls'], budget['unknown_attempts']), (1, 1))
        self.assertEqual(budget['remaining_calls'], 2)

    def test_no_change_review_never_reserves_or_charges_a_provider(self):
        self.approved_root()
        with patch.object(reviewer, 'call', side_effect=AssertionError('nothing to send')):
            result = verdict.run(self.ledger, 'P1', 'M1')
        self.assertEqual(result['milestones'][0]['state'], 'passed')
        self.assertEqual(self.counters()['used_calls'], 0)

    def test_root_deadline_blocks_command_before_dispatch_and_caps_a_running_command(self):
        # The window between the root deadline and the dispatch must outlast the pre-dispatch identity work (verified_sha, checkout, evidence
        # binding), which depends on the machine: it is sized from a measured identity pass (2 s on a fast machine, more under load; U1-20261101-
        # V24-DEADLINE-1). The command sleeps far longer than the window, so a finished command would fail the elapsed assertion: what is
        # proven is unchanged - a run past the deadline never dispatches, a running command is cut at the deadline (timed_out, inconclusive).
        from onecrew.v2.verifiers import command as _command
        probe = time.monotonic(); _command.verified_sha(str(self.root)); identity_seconds = time.monotonic() - probe
        window = max(2, int(4 * identity_seconds) + 2); sleep = 6 * window
        raw = plan_json(milestones=[milestone(argv=[sys.executable, '-c', f'import time; print("started",flush=True); time.sleep({sleep})'])])
        plan.propose(self.ledger, 'P1', raw, 'codex', workflow=True)
        plan.approve(self.ledger, 'P1', 'owner', 'temporary deadline fixture')
        with patch.object(internal_plan, 'ceilings', return_value={'remaining_seconds': 0}):
            with self.assertRaisesRegex(LedgerError, 'root deadline'): verdict.run(self.ledger, 'P1', 'M1')
        deadline = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=window)).isoformat()
        began = time.monotonic()
        with patch.object(internal_plan, 'ceilings', return_value={'remaining_seconds': window, 'deadline': deadline}):
            result = verdict.run(self.ledger, 'P1', 'M1')
        self.assertLess(time.monotonic() - began, sleep)
        recorded = next(p for k, p in self.events('P1') if k == 'verdict.recorded')
        from onecrew.snapshots import Snapshots
        receipt = json.loads(Snapshots(self.ledger.state_root).read_blob(recorded['receipt']))
        self.assertTrue(receipt['timed_out']); self.assertEqual(recorded['result'], 'inconclusive')
