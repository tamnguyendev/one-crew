"""OneCrew v2, slice L2: enforcement while the AI works. Part A closes the Opus review conditions C6-C8; the hook tests run the
real `onecrew hook ...` as a subprocess with stdin JSON in the documented Claude Code format.
"""
import contextlib
import datetime as dt
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew import budget, solution_gate
from onecrew.control import Control, migrate
from onecrew.ledger import Ledger, LedgerError
from onecrew.owned_intake import submit
from onecrew.v2 import gate, plan as plans, verdict
from onecrew.v2.verifiers import command

import test_v2_l1 as l1
from test_v2_l1 import BAD, PY, Fixture, milestone, plan_json


class ReviewConditionTests(Fixture):
    """C6, C7, C8 of the Opus review of L1 (04443a5)."""

    def test_c6_a_clean_clone_nested_in_the_project_is_refused(self):
        self.approved(value=plan_json(milestones=[milestone(argv=BAD)]))
        decoy = self.root / 'decoy'
        subprocess.check_call(['git', 'clone', '-q', str(self.root), str(decoy)])
        with self.assertRaises(LedgerError) as caught: verdict.run(self.ledger, 'P1', 'M1', decoy)
        self.assertIn('not the project repository', str(caught.exception))
        self.assertEqual(plans.show(self.ledger, 'P1')['milestones'][0]['runs'], 0)
        (self.root / 'sub').mkdir(); (self.root / 'sub' / 'x').write_text('x')       # a plain subdirectory of the project is still fine
        self.assertEqual(verdict.run(self.ledger, 'P1', 'M1', self.root / 'sub')['milestones'][0]['failures'], 1)

    def test_c8_the_command_runs_on_a_clean_checkout_not_on_the_live_workspace(self):
        (self.root / '.gitignore').write_text('__pycache__/\nnote.txt\n'); (self.root / 'm.py').write_text('VALUE = 0\n')
        self.git('add', '.'); self.git('commit', '-q', '-m', 'module')
        check = 'import sys, os; import m; sys.exit(m.VALUE or (3 if os.path.exists("note.txt") else 0))'
        self.approved(value=plan_json(milestones=[milestone(argv=[PY, '-c', check])]))
        import py_compile
        poisoned = self.root / '__pycache__'; poisoned.mkdir()
        fake = self.root / 'fake.py'; fake.write_text('VALUE = 1\n')                  # an unchecked-hash .pyc is loaded without looking at m.py
        py_compile.compile(str(fake), cfile=str(poisoned / f'm.cpython-{sys.version_info.major}{sys.version_info.minor}.pyc'),
                           invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
        fake.unlink(); (self.root / 'note.txt').write_text('ignored file that fails the check')
        before = self.tree()
        live = subprocess.run([PY, '-c', check], cwd=self.root, capture_output=True)
        self.assertNotEqual(live.returncode, 0)                                        # on the live workspace the poison works
        view = verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(view['milestones'][0]['state'], 'passed')                     # on the artifact it does not
        self.assertEqual(view['milestones'][0]['last_verdict']['artifact_sha'], before)
        self.assertEqual(self.tree(), before)

    def test_c8_the_scratch_checkout_is_removed(self):
        self.approved()
        seen = []
        real = command._checkout

        def spy(*args):
            seen.append(real(*args)); return seen[-1]
        with patch.object(command, '_checkout', spy): verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertTrue(seen and not seen[0].exists())

    def _execution(self, limits):
        gate.set_enforced(self.ledger, True, 'owner', 'test')
        self.approved('job1', plan_json(budget={'max_calls': 100, 'time': 30}))
        task = submit(self.ledger, None, 'job1', mode='work', provider='kiro', model='claude-sonnet-5',
                      contract=dict(l1.DispatchGateTests.WORK), **limits)
        migrate(self.ledger)
        control = Control(self.ledger)
        control.configure(task['id'], task['revision'], {'mode': 'test'})
        return task, control

    def _extend(self, task, control, key='ext', **values):
        old = self.ledger.task(task['id'])['budget']
        created = dt.datetime.fromisoformat(task['created_at'])
        arguments = {'revision': old['revision'], 'request_key': key, 'max_calls': 20,
                     'deadline': (created + dt.timedelta(minutes=20)).isoformat(), 'reason': 'test'}
        arguments.update(values)
        return budget.extend(control, task['id'], **arguments)

    def test_c7_extend_cannot_pass_the_approved_plan_budget(self):
        task, control = self._execution({'max_calls': 20, 'max_seconds': 600})
        created = dt.datetime.fromisoformat(task['created_at'])
        with self.assertRaises(LedgerError) as caught: self._extend(task, control, 'a', max_calls=5000)
        self.assertIn('exceeds the approved plan budget of 100', str(caught.exception))
        with self.assertRaises(LedgerError) as caught: self._extend(task, control, 'b', deadline=(created + dt.timedelta(minutes=45)).isoformat())
        self.assertIn('exceeds the approved plan budget of 30 minutes', str(caught.exception))
        with self.assertRaises(LedgerError):
            budget.remove_deadline(control, task['id'], self.ledger.task(task['id'])['budget']['revision'], 'rm1', 'no limit')
        self.assertEqual(self.ledger.task(task['id'])['budget']['limits']['max_calls'], 20)
        receipt = self._extend(task, control, 'c', max_calls=60, deadline=(created + dt.timedelta(minutes=25)).isoformat())   # inside the plan
        self.assertEqual(receipt['budget']['limits']['max_calls'], 60)

    def test_c7_the_gate_compares_the_current_budget_not_only_the_grant(self):
        task, control = self._execution({'max_calls': 20, 'max_seconds': 600})
        self.assertIsNone(solution_gate.check(self.ledger, task['id']))
        widened = {'limits': {'max_calls': 5000, 'max_seconds': 600}, 'deadline': task['deadline'], 'revision': 'x'}
        with self.ledger.transaction(write=True) as conn:                             # however the control got wider (a bug, a direct write)
            self.ledger._event(conn, task['id'], 'grant.extended', {'request_key': 'sneaky', 'budget': widened})
        with self.assertRaises(LedgerError) as caught: solution_gate.check(self.ledger, task['id'])
        self.assertIn('5000 calls', str(caught.exception))

    def test_c7_extend_is_unchanged_when_the_gate_is_off(self):
        task = submit(self.ledger, None, 'free', mode='work', provider='kiro', model='claude-sonnet-5',
                      contract=dict(l1.DispatchGateTests.WORK), max_calls=20, max_seconds=600)
        migrate(self.ledger); control = Control(self.ledger); control.configure(task['id'], task['revision'], {'mode': 'test'})
        self.assertEqual(self._extend(task, control, max_calls=5000)['budget']['limits']['max_calls'], 5000)


REPO = Path(__file__).resolve().parents[1]
OWNED = ['a.txt', 'src/']


def owned_plan(**extra):
    return plan_json(**dict({'scope': {'owned': OWNED}, 'non_goals': ['docs/secret.md', 'Nothing else, no refactors']}, **extra))


class HookFixture(Fixture):
    """Runs `onecrew hook ...` as a real subprocess with the documented stdin JSON."""

    def setUp(self):
        super().setUp()
        (self.root / 'src').mkdir(); (self.root / 'docs').mkdir()
        self.state = Path(self.ledger.state_root)

    def enforce(self, name='P1', value=None, mode='enforce'):
        self.approved(name, value or owned_plan())
        from onecrew.v2 import active_plan
        active_plan.set_mode(self.ledger, mode)
        active_plan.export(self.ledger, name)

    def run_hook(self, verb, event=None, raw=None, extra=(), project=True, env=None):
        arguments = [PY, '-X', 'utf8', '-m', 'onecrew', *(['--project', str(self.root)] if project else []), '--state-root', str(self.state), 'hook', verb, *extra]
        data = raw if raw is not None else json.dumps(event or {}).encode('utf-8')
        done = subprocess.run(arguments, input=data, capture_output=True, cwd=REPO, timeout=120, env=dict(dict({k: v for k, v in os.environ.items() if k not in ('CLAUDE_CODE_CHILD_SESSION', 'CLAUDECODE')}, PYTHONUTF8='1'), **(env or {})))
        return done.returncode, done.stdout.decode('utf-8'), done.stderr.decode('utf-8')

    def tool(self, name, **tool_input):
        return {'session_id': 's1', 'cwd': str(self.root), 'hook_event_name': 'PreToolUse', 'permission_mode': 'default',
                'tool_name': name, 'tool_input': tool_input, 'tool_use_id': 'toolu_1'}

    def edit(self, rel, tool='Edit'):
        key = 'notebook_path' if tool == 'NotebookEdit' else 'file_path'
        return self.tool(tool, **{key: str(self.root / rel)})

    def shell(self, command, tool='Bash'):
        return self.tool(tool, command=command)

    def violations(self):
        path = self.root / '.onecrew' / 'violations.jsonl'
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []


class ExportTests(HookFixture):
    def test_approve_and_amend_export_the_active_plan_in_two_places(self):
        self.approved('P1', owned_plan())
        inside, outside = self.root / '.onecrew' / 'active-plan.json', self.state / 'plans' / 'P1' / 'active-plan.json'
        for path in (inside, outside): self.assertTrue(path.exists(), path)
        document = json.loads(inside.read_text(encoding='utf-8'))
        self.assertEqual((document['plan'], document['revision'], document['mode'], document['status']), ('P1', 1, 'log', 'approved'))
        self.assertEqual(document['owned'], OWNED)
        self.assertEqual(document['plan_sha'], plans.show(self.ledger, 'P1')['sha'])
        for key in ('non_goals', 'bash_deny', 'scratch', 'budget', 'expires', 'milestones', 'protected'): self.assertIn(key, document)
        self.assertTrue(any('push' in rule for rule in document['bash_deny']))

    def test_an_amendment_does_not_widen_what_is_allowed_until_the_owner_approves_it(self):
        self.enforce()
        plans.amend(self.ledger, 'P1', owned_plan(scope={'owned': OWNED + ['more.txt']}), 'need more.txt', 'claude')
        document = json.loads((self.root / '.onecrew' / 'active-plan.json').read_text(encoding='utf-8'))
        self.assertEqual((document['revision'], document['pending_revision'], document['owned']), (1, 2, OWNED))
        self.assertEqual(self.run_hook('check', self.edit('more.txt'))[0], 2)
        plans.approve(self.ledger, 'P1', 'owner', 'ok')
        self.assertEqual(self.run_hook('check', self.edit('more.txt'))[0], 0)

    def test_hook_files_are_not_part_of_the_artifact_also_when_the_project_ignores_them(self):
        (self.root / '.gitignore').write_text('.onecrew/\n'); self.git('add', '.'); self.git('commit', '-q', '-m', 'ignore .onecrew')
        self.enforce()
        before = self.tree()
        self.run_hook('check', self.edit('docs/x.md'))
        self.assertEqual(self.tree(), before)
        self.assertEqual(verdict.run(self.ledger, 'P1', 'M1', self.root)['milestones'][0]['state'], 'passed')   # found by the real run

    def test_hook_files_are_not_part_of_the_artifact(self):
        self.enforce()
        before = self.tree()
        self.run_hook('check', self.edit('docs/x.md'))                                  # writes violations.jsonl
        self.assertTrue(self.violations())
        self.assertEqual(self.tree(), before)


class CheckTests(HookFixture):
    def test_an_edit_inside_owned_passes_and_outside_owned_is_blocked_with_the_rule_and_the_way_to_ask(self):
        self.enforce()
        for tool in ('Edit', 'Write', 'MultiEdit'):
            self.assertEqual(self.run_hook('check', self.edit('src/deep/x.py', tool))[0], 0, tool)
        self.assertEqual(self.run_hook('check', self.edit('a.txt'))[0], 0)
        for tool in ('Edit', 'Write', 'MultiEdit', 'NotebookEdit'):
            code, out, err = self.run_hook('check', self.edit('other.py', tool))
            self.assertEqual(code, 2, tool)
            self.assertIn('not in the owned scope', err); self.assertIn('plan amend P1', err); self.assertIn('a.txt', err)
        self.assertEqual(self.run_hook('check', self.edit('../outside.txt'))[0], 2)         # normalized against the project root
        self.assertEqual(self.run_hook('check', self.edit('src/../other.py'))[0], 2)
        self.assertEqual(self.violations()[-1]['event'], 'blocked')

    def test_a_non_goal_is_blocked_even_when_the_directory_is_owned(self):
        self.enforce(value=owned_plan(scope={'owned': OWNED + ['docs/']}))
        self.assertEqual(self.run_hook('check', self.edit('docs/ok.md'))[0], 0)
        code, _, err = self.run_hook('check', self.edit('docs/secret.md'))
        self.assertEqual(code, 2); self.assertIn('non_goal', err)

    def test_the_plan_files_and_hook_files_cannot_be_edited(self):
        self.enforce()
        for target in ('.onecrew/active-plan.json', '.onecrew/violations.jsonl', '.claude/settings.json'):
            code, _, err = self.run_hook('check', self.edit(target))
            self.assertEqual(code, 2, target); self.assertIn('protected', err)
        for target in (self.state / 'plans' / 'policy.json', self.state / 'ledger.sqlite3', self.state / 'plans' / 'P1' / 'v1.json'):
            event = self.tool('Write', file_path=str(target))
            self.assertEqual(self.run_hook('check', event)[0], 2, str(target))
        self.assertEqual(self.run_hook('check', self.edit('.onecrew/scratch/note.txt'))[0], 0)

    def test_bash_and_powershell_deny_rules(self):
        self.enforce()
        denied = ['git -c core.x=1 push', 'git --no-pager  push origin', 'git -C . push', 'git config alias.p push', 'git push origin main', 'git tag v1', 'rm -rf build', 'pip install requests', 'cd x && git push', 'Remove-Item -Recurse -Force out',
                  'onecrew plan approve P1 --by owner --reference x', 'python -m onecrew plan accept P1 --by owner', 'onecrew plan enforce off --by owner',
                  'onecrew verdict record --plan P1 --milestone M1 --result pass --by owner', 'ONECREW_ACTOR=user onecrew plan show P1',
                  'onecrew hook mode log --by owner --reference x', 'python -m onecrew plan "approve" P1 --by owner', 'onecrew verdict record --by "owner" --plan P1',
                  'env -i python -m onecrew plan app\\rove P1 --by owner', 'env -u CLAUDECODE onecrew plan show', 'python -m onecrew.v2.plan_cli plan approve P1 --by owner',
                  r'D:\venv\Scripts\python.exe -X utf8 -m onecrew --project P plan approve P1 --by owner', 'ri -r -fo .onecrew', 'cmd //c rd /s /q .onecrew',
                  'python -c "import shutil; shutil.rmtree(\'.onecrew\')"', 'rmdir /s .onecrew']
        for tool in ('Bash', 'PowerShell'):
            for command in denied:
                code, _, err = self.run_hook('check', self.shell(command, tool))
                self.assertEqual(code, 2, (tool, command)); self.assertIn('bash_deny', err)
        for command in ('git tag -a v1 -m x', 'git tag -d v1', 'git tag v1 HEAD~1'):
            self.assertEqual(self.run_hook('check', self.shell(command))[0], 2, command)
        for command in ('python -m unittest discover', 'git status', 'git diff --stat', 'ls src', 'onecrew plan show P1', 'echo hi',
                        'git tag', 'git tag -l hook-demo-tag', 'git tag --list', 'git status --short; git tag -l x'):       # the real run found `git tag -l` blocked
            self.assertEqual(self.run_hook('check', self.shell(command))[0], 0, command)

    def test_writes_through_the_shell_to_a_file_outside_owned_are_blocked(self):
        self.enforce()
        blocked = ['echo x > other.txt', 'echo x>>other.txt', 'cat a.txt | tee other.txt', 'echo x > "other file.txt"',
                   'sed -i s/a/b/ other.py', 'cp a.txt other.txt', 'mv a.txt other.txt', 'rm other.txt', 'echo x > ../up.txt']
        for command in blocked:
            self.assertEqual(self.run_hook('check', self.shell(command))[0], 2, command)
        for command in ('Set-Content -Path other.txt -Value hi', 'Set-Content other.txt "hi there"', 'Out-File -FilePath other.txt',
                        'Add-Content other.txt hi', '"x" | Out-File other.txt', 'echo hi > $HOME/x', 'Copy-Item a.txt -Destination other.txt'):
            self.assertEqual(self.run_hook('check', self.shell(command, 'PowerShell'))[0], 2, command)
        for command in ('echo x > a.txt', 'echo x >> src/new.py', 'python run.py > /dev/null 2>&1', 'python run.py 2>&1 | tee src/log.txt',
                        'python run.py > NUL', 'cp other.txt src/copy.txt', 'ls > .onecrew/scratch/ls.txt'):
            self.assertEqual(self.run_hook('check', self.shell(command))[0], 0, command)
        self.assertEqual(self.run_hook('check', self.shell('Set-Content -Path a.txt -Value hi', 'PowerShell'))[0], 0)
        self.assertEqual(self.run_hook('check', self.shell('"x" | Out-File $null', 'PowerShell'))[0], 0)

    def test_a_shell_command_that_touches_the_ledger_or_plans_is_blocked_unless_it_only_reads(self):
        self.enforce()
        base = str(self.state).replace('\\', '/')
        for command in (f'python -c "open(\'{base}/plans/policy.json\',\'w\')"', f'sqlite3 {base}/ledger.sqlite3 "delete from events"',
                        f'echo {{}} > {base}/plans/policy.json', 'python edit.py .onecrew/active-plan.json'):
            self.assertEqual(self.run_hook('check', self.shell(command))[0], 2, command)
        self.assertEqual(self.run_hook('check', self.shell(f'cat {base}/plans/P1/v1.json'))[0], 0)

    def test_an_internal_error_blocks_in_enforce_and_passes_in_log(self):
        self.enforce()
        for raw in (b'{ not json', b'', b'[1,2]'):
            self.assertEqual(self.run_hook('check', raw=raw)[0], 2, raw)                       # fail closed
        self.assertEqual(self.run_hook('check', self.tool('Edit'))[0], 2)                      # an edit with no path field
        self.assertEqual(self.run_hook('check', self.tool('Bash'))[0], 2)                      # a shell call with no command
        self.assertIn('hook error', self.violations()[-1]['reason'])
        (self.root / '.onecrew' / 'active-plan.json').write_text('{ broken', encoding='utf-8')
        code, _, err = self.run_hook('check', self.edit('a.txt'))
        self.assertEqual(code, 2); self.assertIn('unreadable', err)                              # an unreadable plan file is treated as enforce
        from onecrew.v2 import active_plan
        active_plan.set_mode(self.ledger, 'log'); active_plan.export(self.ledger, 'P1')
        for raw in (b'{ not json', b''):
            self.assertEqual(self.run_hook('check', raw=raw)[0], 0, raw)                         # log mode: never blocks
        self.assertEqual(self.violations()[-1]['event'], 'logged')

    def test_an_expired_plan_blocks_in_enforce(self):
        self.enforce()
        for path in (self.root / '.onecrew' / 'active-plan.json', self.state / 'plans' / 'P1' / 'active-plan.json'):    # the state-root copy governs
            document = json.loads(path.read_text(encoding='utf-8')); document['expires'] = '2020-01-01T00:00:00+00:00'
            path.write_text(json.dumps(document), encoding='utf-8')
        code, _, err = self.run_hook('check', self.edit('a.txt'))
        self.assertEqual(code, 2); self.assertIn('expired', err)

    def test_log_mode_never_blocks_but_records_what_it_would_have_blocked(self):
        self.enforce(mode='log')
        for event in (self.edit('other.py'), self.shell('git push'), self.shell('echo x > other.txt')):
            self.assertEqual(self.run_hook('check', event)[0], 0)
        self.assertEqual([v['event'] for v in self.violations()], ['logged'] * 3)
        self.assertEqual({v['mode'] for v in self.violations()}, {'log'})

    def test_no_active_plan_passes_and_leaves_the_repository_alone(self):
        self.assertEqual(self.run_hook('check', self.edit('other.py'))[0], 0)
        self.assertEqual(self.run_hook('check', raw=b'garbage')[0], 0)
        self.assertFalse((self.root / '.onecrew').exists())

    def test_an_explicit_project_is_not_governed_by_the_plan_of_another_directory(self):
        self.enforce()
        inner = self.root / 'inner'; inner.mkdir()
        event = dict(self.edit('other.py'), cwd=str(inner))
        arguments = [PY, '-X', 'utf8', '-m', 'onecrew', '--project', str(inner), 'hook', 'check']
        done = subprocess.run(arguments, input=json.dumps(event).encode(), capture_output=True, cwd=REPO, timeout=120)
        self.assertEqual(done.returncode, 0)                                              # the plan of the directory above does not govern inner/
        self.assertEqual(self.run_hook('check', self.edit('other.py'))[0], 2)

    def test_stopped_plans_block_edits_and_accepted_plans_do_not(self):
        self.enforce(value=owned_plan(milestones=[milestone(argv=BAD, max_repairs=0)]))
        verdict.run(self.ledger, 'P1', 'M1', self.root)                                          # fails past max_repairs: stopped_with_report
        code, _, err = self.run_hook('check', self.edit('a.txt'))
        self.assertEqual(code, 2); self.assertIn('stopped_with_report', err)

    def stopped(self):
        self.enforce(value=owned_plan(milestones=[milestone(argv=BAD, max_repairs=0)]))
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(plans.show(self.ledger, 'P1')['status'], 'stopped_with_report')

    def test_a_stopped_plan_still_lets_the_ai_read_the_evidence(self):
        self.stopped()
        reads = ['cat .onecrew/active-plan.json', 'git status', 'git status --short', 'git log --oneline -3', 'git diff --stat', 'git show HEAD', 'ls src',
                 'head -5 a.txt', 'grep -n x a.txt | head -3', 'find . -name "*.py"', 'git status; git rev-parse HEAD', 'cd src && ls', 'onecrew plan show P1',
                 'onecrew --project . plan precheck P1', f'{PY} -X utf8 onecrew_cli.py --project . --state-root {self.state} plan show P1',
                 f'{PY} -X utf8 -m onecrew --state-root {self.state} plan show P1', 'git blame a.txt', 'cat "a.txt"']
        for command in reads:
            self.assertEqual(self.run_hook('check', self.shell(command))[0], 0, command)
        for command in ('Get-Content a.txt', 'Get-ChildItem src', 'git status', 'type a.txt', 'dir', 'Get-Content a.txt | Select-String x'):
            self.assertEqual(self.run_hook('check', self.shell(command, 'PowerShell'))[0], 0, command)
        self.assertFalse([v for v in self.violations() if v['event'] == 'blocked'])

    def test_a_stopped_plan_still_blocks_writes_and_side_effects(self):
        self.stopped()
        for tool in ('Edit', 'Write', 'MultiEdit', 'NotebookEdit'):
            code, _, err = self.run_hook('check', self.edit('a.txt', tool))
            self.assertEqual(code, 2, tool); self.assertIn('stopped_with_report', err)
        writes = ['echo x > a.txt', 'echo x >> a.txt', 'cat a.txt > b.txt', 'cat a.txt | tee b.txt', 'cat a | tee b', 'cat a.txt 2>&1 > b.txt', 'git push', 'git push origin main',
                  'git commit -am x', 'git checkout .', 'git reset --hard', 'git clean -fd', 'git add .', 'git diff --output=a.txt', 'git -c core.pager=x log',
                  'rm a.txt', 'find . -delete', 'find . -exec rm {} ;', 'echo hi', 'python run.py', 'sed -i s/a/b/ a.txt', 'cat $(rm a.txt)', 'cat `rm a.txt`',
                  'onecrew plan approve P1 --by owner', 'onecrew plan show P1; rm a.txt', 'onecrew plan show P1 && git push', 'onecrew plan accept P1',
                  f'{PY} evil.py onecrew_cli.py plan show P1', 'rg --pre ./x foo', 'grep x a.txt > b.txt', 'git status\ngit commit -am x', 'cat a.txt &  rm a.txt',
                  f'{PY} -m onecrew_evil plan show P1', 'rg --hostname-bin ./x foo']
        quoting = ['cat " ; rm a.txt ; "', 'echo "x', "cat 'x", 'cat \\" ; rm a.txt ; \\"', "cat \\' ; rm a.txt ; \\'", 'cat "a.txt\\"', 'grep "a|b" a.txt',
                   'onecrew approve plan show P1', 'onecrew plan approve P1 plan show', 'onecrew --project . approve plan show P1']      # a string is not where a command can hide
        for command in writes + quoting + ['cat (Remove-Item a.txt)', 'cat @(Remove-Item a.txt)', 'Get-Content (Set-Content a.txt hi)']:
            self.assertEqual(self.run_hook('check', self.shell(command))[0], 2, command)
        for command in ('grep "a b" a.txt', "grep 'a b' a.txt", 'cat "a.txt" | head -2', 'onecrew --project . --state-root X plan show P1', 'onecrew --project=. plan show P1'):
            self.assertEqual(self.run_hook('check', self.shell(command))[0], 0, command)
        self.assertEqual(self.run_hook('check', self.shell('cat (Remove-Item a.txt)', 'PowerShell'))[0], 2)
        self.assertEqual(self.run_hook('check', self.shell('grep "f(x)" a.txt'))[0], 0)               # a quoted parenthesis is only text
        for command in ('Set-Content a.txt hi', 'Out-File a.txt', 'Remove-Item a.txt', 'Get-Content a.txt | Out-File b.txt', 'git push', 'Add-Content a.txt hi', 'echo x > a.txt'):
            self.assertEqual(self.run_hook('check', self.shell(command, 'PowerShell'))[0], 2, command)
        self.assertEqual(self.run_hook('check', self.tool('Bash', command=7))[0], 2)
        self.assertEqual(self.run_hook('check', self.tool('Bash'))[0], 2)

    def test_a_compound_command_starting_with_an_assignment_is_not_a_path(self):
        self.enforce()
        for command in ('O=/tmp/x; echo hi', 'O=/tmp/x cat a.txt', 'O=/tmp/x && echo hi', 'O=D:/OneCrewRuns/x; cat "$O/receipt.json"'):
            code, _, err = self.run_hook('check', self.shell(command))
            self.assertEqual(code, 0, (command, err))
        self.assertEqual(self.run_hook('check', self.shell('O=/tmp/x; echo hi > other.txt'))[0], 2)      # a write outside owned is still judged by its target

    def test_the_installed_exec_form_works(self):
        from onecrew.v2 import hook_cli
        self.enforce()
        handler = hook_cli.settings(self.root, self.state, REPO)['hooks']['PreToolUse'][0]['hooks'][0]
        done = subprocess.run([handler['command'], *handler['args']], input=json.dumps(self.edit('other.py')).encode(), capture_output=True,
                              cwd=self.temp.name, timeout=120)
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertEqual(handler['onFailure'], 'block')
        others = [h['hooks'][0]['onFailure'] for event, h in ((e, hook_cli.settings(self.root, self.state, REPO)['hooks'][e][0]) for e in ('UserPromptSubmit', 'Stop', 'SessionStart'))]
        self.assertEqual(others, ['continue'] * 3)                                   # a crash in these must not lock the session


class StopPromptSessionTests(HookFixture):
    def stop(self, session='s1', **extra):
        return self.run_hook('stop', dict({'session_id': session, 'cwd': str(self.root), 'hook_event_name': 'Stop', 'stop_hook_active': False}, **extra))

    def test_stop_blocks_until_the_milestone_has_a_verdict_at_most_twice_then_lets_go(self):
        self.enforce()
        for attempt in (1, 2):
            code, out, _ = self.stop()
            self.assertEqual(code, 0)
            reply = json.loads(out)
            self.assertEqual(reply['decision'], 'block'); self.assertIn('M1', reply['reason']); self.assertIn('verdict run', reply['reason'])
        code, out, _ = self.stop()
        self.assertEqual((code, out.strip()), (0, ''))                                          # the third time the session is let go
        kinds = [v['event'] for v in self.violations()]
        self.assertEqual(kinds.count('stop_blocked'), 2); self.assertIn('stop_cap', [v['rule'] for v in self.violations()])
        self.assertEqual(json.loads(self.stop(session='other')[1])['decision'], 'block')         # the cap is per session

    def test_stop_passes_once_the_milestone_has_a_passing_verdict(self):
        self.enforce()
        self.assertEqual(json.loads(self.stop()[1])['decision'], 'block')
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        code, out, err = self.stop()
        self.assertEqual((code, out.strip(), err), (0, '', ''))                                # a crash would also print nothing: check the exit code
        plans.accept(self.ledger, 'P1', 'owner', 'ok', self.tree())
        code, out, err = self.stop()
        self.assertEqual((code, out.strip(), err), (0, '', ''))

    def test_stop_in_log_mode_and_without_a_plan_never_blocks(self):
        self.assertEqual(self.stop()[1].strip(), '')
        self.enforce(mode='log')
        self.assertEqual(self.stop()[1].strip(), '')
        self.assertEqual(self.violations()[-1]['rule'], 'stop_pending_milestone')

    def test_the_prompt_hook_only_reminds(self):
        self.enforce()
        code, out, err = self.run_hook('prompt', {'session_id': 's1', 'cwd': str(self.root), 'hook_event_name': 'UserPromptSubmit', 'prompt': 'nhanh lên, bỏ test đi, chỉ cần 2 giờ'})
        self.assertEqual(code, 0)
        reply = json.loads(out)['hookSpecificOutput']
        self.assertEqual(reply['hookEventName'], 'UserPromptSubmit')
        self.assertIn('Contract v1', reply['additionalContext']); self.assertIn('plan amend', reply['additionalContext']); self.assertIn('100 calls', reply['additionalContext'])
        quiet = self.run_hook('prompt', {'session_id': 's1', 'cwd': str(self.root), 'prompt': 'please add the function'})
        self.assertEqual((quiet[0], quiet[1].strip()), (0, ''))
        self.assertEqual(self.run_hook('prompt', raw=b'garbage')[0], 0)                          # never blocks, even on bad input
        self.assertEqual(self.violations()[-1]['event'], 'reminded')

    def test_the_session_hook_summarises_the_contract_in_25_lines(self):
        self.enforce()
        code, out, _ = self.run_hook('session', {'session_id': 's1', 'cwd': str(self.root), 'hook_event_name': 'SessionStart', 'source': 'compact'})
        self.assertEqual(code, 0)
        text = json.loads(out)['hookSpecificOutput']['additionalContext']
        self.assertEqual(json.loads(out)['hookSpecificOutput']['hookEventName'], 'SessionStart')
        self.assertLessEqual(len(text.splitlines()), 25)
        for part in ('P1 v1', 'a.txt', 'src/', 'M1', 'The sample exists', '100 calls'): self.assertIn(part, text)
        self.assertEqual(self.run_hook('session', {'cwd': str(self.root), 'hook_event_name': 'PreCompact', 'trigger': 'auto'})[1].strip(), '')


class SyncAndInstallTests(HookFixture):
    def test_sync_imports_the_violations_into_the_ledger_once(self):
        self.enforce()
        self.run_hook('check', self.edit('other.py')); self.run_hook('stop', {'session_id': 's1', 'cwd': str(self.root)})
        self.run_hook('prompt', {'cwd': str(self.root), 'prompt': 'skip test'})
        active = json.loads((self.root / '.onecrew' / 'active-plan.json').read_text(encoding='utf-8'))
        import onecrew.v2.active_plan as active_plan
        active_plan.set_mode(self.ledger, 'log'); active_plan.export(self.ledger, 'P1')
        self.run_hook('check', self.edit('other2.py'))
        code, out, _ = self.run_hook('sync')
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)['imported'], 4)
        self.assertEqual(json.loads(self.run_hook('sync')[1])['imported'], 0)
        kinds = [k for k in self.kinds() if k.startswith('hook.')]
        self.assertEqual(sorted(kinds), ['hook.blocked', 'hook.logged', 'hook.reminded', 'hook.stop_blocked'])
        self.assertEqual(active['plan'], 'P1')

    def test_install_print_gives_the_settings_and_changes_nothing(self):
        self.approved('P1', owned_plan())
        before = sorted(str(p) for p in self.root.rglob('*') if '.git' not in p.parts)
        code, out, _ = self.run_hook('install', extra=['--print'])
        self.assertEqual(code, 0)
        config = json.loads(out)
        self.assertEqual(sorted(config['hooks']), ['PreToolUse', 'SessionStart', 'Stop', 'UserPromptSubmit'])
        self.assertEqual(config['hooks']['PreToolUse'][0]['matcher'], 'Edit|Write|MultiEdit|NotebookEdit|Bash|PowerShell')
        deny = config['permissions']['deny']
        for needle in ('**/plans/**', '**/*.sqlite*', 'plan approve', 'plan accept', 'plan enforce', 'verdict record', 'active-plan.json', 'settings'):
            self.assertTrue(any(needle in rule for rule in deny), needle)
        self.assertFalse((self.root / '.claude').exists())
        self.assertFalse(any('.onecrew/**' in rule for rule in deny))        # .onecrew/scratch/ must stay writable (found by the claude -p run)
        self.assertEqual(sorted(str(p) for p in self.root.rglob('*') if '.git' not in p.parts), before)

    def test_only_the_owner_changes_the_hook_mode(self):
        self.approved('P1', owned_plan())
        self.assertEqual(self.run_hook('mode', extra=['enforce', '--by', 'claude', '--reference', 'x'])[0], 2)
        self.assertEqual(self.run_hook('mode', extra=['enforce', '--by', 'owner', '--reference', 'x'], env={'ONECREW_ACTOR': 'claude'})[0], 2)
        code, out, _ = self.run_hook('mode', extra=['enforce', '--by', 'owner', '--reference', 'x'], env={'ONECREW_ACTOR': 'user'})
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads((self.root / '.onecrew' / 'active-plan.json').read_text(encoding='utf-8'))['mode'], 'enforce')

