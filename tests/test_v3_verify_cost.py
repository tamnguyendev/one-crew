"""OneCrew 2.2.0.dev2 (batch 1): cheaper verification without touching the six invariants.

* a verdict is carried over to a new revision when the milestone (title + verifier) is byte-identical and the artifact is the same, or differs only
  in scope.neutral paths (command milestones); a reviewer milestone never crosses a neutral difference;
* the reviewer is sent the diff of TRACKED files only, from the artifact its own milestone last passed on; `verdict diff` / `verdict artifact`;
* `plan lint`: criterion_literal_present, criterion_no_fail_clause, criterion_vs_non_goal (and --ack-criteria), unknowns_missing;
* the report ends with the reviewer's remarks outside the criteria.
No test calls a model: reviewer.call is replaced.
"""
import contextlib
import io
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.v2 import contract as contracts, lint, plan as plans, plan_cli, report, step0, verdict
from onecrew.v2.verifiers import command, reviewer
from tests.test_v2_l1 import OK, Fixture, milestone, plan_json


def review_milestone(mid='M1', **config):
    return {'id': mid, 'title': 'Review ' + mid, 'covers': ['O1'], 'verifier': {'type': 'reviewer', 'config': dict(
        {'provider': 'claude', 'model': 'claude-haiku-5-5', 'max_minutes': 5,
         'criteria': [{'id': 'R1', 'question': 'Does the diff keep a.txt readable? fail if a.txt was deleted.'}]}, **config)}}


def passing(outside=()):
    return json.dumps({'criteria': [{'id': 'R1', 'verdict': 'pass', 'evidence': [{'file': 'a.txt', 'line': 1, 'note': 'seen'}]}], 'outside_criteria': list(outside)})


class Cli:
    """The `onecrew` command line against the fixture's project and ledger."""

    def cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = plan_cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), *argv])
        return code, out.getvalue()


