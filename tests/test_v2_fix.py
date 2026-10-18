"""OneCrew v2, fix slice: the Opus review conditions C9-C13 and stop{max_stuck, max_repairs_total}. Each test replays the way the reviewer got
around the old check (opus-bypass-l2-r2.py, opus-bypass-l3.py) and at least one variant of it.

Run with:  python -m unittest discover -s tests -p test_v2_fix.py   (it builds on the fixtures of test_v2_l1/l2/l3, imported as top-level modules)
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew import cli
from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import contract as contracts, gate, hook_cli, ownership, plan as plans, step0, verdict

import test_v2_l1 as l1
import test_v2_l2 as l2
import test_v2_l3 as l3
from test_v2_l1 import BAD, PY, milestone, plan_json

REPO = Path(__file__).resolve().parents[1]
AI = {'CLAUDE_CODE_CHILD_SESSION': '1'}                          # what Claude Code sets for every tool-call subprocess
VENV = r'D:\TamNT\Workspace\9.VMAgent\onecrew\.venv\Scripts\python.exe'


def clean_env(**extra):
    return dict({k: v for k, v in os.environ.items() if k not in ('CLAUDE_CODE_CHILD_SESSION', 'CLAUDECODE', 'ONECREW_ACTOR')}, PYTHONUTF8='1', **extra)


class HookCase(l2.HookFixture):
    def setUp(self):
        super().setUp()
        self.enforce()

    def judge(self, command):
        plan, bad = hook_cli.load_plan(self.root / '.onecrew' / 'active-plan.json')
        self.assertIsNone(bad)
        return hook_cli.judge_shell(plan, self.root, self.root, command)

    def assertBlocked(self, command, rule=None):
        found = self.judge(command)
        self.assertIsNotNone(found, 'not blocked: ' + command)
        if rule: self.assertEqual(found[0], rule, command)

    def assertAllowed(self, command):
        self.assertIsNone(self.judge(command), 'blocked: ' + command)

    def exit_code(self, command, tool='Bash'):
        return self.run_hook('check', self.shell(command, tool))[0]


# ---- C9 ------------------------------------------------------------------------------------------------------------------------

class C9GitPush(HookCase):
    def test_the_reviewers_three_ways_exit_2(self):
        for command in ('git.exe push origin main', '"C:/Program Files/Git/cmd/git.exe" push origin main', 'git send-pack origin main'):
            self.assertEqual(self.exit_code(command), 2, command)
        self.assertEqual(self.exit_code('& "C:\\Program Files\\Git\\cmd\\git.exe" push origin main', 'PowerShell'), 2)
        self.assertEqual(self.exit_code('git status'), 0)                                    # the control still passes

    def test_c14_git_cmd_and_an_alias_given_with_dash_c_exit_2(self):
        for command in ('git.cmd push origin main', 'git -c alias.p=push p origin main'):
            self.assertEqual(self.exit_code(command), 2, command)
        self.assertEqual(self.exit_code('git log --grep push'), 0)                          # the control
        self.assertEqual(self.exit_code('git.cmd push origin main', 'PowerShell'), 2)
        self.assertEqual(self.exit_code('& "C:\\Program Files\\Git\\cmd\\git.cmd" -c alias.p=push p origin main', 'PowerShell'), 2)

    def test_c14_variants_are_blocked(self):
        for command in ('"C:/Program Files/Git/cmd/git.cmd" push', 'GIT.CMD send-pack origin', 'git.cmd -C sub push', 'git.exe -c alias.p=push p', 'git -calias.p=push p origin',
                        'git -c alias.s=send-pack s origin main', 'git -c user.name=x -c alias.p=push p', 'git -c alias.p="!git push" p', 'git.cmd -c alias.h=http-push h x',
                        'cd sub && git -c alias.p=push p', 'git --config-env=alias.p=PUSHCMD p', 'git --config-env alias.p=PUSHCMD p',
                        'GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.p GIT_CONFIG_VALUE_0=push git p', 'git.cmd config alias.p push', 'git.cmd tag v1'):
            self.assertBlocked(command, 'bash_deny')

    def test_c14_what_only_looks_like_it_is_not_blocked(self):
        for command in ('git log --grep push', 'git.cmd status', 'git -c core.pager=cat log --grep push', 'git -c alias.l=log l', 'git.cmd -c user.name=x commit -m "push it"',
                        'git config user.name pusher', 'git.cmd tag -l'):
            self.assertAllowed(command)

    def test_c14_the_generated_permission_rules_cover_git_cmd_and_dash_c_aliases(self):
        deny = hook_cli.settings(self.root, self.state, REPO)['permissions']['deny']
        for rule in ('Bash(*git.cmd*push*)', 'PowerShell(*git.cmd*push*)', 'Bash(*-c*alias.*push*)', 'PowerShell(*-c*alias.*send-pack*)', 'Bash(*--config-env*)'): self.assertIn(rule, deny)

    def test_variants_are_blocked(self):
        for command in ("'C:\\Program Files\\Git\\cmd\\git.exe' push", 'GIT.EXE PUSH origin', 'git.exe send-pack x', 'git http-push x', 'git.exe -C sub push',
                        'git -C . push origin main', '"C:/Program Files/Git/cmd/git.exe" -c core.x=1 push', 'git.exe --no-pager push', 'git.exe config alias.p push',
                        '/usr/bin/git push origin', 'cd sub && git.exe push', 'git.exe tag v1'):
            self.assertBlocked(command, 'bash_deny')

    def test_reading_git_is_not_blocked(self):
        for command in ('git status', 'git.exe status', '"C:/Program Files/Git/cmd/git.exe" log --oneline', 'git.exe tag -l', 'git commit -m "push the button"',
                        'git log --grep push', 'git.exe diff --stat', 'echo digit push', 'mygit push'):
            self.assertAllowed(command)

    def test_the_generated_permission_rules_name_git_exe_and_send_pack(self):
        deny = hook_cli.settings(self.root, self.state, REPO)['permissions']['deny']
        for rule in ('Bash(*git.exe*push*)', 'PowerShell(*git.exe*push*)', 'Bash(*send-pack*)', 'PowerShell(*send-pack*)'): self.assertIn(rule, deny)


# ---- C10 -----------------------------------------------------------------------------------------------------------------------

class C10NestedWrites(HookCase):
    def test_the_reviewers_two_ways_exit_2_and_the_control_passes(self):
        self.assertEqual(self.exit_code("iex 'sc README.md x'", 'PowerShell'), 2)
        self.assertEqual(self.exit_code('powershell -c "sc README.md x"', 'PowerShell'), 2)
        self.assertEqual(self.exit_code("iex 'sc src/y.py x'", 'PowerShell'), 0)
        self.assertEqual(self.exit_code('powershell -c "sc src/y.py x"', 'PowerShell'), 0)

    def test_variants_are_blocked(self):
        for command in ('powershell -Command "Set-Content README.md x"', 'cmd /c "copy src\\a.py README.md"', "bash -c 'echo hi > README.md'",
                        "bash -c 'echo hi | tee README.md'", 'powershell -c "iex \'sc README.md x\'"', 'pwsh -c "Add-Content -Path README.md -Value x"',
                        'Invoke-Expression "ac README.md x"', 'iex "[IO.File]::WriteAllText(\'README.md\',\'x\')"', 'bash -c "rm README.md"',
                        "iex 's`c README.md x'", "bash -c \"bash -c 'rm README.md'\"", 's`c README.md x', 'co^py src\\a.py README.md', 'powershell -c "s`c README.md x"'):
            self.assertBlocked(command)

    def test_writes_inside_the_owned_scope_stay_allowed(self):
        for command in ("bash -c 'echo hi > src/y.py'", "bash -c 'echo ok'", 'cmd /c "dir"', 'powershell -c "Get-Content README.md"', "iex 'sc a.txt x'",
                        'git commit -m "Move the notes to docs"', 'git commit -m "Copy files over" && echo done', 'echo "touch up the tee"'):   # a message is not a command
            self.assertAllowed(command)


# ---- C11 -----------------------------------------------------------------------------------------------------------------------

class C11OwnerVerbsInAnAiSession(l1.Fixture):
    def ai(self, **extra):
        env = patch.dict(os.environ, dict(AI, **extra)); env.start(); self.addCleanup(env.stop)

    def py(self, *argv, env=None):
        done = subprocess.run([PY, '-X', 'utf8', *argv], cwd=REPO, capture_output=True, env=env or clean_env(), timeout=120)
        return done.returncode, done.stdout.decode('utf-8'), done.stderr.decode('utf-8')

    def cli_args(self, *argv):
        return ['--project', str(self.root), '--state-root', str(self.ledger.state_root), *argv]

    def test_plan_functions_refuse_when_the_ai_marker_is_set(self):
        self.propose(); self.ai()
        with self.assertRaises(LedgerError) as caught: plans.approve(self.ledger, 'P1', 'owner', 'r')
        self.assertIn('AI tool session', str(caught.exception))
        self.assertNotIn('plan.approved', self.kinds())
        os.environ.pop('CLAUDE_CODE_CHILD_SESSION')
        plans.approve(self.ledger, 'P1', 'owner', 'r')                                        # the same call outside the AI session works
        os.environ.update(AI)
        with self.assertRaises(LedgerError): plans.accept(self.ledger, 'P1', 'owner', 'r', self.tree())
        with self.assertRaises(LedgerError): gate.set_enforced(self.ledger, True, 'owner', 'r')
        with self.assertRaises(LedgerError): plans.require_owner('owner', 'x')
        self.assertNotIn('plan.accepted', self.kinds())

    def test_the_owner_verdict_and_the_l3_owner_verbs_refuse_too(self):
        manual = {'id': 'M1', 'title': 'Looks right', 'verifier': {'type': 'owner-manual'}, 'covers': ['O1']}
        self.approved(value=plan_json(milestones=[manual]))
        blob = Snapshots(self.ledger.state_root).blob(b'checked')
        self.ai()
        with self.assertRaises(LedgerError): verdict.record(self.ledger, 'P1', 'M1', 'pass', 'owner', blob, self.tree())
        self.assertNotIn('verdict.recorded', self.kinds())

    def test_closing_an_unknown_as_the_owner_or_recording_a_poc_as_the_owner_is_refused_but_doc_and_poc_are_not(self):
        self.propose(value=l3.step0_json(size='S', unknowns=['U1', 'U2', 'U3']))
        evidence = self.root / 'poc.out'; evidence.write_text('three cases, all pass\n')
        self.ai()
        with self.assertRaises(LedgerError): step0.close_unknown(self.ledger, 'P1', 'U1', 'owner', 'the owner said so, in chat')
        with self.assertRaises(LedgerError): step0.poc_record(self.ledger, 'P1', 'U1', 'a', evidence, 'high', by='owner')
        self.assertNotIn('unknown.closed', self.kinds())
        step0.close_unknown(self.ledger, 'P1', 'U1', 'doc', 'a.txt:1')                       # an AI may close with a pointer ...
        step0.poc_record(self.ledger, 'P1', 'U2', 'a', evidence, 'high')                    # ... or with a PoC that has an evidence file
        closed = [p for k, p in self.events() if k == 'unknown.closed']
        self.assertEqual([(p['unknown'], p['by'], p['ai_session']) for p in closed], [('U1', 'doc', True), ('U2', 'poc', True)])
        poc = [p for k, p in self.events() if k == 'poc.answered'][0]
        self.assertEqual((poc['by'], poc['ai_session']), ('poc', True))

    def test_plan_cli_run_directly_is_refused_with_the_marker_and_works_without_it(self):
        self.propose()
        base = ['-m', 'onecrew.v2.plan_cli', '--project', str(self.root), '--state-root', str(self.ledger.state_root), 'plan', 'approve', 'P1', '--by', 'owner', '--reference', 'r']
        code, out, _ = self.py(*base, env=clean_env(**AI))                                   # the reviewer's way: exit 0 and approved before this fix
        self.assertEqual(code, 2); self.assertIn('AI tool session', out)
        self.assertNotIn('plan.approved', self.kinds())
        self.assertEqual(self.py(*base)[0], 0)
        self.assertIn('plan.approved', self.kinds())

    def test_python_c_calling_plan_approve_fails_with_the_marker(self):
        self.propose()
        code_text = ("import onecrew.v2.plan as p; from onecrew.ledger import Ledger; "
                     f"p.approve(Ledger({str(self.root)!r}, {str(self.ledger.state_root)!r}), 'P1', 'owner', 'r')")
        code, _, err = self.py('-c', code_text, env=clean_env(**AI))
        self.assertNotEqual(code, 0); self.assertIn('LedgerError', err)
        self.assertNotIn('plan.approved', self.kinds())

    def test_the_router_refuses_the_new_verbs_but_not_what_an_ai_may_do(self):
        self.ai()
        for argv in (['plan', 'unknown', 'close', 'P1', 'U1', '--by', 'owner', '--evidence', 'x'], ['plan', 'unknown', 'close', 'P1', 'U1', '--b=owner', '--evidence', 'x'],
                     ['plan', 'poc', 'record', 'P1', 'U1', '--answer', 'a', '--evidence', 'f', '--confidence', 'high', '--by', 'owner'],
                     ['verdict', 'record', '--plan', 'P1', '--milestone', 'M1', '--result', 'pass', '--b', 'owner', '--artifact-sha', 'a' * 40, '--receipt', 'b' * 64],
                     ['hook', 'mode', 'enforce', '--by', 'owner', '--reference', 'r']):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(ownership.refuse_argv(argv), 2, argv)
                self.assertEqual(cli.main(self.cli_args(*argv)), 2, argv)
        for argv in (['plan', 'unknown', 'close', 'P1', 'U1', '--by', 'doc', '--evidence', 'a.txt:1'],
                     ['plan', 'poc', 'record', 'P1', 'U1', '--answer', 'a', '--evidence', 'f', '--confidence', 'high', '--by', 'poc'],
                     ['plan', 'poc', 'record', 'P1', 'U1', '--answer', 'a', '--evidence', 'f', '--confidence', 'high'], ['plan', 'show', 'P1']):
            self.assertIsNone(ownership.refuse_argv(argv), argv)

    def test_events_say_who_ran_it(self):
        self.propose()
        plans.approve(self.ledger, 'P1', 'owner', 'r')
        approved = [p for k, p in self.events() if k == 'plan.approved'][0]
        self.assertEqual((approved['actor_env'], approved['ai_session']), (None, 'unknown'))   # no marker and no declaration: nothing is claimed
        self.propose('P2')
        os.environ['ONECREW_ACTOR'] = 'user'
        plans.approve(self.ledger, 'P2', 'owner', 'r')
        second = [p for k, p in self.events('P2') if k == 'plan.approved'][0]
        self.assertEqual((second['actor_env'], second['ai_session']), ('user', False))
        manual = {'id': 'M1', 'title': 'Looks right', 'verifier': {'type': 'owner-manual'}, 'covers': ['O1']}
        self.approved('P3', plan_json(milestones=[manual]))
        verdict.record(self.ledger, 'P3', 'M1', 'pass', 'owner', Snapshots(self.ledger.state_root).blob(b'ok'), self.tree())
        plans.accept(self.ledger, 'P3', 'owner', 'r', self.tree())
        accepted = [p for k, p in self.events('P3') if k == 'plan.accepted'][0]
        self.assertEqual((accepted['actor_env'], accepted['ai_session']), ('user', False))

    def test_an_ai_session_cannot_write_a_revision_in_the_owners_name(self):
        self.ai()
        for author in ('owner', 'user'):
            with self.assertRaises(LedgerError): plans.propose(self.ledger, 'P1', plan_json(), author)
        self.assertEqual(plans.propose(self.ledger, 'P1', plan_json(), 'claude')['status'], 'proposed')
        with self.assertRaises(LedgerError): plans.amend(self.ledger, 'P1', plan_json(title='Other'), 'why', 'owner')


# ---- C12 -----------------------------------------------------------------------------------------------------------------------

class C12Evidence(l3.Step0):
    def test_an_assumption_with_a_sentence_for_evidence_is_refused_naming_the_field(self):
        error = self.refused(l3.step0_json(size='S', assumptions=[('the base builds', 'trust me')]))              # L08
        self.assertEqual(l3.reasons(error), ['assumption_evidence_invalid'])
        self.assertIn('understanding.assumptions[1].evidence', str(error)); self.assertIn('trust me', str(error))

    def test_an_option_with_a_sentence_for_evidence_is_refused_naming_the_field(self):
        value = l3.step0_json(); value['options']['items'][0]['evidence'] = ['x']                               # L09
        error = self.refused(value, choose='A')
        self.assertEqual(l3.reasons(error), ['option_evidence_invalid'])
        self.assertIn('options.items[A].evidence[1]', str(error))

    def test_an_option_the_owner_did_not_choose_is_judged_too(self):
        value = l3.step0_json(); value['options']['items'][1]['evidence'] = ['x/y.py:1', 'because I say so']
        error = self.refused(value, choose='A')
        self.assertIn('options.items[B].evidence[2]', str(error))

    def test_a_pointer_is_evidence_whatever_it_points_at(self):
        blob = Snapshots(self.ledger.state_root).blob(b'a measurement')
        value = l3.step0_json(assumptions=[('a', 'https://example.org/spec'), ('b', 'src/a.py:12'), ('c', blob)])
        value['options']['items'][0]['evidence'] = ['x/y.py:1', blob]
        self.assertEqual(self.approve_ok(value, choose='A')['status'], 'approved')

    def test_a_blob_key_that_is_not_in_this_state_root_is_refused(self):
        self.assertIn('no such blob', str(self.refused(l3.step0_json(size='S', assumptions=[('a', 'f' * 64)]))))

    def test_a_statement_is_evidence_only_when_the_owner_wrote_the_revision(self):
        value = l3.step0_json(size='S', assumptions=[('the base builds', 'the owner told me in chat')])
        self.refused(value, 'ByAi')                                                                              # claude wrote it
        plans.propose(self.ledger, 'ByOwner', value, 'owner')
        self.assertEqual(plans.approve(self.ledger, 'ByOwner', 'owner', 'r')['status'], 'approved')

    def test_closing_an_unknown_as_the_owner_does_not_turn_the_ais_sentence_into_evidence(self):
        value = l3.step0_json(size='S', unknowns=['U1'], assumptions=[('the base builds', 'trust me, it builds')])
        self.propose('P1', value)
        step0.close_unknown(self.ledger, 'P1', 'U1', 'owner', 'the owner decided this in chat')                  # revision 2, author owner, text still the AI's
        with self.assertRaises(LedgerError) as caught: plans.approve(self.ledger, 'P1', 'owner', 'r')
        self.assertEqual(l3.reasons(caught.exception), ['assumption_evidence_invalid'])

    def test_an_ai_cannot_claim_to_be_the_owner_to_get_a_statement_through(self):
        env = patch.dict(os.environ, AI); env.start(); self.addCleanup(env.stop)
        with self.assertRaises(LedgerError): plans.propose(self.ledger, 'P1', l3.step0_json(size='S', assumptions=[('a', 'trust me please')]), 'owner')


# ---- C13 -----------------------------------------------------------------------------------------------------------------------

class C13HookCoversTheL3Verbs(HookCase):
    OWNER_FORMS = ('plan unknown close P1 U1 --by owner --evidence "owner said so"', 'plan unknown close P1 U1 --by=owner --evidence x',
                   'plan unknown close P1 U1 --b owner --evidence x', 'plan unknown close P1 U1 --by "owner" --evidence x', "plan unknown close P1 U1 --by 'owner' --evidence x",
                   'plan poc record P1 U1 --answer a --evidence f.txt --confidence high --by owner', 'plan poc record P1 U1 --answer a --evidence f.txt --confidence high --b=owner',
                   'hook mode enforce --by owner --reference x', 'hook  mode log --by owner --reference x', 'verdict record --plan P1 --milestone M1 --result pass --b owner',
                   'plan unknown close P1 U1 --evidence x --by owner', 'plan unknown close P1 U1 `\n --by owner')

    def test_the_owner_forms_exit_2_through_a_venv_python_in_bash_and_powershell(self):
        for form in self.OWNER_FORMS:
            self.assertEqual(self.exit_code(f'{VENV} -X utf8 -m onecrew {form}'), 2, form)
            self.assertEqual(self.exit_code(f'& "{VENV}" -X utf8 -m onecrew {form}', 'PowerShell'), 2, form)
            self.assertEqual(self.exit_code(f'onecrew {form}'), 2, form)

    def test_what_an_ai_may_do_still_passes(self):
        for form in ('plan unknown close P1 U1 --by doc --evidence src/a.py:3', 'plan poc record P1 U1 --answer a --evidence f.txt --confidence high --by poc',
                     'plan poc record P1 U1 --answer a --evidence f.txt --confidence high', 'plan show P1', 'plan precheck P1'):
            self.assertEqual(self.exit_code(f'{VENV} -X utf8 -m onecrew {form}'), 0, form)

    def test_calling_the_verbs_as_python_functions_is_named_too(self):
        for command in ('python -c "import onecrew.v2.plan as p; p.approve(L, \'P1\', \'owner\', \'r\')"', 'python -c "from onecrew.v2.plan import accept; accept(L)"',
                        'python -c "import onecrew.v2.step0 as s; s.close_unknown(L, \'P1\', \'U1\', \'owner\', \'e\')"',
                        'python -c "import onecrew.v2.gate as g; g.set_enforced(L, False, \'o\', \'r\')"'):
            self.assertBlocked(command, 'bash_deny')
        self.assertAllowed('python -c "import onecrew.v2.plan as p; print(p.show)"')

    def test_the_permission_rules_cover_the_two_new_verbs_without_blocking_doc_and_poc(self):
        deny = hook_cli.settings(self.root, self.state, REPO)['permissions']['deny']
        for rule in ('Bash(*plan unknown close*owner*)', 'PowerShell(*plan poc record*owner*)'): self.assertIn(rule, deny)
        self.assertNotIn('Bash(*plan unknown close*)', deny)

    def test_in_a_shell_with_the_ai_marker_the_command_exits_2_and_changes_nothing(self):
        self.propose('P2', l3.step0_json(size='S', unknowns=['U1']))
        for argv in (['plan', 'unknown', 'close', 'P2', 'U1', '--by', 'owner', '--evidence', 'the owner decided this'],
                     ['plan', 'poc', 'record', 'P2', 'U1', '--answer', 'a', '--evidence', str(self.root / 'a.txt'), '--confidence', 'high', '--by', 'owner']):
            done = subprocess.run([PY, '-X', 'utf8', '-m', 'onecrew', '--project', str(self.root), '--state-root', str(self.state), *argv], cwd=REPO, capture_output=True,
                                  env=clean_env(**AI), timeout=120)
            self.assertEqual(done.returncode, 2, argv); self.assertIn('refused', done.stdout.decode('utf-8'))
        self.assertNotIn('unknown.closed', self.kinds('P2'))


# ---- stop{max_stuck, max_repairs_total} ----------------------------------------------------------------------------------------

def manual(mid='M1', **extra):
    return dict({'id': mid, 'title': 'Milestone ' + mid, 'verifier': {'type': 'owner-manual'}, 'covers': ['O1'], 'max_repairs': 5}, **extra)


class StopLimits(l1.Fixture):
    def fail(self, mid, n, result='fail'):
        """A failed owner-manual verdict on artifact number n (a different n is a different artifact)."""
        return verdict.record(self.ledger, 'P1', mid, result, 'owner', Snapshots(self.ledger.state_root).blob(f'checked {mid} {n}'.encode()), format(n, '040x'))

    def stopped(self):
        return [p for k, p in self.events() if k == 'milestone.stopped']

    def questions(self):
        with self.ledger.transaction() as conn:
            task = plans.derive(self.ledger, conn, 'P1')['task_id']
        return [r for r in self.ledger.requests(task) if r['question'].get('action', {}).get('type') == 'v2.plan_stopped']

    def test_the_contract_has_stop_limits_with_defaults_and_bounds(self):
        normal = contracts.validate(plan_json())
        self.assertEqual(normal['stop'], {'max_stuck': 3, 'max_repairs_total': 8})
        self.assertEqual(contracts.validate(plan_json(stop={'max_stuck': 2}))['stop'], {'max_stuck': 2, 'max_repairs_total': 8})
        for bad in ({'max_stuck': 1}, {'max_stuck': 11}, {'max_repairs_total': 0}, {'max_repairs_total': 51}, {'max_stuck': True}, {'max_stuck': '3'},
                    {'forever': 1}, {'max_stuck': 3, 'max_repairs_total': 1.5}, 'no', [3]):
            with self.assertRaises(LedgerError): contracts.validate(plan_json(stop=bad))
        self.assertEqual(contracts.stop_limits({}), {'max_stuck': 3, 'max_repairs_total': 8})                    # a revision stored before the field existed
        self.assertEqual(self.approved(value=plan_json(stop={'max_stuck': 4}))['stop'], {'max_stuck': 4, 'max_repairs_total': 8, 'repairs_used': 0})

    def test_max_repairs_total_counts_failures_over_all_milestones(self):
        self.approved(value=plan_json(milestones=[manual('M1'), manual('M2')], stop={'max_stuck': 10, 'max_repairs_total': 2}))
        self.fail('M1', 1)                                                          # total 1
        verdict.record(self.ledger, 'P1', 'M1', 'pass', 'owner', Snapshots(self.ledger.state_root).blob(b'ok'), format(2, '040x'))
        self.fail('M2', 3)                                                          # total 2: at the cap, not over it
        self.assertEqual(self.stopped(), [])
        view = self.fail('M2', 4)                                                   # total 3 > 2, although M2 still has 5 repairs of its own
        self.assertEqual(view['status'], 'stopped_with_report')
        self.assertIn('max_repairs_total exceeded', self.stopped()[0]['reason'])
        self.assertEqual(self.stopped()[0]['milestone'], 'M2')
        self.assertEqual(view['stopped']['question'], 'created')
        self.assertEqual((view['attention']['questions_used'], len(self.questions())), (1, 1))
        self.assertIn('max_repairs_total', self.questions()[0]['question']['question'])
        with self.assertRaises(LedgerError): self.fail('M2', 5)                    # the AI cannot try again past the limit

    def test_max_stuck_stops_a_milestone_that_fails_again_on_an_unchanged_artifact(self):
        self.approved(value=plan_json(milestones=[manual()], stop={'max_stuck': 2, 'max_repairs_total': 50}))
        self.assertEqual(self.fail('M1', 7)['status'], 'approved')
        view = self.fail('M1', 7)                                                   # the same artifact again: the AI changed nothing
        self.assertEqual(view['status'], 'stopped_with_report')
        self.assertIn('max_stuck reached', self.stopped()[0]['reason'])
        self.assertEqual((self.stopped()[0]['failures'], view['stopped']['question']), (2, 'created'))
        self.assertEqual(len(self.questions()), 1)

    def test_a_changed_artifact_resets_the_stuck_count(self):
        self.approved(value=plan_json(milestones=[manual()], stop={'max_stuck': 2, 'max_repairs_total': 50}))
        for n in (1, 2, 1, 3, 3 + 1): self.fail('M1', n)                            # four different neighbours in a row: never two the same in a row
        self.assertEqual(self.stopped(), [])
        self.assertEqual(plans.show(self.ledger, 'P1')['status'], 'approved')

    def test_the_default_max_stuck_stops_the_third_identical_failure_of_a_real_command(self):
        self.approved(value=plan_json(milestones=[milestone(argv=BAD, max_repairs=5)]))
        self.assertEqual(verdict.run(self.ledger, 'P1', 'M1', self.root)['status'], 'approved')
        self.assertEqual(verdict.run(self.ledger, 'P1', 'M1', self.root)['status'], 'approved')
        view = verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(view['status'], 'stopped_with_report')
        self.assertIn('max_stuck', self.stopped()[0]['reason'])

    def test_max_repairs_is_still_the_first_reason(self):
        self.approved(value=plan_json(milestones=[manual(max_repairs=1)], stop={'max_stuck': 2, 'max_repairs_total': 1}))
        self.fail('M1', 1)
        self.fail('M1', 2)
        self.assertEqual(self.stopped()[0]['reason'], 'max_repairs exceeded')

    def test_the_question_counts_against_attention_and_a_second_stop_is_not_asked(self):
        self.approved(value=plan_json(milestones=[manual()], stop={'max_stuck': 2, 'max_repairs_total': 50}, attention={'questions': 1}))
        self.fail('M1', 1); self.fail('M1', 1)
        plans.amend(self.ledger, 'P1', plan_json(milestones=[manual()], stop={'max_stuck': 2, 'max_repairs_total': 50}, attention={'questions': 1}, title='Retry'), 'again', 'claude')
        plans.approve(self.ledger, 'P1', 'owner', 'r')
        self.fail('M1', 5)
        again = self.fail('M1', 5)
        self.assertEqual(again['status'], 'stopped_with_report')
        self.assertEqual(again['stopped']['question'], 'refused')                   # attention.questions=1 was used by the first stop
        self.assertIn('attention.exceeded', self.kinds())


if __name__ == '__main__':
    unittest.main()
