"""OneCrew v2, slice L1: one test (at least) per invariant, each proving the way around it does not work.

(1) no approved plan, no dispatch (also in work mode)   (2) --  (L2: hook)   (3) the stop at max_repairs and AI cannot extend it
(4) a milestone without a passing verdict does not pass (5) -- (L4)           (6) acceptance is the owner's and needs verdicts.
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew import cli, solution_gate
from onecrew.ledger import Ledger, LedgerError
from onecrew.owned import Owned
from onecrew.owned_intake import submit
from onecrew.snapshots import Snapshots
from onecrew.v2 import contract as contracts, gate, plan as plans, verdict
from onecrew.v2.verifiers import command

PY = sys.executable
OK = [PY, '-c', 'print("ok")']
BAD = [PY, '-c', 'raise SystemExit(3)']


def milestone(mid='M1', argv=OK, **extra):
    return dict({'id': mid, 'title': 'Milestone ' + mid, 'verifier': {'type': 'command', 'config': {'argv': argv}}, 'covers': ['O1']}, **extra)


def plan_json(milestones=None, **extra):
    # L3: the smallest contract that passes step 0 (size S: no options; one precondition; nothing open). tests/test_v2_l3.py covers step 0 itself.
    value = {'schema_version': 2, 'title': 'Sample', 'size': 'S',
             'understanding': {'restated_goal': 'Do the sample and prove it.', 'target': {'repo': '.', 'ref': 'HEAD', 'paths': ['a.txt']},
                               'assumptions': [], 'confidence': 'high', 'unknowns': []},
             'preconditions': [{'id': 'P1', 'check': 'path_exists', 'args': {'path': 'a.txt'}, 'why': 'the file to work on is there'}],
             'output': ['The sample exists'],
             'scope': {'owned': ['a.txt']}, 'non_goals': ['Nothing else'],
             'items': [{'id': 'I1', 'title': 'Do it', 'tier': 'must', 'milestone': 'M1'},
                       {'id': 'S1', 'title': 'Nice to have', 'tier': 'should'}, {'id': 'W1', 'title': 'Never', 'tier': 'wont'}],
             'milestones': milestones or [milestone()], 'budget': {'max_calls': 100, 'time': 120}, 'attention': {'questions': 1},
             'profile_version': None}
    return dict(value, **extra)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root = base / 'project'; self.root.mkdir()
        self.git('init', '-q'); self.git('config', 'user.name', 'T'); self.git('config', 'user.email', 't@localhost')
        (self.root / 'a.txt').write_text('one\n'); self.git('add', '.'); self.git('commit', '-q', '-m', 'base')
        self.ledger = Ledger(self.root, base / 'state')
        env = patch.dict(os.environ); env.start(); self.addCleanup(env.stop)
        for name in ('ONECREW_ACTOR', 'ONECREW_V2_REQUIRE_PLAN', 'CLAUDECODE', 'CLAUDE_CODE_CHILD_SESSION'): os.environ.pop(name, None)

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.PIPE).decode().strip()

    def propose(self, name='P1', value=None):
        return plans.propose(self.ledger, name, value or plan_json(), 'claude')

    def approved(self, name='P1', value=None, **kw):
        self.propose(name, value)
        return plans.approve(self.ledger, name, 'owner', 'said yes in chat', **kw)

    def events(self, name='P1'):
        with self.ledger.transaction() as conn:
            task = plans.derive(self.ledger, conn, name)['task_id']
        return [(e['kind'], e['payload']) for e in self.ledger.events(task)]

    def kinds(self, name='P1'):
        return [k for k, _ in self.events(name)]

    def tree(self):
        return command.artifact_sha(self.root)

    def issue(self, blob, milestone='M1', revision=1):
        """What verdict.run does just before it records: announce the receipt it made."""
        with self.ledger.transaction(write=True) as conn:
            task = plans.derive(self.ledger, conn, 'P1')['task_id']
            plans.emit(self.ledger, conn, task, 'verdict.receipt_issued', {'plan': 'P1', 'revision': revision, 'milestone': milestone, 'receipt': blob})

    def receipt(self, **fields):
        body = {'kind': 'command-receipt', 'plan': 'P1', 'revision': 1, 'milestone': 'M1', 'argv': OK, 'exit_code': 0, 'timed_out': False,
                'error': None, 'artifact_sha': self.tree(), 'artifact_sha_after': self.tree()}
        with self.ledger.transaction() as conn:
            body['plan_sha'] = plans.derive(self.ledger, conn, 'P1')['revisions'][1]['sha']
        body.update(fields)
        return Snapshots(self.ledger.state_root).blob(json.dumps(body, sort_keys=True).encode()), body


class ContractTests(Fixture):
    def test_a_contract_file_cannot_carry_status_or_unknown_fields(self):
        for extra in ({'approved': True}, {'status': 'approved'}, {'accepted': True}, {'revision': 9}):
            with self.assertRaises(LedgerError): self.propose('P1', plan_json(**extra))
        self.assertEqual(self.propose('P2')['status'], 'proposed')

    def test_the_contract_is_validated(self):
        bad = [plan_json(items=[{'id': 'S1', 'title': 'x', 'tier': 'should'}]),                       # no must item
               plan_json(milestones=[milestone(max_repairs=9)]), plan_json(milestones=[milestone(mode='forever')]),
               plan_json(profile_version=1), plan_json(understanding=''), plan_json(output=[]),
               plan_json(milestones=[dict(milestone(), verifier={'type': 'magic'})]),
               plan_json(items=[{'id': 'I1', 'title': 'x', 'tier': 'must', 'milestone': 'M9'}])]
        for value in bad:
            with self.assertRaises(LedgerError): contracts.validate(value)
        normal = contracts.validate(plan_json())
        self.assertEqual(normal['milestones'][0]['max_repairs'], 1)           # default
        self.assertEqual(normal['milestones'][0]['mode'], 'once')

    def test_a_revision_file_is_write_once_and_hashed(self):
        self.propose()
        with self.assertRaises(OSError): contracts.write_revision(self.ledger, 'P1', 1, contracts.validate(plan_json()))
        path = contracts.revision_path(self.ledger, 'P1', 1)
        path.write_text(path.read_text(encoding='utf-8').replace('Do the sample', 'Do EVERYTHING'), encoding='utf-8')
        with self.assertRaises(LedgerError): plans.show(self.ledger, 'P1')    # edited in place: the hash no longer matches


class ApprovalTests(Fixture):
    def test_only_the_owner_can_approve_an_ai_cannot(self):
        self.propose()
        for by in ('claude', 'codex', 'reviewer', 'author'):
            with self.assertRaises(LedgerError): plans.approve(self.ledger, 'P1', by, 'ref')
        os.environ['ONECREW_ACTOR'] = 'claude'
        with self.assertRaises(LedgerError): plans.approve(self.ledger, 'P1', 'owner', 'ref')   # an AI shell claiming to be the owner
        self.assertEqual(plans.show(self.ledger, 'P1')['status'], 'proposed')
        os.environ['ONECREW_ACTOR'] = 'user'
        self.assertEqual(plans.approve(self.ledger, 'P1', 'owner', 'ref')['status'], 'approved')

    def test_should_items_run_only_when_ticked_and_wont_never(self):
        self.propose()
        with self.assertRaises(LedgerError): plans.approve(self.ledger, 'P1', 'owner', 'ref', tick=['W1'])
        with self.assertRaises(LedgerError): plans.approve(self.ledger, 'P1', 'owner', 'ref', tick=['I1'])
        runs = lambda view: {i['id']: i['runs'] for i in view['contract']['items']}
        self.assertEqual(runs(plans.show(self.ledger, 'P1')), {'I1': True, 'S1': False, 'W1': False})
        view = plans.approve(self.ledger, 'P1', 'owner', 'ref', tick=['S1'])
        self.assertEqual(runs(view), {'I1': True, 'S1': True, 'W1': False})

    def test_amend_makes_a_new_revision_and_never_overwrites(self):
        self.approved()
        first = contracts.revision_path(self.ledger, 'P1', 1).read_bytes()
        changed = plan_json(title='Sample, amended')
        view = plans.amend(self.ledger, 'P1', changed, 'Owner asked for a clearer title', 'claude')
        self.assertEqual((view['latest_revision'], view['status']), (2, 'proposed'))   # the old approval does not carry over
        self.assertEqual(contracts.revision_path(self.ledger, 'P1', 1).read_bytes(), first)
        self.assertNotEqual(view['revisions'][0]['sha'], view['revisions'][1]['sha'])
        amended = [p for k, p in self.events() if k == 'plan.amended'][0]
        self.assertEqual((amended['from_revision'], amended['parent_sha']), (1, view['revisions'][0]['sha']))
        with self.assertRaises(LedgerError): plans.amend(self.ledger, 'P1', changed, 'same again', 'claude')      # identical
        with self.assertRaises(LedgerError): plans.amend(self.ledger, 'P1', plan_json(title='X'), 'r' * 201, 'claude')  # reason > 200
        with self.assertRaises(LedgerError): plans.amend(self.ledger, 'P1', plan_json(title='X'), '', 'claude')
        with self.assertRaises(OSError): contracts.write_revision(self.ledger, 'P1', 1, contracts.validate(changed))   # no in-place edit
        with self.assertRaises(LedgerError): plans.approve(self.ledger, 'P1', 'owner', 'ref', revision=1)             # only the latest

    def test_propose_twice_is_refused_use_amend(self):
        self.propose()
        with self.assertRaises(LedgerError): self.propose()


class DispatchGateTests(Fixture):
    WORK = {'schema_version': 1, 'goal': 'A work job', 'acceptance': ['done'], 'preserve': ['everything'], 'authority': {},
            'authorized_by': {'source': 'user', 'reference': 'test'}}

    def work_job(self, key='job1'):
        return submit(self.ledger, None, key, mode='work', provider='kiro', model='claude-sonnet-5', contract=dict(self.WORK))['id']

    def test_enforcement_is_opt_in_so_v1_behaves_as_before(self):
        task = self.work_job()
        self.assertFalse(gate.enforced(self.ledger))
        self.assertIsNone(solution_gate.check(self.ledger, task))                  # v1: a work job needs no SOL and no plan

    def test_work_mode_without_an_approved_plan_cannot_be_dispatched(self):
        task = self.work_job()
        gate.set_enforced(self.ledger, True, 'owner', 'test')
        with self.assertRaises(LedgerError) as caught: solution_gate.check(self.ledger, task)
        self.assertIn('no plan named job1', str(caught.exception))
        with self.assertRaises(LedgerError): Owned(self.ledger).enable(task)       # the real start path (job start) refuses too
        with self.assertRaises(LedgerError): Owned(self.ledger).resume(task)
        self.propose('job1')                                                       # proposed is not approved
        with self.assertRaises(LedgerError) as caught: solution_gate.check(self.ledger, task)
        self.assertIn('proposed, not approved', str(caught.exception))
        plans.approve(self.ledger, 'job1', 'owner', 'ref')
        self.assertIsNone(solution_gate.check(self.ledger, task))                  # approved: the gate opens
        plans.amend(self.ledger, 'job1', plan_json(title='Changed'), 'scope changed', 'claude')
        with self.assertRaises(LedgerError): solution_gate.check(self.ledger, task)  # the new revision is not approved yet

    def test_other_modes_are_gated_too_and_refusals_become_ledger_events(self):
        audit = submit(self.ledger, 'Audit it', 'job2')['id']
        gate.set_enforced(self.ledger, True, 'owner', 'test')
        with self.assertRaises(LedgerError): solution_gate.check(self.ledger, audit)
        self.assertEqual(gate.sync_refusals(self.ledger), 1)
        self.assertEqual(gate.sync_refusals(self.ledger), 0)                       # idempotent
        refused = [e for e in self.ledger.events(audit) if e['kind'] == 'dispatch.refused_no_plan']
        self.assertEqual(len(refused), 1)
        self.assertEqual(refused[0]['payload']['request_key'], 'job2')

    def test_an_edited_plan_file_closes_the_gate(self):
        task = self.work_job('P1'); gate.set_enforced(self.ledger, True, 'owner', 'test')
        self.approved('P1')
        self.assertIsNone(solution_gate.check(self.ledger, task))
        path = contracts.revision_path(self.ledger, 'P1', 1)
        path.write_text(path.read_text(encoding='utf-8').replace('"max_calls": 10', '"max_calls": 9999'), encoding='utf-8')
        with self.assertRaises(LedgerError): solution_gate.check(self.ledger, task)

    def test_only_the_owner_can_turn_enforcement_off(self):
        cli_args = ['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'plan', 'enforce']
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(cli_args + ['on', '--by', 'claude', '--reference', 'r']), 2)
            self.assertFalse(gate.enforced(self.ledger))
            self.assertEqual(cli.main(cli_args + ['on', '--by', 'owner', '--reference', 'r']), 0)
            self.assertTrue(gate.enforced(self.ledger))
            self.assertEqual(cli.main(cli_args + ['off', '--by', 'claude', '--reference', 'r']), 2)
        self.assertTrue(gate.enforced(self.ledger))


class VerdictTests(Fixture):
    def test_command_verifier_runs_and_records_a_bound_pass(self):
        self.approved()
        view = verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(view['milestones'][0]['state'], 'passed')
        last = view['milestones'][0]['last_verdict']
        self.assertEqual((last['result'], last['by'], last['artifact_sha']), ('pass', 'command', self.tree()))
        receipt = json.loads(Snapshots(self.ledger.state_root).read_blob(last['receipt']))
        self.assertEqual((receipt['exit_code'], receipt['argv']), (0, OK))
        self.assertEqual(Snapshots(self.ledger.state_root).read_blob(receipt['stdout']).strip(), b'ok')

    def test_a_verdict_with_the_wrong_artifact_sha_is_refused(self):
        self.approved()
        blob, body = self.receipt()
        with self.assertRaises(LedgerError) as caught:
            verdict.record(self.ledger, 'P1', 'M1', 'pass', 'command', blob, 'f' * 40)
        self.assertIn('does not match', str(caught.exception))
        with self.assertRaises(LedgerError): verdict.record(self.ledger, 'P1', 'M1', 'pass', 'command', blob, 'not-a-sha')
        self.assertEqual(plans.show(self.ledger, 'P1')['milestones'][0]['state'], 'pending')
        with self.assertRaises(LedgerError): verdict.record(self.ledger, 'P1', 'M1', 'pass', 'command', blob, body['artifact_sha'])   # not issued
        self.issue(blob)
        verdict.record(self.ledger, 'P1', 'M1', 'pass', 'command', blob, body['artifact_sha'])      # the right sha, an issued receipt

    def test_a_pass_cannot_be_typed_in(self):
        # Each bad receipt is announced as issued first, so it is the receipt's CONTENT (not the issued check) that must refuse it.
        self.approved()
        def refused(**fields):
            blob, _ = self.receipt(**fields); self.issue(blob)
            with self.assertRaises(LedgerError): verdict.record(self.ledger, 'P1', 'M1', 'pass', 'command', blob, self.tree())
        refused(exit_code=3)
        refused(artifact_sha_after='0' * 40)                                  # the command changed the tree it verified
        refused(milestone='M2')
        refused(argv=[PY, '-c', 'pass'])
        refused(timed_out=True)
        with self.assertRaises(LedgerError): verdict.record(self.ledger, 'P1', 'M1', 'pass', 'command', 'a' * 64, self.tree())  # no such blob
        with self.assertRaises(LedgerError): verdict.record(self.ledger, 'P1', 'M1', 'pass', 'claude', self.receipt()[0], self.tree())
        self.assertEqual(plans.show(self.ledger, 'P1')['milestones'][0]['state'], 'pending')

    def test_a_verdict_needs_an_approved_plan_and_goes_in_order(self):
        self.propose()
        blob, _ = self.receipt()
        with self.assertRaises(LedgerError): verdict.record(self.ledger, 'P1', 'M1', 'pass', 'command', blob, self.tree())  # not approved
        plans.amend(self.ledger, 'P1', plan_json(milestones=[milestone('M1'), milestone('M2')]), 'two steps', 'claude')
        plans.approve(self.ledger, 'P1', 'owner', 'ref')
        with self.assertRaises(LedgerError) as caught: verdict.run(self.ledger, 'P1', 'M2', self.root)
        self.assertIn('M1 has not passed', str(caught.exception))
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        with self.assertRaises(LedgerError): verdict.run(self.ledger, 'P1', 'M1', self.root)       # already passed for this artifact
        self.assertEqual(verdict.run(self.ledger, 'P1', 'M2', self.root)['milestones'][1]['state'], 'passed')

    def test_a_verdict_does_not_survive_an_amendment(self):
        self.approved(); verdict.run(self.ledger, 'P1', 'M1', self.root)
        plans.amend(self.ledger, 'P1', plan_json(title='Different', milestones=[milestone('M1', title='Rescoped milestone')]), 'rescoped', 'claude')   # 2.2.0.dev2: an unchanged milestone is carried over (tests/test_v3_verify_cost.py); a changed one is not
        plans.approve(self.ledger, 'P1', 'owner', 'ref')
        self.assertEqual(plans.show(self.ledger, 'P1')['milestones'][0]['state'], 'pending')
        with self.assertRaises(LedgerError): plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())

    def test_owner_manual_verdicts_are_the_owners(self):
        manual = {'id': 'M1', 'title': 'Looks right', 'verifier': {'type': 'owner-manual'}, 'covers': ['O1']}
        self.approved(value=plan_json(milestones=[manual]))
        blob = Snapshots(self.ledger.state_root).blob('Checked on the device by the owner.\n'.encode())
        for by in ('claude', 'command', 'reviewer'):
            with self.assertRaises(LedgerError): verdict.record(self.ledger, 'P1', 'M1', 'pass', by, blob, self.tree())
        os.environ['ONECREW_ACTOR'] = 'codex'
        with self.assertRaises(LedgerError): verdict.record(self.ledger, 'P1', 'M1', 'pass', 'owner', blob, self.tree())
        os.environ.pop('ONECREW_ACTOR')
        self.assertEqual(verdict.record(self.ledger, 'P1', 'M1', 'pass', 'owner', blob, self.tree())['milestones'][0]['state'], 'passed')

    def test_command_output_is_captured_as_utf8(self):
        self.approved(value=plan_json(milestones=[milestone(argv=[PY, '-c', 'print("Việt Nam")'])]))
        view = verdict.run(self.ledger, 'P1', 'M1', self.root)
        store = Snapshots(self.ledger.state_root)
        receipt = json.loads(store.read_blob(view['milestones'][0]['last_verdict']['receipt']))
        self.assertEqual(store.read_blob(receipt['stdout']).decode('utf-8').strip(), 'Việt Nam')

    def test_timeout_and_a_changed_tree_are_inconclusive_not_pass(self):
        self.approved(value=plan_json(milestones=[milestone(argv=[PY, '-c', 'import time; time.sleep(30)'])]))
        with self.ledger.transaction() as conn:
            state = plans.derive(self.ledger, conn, 'P1'); contract, sha = plans.load(self.ledger, state)
        slow = dict(contract['milestones'][0]); slow['verifier'] = {'type': 'command', 'config': dict(slow['verifier']['config'], max_minutes=0.02)}
        _, receipt = command.run(self.ledger, 'P1', 1, sha, slow, self.root)
        self.assertTrue(receipt['timed_out'])
        self.assertEqual(command.expected_result(receipt), 'inconclusive')
        writer = dict(slow); writer['verifier'] = {'type': 'command', 'config': {'argv': [PY, '-c', 'open(%r,"w").write("x")' % str(self.root / 'new.txt')], 'max_minutes': 1}}  # L2: the command runs on a scratch checkout, so it reaches the live tree only by an absolute path
        _, receipt = command.run(self.ledger, 'P1', 1, sha, writer, self.root)
        self.assertEqual((receipt['exit_code'], command.expected_result(receipt)), (0, 'inconclusive'))
        self.assertNotEqual(receipt['artifact_sha'], receipt['artifact_sha_after'])


class StopTests(Fixture):
    def failing(self, repairs=1, questions=1):
        return plan_json(milestones=[milestone(argv=BAD, max_repairs=repairs)], attention={'questions': questions})

    def test_a_once_milestone_stops_after_max_repairs_and_asks_the_owner_once(self):
        self.approved(value=self.failing())
        first = verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual((first['status'], first['milestones'][0]['repairs_left']), ('approved', 0))   # one repair round remains to be tried
        self.assertNotIn('stopped', first)
        second = verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(second['status'], 'stopped_with_report')
        self.assertEqual(second['milestones'][0]['state'], 'stopped')
        self.assertEqual(second['stopped']['question'], 'created')
        self.assertEqual((second['attention']['questions_used'], second['attention']['questions_limit']), (1, 1))
        request = self.ledger.request(second['stopped']['request'])
        self.assertEqual(request['state'], 'pending')
        self.assertEqual(request['question']['action']['type'], 'v2.plan_stopped')
        with self.assertRaises(LedgerError): verdict.run(self.ledger, 'P1', 'M1', self.root)   # the AI cannot try again past the limit
        blob, body = self.receipt(exit_code=0)
        with self.assertRaises(LedgerError): verdict.record(self.ledger, 'P1', 'M1', 'pass', 'command', blob, body['artifact_sha'])
        self.assertIn('milestone.stopped', self.kinds())

    def test_a_stopped_plan_is_not_dispatchable_and_not_acceptable(self):
        task = submit(self.ledger, 'Audit it', 'P1')['id']
        self.approved(value=self.failing(repairs=0)); gate.set_enforced(self.ledger, True, 'owner', 'test')
        self.assertIsNone(solution_gate.check(self.ledger, task))
        self.assertEqual(verdict.run(self.ledger, 'P1', 'M1', self.root)['status'], 'stopped_with_report')   # max_repairs 0: first failure
        with self.assertRaises(LedgerError): solution_gate.check(self.ledger, task)
        with self.assertRaises(LedgerError): plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())

    def test_the_attention_budget_refuses_a_second_question(self):
        self.approved(value=self.failing(repairs=0, questions=1))
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        plans.amend(self.ledger, 'P1', plan_json(milestones=[milestone(argv=BAD, max_repairs=0)], attention={'questions': 1}, title='Retry'), 'try again', 'claude')
        plans.approve(self.ledger, 'P1', 'owner', 'ref')
        again = verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual(again['status'], 'stopped_with_report')                  # the stop stands ...
        self.assertEqual(again['stopped']['question'], 'refused')                 # ... but the owner is not asked a second time
        self.assertEqual(len(self.ledger.requests(again['anchor_task'])), 1)
        self.assertIn('attention.exceeded', self.kinds())

    def test_inconclusive_counts_as_a_failed_run(self):
        self.approved(value=plan_json(milestones=[milestone(max_repairs=0)]))
        blob, body = self.receipt(timed_out=True, exit_code=None)
        self.issue(blob)
        view = verdict.record(self.ledger, 'P1', 'M1', 'inconclusive', 'command', blob, body['artifact_sha'])
        self.assertEqual(view['status'], 'stopped_with_report')


class AcceptTests(Fixture):
    def test_accept_is_refused_until_every_milestone_has_a_passing_verdict(self):
        self.approved(value=plan_json(milestones=[milestone('M1'), milestone('M2')]))
        tree = self.tree()
        with self.assertRaises(LedgerError) as caught: plans.accept(self.ledger, 'P1', 'owner', 'ref', tree)
        self.assertIn('M1, M2', str(caught.exception))
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        with self.assertRaises(LedgerError) as caught: plans.accept(self.ledger, 'P1', 'owner', 'ref', tree)
        self.assertIn('M2', str(caught.exception))
        verdict.run(self.ledger, 'P1', 'M2', self.root)
        with self.assertRaises(LedgerError): plans.accept(self.ledger, 'P1', 'owner', 'ref', 'e' * 40)   # not the verified artifact
        self.assertEqual(plans.show(self.ledger, 'P1')['status'], 'approved')
        self.assertEqual(plans.accept(self.ledger, 'P1', 'owner', 'ref', tree)['status'], 'accepted')
        self.assertEqual(plans.accept(self.ledger, 'P1', 'owner', 'ref', tree)['status'], 'accepted')    # repeat: no second event
        self.assertEqual(self.kinds().count('plan.accepted'), 1)
        with self.assertRaises(LedgerError): plans.amend(self.ledger, 'P1', plan_json(title='After'), 'late', 'claude')

    def test_a_failed_verdict_does_not_allow_accept_and_an_ai_cannot_accept(self):
        self.approved(value=plan_json(milestones=[milestone(argv=BAD, max_repairs=3)]))
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        with self.assertRaises(LedgerError): plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())
        for by in ('claude', 'command'):
            with self.assertRaises(LedgerError): plans.accept(self.ledger, 'P1', by, 'ref', self.tree())
        os.environ['ONECREW_ACTOR'] = 'claude'
        with self.assertRaises(LedgerError): plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())

    def test_nothing_but_approve_and_accept_writes_those_events(self):
        # Every path that records plan state, run end to end: the only commands that add plan.approved / plan.accepted are the two owner commands.
        self.propose()
        os.environ['ONECREW_ACTOR'] = 'claude'
        for attempt in (lambda: plans.approve(self.ledger, 'P1', 'owner', 'r'), lambda: plans.accept(self.ledger, 'P1', 'owner', 'r', 'a' * 40),
                        lambda: plans.amend(self.ledger, 'P1', plan_json(title='Y'), 'why', 'claude')):
            with contextlib.suppress(LedgerError): attempt()
        self.assertNotIn('plan.approved', self.kinds()); self.assertNotIn('plan.accepted', self.kinds())


class ForgeryTests(Fixture):
    """F1 (Opus review 1): a hand-written receipt with the real plan_sha and argv, exit 0, must not buy a pass."""

    def forged_file(self):
        with self.ledger.transaction() as conn:
            sha = plans.derive(self.ledger, conn, 'P1')['revisions'][1]['sha']
        body = {'kind': 'command-receipt', 'plan': 'P1', 'revision': 1, 'plan_sha': sha, 'milestone': 'M1', 'argv': BAD, 'exit_code': 0,
                'timed_out': False, 'error': None, 'artifact_sha': self.tree(), 'artifact_sha_after': self.tree()}
        path = Path(self.temp.name) / 'forged.json'; path.write_text(json.dumps(body), encoding='utf-8')
        return path

    def cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), *argv])
        return code, json.loads(out.getvalue())

    def test_the_exact_forgery_from_the_review_is_refused_and_acceptance_stays_closed(self):
        self.approved(value=plan_json(milestones=[milestone(argv=BAD)]))
        forged = self.forged_file(); tree = self.tree()
        code, out = self.cli('verdict', 'record', '--plan', 'P1', '--milestone', 'M1', '--result', 'pass', '--by', 'command',
                             '--receipt-file', str(forged), '--artifact-sha', tree)
        self.assertEqual(code, 2); self.assertIn('only for an owner-manual', out['error'])
        blob = Snapshots(self.ledger.state_root).blob(forged.read_bytes())          # stored by other means, then named
        code, out = self.cli('verdict', 'record', '--plan', 'P1', '--milestone', 'M1', '--result', 'pass', '--by', 'command',
                             '--receipt', blob, '--artifact-sha', tree)
        self.assertEqual(code, 2); self.assertIn('not issued by verdict run', out['error'])
        with self.assertRaises(LedgerError): verdict.record(self.ledger, 'P1', 'M1', 'pass', 'command', blob, tree)
        self.assertEqual(plans.show(self.ledger, 'P1')['milestones'][0]['state'], 'pending')
        with self.assertRaises(LedgerError): plans.accept(self.ledger, 'P1', 'owner', 'ref', tree)
        self.assertEqual(verdict.run(self.ledger, 'P1', 'M1', self.root)['milestones'][0]['last_verdict']['result'], 'fail')  # the real command fails
        self.assertEqual(self.kinds().count('verdict.receipt_issued'), 1)

    def test_a_receipt_issued_for_another_milestone_does_not_carry_over(self):
        self.approved(value=plan_json(milestones=[milestone('M1'), milestone('M2')]))
        blob, body = self.receipt(milestone='M2')
        self.issue(blob, milestone='M1')                                              # issued for M1, content says M2
        with self.assertRaises(LedgerError): verdict.record(self.ledger, 'P1', 'M2', 'pass', 'command', blob, body['artifact_sha'])


class LatestVerdictTests(Fixture):
    """F2: every milestone must have passed on exactly the artifact being accepted."""

    def test_accept_needs_every_milestone_to_pass_on_the_accepted_artifact(self):
        self.approved(value=plan_json(milestones=[milestone('M1'), milestone('M2')]))
        verdict.run(self.ledger, 'P1', 'M1', self.root); first = self.tree()
        (self.root / 'a.txt').write_text('changed after M1\n')
        verdict.run(self.ledger, 'P1', 'M2', self.root); second = self.tree()
        self.assertNotEqual(first, second)
        with self.assertRaises(LedgerError) as caught: plans.accept(self.ledger, 'P1', 'owner', 'ref', second)
        message = str(caught.exception)
        self.assertIn(f'M1 passed on {first}', message); self.assertIn(f'M2 passed on {second}', message)
        with self.assertRaises(LedgerError): plans.accept(self.ledger, 'P1', 'owner', 'ref', first)
        verdict.run(self.ledger, 'P1', 'M1', self.root)                               # the milestone that differs is re-run on the new tree
        self.assertEqual(plans.accept(self.ledger, 'P1', 'owner', 'ref', second)['status'], 'accepted')

    def test_a_later_failure_reopens_a_passed_milestone(self):
        check = 'import pathlib,sys; print("checked"); sys.exit(0 if pathlib.Path("a.txt").read_text().startswith("one") else 1)'
        self.approved(value=plan_json(milestones=[milestone('M1', argv=[PY, '-c', check], max_repairs=2)]))
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        (self.root / 'a.txt').write_text('broken\n')
        view = verdict.run(self.ledger, 'P1', 'M1', self.root)
        self.assertEqual((view['milestones'][0]['state'], view['milestones'][0]['failures']), ('failed', 1))
        with self.assertRaises(LedgerError): plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())


class WorkspaceTests(Fixture):
    """F3: verdict run only looks at the plan's project."""

    def test_a_clean_clone_outside_the_project_is_refused(self):
        self.approved(value=plan_json(milestones=[milestone(argv=BAD)]))
        clone = Path(self.temp.name) / 'clean-clone'
        subprocess.check_call(['git', 'clone', '-q', str(self.root), str(clone)])
        with self.assertRaises(LedgerError) as caught: verdict.run(self.ledger, 'P1', 'M1', clone)
        self.assertIn('outside the plan', str(caught.exception))
        self.assertEqual(plans.show(self.ledger, 'P1')['milestones'][0]['runs'], 0)

    def test_a_directory_inside_the_project_is_allowed_and_its_cwd_is_shown(self):
        self.approved()
        (self.root / 'sub').mkdir(); (self.root / 'sub' / 'x.txt').write_text('x\n')
        view = verdict.run(self.ledger, 'P1', 'M1', self.root / 'sub')
        self.assertEqual(Path(view['milestones'][0]['last_verdict']['cwd']), (self.root / 'sub').resolve())
        with self.assertRaises(LedgerError): verdict.run(self.ledger, 'P1', 'M1', self.root / '..')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'plan', 'show', 'P1'])
        self.assertEqual(Path(json.loads(out.getvalue())['milestones'][0]['last_verdict']['cwd']), (self.root / 'sub').resolve())