class Carry(Fixture):
    def two(self, **extra):
        return plan_json(milestones=[milestone('M1'), milestone('M2')], **extra)

    def view(self, mid, name='P1'):
        return next(m for m in plans.show(self.ledger, name)['milestones'] if m['id'] == mid)

    def reword_m2(self, title='Milestone M2 reworded', **extra):
        return plan_json(milestones=[milestone('M1'), milestone('M2', title=title)], **extra)

    def test_an_unchanged_milestone_is_carried_over_a_wording_amendment_and_the_next_one_runs_alone(self):
        self.approved(value=self.two())
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        before = self.view('M1')['last_verdict']['artifact_sha']
        plans.amend(self.ledger, 'P1', self.reword_m2(), 'M2 wording', 'claude')
        self.assertEqual(self.view('M1')['state'], 'pending')
        plans.approve(self.ledger, 'P1', 'owner', 'said yes')
        m1 = self.view('M1')
        self.assertEqual((m1['state'], m1['carried_from'], m1['last_verdict']['artifact_sha'], m1['runs']), ('passed', 1, before, 0))
        self.assertNotIn('neutral_diff', m1)
        self.assertEqual(self.view('M2')['state'], 'pending')
        done = verdict.run(self.ledger, 'P1', 'M2', self.root)
        self.assertEqual([m['state'] for m in done['milestones']], ['passed', 'passed'])
        self.assertEqual(plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())['status'], 'accepted')
        accepted = [json.loads(p) if isinstance(p, str) else p for k, p in self.events() if k == 'plan.accepted'][0]
        self.assertEqual(accepted['carried'], {'M1': 1})

    def test_accept_reads_a_commit_as_its_tree(self):
        self.approved(value=plan_json())
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        accepted = plans.accept(self.ledger, 'P1', 'owner', 'ref', self.git('rev-parse', 'HEAD'))
        self.assertEqual(accepted['status'], 'accepted')
        event = [json.loads(p) if isinstance(p, str) else p for k, p in self.events() if k == 'plan.accepted'][0]
        self.assertEqual(event['artifact_sha'], self.tree())
        with self.assertRaises(LedgerError): plans.accept(self.ledger, 'P1', 'owner', 'ref', 'zzzz')

    def test_accept_takes_only_a_hex_id_and_never_hands_anything_else_to_git(self):
        self.approved(value=plan_json())
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        (self.root / 'a.txt').write_text('changed\n'); (self.root / 'docs').mkdir(); (self.root / 'docs' / 'r.md').write_text('# r\n'); self.git('add', '.'); self.git('commit', '-q', '-m', 'real change')
        for bad in ('--relative=docs', '--stat', '-p', '', None, 'HEAD', 'main', self.tree().upper(), 'zzzz', '1' * 39):
            with self.subTest(bad=bad):
                with self.assertRaises(LedgerError) as caught: plans.accept(self.ledger, 'P1', 'owner', 'ref', bad)
                self.assertIn('hex', str(caught.exception))
        self.assertNotIn('plan.accepted', self.kinds())
        with self.assertRaises(LedgerError): command.changed_paths(self.root, '--relative=docs', self.tree())
        with self.assertRaises(LedgerError): command.changed_paths(self.root, self.tree(), '--relative=docs')
        with self.assertRaises(LedgerError): plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())

    def test_a_changed_title_or_verifier_is_not_carried(self):
        for changed in (plan_json(milestones=[milestone('M1', title='Another title'), milestone('M2')]),
                        plan_json(milestones=[milestone('M1', argv=OK + ['again']), milestone('M2')])):
            with self.subTest(changed=changed['milestones'][0]):
                self.setUp()
                self.approved(value=self.two())
                verdict.run(self.ledger, 'P1', 'M1', self.root)
                plans.amend(self.ledger, 'P1', changed, 'M1 changed', 'claude'); plans.approve(self.ledger, 'P1', 'owner', 'ref')
                self.assertEqual(self.view('M1')['state'], 'pending')
                with self.assertRaises(LedgerError): plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())

    def test_a_carried_milestone_is_pending_again_once_the_artifact_moves(self):
        self.approved(value=self.two())
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        plans.amend(self.ledger, 'P1', self.reword_m2(), 'r2', 'claude'); plans.approve(self.ledger, 'P1', 'owner', 'ref')
        (self.root / 'a.txt').write_text('one\nmore\n'); self.git('add', '.'); self.git('commit', '-q', '-m', 'work')
        self.assertEqual(self.view('M1')['state'], 'pending')
        plans.amend(self.ledger, 'P1', self.reword_m2('Milestone M2 reworded twice'), 'r3', 'claude'); plans.approve(self.ledger, 'P1', 'owner', 'ref')
        self.assertEqual(self.view('M1')['state'], 'pending')

    def test_a_pass_on_another_artifact_is_stale_and_acceptance_says_so(self):
        self.approved(value=self.two())
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        (self.root / 'a.txt').write_text('one\nmore\n'); self.git('add', '.'); self.git('commit', '-q', '-m', 'work')
        m1 = self.view('M1')
        self.assertEqual((m1['state'], m1.get('stale')), ('pending', True))
        verdict.run(self.ledger, 'P1', 'M2', self.root)
        with self.assertRaises(LedgerError) as caught: plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())
        self.assertIn('exactly that artifact', str(caught.exception))
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())['status'], 'accepted')

    def test_a_commit_that_touches_only_neutral_paths_keeps_a_command_milestone_passed(self):
        value = plan_json(scope={'owned': ['a.txt'], 'neutral': ['docs/**']})
        self.approved(value=value)
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        before = self.tree()
        (self.root / 'docs').mkdir(); (self.root / 'docs' / 'r.md').write_text('# r\n'); self.git('add', '.'); self.git('commit', '-q', '-m', 'docs')
        self.assertNotEqual(self.tree(), before)
        m1 = self.view('M1')
        self.assertEqual((m1['state'], m1['carried_from'], m1.get('neutral_diff'), m1['last_verdict']['artifact_sha']), ('passed', 1, True, before))
        self.assertEqual(plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())['status'], 'accepted')

    def test_a_commit_that_touches_a_neutral_and_a_real_path_does_not(self):
        self.approved(value=plan_json(scope={'owned': ['a.txt'], 'neutral': ['docs/**']}))
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        (self.root / 'docs').mkdir(); (self.root / 'docs' / 'r.md').write_text('# r\n'); (self.root / 'a.txt').write_text('two\n')
        self.git('add', '.'); self.git('commit', '-q', '-m', 'both')
        self.assertEqual(self.view('M1')['state'], 'pending')

    def test_the_default_neutral_paths_are_read_not_written(self):
        stored = contracts.validate(plan_json())
        self.assertEqual(stored['scope'], {'owned': ['a.txt']})
        self.assertEqual(contracts.neutral_globs(stored), [])
        self.assertEqual(contracts.neutral_globs(contracts.validate(plan_json(scope={'owned': ['a.txt'], 'neutral': []}))), [])
        self.approved(value=plan_json())
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        (self.root / 'NOTES.md').write_text('notes\n'); (self.root / 'CHANGELOG').write_text('x\n'); self.git('add', '.'); self.git('commit', '-q', '-m', 'notes')
        self.assertNotEqual(self.view('M1')['state'], 'passed')
        with self.assertRaises(LedgerError): plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())

    def test_neutral_globs_do_not_cross_a_slash_except_double_star(self):
        default = ['docs/**', '*.md', 'CHANGELOG*']
        for path in ('README.md', 'docs/a.txt', 'docs/deep/er/b.png', 'CHANGELOG', 'CHANGELOG.md'):
            self.assertTrue(contracts.neutral_match(path, default), path)
        for path in ('onecrew/templates/owner-rules.vi.md', 'src/notes.md', 'a.txt', 'docsx/a.txt', 'sub/CHANGELOG.md'):
            self.assertFalse(contracts.neutral_match(path, default), path)
        self.assertTrue(contracts.neutral_match('src/notes.md', ['**/*.md'])); self.assertTrue(contracts.neutral_match('notes.md', ['**/*.md']))
        self.assertTrue(contracts.neutral_match('a/b.txt', ['a/?.txt'])); self.assertFalse(contracts.neutral_match('a/b/c.txt', ['a/*.txt']))

    def test_a_markdown_file_below_the_top_is_not_neutral_by_default(self):
        self.approved(value=plan_json())
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        (self.root / 'onecrew').mkdir(); (self.root / 'onecrew' / 'x.md').write_text('shipped text\n'); self.git('add', '.'); self.git('commit', '-q', '-m', 'template')
        self.assertEqual(self.view('M1')['state'], 'pending')

    def test_scope_neutral_is_validated(self):
        for bad in (['x'] * 21, ['y' * 301], 'docs/**', [1]):
            with self.assertRaises(LedgerError, msg=bad): contracts.validate(plan_json(scope={'owned': ['a.txt'], 'neutral': bad}))
        with self.assertRaises(LedgerError): contracts.validate(plan_json(scope={'owned': ['a.txt'], 'other': []}))
        self.assertEqual(contracts.validate(plan_json(scope={'owned': ['a.txt'], 'neutral': ['x'] * 20}))['scope']['neutral'], ['x'] * 20)

    def test_no_event_kind_was_added_by_carrying_a_verdict_over(self):
        self.approved(value=self.two()); verdict.run(self.ledger, 'P1', 'M1', self.root)
        plans.amend(self.ledger, 'P1', self.reword_m2(), 'r2', 'claude'); plans.approve(self.ledger, 'P1', 'owner', 'ref')
        before = self.kinds(); self.view('M1')
        self.assertEqual(self.kinds(), before)
        self.assertEqual([k for k in before if k == 'verdict.recorded'], ['verdict.recorded'])

    def test_an_owner_manual_pass_is_carried_on_the_same_artifact_only(self):
        manual = {'id': 'M2', 'title': 'Looks right', 'verifier': {'type': 'owner-manual'}, 'covers': ['O1']}
        value = plan_json(milestones=[milestone('M1'), manual], scope={'owned': ['a.txt'], 'neutral': ['docs/**']})
        self.approved(value=value)
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        from onecrew.snapshots import Snapshots
        blob = Snapshots(self.ledger.state_root).blob(b'checked on the device by the owner\n')
        verdict.record(self.ledger, 'P1', 'M2', 'pass', 'owner', blob, self.tree())
        plans.amend(self.ledger, 'P1', dict(value, title='Retitled'), 'title', 'claude'); plans.approve(self.ledger, 'P1', 'owner', 'ref')
        self.assertEqual((self.view('M1')['state'], self.view('M2')['state']), ('passed', 'passed'))
        (self.root / 'docs').mkdir(); (self.root / 'docs' / 'r.md').write_text('# r\n'); self.git('add', '.'); self.git('commit', '-q', '-m', 'docs')
        self.assertEqual((self.view('M1')['state'], self.view('M2')['state']), ('passed', 'pending'))