class ItemBudgetTests(Fixture):
    """DESIGN-MVP section 4: per-item budgets, repair reserve, tiers, one question, attention shared with plan_stopped."""

    def items(self, max_calls=20, tick=('S1',), **extra):
        value = plan_json(items=[{'id': 'I1', 'title': 'First must', 'tier': 'must', 'milestone': 'M1'}, {'id': 'I2', 'title': 'Second must', 'tier': 'must'},
                                 {'id': 'S1', 'title': 'Ticked should', 'tier': 'should'}, {'id': 'S2', 'title': 'Unticked should', 'tier': 'should'},
                                 {'id': 'W1', 'title': 'Never', 'tier': 'wont'}], budget={'max_calls': max_calls, 'time': 30}, **extra)
        gate.set_enforced(self.ledger, True, 'owner', 'test')
        self.propose('job1', value)
        plans.approve(self.ledger, 'job1', 'owner', 'ref', tick=list(tick))
        task = submit(self.ledger, None, 'job1', mode='work', provider='kiro', model='claude-sonnet-5',
                      contract=dict(l1.DispatchGateTests.WORK), max_calls=max_calls, max_seconds=1800)
        migrate(self.ledger)
        self.control = Control(self.ledger)
        self.task = task['id']
        self.execution = self.control.configure(task['id'], task['revision'], {'mode': 'test'})
        self.count = 0

    def call(self, item=None):
        self.count += 1
        operation = {'stage': 'work'} if item is None else {'stage': 'work', 'item': item}
        attempt = self.control.reserve(self.task, self.execution['revision'], f'k{self.count}', operation)
        self.control.finish(attempt['id'], attempt['generation'], {'fixture': True})
        return attempt

    def anchor(self):
        with self.ledger.transaction() as conn:
            return plans.derive(self.ledger, conn, 'job1')['task_id']

    def requests(self):
        return [r for r in self.ledger.requests(self.anchor()) if r['question']['action']['type'] == 'v2.item_budget']

    def test_wont_unticked_should_and_unknown_items_never_run(self):
        self.items()
        for item, word in (('W1', 'wont'), ('S2', 'did not tick'), ('Z9', 'not in the approved plan')):
            with self.assertRaises(LedgerError) as caught: self.call(item)
            self.assertIn(word, str(caught.exception))
        self.call('S1')                                                             # ticked at approval: it runs
        self.assertEqual(self.control.status(self.task)['used_calls'], 1)           # the refused calls were never reserved

    def test_a_must_item_at_its_cap_stops_and_asks_one_question_other_items_continue(self):
        self.items()                                                                # 20 calls, reserve 4, 3 runnable items: 5 each
        for _ in range(5): self.call('I1')
        with self.assertRaises(LedgerError) as caught: self.call('I1')
        self.assertIn('used its 5 calls', str(caught.exception))
        self.assertEqual(self.requests(), [])                                       # spooled until the next plan/verdict command
        gate.sync_refusals(self.ledger)
        asked = self.requests()
        self.assertEqual(len(asked), 1)
        self.assertEqual(asked[0]['question']['action']['parameters']['item'], 'I1')
        with self.assertRaises(LedgerError): self.call('I1')                        # asking again does not ask twice
        gate.sync_refusals(self.ledger); gate.sync_refusals(self.ledger)
        self.assertEqual(len(self.requests()), 1)
        self.call('I2')                                                             # independent items continue
        refused = [e for e in self.ledger.events(self.task) if e['kind'] == 'dispatch.refused_no_plan']
        self.assertEqual(len(refused), 2)

    def test_a_should_item_at_its_cap_just_stops_without_a_question(self):
        self.items()
        for _ in range(5): self.call('S1')
        with self.assertRaises(LedgerError) as caught: self.call('S1')
        self.assertIn('next item starts', str(caught.exception))
        gate.sync_refusals(self.ledger)
        self.assertEqual(self.requests(), [])

    def test_the_repair_reserve_is_kept_for_must_items(self):
        self.items(max_calls=14)                                                    # reserve 3: should items stop at 11 calls spent
        for _ in range(11): self.call()                                             # unassigned calls count against the total only
        with self.assertRaises(LedgerError) as caught: self.call('S1')
        self.assertIn('repair reserve (3)', str(caught.exception))
        self.call('I1')                                                             # a must item may still use it

    def test_item_questions_share_the_attention_limit_with_plan_stops(self):
        self.items()
        for _ in range(5):
            self.call('I1'); self.call('I2')
        for item in ('I1', 'I2'):
            with self.assertRaises(LedgerError): self.call(item)
        gate.sync_refusals(self.ledger)
        self.assertEqual(len(self.requests()), 1)                                   # attention.questions = 1
        self.assertEqual([e['kind'] for e in self.ledger.events(self.anchor())].count('attention.exceeded'), 1)

    def test_calls_without_an_item_and_a_plan_gate_that_is_off_are_unchanged(self):
        self.items()
        self.call(); self.call()
        free = submit(self.ledger, None, 'free', mode='work', provider='kiro', model='claude-sonnet-5', contract=dict(l1.DispatchGateTests.WORK), max_calls=5)
        gate.set_enforced(self.ledger, False, 'owner', 'off')
        control = Control(self.ledger); execution = control.configure(free['id'], free['revision'], {'mode': 'test'})
        attempt = control.reserve(free['id'], execution['revision'], 'k', {'stage': 'work', 'item': 'W1'})      # the gate is off: v1 as before
        self.assertEqual(attempt['status'], 'reserved')