class PolicyAndBudgetTests(Fixture):
    """F4, F5, F6."""
    WORK = DispatchGateTests.WORK
    work_job = DispatchGateTests.work_job

    def test_an_unreadable_policy_file_closes_the_gate(self):
        task = self.work_job()
        self.assertFalse(gate.enforced(self.ledger))                                  # no file: v1 as before
        policy = Path(self.ledger.state_root) / 'plans' / 'policy.json'
        policy.parent.mkdir(parents=True, exist_ok=True)
        for broken in ('{"require_plan": tr', '', '[]', '\x00\x01'):
            policy.write_text(broken, encoding='utf-8')
            self.assertTrue(gate.enforced(self.ledger), broken)
            with self.assertRaises(LedgerError): solution_gate.check(self.ledger, task)

    def test_the_policy_is_written_through_a_temporary_file(self):
        gate.set_enforced(self.ledger, True, 'owner', 'r'); gate.set_enforced(self.ledger, False, 'owner', 'r')
        names = sorted(p.name for p in (Path(self.ledger.state_root) / 'plans').iterdir())
        self.assertEqual(names, ['audit.jsonl', 'policy.json'])
        with patch('os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): gate.set_enforced(self.ledger, True, 'owner', 'r')
        self.assertFalse(gate.enforced(self.ledger))                                  # the old policy is intact

    def test_a_job_cannot_carry_larger_limits_than_the_approved_plan_budget(self):
        gate.set_enforced(self.ledger, True, 'owner', 'test')
        value = plan_json(budget={'max_calls': 20, 'time': 30})
        for key in ('big', 'long', 'ok'): self.approved(key, value)
        make = lambda key, **limits: submit(self.ledger, None, key, mode='work', provider='kiro', model='claude-sonnet-5',
                                            contract=dict(self.WORK), **limits)['id']
        calls, seconds, fine = make('big', max_calls=5000), make('long', max_calls=20, max_seconds=3600), make('ok', max_calls=20, max_seconds=1800)
        with self.assertRaises(LedgerError) as caught: solution_gate.check(self.ledger, calls)
        self.assertIn('5000 calls', str(caught.exception)); self.assertIn('budget is 20', str(caught.exception))
        with self.assertRaises(LedgerError) as caught: solution_gate.check(self.ledger, seconds)
        self.assertIn('3600 seconds', str(caught.exception)); self.assertIn('1800', str(caught.exception))
        self.assertIsNone(solution_gate.check(self.ledger, fine))

    def test_a_damaged_refusal_spool_line_is_skipped_with_a_warning(self):
        audit = submit(self.ledger, 'Audit it', 'job2')['id']
        gate.set_enforced(self.ledger, True, 'owner', 'test')
        with self.assertRaises(LedgerError): solution_gate.check(self.ledger, audit)
        spool = Path(self.ledger.state_root) / 'plans' / 'refusals.jsonl'
        with spool.open('a', encoding='utf-8') as stream: stream.write('{"id": "half a line\n[1,2]\n{"id": 5}\n')
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors): self.assertEqual(gate.sync_refusals(self.ledger), 1)
        self.assertIn('skipped 3 unreadable line(s)', errors.getvalue())
        self.propose('P9')
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'plan', 'approve', 'P9', '--by', 'owner', '--reference', 'r'])
        self.assertEqual(code, 0)                                                      # the owner can still approve