class ReviewerFixture(Fixture, Cli):
    def setUp(self):
        super().setUp()
        self.prompts = []

        def fake(prompt, config, env, scratch, limit):
            self.prompts.append(prompt)
            return self.reply, {}, None, False, b'raw'
        self.reply = passing()
        patcher = patch.object(reviewer, 'call', fake); patcher.start(); self.addCleanup(patcher.stop)

    def start(self, milestones=None, **extra):
        plans.propose(self.ledger, 'P1', plan_json(milestones=milestones or [review_milestone()], **extra), 'codex')
        plans.approve(self.ledger, 'P1', 'owner', 'said yes in chat')

    def commit(self, name, text, message='work'):
        (self.root / name).parent.mkdir(parents=True, exist_ok=True)
        (self.root / name).write_text(text); self.git('add', '.'); self.git('commit', '-q', '-m', message)

    def receipt(self):
        from onecrew.snapshots import Snapshots
        recorded = [p for k, p in self.events() if k == 'verdict.recorded'][-1]
        return json.loads(Snapshots(self.ledger.state_root).read_blob(recorded['receipt']))

    def sent_diff(self):
        from onecrew.snapshots import Snapshots
        return Snapshots(self.ledger.state_root).read_blob(self.receipt()['diff']).decode('utf-8')


