"""OneCrew 2.2.0.dev3 (v22-trust-fixes): one test per defect that the independent review found at 8383446. Each fails on that commit and passes here.

P0.1 the portable hook finds its plan without the project copy and stops at the repository boundary    P0.2 the reviewer sees what Git tracks (staged files
included) and a file it cannot see is not a pass    P0.3 the diff is cut from one recorded tree, so a change made during the review is not a pass    P0.4 nothing
is neutral unless the contract says so    P0.5 `plan report` reads the same milestone views as `plan show`    P0.6 a carried verdict needs the same covers and
the same text of every covered output, and the independence rule for the new revision    P0.7 the hooks print UTF-8 and `init` keeps other tools' handlers
D3 a tree id read from a receipt is hex before git sees it, and a plan without a usable base gives an inconclusive receipt.
No test calls a model: reviewer.call is replaced.
"""
import argparse
import contextlib
import io
import json
import os
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

    def document(self, project, mode='enforce', owned=('a.txt',)):
        return {'plan': 'p', 'revision': 1, 'plan_sha': 'x', 'status': 'approved', 'mode': mode, 'owned': list(owned), 'non_goals': [], 'bash_deny': [], 'protected': [],
                'scratch': [], 'title': 'Hợp đồng thử tiếng Việt', 'output': ['Tệp mẫu tồn tại'], 'budget': {'max_calls': 5, 'time': 30},
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

    def check(self, tool, target, project=None):
        event = json.dumps({'tool_name': tool, 'tool_input': {'file_path': str(target)}, 'cwd': str(project or self.repo), 'session_id': 's'})
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

    def test_the_plan_of_another_project_does_not_govern(self):
        other = self.base / 'other'; (other / '.git').mkdir(parents=True)
        self.project_copy(other)
        self.assertEqual(self.governing(other)[0]['plan'], 'p')
        self.assertIsNone(self.governing(self.repo, cwd=other)[0])             # the project is CLAUDE_PROJECT_DIR; the cwd of the event is not another project to ask
        self.config(self.repo); self.state_copy(other)
        self.assertIsNone(self.governing(self.repo)[0])                        # a state-root copy names its own project, not this one

    def test_an_explicit_project_is_still_searched_in_itself_only(self):
        self.project_copy(self.repo)
        sub = self.repo / 'sub'; sub.mkdir()
        args = argparse.Namespace(project=sub, state_root=None)
        self.assertEqual(hook_cli.locate(args, {}), (None, sub, None))


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

    def test_a_path_the_diff_does_not_name_is_reported(self):
        self.start(); self.commit('a.txt', 'one\ntwo\n'); self.commit('data.bin', 'binary-ish\n')
        tracked = command.tracked_tree(self.root)
        base = [p for k, p in self.events() if k == 'plan.approved'][0]['base_tracked']
        diff = verdict.diff(self.ledger, 'P1', 'M1')
        self.assertEqual(reviewer.not_shown(self.root, base, tracked, diff), [])
        self.assertEqual(reviewer.not_shown(self.root, base, tracked, diff.replace('data.bin', 'x')), ['data.bin'])


class ReviewerDiffIsOneTree(ReviewerBase):
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
        with patch.object(plans, '_base_tracked', return_value=None), patch.object(plans, '_base_artifact', return_value=None): self.start()
        self.commit('a.txt', 'one\ntwo\n')
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        receipt = self.last()
        self.assertEqual((receipt['result'], receipt['calls'], self.prompts), ('inconclusive', 0, []))
        self.assertIn('no tracked-only base tree', receipt['error'])


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
        self.assertIn('Reviewer ghi chú', text); self.assertIn('OUTSIDE-NOTE-7731', text)

    def test_a_pass_the_artifact_has_left_is_stale_in_the_report_too(self):
        self.approved(); verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertIn('O1 ĐẠT', self.text())
        self.commit('a.txt', 'one\nmore\n')
        shown = self.view()
        self.assertEqual((shown['state'], shown.get('stale')), ('pending', True))
        text = self.text()
        self.assertIn('O1 CHƯA', text); self.assertNotIn('O1 ĐẠT', text)

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
