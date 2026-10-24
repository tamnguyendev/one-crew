"""T36b gaps (R03 W32a/W33a): fake-clock execution/wait/deadline split, restart keeps estimate state, no 'calibrated' wording,
work.additional is class A for the old version.

Fixture: real temporary ledger (tests.test_v2_l1.Fixture); root R approved with the 6-8 h baseline and a deadline. The fake clock is
the `at`/`until` times given to executors.observe (the module's time injection); nothing sleeps.
"Restart of the coordinating process" = a NEW Python process opening the same state root (subprocess) and reading it back.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from onecrew.ledger import Ledger
from onecrew.v2 import estimates, executors, plan, report
from tests.test_v2_l1 import Fixture
from tests import wf_oldversion as ov

REPO = Path(__file__).resolve().parents[1]
DEADLINE = '2026-10-25T18:00:00+07:00'
BASELINE = [21600, 28800]
MANAGED = executors.Declaration('fixture-managed', 'managed', ('measure',), ('time',))   # an executor that measures time


def restart_read(state_root, project, selector='P1'):
    """estimates.read in a new process on the same state root (the coordinating process restarted)."""
    code = ('import json,sys\nfrom onecrew.ledger import Ledger\nfrom onecrew.v2 import estimates\n'
            'out = estimates.read(Ledger(sys.argv[1], sys.argv[2]), sys.argv[3])\n'
            'print(json.dumps({k: out[k] for k in ("baseline", "history", "additional", "remaining_seconds", "deadline")}))')
    env = dict(os.environ, PYTHONPATH=str(REPO)); env.pop('ONECREW_ACTOR', None)
    child = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(project), str(state_root), selector], cwd=str(REPO), env=env,
                           capture_output=True, text=True, encoding='utf-8')
    if child.returncode: raise AssertionError(child.stderr)
    return json.loads(child.stdout)


def baseline_kept(out):
    return out['baseline'] is not None and out['baseline']['execution_seconds'] == BASELINE and out['baseline']['revision'] == 1


def anchor_state(ledger, selector):
    with ledger.transaction() as conn:
        return plan.anchor_events(ledger, conn, selector)


class T36bGaps(Fixture):
    def start(self, name='P1'):
        self.approved(name, estimate={'execution_seconds': BASELINE, 'evidence': ['fixture:task decomposition'], 'deadline': DEADLINE})

    def observe(self, attempt, what, at, until=None):
        return executors.observe(self.ledger, 'P1', MANAGED, attempt, what, source='executor_clock', ref=f'clock:{attempt}:{what}:{at}',
                                 at=at, until=until, wait_reason='owner' if what == 'wait' else None)

    # ---- [E4] / [E7]: execution, waiting and deadline are separate after a 2-hour owner wait (fake clock) ---------------------------
    def test_e4_e7_two_hour_owner_wait_is_waiting_not_execution_and_deadline_is_unchanged(self):
        self.start()
        self.observe('m1', 'start', '2026-10-25T08:00:00+07:00')
        self.observe('m1', 'end', '2026-10-25T09:00:00+07:00')                          # milestone 1 executes 1 hour
        self.observe('m1', 'wait', '2026-10-25T09:00:00+07:00', until='2026-10-25T11:00:00+07:00')   # R waits for the owner 2 hours
        out = estimates.read(self.ledger, 'P1')
        self.assertEqual(out['execution_seconds'], 3600)                                 # [E7] the 2 h wait is NOT execution
        self.assertEqual(out['waiting_seconds'], 7200)                                   # [E4] the wait is its own figure
        self.assertEqual(out['deadline'], DEADLINE)                                      # the wait does not move the deadline
        self.assertEqual(out['baseline']['execution_seconds'], BASELINE)
        text = report.render_report(self.ledger.state_root, 'P1')
        self.assertIn('Thực thi: 1 giờ; chờ: 2 giờ; deadline: ' + DEADLINE, text)       # three separate figures in the report
        present = report.render_present(self.ledger.state_root, 'P1')
        self.assertIn('Thực thi: 1 giờ; chờ: 2 giờ; deadline: ' + DEADLINE, present)
        self.assertNotIn('Thực thi: 3 giờ', text)                                        # counter-example: the wait folded into execution

    # ---- [E9] / [E13] / [E14]: a restart reads the same baseline, ETA history and additions; nothing is reset -----------------------
    def test_e9_e13_e14_restart_keeps_baseline_history_and_additions(self):
        self.start()
        estimates.reforecast(self.ledger, 'P1', 'm1-done', [18000, 25200], 'M1 completed with receipt', ['receipt:m1'])
        estimates.additional(self.ledger, 'P1', 'migration', 'mandatory', 'missing migration for A2', ['O1'], [3600, 7200], ['evidence:migration'])
        estimates.additional(self.ledger, 'P1', 'cleanup', 'optional', 'tidy code', ['O1'], [1800, 3600], ['evidence:cleanup'])
        estimates.additional(self.ledger, 'P1', 'other-repo', 'outside_authority', 'needs a repo outside scope', ['O1'], [3600, 3600], ['evidence:repo'])
        before = estimates.read(self.ledger, 'P1')
        self.assertTrue(baseline_kept(before))
        self.assertNotEqual(before['baseline']['execution_seconds'], before['history'][-1]['remaining_seconds'])   # [E14] not overwritten by the ETA
        after = restart_read(self.ledger.state_root, self.root)
        for key in ('baseline', 'history', 'additional', 'remaining_seconds', 'deadline'):
            self.assertEqual(json.loads(json.dumps(before[key])), after[key], key)       # [E13] same from the ledger in a new process
        self.assertTrue(baseline_kept(after))                                            # [E9]
        self.assertEqual([a['category'] for a in after['additional']], ['mandatory', 'optional', 'outside_authority'])
        self.assertEqual(after['remaining_seconds'], [21600, 32400])                     # ETA + mandatory only; optional stays out
        # after the restart a re-approval through a new ledger handle writes no second baseline ([E14] "reset after restart")
        plan.approve(Ledger(self.root, self.ledger.state_root), 'P1', 'owner', 'repeat after restart')
        self.assertEqual(self.kinds().count('estimate.baseline'), 1)
        self.assertTrue(baseline_kept(restart_read(self.ledger.state_root, self.root)))
        # counter-example: a reading whose baseline was replaced by the newest ETA fails the same check
        mutant = dict(after, baseline=dict(after['baseline'], execution_seconds=after['history'][-1]['remaining_seconds']))
        self.assertFalse(baseline_kept(mutant))

    # ---- [E18]: neither page calls the range calibrated nor states a probability ---------------------------------------------------
    def test_e18_present_and_report_never_claim_calibration_p85_or_probability(self):
        self.start()
        estimates.reforecast(self.ledger, 'P1', 'm1-done', [18000, 25200], 'M1 completed with receipt', ['receipt:m1'])
        estimates.additional(self.ledger, 'P1', 'migration', 'mandatory', 'missing migration for A2', ['O1'], [3600, 7200], ['evidence:migration'])
        for render in (report.render_present, report.render_report):
            text = render(self.ledger.state_root, 'P1')
            self.assertIn('6–8 giờ', text)                                               # the range is on the page (the grep has a subject)
            lowered = text.casefold()
            for banned in ('đã hiệu chỉnh', 'p85', 'p90', 'p50', 'xác suất', 'probability', 'calibrated eta'):
                self.assertNotIn(banned, lowered, (render.__name__, banned))
            self.assertIsNone(re.search(r'\d+\s*%\s*(khả năng|xác suất|chance|probab)', lowered))
            self.assertIn('chưa hiệu chỉnh', text)                                       # the only use of the word: "not calibrated"
        self.assertFalse(estimates.read(self.ledger, 'P1')['calibrated'])

    # ---- [E21]: work.additional on the anchor is class A for the old version (S, G, C identical); one baseline per revision ----------
    def test_e21_old_version_reads_same_status_gate_continue_with_work_additional(self):
        old = ov.OldVersion(ov.archive('d3120c6', REPO, self.temp.name))
        contract_file = Path(self.temp.name) / 'old-contract.json'
        contract_file.write_text(json.dumps(ov.contract('old')), encoding='utf-8')
        code, out = old.run(self.root, self.ledger.state_root, 'plan', 'propose', 'OLD', '--file', str(contract_file), '--author', 'fixture')
        self.assertEqual(code, 0, out)
        plan.approve(self.ledger, 'plan:OLD', 'owner', 'local fixture', estimate={'execution_seconds': BASELINE, 'evidence': ['fixture:baseline']})
        before = ov.read(old, self.root, self.ledger.state_root, 'OLD')
        estimates.additional(self.ledger, 'plan:OLD', 'migration', 'mandatory', 'missing migration', ['O1'], [3600, 7200], ['evidence:migration'])
        estimates.additional(self.ledger, 'plan:OLD', 'cleanup', 'optional', 'tidy code', ['O1'], [1800, 3600], ['evidence:cleanup'])
        state = anchor_state(self.ledger, 'plan:OLD')
        kinds = [e['kind'] for e in self.ledger.events(state['task_id'])]
        self.assertEqual(kinds.count('work.additional'), 2)                              # the events under test are on the anchor
        self.assertEqual(kinds.count('estimate.baseline'), 1)                            # one baseline for revision 1
        after = ov.read(old, self.root, self.ledger.state_root, 'OLD')
        same = ov.compare(before, after)
        self.assertTrue(same['S'] and same['G'] and same['C'], (before, after))
        self.assertFalse(after['read_blocked'])
        self.assertEqual(after['S']['status'], 'approved')
        contract = plan.load(self.ledger, state)[0]                                       # the baseline is an event, not a contract field
        self.assertFalse({'estimate', 'estimates', 'eta', 'baseline'} & set(contract))