class ReviewerDiff(ReviewerFixture):
    def test_an_untracked_file_is_never_in_the_diff_and_verdict_diff_makes_no_call_and_writes_nothing(self):
        self.start(); self.commit('a.txt', 'one\ntwo\n')
        (self.root / 'big.bin').write_bytes(os.urandom(1024 * 1024))
        kinds = self.kinds()
        text = verdict.diff(self.ledger, 'P1', 'M1')
        self.assertIn('+two', text); self.assertNotIn('big.bin', text); self.assertLess(len(text.encode('utf-8')), 10_000)
        self.assertEqual((self.prompts, self.kinds()), ([], kinds))
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        receipt = self.receipt()
        self.assertEqual(receipt['result'], 'inconclusive'); self.assertIn('big.bin', receipt['error'])
        self.assertEqual(self.prompts, [])

    def test_an_ignored_directory_does_not_break_the_cap(self):
        self.start(); self.commit('.gitignore', 'build/\n')
        (self.root / 'build').mkdir(); (self.root / 'build' / 'out.bin').write_bytes(b'x' * (reviewer.MAX_DIFF + 10))
        self.commit('a.txt', 'one\ntwo\n')
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual((self.receipt()['result'], len(self.prompts)), ('pass', 1))

    def test_a_file_that_only_lay_around_at_approval_is_not_shown_as_deleted(self):
        (self.root / 'build').mkdir(); (self.root / 'build' / 'out.txt').write_text('left over\n')
        self.start(); (self.root / 'a.txt').write_text('one\ntwo\n'); self.git('add', 'a.txt'); self.git('commit', '-q', '-m', 'work')
        text = verdict.diff(self.ledger, 'P1', 'M1')
        self.assertIn('+two', text); self.assertNotIn('out.txt', text)

    def test_a_path_deleted_long_ago_that_holds_an_untracked_file_at_approval_is_not_in_the_diff(self):
        self.commit('old.txt', 'was tracked once\n', 'add old'); self.git('rm', '-q', 'old.txt'); self.git('commit', '-q', '-m', 'drop old')
        (self.root / 'old.txt').write_text('untracked secret scratch\n')
        self.start(); (self.root / 'b.txt').write_text('new work\n'); self.git('add', 'b.txt'); self.git('commit', '-q', '-m', 'work')
        (self.root / 'old.txt').unlink()
        text = verdict.diff(self.ledger, 'P1', 'M1')
        self.assertIn('+new work', text); self.assertNotIn('old.txt', text); self.assertNotIn('scratch', text)

    def test_a_file_tracked_at_the_base_and_removed_since_is_shown_after_a_pass_too(self):
        self.commit('f.txt', 'keep me\n', 'f'); self.start(); self.commit('a.txt', 'one\ntwo\n')
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.git('rm', '-q', 'f.txt'); self.git('commit', '-q', '-m', 'drop f')
        text = verdict.diff(self.ledger, 'P1', 'M1')
        self.assertIn('-keep me', text); self.assertNotIn('+two', text)

    def test_a_file_untracked_at_approval_and_committed_later_is_a_new_file_never_a_deletion_with_its_old_content(self):
        (self.root / 'late.txt').write_text('OLD-UNTRACKED-CONTENT\n')
        self.start(); self.commit('late.txt', 'committed text\n')
        text = verdict.diff(self.ledger, 'P1', 'M1')
        self.assertIn('+committed text', text); self.assertNotIn('OLD-UNTRACKED-CONTENT', text)
        self.assertNotIn('-OLD', text)

    def test_the_same_after_a_pass_the_pass_remembers_the_tracked_tree_not_the_untracked_files(self):
        self.start(); self.commit('a.txt', 'one\ntwo\n')
        (self.root / 'late.txt').write_text('SCRATCH-AT-THE-PASS\n')
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        refused = self.receipt()
        self.assertEqual(refused['result'], 'inconclusive'); self.assertIn('late.txt', refused['error'])
        self.assertEqual(self.prompts, [])
        self.commit('.gitignore', 'late.txt\n')
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        first = self.receipt()
        self.assertEqual(first['result'], 'pass')
        self.assertEqual(first['tracked_tree'], command.tracked_tree(self.root))
        self.assertNotIn('late.txt', self.git('ls-tree', '-r', '--name-only', first['tracked_tree']))
        (self.root / 'late.txt').write_text('now committed\n'); self.git('add', '-f', 'late.txt'); self.git('commit', '-q', '-m', 'late')
        text = verdict.diff(self.ledger, 'P1', 'M1')
        self.assertIn('+now committed', text); self.assertNotIn('SCRATCH-AT-THE-PASS', text)

    def test_the_approval_records_the_tracked_tree_next_to_the_artifact(self):
        (self.root / 'scratch.txt').write_text('lying around\n')
        self.start()
        approved = [p for k, p in self.events() if k == 'plan.approved'][0]
        approved = json.loads(approved) if isinstance(approved, str) else approved
        self.assertEqual((approved['base_tracked'], approved['base_artifact']), (self.git('rev-parse', 'HEAD^{tree}'), command.artifact_sha(self.root)))
        self.assertNotEqual(approved['base_tracked'], approved['base_artifact'])

    def test_without_a_recorded_tracked_base_there_is_no_diff_and_no_call_only_an_explicit_error(self):
        with patch.object(plans, '_base_tracked', return_value=None): self.start()
        self.commit('a.txt', 'one\ntwo\n')
        with self.assertRaises(LedgerError) as caught: verdict.diff(self.ledger, 'P1', 'M1')
        self.assertIn('no tracked-only base tree', str(caught.exception))
        code, text = self.cli('verdict', 'diff', '--plan', 'P1', '--milestone', 'M1')
        self.assertEqual(code, 2); self.assertIn('no tracked-only base tree', text)
        view = verdict.run(self.ledger, 'P1', 'M1', self.root)
        receipt = self.receipt()
        self.assertEqual((receipt['result'], receipt['calls'], self.prompts, receipt['base_source']), ('inconclusive', 0, [], 'none'))
        self.assertIn('no tracked-only base tree', receipt['error']); self.assertNotEqual(view['milestones'][0]['state'], 'passed')

    def test_only_a_pass_with_the_same_reviewer_config_is_a_base(self):
        self.start(); self.commit('a.txt', 'one\ntwo\n')
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.commit('a.txt', 'one\ntwo\nthree\n')
        self.assertNotIn('+two', verdict.diff(self.ledger, 'P1', 'M1'))
        changed = review_milestone(criteria=[{'id': 'R1', 'question': 'Does a.txt still hold the line three? fail if the line is gone.'}])
        plans.amend(self.ledger, 'P1', plan_json(milestones=[changed]), 'criteria', 'codex'); plans.approve(self.ledger, 'P1', 'owner', 'ref')
        text = verdict.diff(self.ledger, 'P1', 'M1')
        self.assertIn('+two', text); self.assertIn('+three', text)

    def test_a_real_deletion_is_still_shown(self):
        self.commit('f.txt', 'keep me\n', 'f'); self.start()
        self.git('rm', '-q', 'f.txt'); self.git('commit', '-q', '-m', 'drop f')
        text = verdict.diff(self.ledger, 'P1', 'M1')
        self.assertIn('f.txt', text); self.assertIn('-keep me', text)

    def test_the_diff_starts_from_the_last_pass_of_this_milestone(self):
        self.start(); self.commit('a.txt', 'one\ntwo\n')
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        first = self.receipt()
        self.assertEqual(first['base_source'], 'first_approval'); self.assertIn('+two', self.sent_diff())
        self.commit('a.txt', 'one\ntwo\nthree\n')
        text = verdict.diff(self.ledger, 'P1', 'M1')
        self.assertIn('+three', text); self.assertNotIn('+two', text)
        self.reply = json.dumps({'criteria': [{'id': 'R1', 'verdict': 'fail', 'evidence': [{'file': 'a.txt', 'line': 3, 'note': 'x'}]}], 'outside_criteria': []})
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(self.receipt()['base_artifact'], first['artifact_sha']); self.assertEqual(self.receipt()['base_source'], 'previous_pass')
        self.assertIn('+three', self.sent_diff())

    def test_the_first_review_keeps_the_approval_tree_as_its_base_and_the_receipt_keeps_the_add_all_artifact(self):
        self.start(); self.commit('a.txt', 'one\ntwo\n')
        (self.root / 'scratch.txt').write_text('untracked\n')
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        receipt = self.receipt()
        self.assertEqual(receipt['artifact_sha'], command.artifact_sha(self.root))
        self.assertNotIn('scratch.txt', self.sent_diff())

    def test_the_cap_still_holds(self):
        self.start(); self.commit('big.txt', 'x\n' * reviewer.MAX_DIFF)
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual((self.receipt()['result'], self.prompts), ('inconclusive', []))

    def test_verdict_diff_needs_a_reviewer_milestone_and_no_earlier_pass(self):
        self.start(milestones=[milestone('M1'), review_milestone('M2')]); self.commit('a.txt', 'one\ntwo\n')
        self.assertIn('+two', verdict.diff(self.ledger, 'P1', 'M2'))
        with self.assertRaises(LedgerError): verdict.diff(self.ledger, 'P1', 'M1')
        with self.assertRaises(LedgerError): verdict.diff(self.ledger, 'P1', 'M9')

    def test_the_command_line(self):
        self.start(); self.commit('a.txt', 'one\ntwo\n')
        code, text = self.cli('verdict', 'diff', '--plan', 'P1', '--milestone', 'M1')
        self.assertEqual(code, 0); self.assertIn('+two', text)
        code, text = self.cli('verdict', 'artifact', '--plan', 'P1')
        self.assertEqual((code, json.loads(text)), (0, {'artifact_sha': command.artifact_sha(self.root)}))
        code, text = self.cli('verdict', 'artifact', '--plan', 'nope')
        self.assertEqual(code, 2)


