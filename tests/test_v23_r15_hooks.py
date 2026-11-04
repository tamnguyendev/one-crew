"""OneCrew 2.3: the hook and lint fixes taken from the beta R15 fix (wf-codex `e432be2`, 29/10; beta report BAO-CAO-R15-2026-10-29, section 2).

  B6  the Stop hook repeats its reminder while a milestone waits for the owner, and tells the session to re-run a verdict that cannot change
      (onecrew/v2/hook_cli.py, onecrew/v2/active_plan.py);
  B1  `Remove-Item Env:NAME -ErrorAction SilentlyContinue` is judged as writing two files (onecrew/v2/hook_cli.py);
  B2  `<`, `>` and `|` inside a quoted string are read as a redirect or a pipe (onecrew/v2/hook_cli.py);
  B4  `plan lint` does not say that budget.max_calls is not counted for an AI session under the hooks (onecrew/v2/lint.py, onecrew/v2/plan_cli.py).

The classes B6StopTests, B1B2CheckTests and B4LintNoteTests, with the fixture they use (Hooks, command_milestone, SILENT, FAILS), are copied unchanged
from tests/test_wf_r15_beta_signsdk.py at e432be2 (lines 263-408 and 433-451); only the import block is cut down to what these three classes use.
The B3 and B5 classes of that file are in tests/test_v23_r15_port.py. Every hook test runs the hook as a subprocess with LOCALAPPDATA and APPDATA of
its own (the user's hook-projects.json is never read or written). No model is called.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))          # test_v2_l2 imports test_v2_l1 by its plain name
from test_v2_l2 import HookFixture, owned_plan                      # noqa: E402

from onecrew.v2 import verdict                                      # noqa: E402

from tests.test_v2_l1 import Fixture, plan_json                     # noqa: E402


# ---- the hooks: B6 (Stop), B1 and B2 (check) ---------------------------------------------------------------------------------

PY = sys.executable
SILENT = [PY, '-c', 'pass']                                          # exit 0 with no output: the command verifier calls it inconclusive
FAILS = [PY, '-c', 'import sys; print("not yet"); sys.exit(3)']


def command_milestone(argv, mid='M1', **extra):
    return dict({'id': mid, 'title': 'Milestone ' + mid, 'verifier': {'type': 'command', 'config': {'argv': argv}}, 'covers': ['O1']}, **extra)


class Hooks(HookFixture):
    """The hooks as subprocesses, with LOCALAPPDATA/APPDATA of the test (never the user's)."""

    def setUp(self):
        super().setUp()
        self.appdata = Path(self.temp.name) / 'appdata'
        (self.appdata / 'local').mkdir(parents=True); (self.appdata / 'roaming').mkdir()

    def hook(self, verb, event):
        return self.run_hook(verb, event, env={'LOCALAPPDATA': str(self.appdata / 'local'), 'APPDATA': str(self.appdata / 'roaming')})

    def stop(self, session='s1'):
        code, out, err = self.hook('stop', {'session_id': session, 'cwd': str(self.root), 'hook_event_name': 'Stop', 'stop_hook_active': False})
        self.assertEqual((code, err), (0, ''))
        return json.loads(out) if out.strip() else None

    def check(self, command, tool='PowerShell'):
        code, _, err = self.hook('check', self.shell(command, tool=tool))
        return code, err


class B6StopTests(Hooks):
    def waiting_reply(self, reply):
        self.assertIsNotNone(reply)
        self.assertEqual(reply['decision'], 'block')
        self.assertIn('owner', reply['reason']); self.assertIn('Do not say it is done', reply['reason'])
        self.assertNotIn('verdict run', reply['reason'])                         # dev18: "run `onecrew verdict run --plan ...`"
        return reply['reason']

    def test_an_inconclusive_milestone_is_reminded_once_then_the_session_may_stop(self):
        self.enforce(value=owned_plan(milestones=[command_milestone(SILENT, max_repairs=2)]))
        row = verdict.run(self.ledger, 'P1', 'M1', self.root)['milestones'][0]
        self.assertEqual((row['state'], row['last_verdict']['result']), ('failed', 'inconclusive'))
        reason = self.waiting_reply(self.stop())
        self.assertIn('inconclusive', reason)
        for _ in range(4): self.assertIsNone(self.stop())                        # dev18: block, block, let go, block, block ...
        rules = [v['rule'] for v in self.violations()]
        self.assertEqual(rules.count('stop_owner_wait'), 1); self.assertIn('stop_waiting_owner', rules)
        self.assertEqual(self.waiting_reply(self.stop(session='other')), reason)    # another session is told once too
        document = json.loads((self.root / '.onecrew' / 'active-plan.json').read_text(encoding='utf-8'))
        self.assertEqual({k: document['milestones'][0][k] for k in ('state', 'last_result', 'runs', 'repairs_left')},
                         {'state': 'failed', 'last_result': 'inconclusive', 'runs': 1, 'repairs_left': 1})

    def test_a_new_verdict_on_the_waiting_milestone_is_a_new_reminder(self):
        self.enforce(value=owned_plan(milestones=[command_milestone(SILENT, max_repairs=3)]))
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.waiting_reply(self.stop()); self.assertIsNone(self.stop())
        (self.root / 'a.txt').write_text('changed\n'); self.git('commit', '-qam', 'other work')
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.waiting_reply(self.stop()); self.assertIsNone(self.stop())

    def test_an_owner_manual_milestone_waits_for_the_owner(self):
        manual = {'id': 'M1', 'title': 'Owner looks at it', 'verifier': {'type': 'owner-manual'}, 'covers': ['O1']}
        self.enforce(value=owned_plan(milestones=[manual]))
        self.assertIn('owner-manual', self.waiting_reply(self.stop()))
        self.assertIsNone(self.stop()); self.assertIsNone(self.stop())

    def test_no_repair_left_waits_for_the_owner(self):
        self.enforce(value=owned_plan(milestones=[command_milestone(FAILS, max_repairs=0)]))
        row = verdict.run(self.ledger, 'P1', 'M1', self.root)['milestones'][0]
        self.assertEqual((row['last_verdict']['result'], row['repairs_left']), ('fail', 0))
        reply = self.stop()
        if reply is not None: self.assertIn('no repair', self.waiting_reply(reply))
        self.assertIsNone(self.stop())

    def test_the_ordinary_case_is_unchanged_two_blocks_then_let_go_and_it_says_run_the_verdict(self):
        self.enforce(value=owned_plan(milestones=[command_milestone(FAILS, max_repairs=2)]))
        verdict.run(self.ledger, 'P1', 'M1', self.root)                          # a real fail with repairs left: the session's work
        for _ in range(2):
            reply = self.stop()
            self.assertEqual(reply['decision'], 'block'); self.assertIn('verdict run', reply['reason'])
        self.assertIsNone(self.stop())
        self.assertEqual(self.stop()['decision'], 'block')                        # the dev18 cycle: the session is reminded again

    def test_log_mode_never_blocks(self):
        self.enforce(value=owned_plan(milestones=[command_milestone(SILENT, max_repairs=2)]), mode='log')
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertIsNone(self.stop())
        self.assertIn('stop_owner_wait', [v['rule'] for v in self.violations()])


class B1B2CheckTests(Hooks):
    def setUp(self):
        super().setUp()
        self.enforce()                                                          # owned: a.txt, src/

    def assertAllowed(self, command, tool='PowerShell'):
        code, err = self.check(command, tool)
        self.assertEqual((code, err), (0, ''), command)

    def assertBlocked(self, command, tool='PowerShell', why=None):
        code, err = self.check(command, tool)
        self.assertEqual(code, 2, command)
        if why: self.assertIn(why, err, command)

    def test_b1_the_report_command_is_allowed(self):
        self.assertAllowed('Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue; python -X utf8 -c "print(1)"')    # dev18: Env:PYTHONUTF8 outside_owned

    def test_b1_drives_that_are_not_files_and_values_of_common_parameters(self):
        for command in ('Remove-Item Env:PYTHONUTF8, Env:PYTHONIOENCODING -ErrorAction SilentlyContinue',
                        'Remove-Item -Path Env:A -EA 0', 'Remove-Item Variable:x', 'Remove-Item Function:helper -Force',
                        'Remove-Item Alias:ll', r'Remove-Item HKCU:\Software\DemoTest -Recurse', r'Remove-Item -LiteralPath HKLM:\SOFTWARE\X',
                        'Remove-Item Cert:\\CurrentUser\\My\\ABC', 'New-Item -Path Env:ONECREW_X -Value 1',
                        'Remove-Item src/x.txt -ErrorAction SilentlyContinue', 'Remove-Item src/x.txt -ErrorVariable problems -WarningAction Ignore'):
            with self.subTest(command=command): self.assertAllowed(command)

    def test_b1_a_flag_value_ends_at_the_command_separator(self):
        from onecrew.v2 import hook_cli
        command = 'Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue; python -X utf8 -c "print(1)"'
        self.assertEqual(hook_cli.all_targets(command, powershell=True), ['Env:PYTHONUTF8'])     # dev18: + SilentlyContinue;, python, utf8, -c ...
        self.assertEqual(hook_cli.all_targets('rm -rf build; ls docs'), ['build'])

    def test_b1_files_are_still_judged(self):
        for command in ('Remove-Item b.txt -ErrorAction SilentlyContinue', 'Remove-Item Env:X; Remove-Item b.txt', 'Remove-Item -Path docs/x.md -EA 0',
                        'Remove-Item E:\\data.txt', 'Remove-Item -Path b.txt -ErrorAction SilentlyContinue', 'Set-Content b.txt -Value Env:X'):
            with self.subTest(command=command): self.assertBlocked(command, why='outside_owned')
        self.assertBlocked('rm Env:X', tool='Bash', why='outside_owned')         # D4: only PowerShell has these drives

    def test_b2_the_report_command_is_allowed(self):
        self.assertAllowed(f'git -C "{self.root}" grep -n -E "<TargetFramework|<Version>|<PackageId>" -- "*.csproj"')      # dev18: `--` outside_owned
        self.assertAllowed("git grep -n -E '<TargetFramework|<Version>|<PackageId>' -- '*.csproj'", tool='Bash')

    def test_b2_quoted_operators_are_text(self):
        for command, tool in (('echo "a > b"', 'Bash'), ("echo 'x|tee b.txt'", 'Bash'), ('Write-Output "x 2> err.txt"', 'PowerShell'),
                              ('git log --format="%h <%an>" -n 3', 'PowerShell'), ("Select-String -Pattern '<Version>' -Path src/a.csproj", 'PowerShell')):
            with self.subTest(command=command): self.assertAllowed(command, tool)

    def test_b2_real_redirects_are_still_judged(self):
        for command, tool in (('echo hi > b.txt', 'Bash'), ('echo hi >> b.txt', 'Bash'), ('git log 2> err.txt', 'PowerShell'),
                              ('echo "x" > b.txt', 'Bash'), ('echo "a > b" > b.txt', 'Bash'), ('echo hi > "b c.txt"', 'Bash'),
                              ('echo "$(echo x > b.txt)"', 'Bash'), ('Write-Output "$(Get-Date > b.txt)"', 'PowerShell'),
                              ('powershell -c "echo x > b.txt"', 'PowerShell'), ("bash -c 'echo x > b.txt'", 'Bash'),
                              ('echo "x" | tee b.txt', 'Bash'), ('echo "unbalanced > b.txt', 'Bash')):
            with self.subTest(command=command): self.assertBlocked(command, tool)
        self.assertAllowed('echo hi > src/out.txt', 'Bash')


# ---- B4: budget.max_calls is not counted under the hooks ------------------------------------------------------------------

class B4LintNoteTests(Fixture):
    def lint(self, *flags):
        import contextlib
        import io
        from onecrew.v2 import lint, plan_cli
        path = Path(self.temp.name) / 'contract.json'
        path.write_text(json.dumps(plan_json()), encoding='utf-8')
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = plan_cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'plan', 'lint', '--file', str(path), *flags])
        return code, out.getvalue(), err.getvalue(), lint.check(lint.ReadOnlyLedger(self.root, self.ledger.state_root), plan_json())

    def test_lint_notes_that_max_calls_is_not_counted_and_changes_nothing_else(self):
        code, out, err, checked = self.lint('--author', 'claude-opus-5-5')
        self.assertEqual((code, out.strip(), checked), (0, 'lint: clean', ([], [])))
        self.assertIn('[note budget_calls_untracked]', err)                    # dev18: nothing
        self.assertIn('max_calls', err); self.assertIn('100', err)


if __name__ == '__main__':
    unittest.main()