class ChangeRequestTests(Fixture):
    """CREQ with a limit: a delta, a reason of at most 200 characters, at most 2, the third stops the plan."""

    def setUp(self):
        super().setUp()
        import tests.test_solution_gate as sg
        from onecrew import conversations as c
        self.binding = sg.approve_fixture(self.ledger)
        self.cid = c.show_solution(self.ledger, self.binding['solution_id'])['conversation']

    def job(self):
        self.approved('P1', plan_json())
        gate.set_enforced(self.ledger, True, 'owner', 'test')
        return submit(self.ledger, 'Fix arithmetic', 'P1', mode='change', provider='claude', model='sonnet', image='sha256:' + 'a' * 64, **self.binding)

    def ask(self, n, **extra):
        values = dict(text=f'Change {n}?', reason='The contract cannot be met as written.', affected_tasks=[self.task['id']], source='claude',
                      delta={'budget_delta': 10})
        values.update(extra)
        return solution_gate.question(self.ledger, self.cid, f'q{n}', **values)

    def test_the_limit_the_delta_and_the_reason_length(self):
        self.task = self.job()
        with self.assertRaises(LedgerError): self.ask(1, delta=None)                      # a change request carries a delta
        with self.assertRaises(LedgerError): self.ask(1, delta={'rename': 'x'})
        with self.assertRaises(LedgerError): self.ask(1, reason='r' * 201)                # at most 200 characters
        self.assertEqual(self.ask(1)['payload']['delta'], {'budget_delta': 10})
        self.assertEqual(self.ask(2, delta={'add': ['tests']})['payload']['delta'], {'add': ['tests']})
        with self.assertRaises(LedgerError) as caught: self.ask(3)                       # the third is refused ...
        self.assertIn('max_changes', str(caught.exception))
        self.assertEqual(plans.show(self.ledger, 'P1')['status'], 'stopped_with_report')  # ... and stops the plan
        self.assertEqual(plans.show(self.ledger, 'P1')['questions'][0]['state'], 'pending')
        with self.assertRaises(LedgerError): self.ask(4)

    def test_without_the_gate_a_change_request_is_as_in_v1(self):
        task = submit(self.ledger, 'Fix arithmetic', 'job', mode='change', provider='claude', model='sonnet', image='sha256:' + 'a' * 64, **self.binding)
        for n in range(4):
            solution_gate.question(self.ledger, self.cid, f'q{n}', f'Change {n}?', 'r' * 300, [task['id']], 'claude')