class ReviewerCarry(ReviewerFixture):
    def test_a_reviewer_pass_is_not_carried_over_a_neutral_commit_but_the_rerun_sees_only_that_commit(self):
        self.start(milestones=[milestone('M1'), review_milestone('M2')], scope={'owned': ['a.txt'], 'neutral': ['docs/**']})
        self.commit('a.txt', 'one\ntwo\n')
        verdict.run(self.ledger, 'P1', 'M1', self.root); verdict.run(self.ledger, 'P1', 'M2', self.root)
        self.commit('docs/r.md', '# r\n', 'docs')
        views = {m['id']: m for m in plans.show(self.ledger, 'P1')['milestones']}
        self.assertEqual((views['M1']['state'], views['M1'].get('neutral_diff'), views['M2']['state']), ('passed', True, 'pending'))
        with self.assertRaises(LedgerError): plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())
        self.prompts.clear()
        verdict.run(self.ledger, 'P1', 'M2', self.root)
        self.assertIn('docs/r.md', self.prompts[0]); self.assertNotIn('+two', self.prompts[0])
        self.assertEqual(plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())['status'], 'accepted')

    def test_a_reviewer_pass_is_carried_when_nothing_but_the_wording_of_another_milestone_changed(self):
        self.start(milestones=[review_milestone('M1'), milestone('M2')])
        self.commit('a.txt', 'one\ntwo\n'); verdict.run(self.ledger, 'P1', 'M1', self.root)
        plans.amend(self.ledger, 'P1', plan_json(milestones=[review_milestone('M1'), milestone('M2', title='M2 reworded')]), 'r2', 'codex')
        plans.approve(self.ledger, 'P1', 'owner', 'ref')
        m1 = plans.show(self.ledger, 'P1')['milestones'][0]
        self.assertEqual((m1['state'], m1['carried_from']), ('passed', 1))

    def test_a_reviewer_whose_criteria_changed_runs_again(self):
        self.start(); self.commit('a.txt', 'one\ntwo\n'); verdict.run(self.ledger, 'P1', 'M1', self.root)
        changed = review_milestone(criteria=[{'id': 'R1', 'question': 'Does a.txt still hold the line two? fail if the line is gone.'}])
        plans.amend(self.ledger, 'P1', plan_json(milestones=[changed]), 'criteria', 'codex'); plans.approve(self.ledger, 'P1', 'owner', 'ref')
        self.assertEqual(plans.show(self.ledger, 'P1')['milestones'][0]['state'], 'pending')

    def test_the_hooks_see_a_carried_milestone_as_passed(self):
        from onecrew.v2 import active_plan
        self.start(milestones=[milestone('M1'), milestone('M2')])
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        plans.amend(self.ledger, 'P1', plan_json(milestones=[milestone('M1'), milestone('M2', title='M2 reworded')]), 'r2', 'codex')
        plans.approve(self.ledger, 'P1', 'owner', 'ref')
        document = active_plan.build(self.ledger, 'P1')
        self.assertEqual([m['state'] for m in document['milestones']], ['passed', 'pending'])


