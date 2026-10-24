"""T31 runtime wiring on temporary repositories and temporary ledger state only.

Command checks execute a real process on a real tree. Reviewer infrastructure
failure injects a Git capture error and never calls a provider. Malformed receipt
cases inject verifier output to check refusal before publishing evidence.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import active_plan, plan as plans, retention, verdict
from onecrew.v2.verifiers import command, reviewer
from tests.test_v2_l1 import Fixture, plan_json

REPO = Path(__file__).resolve().parents[1]


def manual_contract():
    return plan_json(milestones=[{'id': 'M1', 'title': 'Owner checks the document',
                                'covers': ['O1'], 'verifier': {'type': 'owner-manual'}}])


def review_contract():
    return plan_json(milestones=[{'id': 'M1', 'title': 'Review the file', 'covers': ['O1'],
                                'verifier': {'type': 'reviewer', 'config': {
                                    'provider': 'claude', 'model': 'claude-haiku-5-5', 'max_minutes': 1,
                                    'criteria': [{'id': 'R1', 'question': 'Does the a.txt diff preserve the document?'}]}}}])


class RetentionIntegrationTests(Fixture):
    def gc(self):
        self.git('reflog', 'expire', '--expire=now', '--all')
        self.git('gc', '--prune=now')

    def cli(self, *args, env=None, data=None):
        return subprocess.run([sys.executable, '-X', 'utf8', '-m', 'onecrew.v2.cli',
                               '--project', str(self.root), '--state-root', str(self.ledger.state_root), *args],
                              cwd=REPO, env=dict(os.environ, **(env or {})), input=data,
                              capture_output=True, text=True, encoding='utf-8', timeout=60)

    def assert_tree_pinned(self, tree):
        self.assertIn(tree, retention.list_refs(self.ledger, 'P1').values())
        self.git('cat-file', '-e', tree)
        self.git('cat-file', '-e', tree + ':a.txt')

    def test_approval_base_artifact_and_tracked_tree_survive_gc_and_restart(self):
        (self.root / 'a.txt').write_text('approval tree\n', encoding='utf-8')
        (self.root / 'untracked.txt').write_text('approval-only evidence\n', encoding='utf-8')
        self.approved()
        approval = next(payload for kind, payload in self.events() if kind == 'plan.approved')
        self.assertNotEqual(approval['base_artifact'], approval['base_tracked'])
        self.git('checkout', '--', 'a.txt')
        (self.root / 'untracked.txt').unlink()
        self.gc()
        for tree in (approval['base_artifact'], approval['base_tracked']):
            self.assert_tree_pinned(tree)
        self.git('cat-file', '-e', approval['base_artifact'] + ':untracked.txt')
        restarted = self.cli('plan', 'show', 'P1')
        self.assertEqual(restarted.returncode, 0, restarted.stderr + restarted.stdout)
        self.assertEqual(json.loads(restarted.stdout)['status'], 'approved')

    def test_command_run_issuance_record_accept_and_receipt_survive_gc_and_restart(self):
        self.approved()
        (self.root / 'a.txt').write_text('verdict and accepted tree\n', encoding='utf-8')
        expected = self.tree()
        emitted = []
        original = plans.emit

        def inspect(ledger, conn, task, kind, payload):
            if kind in ('verdict.receipt_issued', 'verdict.recorded', 'plan.accepted'):
                self.assert_tree_pinned(expected)
                emitted.append(kind)
            return original(ledger, conn, task, kind, payload)

        with patch.object(plans, 'emit', inspect):
            view = verdict.run(self.ledger, 'P1', 'M1')
            self.assertEqual(view['milestones'][0]['state'], 'passed')
            plans.accept(self.ledger, 'P1', 'owner', 'fixture owner acceptance', expected)
        self.assertEqual(emitted, ['verdict.receipt_issued', 'verdict.recorded', 'plan.accepted'])
        recorded = next(payload for kind, payload in self.events() if kind == 'verdict.recorded')
        self.git('checkout', '--', 'a.txt')
        self.gc()
        self.assert_tree_pinned(expected)
        receipt = json.loads(Snapshots(self.ledger.state_root).read_blob(recorded['receipt']))
        self.assertEqual(command.expected_result(receipt), 'pass')
        self.assertEqual(receipt['artifact_sha'], expected)
        restarted = self.cli('plan', 'show', 'P1')
        self.assertEqual(restarted.returncode, 0, restarted.stderr + restarted.stdout)
        self.assertEqual(json.loads(restarted.stdout)['status'], 'accepted')

    def test_issued_receipt_retains_tree_when_later_recording_fails(self):
        self.approved()
        (self.root / 'a.txt').write_text('receipt issued before recording failure\n', encoding='utf-8')
        expected = self.tree()
        with patch.object(verdict, 'record', side_effect=LedgerError('injected interruption after issuance')):
            with self.assertRaisesRegex(LedgerError, 'injected interruption'):
                verdict.run(self.ledger, 'P1', 'M1')
        self.assertIn('verdict.receipt_issued', self.kinds())
        self.assertNotIn('verdict.recorded', self.kinds())
        self.git('checkout', '--', 'a.txt')
        self.gc()
        self.assert_tree_pinned(expected)
        issued = next(payload for kind, payload in self.events() if kind == 'verdict.receipt_issued')
        receipt = json.loads(Snapshots(self.ledger.state_root).read_blob(issued['receipt']))
        self.assertEqual(receipt['artifact_sha'], expected)

    def test_direct_command_record_pins_tree_before_publishing(self):
        self.approved()
        (self.root / 'a.txt').write_text('direct recorded tree\n', encoding='utf-8')
        blob, body = self.receipt()
        self.issue(blob)
        view = verdict.record(self.ledger, 'P1', 'M1', 'pass', 'command', blob, body['artifact_sha'])
        self.assertEqual(view['milestones'][0]['state'], 'passed')
        self.git('checkout', '--', 'a.txt')
        self.gc()
        self.assert_tree_pinned(body['artifact_sha'])

    def test_missing_or_invalid_approval_tree_cannot_publish_approval(self):
        self.propose()
        for invalid in ('f' * 40, 'not-a-tree'):
            with self.subTest(invalid=invalid):
                with patch.object(plans, '_base_artifact', return_value=invalid):
                    with self.assertRaises(LedgerError):
                        plans.approve(self.ledger, 'P1', 'owner', 'fixture approval')
                self.assertNotIn('plan.approved', self.kinds())

    def test_missing_or_invalid_command_tree_cannot_publish_issued_receipt_or_verdict(self):
        self.approved()
        for invalid in ('f' * 40, 'not-a-tree'):
            with self.subTest(invalid=invalid):
                blob, body = self.receipt(artifact_sha=invalid, artifact_sha_after=invalid)
                with patch.object(command, 'run', return_value=(blob, body)):
                    with self.assertRaises(LedgerError):
                        verdict.run(self.ledger, 'P1', 'M1')
                self.assertNotIn('verdict.receipt_issued', self.kinds())
                self.assertNotIn('verdict.recorded', self.kinds())

    def test_missing_command_tree_cannot_publish_direct_verdict(self):
        self.approved()
        blob, body = self.receipt(artifact_sha='f' * 40, artifact_sha_after='f' * 40)
        self.issue(blob)
        before = self.kinds()
        with self.assertRaises(LedgerError):
            verdict.record(self.ledger, 'P1', 'M1', 'pass', 'command', blob, body['artifact_sha'])
        self.assertEqual(self.kinds(), before)

    def test_reviewer_no_artifact_infrastructure_receipt_remains_inconclusive(self):
        plans.propose(self.ledger, 'P1', review_contract(), 'codex')
        plans.approve(self.ledger, 'P1', 'owner', 'fixture review approval')
        before = retention.list_refs(self.ledger, 'P1')
        with patch.object(command, 'artifact_sha', side_effect=LedgerError('injected Git capture unavailable')):
            with patch.object(reviewer, 'call') as provider:
                view = verdict.run(self.ledger, 'P1', 'M1')
        provider.assert_not_called()
        self.assertNotEqual(view['milestones'][0]['state'], 'passed')
        recorded = next(payload for kind, payload in self.events() if kind == 'verdict.recorded')
        self.assertEqual((recorded['result'], recorded['artifact_sha']), ('inconclusive', reviewer.NO_ARTIFACT))
        body = json.loads(Snapshots(self.ledger.state_root).read_blob(recorded['receipt']))
        self.assertIn('injected Git capture unavailable', body['error'])
        self.assertEqual(retention.list_refs(self.ledger, 'P1'), before)

    def test_reviewer_receipt_pins_distinct_artifact_and_tracked_trees_without_provider_call(self):
        plans.propose(self.ledger, 'P1', review_contract(), 'codex')
        plans.approve(self.ledger, 'P1', 'owner', 'fixture review approval')
        (self.root / 'a.txt').write_text('tracked review evidence\n', encoding='utf-8')
        (self.root / 'untracked.txt').write_text('untracked input blocks model review\n', encoding='utf-8')
        with patch.object(reviewer, 'call') as provider:
            verdict.run(self.ledger, 'P1', 'M1')
        provider.assert_not_called()
        recorded = next(payload for kind, payload in self.events() if kind == 'verdict.recorded')
        body = json.loads(Snapshots(self.ledger.state_root).read_blob(recorded['receipt']))
        self.assertEqual(recorded['result'], 'inconclusive')
        self.assertNotEqual(body['artifact_sha'], body['tracked_tree'])
        self.git('checkout', '--', 'a.txt')
        (self.root / 'untracked.txt').unlink()
        self.gc()
        for key in ('artifact_sha', 'artifact_sha_after', 'tracked_tree', 'base_artifact', 'base_tracked'):
            self.assert_tree_pinned(body[key])

    def test_null_command_artifact_cannot_publish_a_pass(self):
        self.approved()
        blob, body = self.receipt(artifact_sha='0' * 40, artifact_sha_after='0' * 40)
        self.issue(blob)
        with self.assertRaises(LedgerError):
            verdict.record(self.ledger, 'P1', 'M1', 'pass', 'command', blob, body['artifact_sha'])
        self.assertNotIn('verdict.recorded', self.kinds())

    def test_owner_manual_tree_is_retained_through_acceptance(self):
        self.approved(value=manual_contract())
        (self.root / 'a.txt').write_text('owner-reviewed tree\n', encoding='utf-8')
        expected = self.tree()
        verdict.record(self.ledger, 'P1', 'M1', 'pass', 'owner', None, expected,
                       receipt_bytes=b'Fixture owner observed this exact document tree')
        plans.accept(self.ledger, 'P1', 'owner', 'fixture accepted tree', expected)
        self.git('checkout', '--', 'a.txt')
        self.gc()
        self.assert_tree_pinned(expected)

    def test_owner_manual_opaque_document_hash_still_works_without_git(self):
        self.approved(value=manual_contract())
        # Preserve the temporary repository; this models an already approved
        # document plan whose project is subsequently available without Git.
        (self.root / '.git').rename(self.root.parent / 'saved-git')
        opaque = 'a' * 64
        view = verdict.record(self.ledger, 'P1', 'M1', 'pass', 'owner', None, opaque,
                              receipt_bytes=b'Fixture owner observed external document evidence')
        self.assertEqual(view['milestones'][0]['state'], 'passed')
        accepted = plans.accept(self.ledger, 'P1', 'owner', 'fixture accepted external document', opaque)
        self.assertEqual(accepted['status'], 'accepted')

    def test_retention_cli_lists_and_owner_cleanup_refuses_ai_actor_and_session(self):
        self.approved()
        before = retention.list_refs(self.ledger, 'P1')
        listed = self.cli('plan', 'retention', 'list', 'P1', env={'ONECREW_ACTOR': 'codex'})
        self.assertEqual(listed.returncode, 0, listed.stderr + listed.stdout)
        self.assertEqual(json.loads(listed.stdout), before)
        for env in ({'ONECREW_ACTOR': 'codex'}, {'ONECREW_ACTOR': 'owner', 'CLAUDE_CODE_CHILD_SESSION': ''}):
            with self.subTest(env=env):
                denied = self.cli('plan', 'retention', 'cleanup', 'P1', '--by', 'owner', env=env)
                self.assertEqual(denied.returncode, 2, denied.stderr + denied.stdout)
                self.assertIn('refused', denied.stdout.lower() + denied.stderr.lower())
                self.assertEqual(retention.list_refs(self.ledger, 'P1'), before)
        cleaned = self.cli('plan', 'retention', 'cleanup', 'P1', '--by', 'owner', env={'ONECREW_ACTOR': 'owner'})
        self.assertEqual(cleaned.returncode, 0, cleaned.stderr + cleaned.stdout)
        self.assertEqual(json.loads(cleaned.stdout)['removed'], sorted(before))
        self.assertEqual(retention.list_refs(self.ledger, 'P1'), {})

    def test_hook_blocks_push_of_retention_refs_with_specific_reason(self):
        self.approved()
        active_plan.set_mode(self.ledger, 'enforce')
        active_plan.export(self.ledger, 'P1')
        ref = next(iter(retention.list_refs(self.ledger, 'P1')))
        for tool, text in (('Bash', 'git push origin ' + ref),
                           ('PowerShell', 'git -C . push origin ' + ref + ':' + ref)):
            event = {'session_id': 'retention-fixture', 'cwd': str(self.root), 'hook_event_name': 'PreToolUse',
                     'tool_name': tool, 'tool_input': {'command': text}}
            done = self.cli('hook', 'check', data=json.dumps(event))
            self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
            self.assertIn('refs/onecrew', done.stdout + done.stderr)
