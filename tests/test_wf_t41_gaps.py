"""T41a [E2] historical reproduction (R03 W44): on the code BEFORE the fix the Stop hook blocks/reminds while a milestone is being
checked in the background ("red for the right reason"); on this checkout, at the same moment on the same ledger, it says nothing.

Fixture: tests/test_wf_r03a_run_started.RunFixture (real `onecrew verdict run` as a background subprocess, waiting for a gate file; the
real `onecrew hook stop` with the documented stdin JSON). The pre-fix hook is the archive of ee46539 (the T41b baseline, before W44),
run UNMODIFIED from its own tree with the same state root. Interface only: not a real Claude Code session.
"""
import json
import os
import subprocess
import sys

import tests.test_wf_r03a_run_started as rs
from tests import wf_oldversion as ov

PRE_FIX = rs.BASELINE        # ee46539


class PreFixStopHookTests(rs.RunFixture):
    def old_stop(self, old, session):
        event = rs._stop_event(session); event['cwd'] = str(self.root)
        env = {k: v for k, v in old.env.items() if k not in ('CLAUDE_CODE_CHILD_SESSION', 'CLAUDECODE')}
        done = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'onecrew', '--project', str(self.root), '--state-root', str(self.state),
                               'hook', 'stop'], input=json.dumps(event), capture_output=True, text=True, encoding='utf-8', errors='replace',
                              cwd=str(old.tree), timeout=120, env=dict(env, PYTHONUTF8='1'))
        return done.returncode, done.stdout, done.stderr

    def test_t41a_e2_pre_fix_hook_blocks_while_running_and_the_fixed_hook_lets_go(self):
        old = ov.OldVersion(ov.archive(PRE_FIX, rs.REPO, self.temp.name))
        self.plan_with([rs.PY, '-c', rs.GATE, str(self.gate)])
        proc = self.background()
        self.assertTrue(self.wait_for('verdict.run_started'), 'verdict run did not write verdict.run_started')
        self.assertIsNone(proc.poll(), 'the run must still be going')
        code, out, err = self.stop('fixed-session')                                      # this checkout: silent
        self.assertEqual((code, out.strip()), (0, ''), f'fixed hook said something while M1 runs: {out!r} {err!r}')
        code, out, err = self.old_stop(old, 'prefix-session')                            # pre-fix code: blocks or reminds
        self.assertIsNone(proc.poll(), 'the run must still be going while the old hook is asked')
        said = out.strip()
        self.assertTrue(said, f'pre-fix hook did not block or remind (exit {code}): {err!r}')
        decision = json.loads(said)
        self.assertEqual(decision.get('decision'), 'block', decision)                    # the right reason: the running milestone M1
        self.assertIn('M1', json.dumps(decision, ensure_ascii=False))
        self.gate.write_text('go')
        _, err = proc.communicate(timeout=120)
        self.assertEqual(proc.returncode, 0, err.decode('utf-8', 'replace'))


def load_tests(loader, tests, pattern):
    """Only this module's own test (RunFixture inherits HookFixture's tests, which belong to tests/test_v2_l2)."""
    return loader.loadTestsFromNames(['test_t41a_e2_pre_fix_hook_blocks_while_running_and_the_fixed_hook_lets_go'], PreFixStopHookTests)