def understanding(**extra):
    return dict({'restated_goal': 'Do the sample and prove it.', 'target': {'repo': '.', 'ref': 'HEAD', 'paths': ['a.txt']},
                 'assumptions': [], 'confidence': 'high', 'unknowns': []}, **extra)


def sourced(value):
    return dict(value, origin={'by': 'owner', 'at': '2026-10-20', 'quote': 'Do the sample.'}, items=[dict(i, source='origin') for i in value['items']])


def size_m(**extra):
    value = plan_json(size='M', **extra)
    value['understanding']['assumptions'] = [{'text': 'a.txt is there', 'evidence': 'a.txt:1'}]
    value['options'] = {'recommended': 'A', 'reason': 'only one way', 'items': [
        {'id': 'A', 'summary': 'do it', 'evidence': ['a.txt:1'], 'strengths': ['simple'], 'weaknesses': [], 'unknowns': [], 'cost': 'tiny', 'risk': 'none'},
        {'id': 'B', 'summary': 'do not', 'evidence': ['a.txt:1'], 'strengths': [], 'weaknesses': ['nothing happens'], 'unknowns': [], 'cost': 'none', 'risk': 'none'}]}
    return sourced(value)


class LintRules(Fixture, Cli):
    def check(self, value, ack=False, author='claude-sonnet-5-5'):
        return lint.check(lint.ReadOnlyLedger(self.root, self.ledger.state_root), value, author, ack)

    def reviewed(self, question, non_goals=None):
        value = plan_json(milestones=[review_milestone(criteria=[{'id': 'R1', 'question': question}])])
        if non_goals is not None: value['non_goals'] = non_goals
        return value

    def codes(self, pairs):
        return [code for code, _ in pairs]

    def test_a_quoted_literal_already_in_the_base_tree_is_a_warning_not_a_refusal(self):
        reasons, warnings = self.check(self.reviewed("Is the string 'one' gone from a.txt? fail if it is still there."))
        self.assertEqual((self.codes(reasons), warnings), ([], []))
        (self.root / 'a.txt').write_text('one\nclaude-opus-5-5\n'); self.git('add', '.'); self.git('commit', '-q', '-m', 'literal')
        for quote in ("'claude-opus-5-5'", '"claude-opus-5-5"', '`claude-opus-5-5`'):
            reasons, warnings = self.check(self.reviewed(f'Is {quote} absent from a.txt? fail if it appears.'))
            self.assertEqual((self.codes(reasons), self.codes(warnings)), ([], ['criterion_literal_present']), quote)
        reasons, warnings = self.check(self.reviewed("Is 'not-in-any-file' in a.txt? fail if it is."))
        self.assertEqual(warnings, [])

    def test_a_criterion_without_fail_if_is_refused_in_any_case(self):
        for question in ('Is a.txt still present?', 'Is a.txt present? Fail If it was deleted.'):
            reasons, _ = self.check(self.reviewed(question))
            self.assertEqual(self.codes(reasons) == ['criterion_no_fail_clause'], 'Fail If' not in question, question)
        reasons, warnings = self.check(self.reviewed('Is a.txt still present?'), ack=True)
        self.assertEqual(self.codes(reasons), ['criterion_no_fail_clause'])

    def test_a_word_shared_with_a_non_goal_is_a_warning_and_ack_criteria_silences_it(self):
        question = 'Are all message lines in the diff translated? fail if an old message line in a .py file is not translated.'
        reasons, warnings = self.check(self.reviewed(question, ['translating old messages']))
        self.assertEqual((self.codes(reasons), self.codes(warnings)), ([], ['criterion_vs_non_goal']))
        self.assertEqual(self.check(self.reviewed(question, ['translating old messages']), ack=True), ([], []))
        self.assertEqual(self.check(self.reviewed(question, ['Nothing else'])), ([], []))

    def test_the_command_line_prints_warnings_with_exit_0_and_refusals_with_exit_1(self):
        (self.root / 'a.txt').write_text('one\nclaude-opus-5-5\n'); self.git('add', '.'); self.git('commit', '-q', '-m', 'literal')
        path = Path(self.temp.name) / 'c.json'

        def run(value, *flags):
            path.write_text(json.dumps(value), encoding='utf-8')
            return self.cli('plan', 'lint', '--file', str(path), '--author', 'claude-sonnet-5-5', *flags)
        code, text = run(self.reviewed("Is 'claude-opus-5-5' absent from a.txt? fail if it appears."))
        self.assertEqual(code, 0); self.assertIn('[criterion_literal_present]', text)
        code, text = run(self.reviewed("Is 'claude-opus-5-5' absent from a.txt? fail if it appears."), '--ack-criteria')
        self.assertEqual((code, text.strip()), (0, 'lint: clean'))
        code, text = run(self.reviewed('Is a.txt present?'))
        self.assertEqual(code, 1); self.assertIn('[criterion_no_fail_clause]', text)

    def test_lint_still_writes_nothing_and_calls_no_model(self):
        before = (len(list(Path(self.ledger.state_root).rglob('*'))), self.git('status', '--porcelain'))
        with patch.object(reviewer, 'call', side_effect=AssertionError('lint called a model')):
            self.check(self.reviewed('Is a.txt present?'))
        self.assertEqual((len(list(Path(self.ledger.state_root).rglob('*'))), self.git('status', '--porcelain')), before)

    def test_size_m_with_no_unknowns_needs_the_statement(self):
        reasons, _ = self.check(size_m())
        self.assertEqual(self.codes(reasons), ['unknowns_missing'])
        value = size_m(); value['understanding']['no_unknowns_because'] = 'read a.txt:1: one line, one path, nothing open'
        self.assertEqual(self.check(value), ([], []))
        value['understanding']['unknowns'] = []
        self.assertEqual(contracts.validate(value)['understanding']['no_unknowns_because'], 'read a.txt:1: one line, one path, nothing open')
        self.assertEqual(self.codes(self.check(sourced(plan_json()))[0]), [])
        for weak in ('None', 'n/a', '', '   ', 'nothing open'):
            short = size_m(); short['understanding']['no_unknowns_because'] = weak
            if weak.strip(): self.assertEqual(self.codes(self.check(short)[0]), ['unknowns_missing'], weak)
            else: self.assertRaises(LedgerError, contracts.validate, short)

    def test_approve_refuses_it_too_and_an_older_contract_is_still_read(self):
        value = size_m(); contract = contracts.validate(value)
        verdict_ = step0.evaluate(self.ledger, 'P1', 1, 'a' * 64, contract, {}, choose='A', run=False)
        self.assertIn('unknowns_missing', [code for code, _ in verdict_['reasons']])
        value['understanding']['no_unknowns_because'] = 'read a.txt:1: nothing open'
        verdict_ = step0.evaluate(self.ledger, 'P1', 1, 'a' * 64, contracts.validate(value), {}, choose='A', run=False)
        self.assertNotIn('unknowns_missing', [code for code, _ in verdict_['reasons']])
        legacy = contracts.validate(plan_json())
        self.assertNotIn('no_unknowns_because', legacy['understanding'])
        with self.assertRaises(LedgerError): contracts.validate(dict(plan_json(), understanding=understanding(no_unknowns_because='x' * 301)))
        legacy_m = plan_json(size='M'); legacy_m['understanding']['assumptions'] = [{'text': 'a', 'evidence': 'a.txt:1'}]
        legacy_m['options'] = size_m()['options']
        verdict_ = step0.evaluate(self.ledger, 'P1', 1, 'a' * 64, contracts.validate(legacy_m), {}, choose='A', run=False)
        self.assertIn('unknowns_missing', [code for code, _ in verdict_['reasons']])
        small = step0.evaluate(self.ledger, 'P1', 1, 'a' * 64, contracts.validate(plan_json()), {}, run=False)
        self.assertNotIn('unknowns_missing', [code for code, _ in small['reasons']])

    def test_the_template_is_valid_json_with_blanks_and_the_notes(self):
        text = (Path(__file__).resolve().parent.parent / 'examples' / 'contract-template.json').read_text(encoding='utf-8')
        value = json.loads(text)
        self.assertIn('<', text); self.assertIn('fail if', text); self.assertIn('no_unknowns_because', value['understanding'])
        self.assertIn('neutral', value['scope'])


