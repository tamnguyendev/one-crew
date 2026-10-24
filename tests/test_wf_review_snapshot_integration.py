"""W15 integration (T04b): the REAL reviewer verifier reviews a fixed candidate snapshot while independent work and the project move on.

Native producer (fake worker through the real CLI), CandidateChecker with an approved reviewer milestone and reviewer.call replaced
by a fixture CLI answer (interface only: no real provider). While the reviewer is "thinking", an independent node is produced and
the project working tree changes; the reviewer receipt must still name the candidate tree it was given and its diff must be that
of the snapshot, not of the later change.
"""
import contextlib
import io
import json
import sys
from unittest.mock import patch

from onecrew import cli
from onecrew.v2.verifiers import reviewer
from tests.test_v2_l1 import milestone
from tests.test_v2_reviewer import answer, row, reviewer_milestone
from tests.test_wf_candidate_reviewer import CandidateReviewerFixture, CRITERIA
from tests.test_wf_engine import node

B_CANDIDATE = 'b candidate' + chr(10)
A_CANDIDATE = 'candidate' + chr(10)
LATER = 'later change in the project' + chr(10)


class ReviewSnapshotIntegrationTests(CandidateReviewerFixture):
    def setUp(self):
        # the same fixture as CandidateFixture, with b.txt in the owned scope for the independent node X
        import os
        from onecrew.common_verification import CandidateChecker
        from onecrew.control import Control, migrate
        from onecrew.snapshots import Snapshots
        from onecrew.v2 import engine, internal_plan, plan as plans
        from tests.test_v2_l1 import Fixture, plan_json
        Fixture.setUp(self)
        (self.root / 'b.txt').write_text('b' + chr(10)); self.git('add', 'b.txt'); self.git('commit', '-qm', 'b')
        self.engine, self.ip = engine, internal_plan
        self.engine_caps = ['namespaced-storage', 'root-budget', 'internal-plan', 'sequential-engine']
        selected = self.milestones(); self.check_ids = [row['id'] for row in selected]
        value = plan_json(milestones=selected, scope={'owned': ['a.txt', 'b.txt']}, authority={
            'edit': True, 'commands': True, 'apply_to_project': True, 'unconfined_commands': True,
            'self_decide': ['Q1', 'Q2', 'Q3', 'Q4', 'Q9', 'Q12']})
        value['understanding']['target']['paths'] = ['a.txt', 'b.txt']
        self.root_view = plans.propose(self.ledger, 'P1', value, 'codex', workflow=True, capabilities=self.engine_caps)
        plans.approve(self.ledger, 'P1', 'owner', 'fixture approved command and apply')
        os.environ['ONECREW_ACTOR'] = 'codex'
        self.store = Snapshots(self.ledger.state_root)
        migrate(self.ledger); self.control = Control(self.ledger)
        self.production_checker = CandidateChecker(self.ledger, 'P1')

    def milestones(self):
        check = [sys.executable, '-c', 'from pathlib import Path; assert Path("a.txt").read_text()=="candidate\\n"; print("candidate tested")']
        return [milestone('M1', argv=check), dict(reviewer_milestone(criteria=CRITERIA), id='M2')]

    def definition(self):
        code = node('C'); code['checks'] = [{'id': cid, 'spec': 'approved ' + cid} for cid in self.check_ids]
        other = node('X', write=('b.txt',)); other['read'] = ['b.txt']; other['checks'] = [{'id': 'M1', 'spec': 'approved M1'}]
        integration = node('I', ['C', 'X'], integration=True, write=()); integration['read'] = []
        integration['checks'] = [{'id': cid, 'spec': 'approved ' + cid} for cid in self.check_ids]
        return [code, other, integration]

    def factory(self, control, provider):
        """One fake worker for both nodes: the file it writes follows the node named in the prompt (no provider call)."""
        class Worker:
            def capability(self): return {'provider': provider, 'mode': 'fixture-tools-disabled'}
            def run(self, attempt, prompt, schema, profile):
                self.node = 'X' if ('"id":"X"' in prompt or '"id": "X"' in prompt) else 'C'
                control.launched(attempt['id'], attempt['generation'], {'fixture': True})
                control.finish(attempt['id'], attempt['generation'], {'exit_code': 0})
            def result(self, attempt):
                path, content = ('b.txt', B_CANDIDATE) if self.node == 'X' else ('a.txt', A_CANDIDATE)
                return {'summary': 'producer ' + self.node, 'files': [{'path': path, 'content': content}], 'backlog': []}, []
        return Worker()

    def step_cli(self, expect):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'engine', 'step', 'plan-ns:P1'])
        self.assertEqual(code, 0, out.getvalue())
        value = json.loads(out.getvalue())
        self.assertEqual(value['node'], expect)
        return value

    def test_reviewer_reviews_the_fixed_snapshot_while_an_independent_node_and_the_project_move_on(self):
        definition = self.definition()
        for item in definition: item['executor'] = dict(self.producer)
        self.revise(definition)
        seen = {}
        def fake(prompt, config, env, scratch, limit):
            seen['prompt'] = prompt
            # independent work continues while the review runs: X is produced through the same CLI, and the project tree changes
            seen['x'] = self.step_cli('X')
            (self.root / 'a.txt').write_text(LATER)
            return answer(row('R1')), {}, None, False, b'fixture'
        with patch('onecrew.artifact_provider_core.make_worker', side_effect=self.factory):
            self.step_cli('C')                                      # C produced (A1)
            a1 = self.engine.state(self.ledger, 'P1')['nodes']['C']['artifact']
            with patch.object(reviewer, 'call', side_effect=fake):
                result = self.engine.verify(self.ledger, 'P1', 'C', self.production_checker)
        self.assertEqual(result['result'], 'pass', result)
        rows = {r['id']: r for r in result['observed']['checks']}
        wrapper = json.loads(self.store.read_blob(rows['M2']['evidence']))
        proof = json.loads(self.store.read_blob(wrapper['reviewer_receipt']))
        tree = result['observed']['candidate_tree']
        self.assertEqual((proof['artifact_sha'], proof['artifact_sha_after']), (tree, tree))          # [E2] the receipt names the snapshot
        self.assertEqual(proof['calls'], 1); self.assertEqual(proof['provider'], 'claude')
        diff = self.store.read_blob(proof['diff']).decode('utf-8')
        self.assertIn('+candidate', diff); self.assertNotIn('later change', diff)                       # [E2] the diff is A1's, not the later tree
        self.assertNotIn('later change', seen['prompt'])
        after = self.engine.state(self.ledger, 'P1')
        self.assertEqual(after['nodes']['C']['artifact'], a1); self.assertEqual(after['nodes']['C']['state'], 'verified')
        self.assertEqual(after['nodes']['X']['state'], 'produced', seen.get('x'))                      # independent work went on
        self.assertEqual(self.store.context(after['nodes']['X']['artifact'])['b.txt'], B_CANDIDATE)
        self.assertEqual((self.root / 'a.txt').read_text(), LATER)                                      # the project was never touched by the review