class ReviewOneTests(HookFixture):
    """Opus review 1 of L2 (eaf4438): B1 and F1-F6, each with the way around it that the review found."""

    # ---- B1 ---------------------------------------------------------------------------------------------------------
    def test_b1_deleting_dot_onecrew_does_not_end_enforcement(self):
        self.enforce()
        for command in ('ri -r -fo .onecrew', 'cmd //c rd /s /q .onecrew', 'python -c "import shutil; shutil.rmtree(\'.onecrew\')"'):   # H27, H28, H29
            self.assertEqual(self.run_hook('check', self.shell(command, 'PowerShell'))[0], 2, command)
        import shutil
        shutil.rmtree(self.root / '.onecrew')                                                  # the AI got round the shell rule anyway (H29)
        code, _, err = self.run_hook('check', self.edit('README.md'))                          # H31: used to be exit 0
        self.assertEqual(code, 2); self.assertIn('not in the owned scope', err)
        self.assertEqual(self.run_hook('check', self.edit('src/ok.py'))[0], 0)                  # the state-root copy still says what is allowed
        self.assertTrue((self.root / '.onecrew' / 'active-plan.json').exists())                 # and the project copy is put back
        self.assertIn('plan_restored', [v['rule'] for v in self.violations()])
        self.assertEqual(self.run_hook('check', self.shell('git push'))[0], 2)
        self.assertTrue(self.violations())                                                     # and the record goes in again

    def test_b1_a_project_copy_that_disagrees_with_the_state_root_is_tampered_with(self):
        self.enforce()
        path = self.root / '.onecrew' / 'active-plan.json'
        document = json.loads(path.read_text(encoding='utf-8')); document['mode'] = 'log'; document['owned'] = ['**']
        path.write_text(json.dumps(document), encoding='utf-8')
        code, _, err = self.run_hook('check', self.edit('README.md'))
        self.assertEqual(code, 2); self.assertIn('differs from the state-root copy', err)

    def test_b1_log_mode_still_passes_when_the_project_copy_is_gone_and_other_projects_are_not_touched(self):
        self.enforce(mode='log')
        import shutil
        shutil.rmtree(self.root / '.onecrew')
        self.assertEqual(self.run_hook('check', self.edit('README.md'))[0], 0)
        other = Path(self.temp.name) / 'other'; other.mkdir()
        arguments = [PY, '-X', 'utf8', '-m', 'onecrew', '--project', str(other), '--state-root', str(self.state), 'hook', 'check']
        done = subprocess.run(arguments, input=json.dumps(self.edit('x.py')).encode(), capture_output=True, cwd=REPO, timeout=120)
        self.assertEqual(done.returncode, 0)                                                   # a plan of another project in the same state root does not govern it

    def test_b1_what_the_install_prints_names_the_state_root(self):
        from onecrew.v2 import hook_cli
        config = hook_cli.settings(self.root, self.state, REPO)
        for entries in config['hooks'].values():
            args = entries[0]['hooks'][0]['args']
            self.assertEqual(args[args.index('--state-root') + 1], str(self.state))

    # ---- F1 ---------------------------------------------------------------------------------------------------------
    def test_f1_the_callers_environment_does_not_reach_the_verifier(self):                      # C8-v1
        (Path(self.temp.name) / 'poison').mkdir()
        (Path(self.temp.name) / 'poison' / 'sitecustomize.py').write_text('import os\nos._exit(0)\n')    # forces exit 0 in any python that sees it
        self.approved(value=plan_json(milestones=[milestone(argv=BAD)]))
        with patch.dict(os.environ, {'PYTHONPATH': str(Path(self.temp.name) / 'poison'), 'GIT_DIR': str(self.root / 'nope')}):
            view = verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual((view['milestones'][0]['state'], view['milestones'][0]['last_verdict']['result']), ('failed', 'fail'))

    def test_f1_export_ignore_does_not_change_the_tree_that_is_checked(self):                    # C8-v2
        (self.root / 'failing.flag').write_text('x\n'); (self.root / '.gitattributes').write_text('failing.flag export-ignore\n')
        self.git('add', '.'); self.git('commit', '-q', '-m', 'flag')
        check = 'import os, sys; sys.exit(1 if os.path.exists("failing.flag") else 0)'
        self.approved(value=plan_json(milestones=[milestone(argv=[PY, '-c', check])]))
        self.assertEqual(subprocess.run([PY, '-c', check], cwd=self.root).returncode, 1)         # on the real tree it fails
        view = verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(view['milestones'][0]['state'], 'failed')                              # git archive would have said passed

    def test_f1_a_git_environment_in_the_caller_is_a_clear_refusal_not_a_crash(self):
        decoy = self.root / 'decoy'; subprocess.check_call(['git', 'clone', '-q', str(self.root), str(decoy)])
        self.approved()
        with patch.dict(os.environ, {'GIT_DIR': str(decoy / '.git'), 'GIT_WORK_TREE': str(decoy)}):   # C6-v2
            view = verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(view['milestones'][0]['last_verdict']['artifact_sha'], self.tree())    # the project's tree, whatever the caller exported

    # ---- F2 ---------------------------------------------------------------------------------------------------------
    def test_f2_the_owners_verbs_are_refused_in_an_ai_tool_session(self):
        from onecrew import cli
        self.propose()
        base = ['--project', str(self.root), '--state-root', str(self.state)]
        with patch.dict(os.environ, {'CLAUDE_CODE_CHILD_SESSION': '1'}):
            for argv in (['plan', 'approve', 'P1', '--by', 'owner', '--reference', 'x'], ['plan', 'accept', 'P1', '--by', 'owner', '--reference', 'x', '--artifact-sha', 'a' * 40],
                         ['plan', 'enforce', 'off', '--by', 'owner', '--reference', 'x'], ['hook', 'mode', 'log', '--by', 'owner', '--reference', 'x'],
                         ['verdict', 'record', '--plan', 'P1', '--milestone', 'M1', '--result', 'pass', '--by', 'owner', '--receipt', 'a' * 64, '--artifact-sha', 'a' * 40]):
                out = io.StringIO()
                with contextlib.redirect_stdout(out): code = cli.main(base + argv)
                self.assertEqual(code, 2, argv); self.assertIn('AI tool session', out.getvalue())
            with self.assertRaises(LedgerError): gate.set_enforced(self.ledger, False, 'owner', 'x')
        self.assertEqual(plans.show(self.ledger, 'P1')['status'], 'proposed')
        with patch.dict(os.environ, {'CLAUDECODE': '1'}):                                           # the owner's IDE terminal has CLAUDECODE but no CHILD_SESSION
            out = io.StringIO()
            with contextlib.redirect_stdout(out): code = cli.main(base + ['plan', 'approve', 'P1', '--by', 'owner', '--reference', 'x'])
        self.assertEqual(code, 0, out.getvalue())

    def test_f2_the_deny_rules_cover_the_way_the_machine_really_calls_onecrew(self):
        from onecrew.v2 import hook_cli
        deny = hook_cli.settings(self.root, self.state, REPO)['permissions']['deny']
        for verb in ('plan approve', 'plan accept', 'plan enforce', 'verdict record', 'hook mode'):
            for tool in ('Bash', 'PowerShell'): self.assertIn(f'{tool}(*{verb}*)', deny)       # leading wildcard: venv python, -X utf8, onecrew.cmd
        for rule in ('Bash(git * push*)', 'PowerShell(git * push*)', 'Bash(git config * alias.*)'): self.assertIn(rule, deny)

    # ---- F4 ---------------------------------------------------------------------------------------------------------
    def test_f4_only_the_memory_folder_of_this_project_is_writable_under_dot_claude(self):
        from onecrew.v2 import active_plan
        self.enforce()
        home = Path.home() / '.claude'
        for target in (home / 'CLAUDE.md', home / 'agents' / 'x.md', home / 'commands' / 'y.md', home / 'settings.json', home / 'projects' / 'other' / 'memory' / 'a.md'):
            self.assertEqual(self.run_hook('check', self.tool('Write', file_path=str(target)))[0], 2, str(target))
        mine = Path(active_plan.memory_dir(self.root)) / 'note.md'
        self.assertEqual(self.run_hook('check', self.tool('Write', file_path=str(mine)))[0], 0, str(mine))

    # ---- F5 ---------------------------------------------------------------------------------------------------------
    def test_f5_every_kind_counts_towards_the_limit_and_needs_a_short_reason(self):
        import tests.test_solution_gate as sg
        from onecrew import conversations as c
        binding = sg.approve_fixture(self.ledger)
        cid = c.show_solution(self.ledger, binding['solution_id'])['conversation']
        self.approved('P1', plan_json())
        gate.set_enforced(self.ledger, True, 'owner', 'test')
        task = submit(self.ledger, 'Fix arithmetic', 'P1', mode='change', provider='claude', model='sonnet', image='sha256:' + 'a' * 64, **binding)
        ask = lambda n, kind, **extra: solution_gate.question(self.ledger, cid, f'k{n}', f'Q{n}?', extra.pop('reason', 'short reason'), [task['id']], 'claude', kind, **extra)
        with self.assertRaises(LedgerError): ask(0, 'technical_review', reason='r' * 300)             # 200 characters for every kind
        ask(1, 'technical_review'); ask(2, 'clarification')
        for n, kind in ((3, 'technical_review'), (4, 'clarification'), (5, 'solution_change')):
            with self.assertRaises(LedgerError) as caught: ask(n, kind, delta={'add': ['x']})
            self.assertIn('max_changes', str(caught.exception))
        self.assertEqual(plans.show(self.ledger, 'P1')['status'], 'stopped_with_report')

    # ---- F3 / F6 ----------------------------------------------------------------------------------------------------
    def test_f6_powershell_aliases_and_dotnet_writes_outside_owned_are_blocked(self):
        self.enforce()
        for command in ('sc README.md x', 'ac README.md x', '"x" | Tee-Object -FilePath README.md', 'x | Tee-Object README.md', '[IO.File]::WriteAllText("README.md","x")',
                        '[System.IO.File]::AppendAllText(\'README.md\', "x")', 'ni README.md', 'ni -Path README.md -ItemType File', 'ri README.md', 'rd other', 'mi a.txt README.md',
                        'cpi a.txt -Destination README.md', 'Export-Csv -Path README.md', 'rni a.txt b.txt'):
            self.assertEqual(self.run_hook('check', self.shell(command, 'PowerShell'))[0], 2, command)
        for command in ('sc a.txt x', 'ac src/new.py "x y"', '[IO.File]::WriteAllText("src/x.py","x")', 'x | Tee-Object src/log.txt', 'ni src/new.txt', 'ri src/old.py',
                        'Get-Content a.txt', 'ls', 'sc.exe query'.replace('sc.exe query', 'Get-ChildItem src')):
            self.assertEqual(self.run_hook('check', self.shell(command, 'PowerShell'))[0], 0, command)

    # ---- F11 (documented behaviour) ---------------------------------------------------------------------------------
    def test_f11_the_stop_counter_restarts_after_it_lets_go(self):
        self.enforce()
        stop = {'session_id': 'sx', 'cwd': str(self.root), 'hook_event_name': 'Stop'}
        answers = [bool(self.run_hook('stop', stop)[1].strip()) for _ in range(4)]
        self.assertEqual(answers, [True, True, False, True])                                        # "2 blocks per stop attempt", not per session


if __name__ == '__main__':
    unittest.main()
