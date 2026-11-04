"""RV-T6: investigation review through the optional door: the paths and probes named inside the node scope and the root grant, in a disposable
copy of the candidate; the provider is a fixture standing in for reviewer.call. Whether a real provider gives useful investigations is unproven."""
import contextlib
import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))          # test_v2_reviewer imports test_v2_l1 by its plain name

from onecrew import budget_core
from onecrew.common_verification import INVESTIGATION_LABEL, InvestigationChecker
from onecrew.ledger import LedgerError
from onecrew.snapshots import Snapshots
from onecrew.v2 import engine, engine_cli, plan, review_dispatch
from onecrew.v2.verifiers import command, reviewer
from tests import test_wf_candidate_handoff as handoff_fixture
from tests.test_v2_l1 import plan_json

ANSWER = json.dumps({'findings': [{'claim': 'a.txt holds the candidate line', 'evidence': 'a.txt:1'}],
                     'not_investigated': ['performance under load'], 'summary': 'Read one file.'})


class InvestigationFixture(handoff_fixture.CandidateFixture):
    commands = True

    def setUp(self):
        def with_policy(**kw):
            kw['authority'] = dict(kw['authority'], commands=self.commands)
            if not self.commands: kw['authority'].pop('unconfined_commands', None)
            return plan_json(review_policy={'depth': 'deep', 'optional_reviews': ['investigate']}, **kw)
        with patch.object(handoff_fixture, 'plan_json', side_effect=with_policy):
            super().setUp()
        cfg = self.root / 'cfg'; cfg.mkdir()
        (cfg / '.env').write_text('DB_PASS=never-send-this-env-value\n', encoding='utf-8')
        (cfg / 'app.ini').write_text('API_KEY=never-send-this-ini-value\n', encoding='utf-8')
        (cfg / 'note.txt').write_text('plain note\n', encoding='utf-8')
        self.git('add', '-f', '.'); self.git('commit', '-qm', 'configuration files')
        nodes = self.definition()
        nodes[0]['read'] = ['a.txt', 'cfg']
        self.revise(nodes)
        self.step()
        self.prompts = []

    def call(self, prompt, config, env, scratch, limit):
        self.prompts.append(prompt)
        return ANSWER, {}, None, False, b'fixture'

    def artifact(self):
        return engine.state(self.ledger, 'P1')['nodes']['C']['artifact']

    def investigate(self, call=None, **config):
        values = dict({'provider': 'claude', 'model': 'claude-haiku-5-5', 'question': 'Does a.txt hold the candidate line?', 'paths': ['a.txt']}, **config)
        port = InvestigationChecker(self.ledger, 'P1', 'investigate', values, call=call or self.call)
        return engine.review_optional(self.ledger, 'P1', 'C', 'investigate', port, self.artifact())

    def used(self):
        with self.ledger.transaction() as conn:
            root = plan.anchor_events(self.ledger, conn, 'P1')
            return budget_core.group(conn, root['task_id'])['used_calls']

    def observed(self, result):
        return json.loads(Snapshots(self.ledger.state_root).read_blob(result['receipt']))