class LedgerEventTests(Fixture):
    def test_every_step_leaves_a_ledger_event(self):
        self.approved(value=plan_json(milestones=[milestone(argv=BAD, max_repairs=0)]))
        verdict.run(self.ledger, 'P1', 'M1', self.root)
        plans.amend(self.ledger, 'P1', plan_json(), 'fix the command', 'claude')
        plans.approve(self.ledger, 'P1', 'owner', 'ref'); verdict.run(self.ledger, 'P1', 'M1', self.root)
        plans.accept(self.ledger, 'P1', 'owner', 'ref', self.tree())
        kinds = self.kinds()
        for kind in ('plan.proposed', 'plan.approved', 'plan.amended', 'plan.accepted', 'verdict.recorded', 'milestone.passed',
                     'milestone.failed', 'milestone.stopped'):
            self.assertIn(kind, kinds)
        approved = [p for k, p in self.events() if k == 'plan.approved'][0]
        self.assertEqual((approved['by'], approved['reference']), ('owner', 'said yes in chat'))
        self.assertTrue(all('at' in p for k, p in self.events() if k.startswith(('plan.', 'verdict.', 'milestone.'))))


class CliTests(Fixture):
    def cli(self, *argv, stdin_env=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), *argv])
        return code, json.loads(out.getvalue())

    def test_the_whole_flow_through_the_router(self):
        file = Path(self.temp.name) / 'plan.json'; file.write_text(json.dumps(plan_json()), encoding='utf-8')
        self.assertEqual(self.cli('plan', 'propose', 'P1', '--file', str(file), '--author', 'claude')[1]['status'], 'proposed')
        code, out = self.cli('plan', 'approve', 'P1', '--by', 'claude', '--reference', 'x')
        self.assertEqual(code, 2)
        self.assertEqual(self.cli('plan', 'approve', 'P1', '--by', 'owner', '--reference', 'chat 19/10')[1]['status'], 'approved')
        code, out = self.cli('plan', 'accept', 'P1', '--by', 'owner', '--reference', 'x', '--artifact-sha', self.tree())
        self.assertEqual(code, 2); self.assertIn('no passing verdict', out['error'])
        self.assertEqual(self.cli('verdict', 'run', '--plan', 'P1', '--milestone', 'M1')[1]['milestones'][0]['state'], 'passed')
        self.assertEqual(self.cli('plan', 'accept', 'P1', '--by', 'owner', '--reference', 'x', '--artifact-sha', self.tree())[1]['status'], 'accepted')
        self.assertEqual(self.cli('plan', 'show', 'P1')[1]['status'], 'accepted')

    def test_owner_manual_receipt_file(self):
        manual = {'id': 'M1', 'title': 'Looks right', 'verifier': {'type': 'owner-manual'}, 'covers': ['O1']}
        self.approved(value=plan_json(milestones=[manual]))
        note = Path(self.temp.name) / 'note.txt'; note.write_text('Đã kiểm tay\n', encoding='utf-8')
        code, out = self.cli('verdict', 'record', '--plan', 'P1', '--milestone', 'M1', '--result', 'pass', '--by', 'owner',
                             '--artifact-sha', self.tree(), '--receipt-file', str(note))
        self.assertEqual((code, out['milestones'][0]['state']), (0, 'passed'))

    def test_v1_verbs_still_route_as_before(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main([]), 0)
        self.assertIn('job        submit', out.getvalue())
        self.assertIn('plan       propose', out.getvalue())


if __name__ == '__main__':
    unittest.main()