class ReportNotes(ReviewerFixture):
    def passed_with(self, outside):
        self.reply = passing(outside)
        self.start(); self.commit('a.txt', 'one\ntwo\n')
        verdict.run(self.ledger, 'P1', 'M1', self.root)

    def text(self):
        return report.render_report(self.ledger.state_root, 'P1')

    def test_the_section_lists_each_note_of_the_reviewer_cut_at_300_characters(self):
        self.passed_with(['config.json is read twice', 'x' * 400])
        text = self.text()
        self.assertIn('Reviewer ghi chú', text)
        tail = text.split('Reviewer ghi chú', 1)[1].splitlines()
        self.assertEqual(tail[1].strip().split()[0], 'M1')
        self.assertIn('    - config.json is read twice', tail)
        long = next(l for l in tail if l.startswith('    - x'))
        self.assertEqual(len(long) - len('    - '), 300); self.assertTrue(long.endswith('…'))

    def test_no_notes_no_section_and_the_rest_of_the_page_is_the_same(self):
        self.passed_with([])
        without = self.text()
        self.assertNotIn('Reviewer ghi chú', without)
        self.setUp(); self.passed_with(['one remark'])
        with_notes = self.text()
        self.assertIn('Reviewer ghi chú', with_notes)
        self.assertEqual(with_notes.split('\nReviewer ghi chú', 1)[0].count('\n8. '), 0)
        self.assertEqual(report.TITLES.__len__(), 7)

    def test_a_command_only_plan_has_no_section(self):
        self.approved(); verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertNotIn('Reviewer ghi chú', self.text())

    def test_the_digest_does_not_change(self):
        self.passed_with(['one remark'])
        self.assertNotIn('Reviewer ghi chú', report.render_digest(self.ledger.state_root))


if __name__ == '__main__':
    unittest.main()