class InvestigationReview(InvestigationFixture):
    def test_t6_result_is_a_limited_observation_and_is_reused_without_another_call(self):
        before = self.used()
        result = self.investigate()
        self.assertEqual(result['status'], 'observed')
        body = self.observed(result)
        observed = body['observed']
        self.assertEqual((body['kind'], body['authority']), ('optional-review-observation', 'none'))
        self.assertEqual((observed['label'], observed['full_review'], observed['method']), (INVESTIGATION_LABEL, False, 'investigation'))
        self.assertEqual(observed['scope']['read'], ['a.txt'])
        self.assertEqual(observed['not_investigated'], ['performance under load'])
        self.assertNotIn('result', observed)
        self.assertFalse(observed['candidate_modified']); self.assertFalse(observed['project_modified'])
        self.assertIn('candidate', self.prompts[0], 'the candidate bytes are what is read, not the project')
        self.assertEqual(engine.state(self.ledger, 'P1')['nodes']['C']['state'], 'produced')
        self.assertNotIn('node.verification', self.kinds())
        self.assertEqual(self.used(), before + 1)
        again = self.investigate(call=lambda *a: self.fail('the same request makes no second model call'))
        self.assertTrue(again['cached_observation'])
        self.assertEqual(again['receipt'], result['receipt'])
        self.assertEqual(self.used(), before + 1)
        other = self.investigate(question='Another question?')
        self.assertNotEqual(other['request_id'], result['request_id'])
        self.assertEqual(self.used(), before + 2)

    def test_t6_a_path_outside_the_node_scope_is_refused_before_any_call(self):
        before = self.used()
        with self.assertRaisesRegex(LedgerError, 'outside this node scope'):
            self.investigate(paths=['b.txt'], call=lambda *a: self.fail('no call'))
        finished = [p for k, p in self.events() if k == 'review.run_finished']
        self.assertEqual([p['outcome'] for p in finished], ['not_dispatched'])
        self.assertEqual(self.used(), before)

    def test_t6_secret_names_content_and_environment_never_reach_the_prompt(self):
        with self.assertRaisesRegex(LedgerError, 'credential paths'):
            self.investigate(paths=['a.txt', 'cfg/.env'], call=lambda *a: self.fail('no call'))
        with patch.dict(os.environ, {'OC_B2_SECRET': 'never-send-this-env-var'}):
            result = self.investigate(paths=['a.txt', 'cfg/app.ini', 'cfg/note.txt'],
                                      probes=[[sys.executable, '-c', 'import os; print(sorted(os.environ)); print(os.environ.get("OC_B2_SECRET", "absent"))']])
        prompt = self.prompts[0]
        for secret in ('never-send-this-env-value', 'never-send-this-ini-value', 'never-send-this-env-var'):
            self.assertNotIn(secret, prompt)
        self.assertIn('plain note', prompt)
        self.assertIn('absent', prompt)
        observed = self.observed(result)['observed']
        self.assertEqual(observed['scope']['read'], ['a.txt', 'cfg/note.txt'])
        self.assertEqual({row['reason'] for row in observed['scope']['withheld']}, {'secret'})
        self.assertEqual(len(observed['scope']['withheld']), 1)
        self.assertNotIn('never-send', json.dumps(observed))

    def test_t6_probes_write_only_in_the_disposable_copy(self):
        tree_before = command.artifact_sha(self.root)
        script = 'from pathlib import Path; Path("a.txt").write_text("changed by the probe\\n"); Path("new.txt").write_text("x"); print("probed")'
        result = self.investigate(probes=[[sys.executable, '-c', script]])
        observed = self.observed(result)['observed']
        self.assertEqual(observed['probes'][0]['exit_code'], 0)
        self.assertFalse(observed['candidate_modified']); self.assertFalse(observed['project_modified'])
        self.assertEqual((self.root / 'a.txt').read_text(), 'one\n')
        self.assertFalse((self.root / 'new.txt').exists())
        self.assertEqual(command.artifact_sha(self.root), tree_before)
        self.assertEqual(self.store.read_blob(self.store.load(self.artifact())['files']['a.txt']['working']), b'candidate\n')

    def test_t4_a_model_error_stays_an_observation_with_no_findings(self):
        result = self.investigate(call=lambda *a: ('', {}, 'provider failed', False, b''))
        observed = self.observed(result)['observed']
        self.assertEqual(observed['error'], 'provider failed')
        self.assertEqual(observed['findings'], [])
        self.assertEqual(engine.state(self.ledger, 'P1')['nodes']['C']['state'], 'produced')

    def test_t4_an_unknown_or_same_producer_is_said_not_counted_independent(self):
        real = self.ledger.task
        def pinned(pin):
            def task(task_id, **kwargs):
                row = real(task_id, **kwargs)
                return dict(row, handoff=dict(row['handoff'], owned_execution=pin)) if kwargs.get('full') else row
            return task
        with patch.object(self.ledger, 'task', side_effect=pinned({})):
            unknown = self.observed(self.investigate())['observed']['independence']
        self.assertEqual(unknown['level'], 'not_established')
        self.assertIn('independence cannot be shown', unknown['reason'])
        with patch.object(self.ledger, 'task', side_effect=pinned({'provider': 'claude', 'model': 'claude-haiku-5-5'})):
            same = self.observed(self.investigate(question='Same model?'))['observed']['independence']
        self.assertEqual(same['level'], 'not_established')
        self.assertIn('author', same['reason'])

    def test_t6_the_cli_runs_it_as_an_optional_review(self):
        config = self.root.parent / 'investigate.json'
        config.write_text(json.dumps({'provider': 'claude', 'model': 'claude-haiku-5-5', 'question': 'Is it there?', 'paths': ['a.txt']}), encoding='utf-8')
        out = io.StringIO()
        with patch.object(reviewer, 'call', side_effect=self.call), contextlib.redirect_stdout(out):
            code = engine_cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'engine', 'review-optional',
                                    'P1', 'C', 'investigate', '--investigate', str(config)], checker=lambda ledger, selector: self.fail('no candidate checker here'))
        self.assertEqual(code, 0, out.getvalue())
        self.assertEqual(json.loads(out.getvalue())['status'], 'observed')
        self.assertEqual(len(self.prompts), 1)


class NoCommandGrant(InvestigationFixture):
    commands = False

    def test_t6_probes_need_the_commands_grant(self):
        before = self.used()
        with self.assertRaisesRegex(LedgerError, 'grant for commands'):
            self.investigate(probes=[[sys.executable, '-c', 'print(1)']], call=lambda *a: self.fail('no call'))
        self.assertEqual(self.used(), before)
        self.assertEqual(self.investigate()['status'], 'observed')      # reading inside the scope needs no command grant
