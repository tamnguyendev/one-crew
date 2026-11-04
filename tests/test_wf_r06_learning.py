"""R06 whole verifier→incident→mid-root lesson flow with a scripted reviewer.

The scripted provider checks a controlled temporary function; CLI/provider
quality is not claimed. Receipts, run IDs, ledger, refs and adapters are real.
"""
import hashlib
import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from onecrew import learning, skills, task_intake
from onecrew.ledger import Ledger, LedgerError, content_hash
from onecrew.v2 import context, decisions, findings, incidents, lessons, learning_cli, plan as plans, verdict
from tests.test_v2_l1 import Fixture, milestone, plan_json
import tests.wf_oldversion as ov

BASELINE = '1b4f4c6'
REPO = str(Path(__file__).resolve().parents[1])


def review_node(mid, criterion, output):
    return {'id': mid, 'title': 'Verify ' + mid, 'covers': [output], 'mode': 'until_pass', 'max_repairs': 5,
            'verifier': {'type': 'reviewer', 'config': {'provider': 'claude', 'model': 'claude-haiku-5-5', 'max_minutes': 5,
                'criteria': [{'id': criterion, 'question': 'Does service.py satisfy ' + criterion + '? Fail if the specified function is absent or wrong.'}]}}}


class LearningWorld(Fixture):
    baseline = None

    @classmethod
    def setUpClass(cls):
        if cls.baseline:
            cls.old_temp = tempfile.TemporaryDirectory()
            cls.old = ov.OldVersion(ov.archive(cls.baseline, REPO, Path(cls.old_temp.name)))

    @classmethod
    def tearDownClass(cls):
        if cls.baseline:
            cls.old_temp.cleanup()

    def setUp(self):
        super().setUp()
        (self.root / '.gitignore').write_text('.onecrew/\n')
        (self.root / 'service.py').write_text('def export_records(rows):\n    return list(rows)[1:]\n')
        self.git('add', '.'); self.git('commit', '-q', '-m', 'buggy export before work')
        value = plan_json(milestones=[review_node('M1', 'R1', 'O1'), review_node('M2', 'R2', 'O2'), milestone('M3', covers=['O3'])],
                          output=['Export rows preserved', 'New feature checked', 'Root integration checked'], scope={'owned': ['a.txt', 'service.py']})
        if self.baseline:
            path = Path(self.temp.name) / 'contract.json'; path.write_text(json.dumps(value))
            code, out = self.old.run(self.root, self.ledger.state_root, 'plan', 'propose', 'R', '--file', str(path), '--author', 'codex', '--workflow')
            self.assertEqual(code, 0, out)
        else:
            plans.propose(self.ledger, 'R', value, 'codex', workflow=True)
        plans.approve(self.ledger, 'R', 'owner', 'fixture approval')
        self.env_failure = True
        self.provider = patch('onecrew.v2.verifiers.reviewer.call', side_effect=self.call)
        self.provider.start(); self.addCleanup(self.provider.stop)

    def call(self, prompt, config, env, scratch, limit):
        namespace = {}
        exec(compile((self.root / 'service.py').read_text(), 'controlled-fixture-service.py', 'exec'), namespace)
        cid = config['criteria'][0]['id']
        passed = namespace['export_records']([1, 2]) == [1, 2] if cid == 'R1' else 'new_feature' in namespace
        answer = json.dumps({'criteria': [{'id': cid, 'verdict': 'pass' if passed else 'fail',
                            'evidence': [{'file': 'service.py', 'line': 2, 'note': 'controlled export check'}]}], 'outside_criteria': []})
        error = 'sdk unavailable: required environment variable is missing' if self.env_failure else None
        self.env_failure = False
        return answer, {}, error, False, b''

    def root_events(self, kind=None):
        with self.ledger.transaction() as conn:
            task = plans.anchor_events(self.ledger, conn, 'R')['task_id']
            return [(r['seq'], r['kind'], json.loads(r['payload'])) for r in conn.execute('SELECT seq,kind,payload FROM events WHERE task_id=? ORDER BY seq', (task,))
                    if kind is None or r['kind'] == kind]

    def prepare_repair(self):
        with patch.object(learning, 'record', wraps=learning.record) as forbidden:
            (self.root / 'a.txt').write_text('attempt one\n'); self.git('add', '.'); self.git('commit', '-q', '-m', 'environment attempt')
            verdict.run(self.ledger, 'R', 'M1')
            first = self.root_events('verdict.recorded')[-1]
            (self.root / 'a.txt').write_text('attempt two\n'); self.git('add', '.'); self.git('commit', '-q', '-m', 'product attempt')
            verdict.run(self.ledger, 'R', 'M1')
            second = self.root_events('verdict.recorded')[-1]
            refuted = context.observe(self.ledger, 'R', {'type': 'hypothesis_refuted', 'text': 'H1: timezone is not used by this code path.',
                                      'source': {'type': 'event', 'id': second[0]}})
            incidents.observe(self.ledger, 'R', 'RF1', second[2]['receipt'],
                              refuted_hypotheses=[{'id': 'H1', 'text': 'timezone caused the defect', 'event': refuted['event']}])
            (self.root / 'service.py').write_text('def export_records(rows):\n    return list(rows)\n')
            self.git('add', '.'); self.git('commit', '-q', '-m', 'verified repair')
            self.fixed = self.git('rev-parse', 'HEAD')
            verdict.run(self.ledger, 'R', 'M1')
            third = self.root_events('verdict.recorded')[-1]
            self.assertEqual(forbidden.call_count, 0)
        self.receipts = [first[2]['receipt'], second[2]['receipt'], third[2]['receipt']]
        self.incident = incidents.list_incidents(self.ledger, 'R')[0]
        self.lesson = lessons._latest(self.ledger, 'R').popitem()[1]


class AutomaticLearningTests(LearningWorld):
    def test_automatic_three_attempt_incident_and_mid_root_project_lesson(self):
        self.prepare_repair()
        self.assertEqual(len(self.root_events('learning.incident')), 1)
        self.assertEqual(len(self.root_events('learning.lesson')), 1)
        count = len(self.root_events())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = learning_cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), 'lesson', 'list', '--name', 'R'])
        self.assertEqual(code, 0, output.getvalue())
        self.assertTrue(json.loads(output.getvalue())['entries'])
        self.assertEqual(len(self.root_events()), count)
        attempts = self.incident['attempts']
        self.assertEqual([a['classification'] for a in attempts], ['environment', 'product', 'verified'])
        self.assertEqual([a['receipt'] for a in attempts], self.receipts)
        self.assertEqual(len({a['attempt'] for a in attempts}), 3)
        self.assertEqual(self.incident['refuted_hypotheses'][0]['id'], 'H1')
        self.assertIsNone(self.incident['cause'])
        self.assertEqual(self.lesson['location']['revision'], self.fixed)
        self.assertEqual(self.lesson['location']['test'], 'reviewer:R1')
        self.assertFalse(self.lesson['automatic_injection']); self.assertFalse(self.lesson['automatic_promotion'])
        self.assertEqual(findings.list_findings(self.ledger, 'R')[0]['status'], 'open', 'a green check never silently closes a finding')
        self.assertEqual(plans.show(self.ledger, 'R')['status'], 'approved')
        self.assertEqual(self.root_events('plan.accepted'), [])
        seq = self.lesson['event']
        green_seq = self.root_events('verdict.recorded')[-1][0]
        self.assertGreater(seq, green_seq)
        entries = context.retrieve(self.ledger, plan='R')['entries']
        self.assertTrue(any(e.get('lesson') == self.lesson['lesson'] for e in entries), 'the next task uses the common reader')
        incidents.after_verdict(self.ledger, 'R', 'M1', self.receipts[-1])
        self.assertEqual(len(self.root_events('learning.incident')), 1)
        self.assertEqual(len(self.root_events('learning.lesson')), 1)

    def test_general_candidate_stale_project_and_withdrawal_remain_data(self):
        self.prepare_repair()
        before = plans.show(self.ledger, 'R')['sha']
        for text in ('The file service.py is always wrong.', 'Project project needs a rule.', 'Reuse export_records to fix every report.'):
            with self.subTest(text=text), self.assertRaises(LedgerError):
                lessons.propose_general(self.ledger, 'R', self.lesson['lesson'], text=text, conditions=['Python'])
        shared = lessons.propose_general(self.ledger, 'R', self.lesson['lesson'], text='Preserve all rows when collecting an iterator.', conditions=['Python', 'sqlite'])
        self.assertEqual(shared['status'], 'proposed'); self.assertIsNone(shared['location'])
        self.assertFalse(shared['automatic_injection']); self.assertFalse(shared['automatic_promotion'])
        self.assertEqual(shared['evidence_event'], self.incident['event'])
        self.assertEqual(plans.show(self.ledger, 'R')['sha'], before)
        (self.root / 'service.py').write_text('def export_records(rows):\n    return list(rows)\n# changed elsewhere in this file\n')
        self.git('add', '.'); self.git('commit', '-q', '-m', 'new code revision')
        stale = next(e for e in context.retrieve(self.ledger, plan='R')['entries'] if e.get('lesson') == self.lesson['lesson'])
        self.assertEqual(stale['label'], 'stale'); self.assertIn('revision', stale['stale_reason'])
        lessons.withdraw(self.ledger, 'R', self.lesson['lesson'], reason='the lesson was too broad')
        self.assertFalse(any(e.get('lesson') in (self.lesson['lesson'], shared['lesson']) for e in context.retrieve(self.ledger, plan='R')['entries']))
        self.assertFalse(any(e.get('lesson') == shared['lesson'] for e in context.retrieve(self.ledger, plan='R', scope='general')['entries']))
        self.assertEqual(lessons._latest(self.ledger, 'R')[self.lesson['lesson']]['status'], 'withdrawn')

    def test_intentional_red_and_forged_evidence_do_not_become_product_learning(self):
        self.prepare_repair()
        with self.assertRaises(LedgerError): incidents.observe(self.ledger, 'R', 'RF1', '0' * 64)
        with self.assertRaises(LedgerError): incidents.finalize(self.ledger, 'R', 'RF1', cause='H1')
        with self.assertRaises(LedgerError):
            lessons.record(self.ledger, 'R', self.incident['event'], text='invent a test', path='service.py', line=2,
                           revision=self.fixed, test='a_test_that_was_never_run')
        with self.ledger.transaction() as conn:
            state = plans.anchor_events(self.ledger, conn, 'R')
        decision = decisions.record(self.ledger, state['task_id'], subject={'component': 'test-preparation', 'model': 'fixture'},
            authority={'grant_id': 'fixture-tests', 'revision': state['revisions'][1]['sha']}, evidence=[self.receipts[-1]],
            basis='Record the missing feature acceptance test before implementation.', scope='acceptance-test-preparation')
        intent = self.root_events('decision.recorded')[-1][0]
        (self.root / 'a.txt').write_text('new feature acceptance red\n'); self.git('add', '.'); self.git('commit', '-q', '-m', 'test first')
        verdict.run(self.ledger, 'R', 'M2')
        red = self.root_events('verdict.recorded')[-1][2]
        finding = next(f for f in findings.list_findings(self.ledger, 'R') if f['node'] == 'M2')
        observed = incidents.observe(self.ledger, 'R', finding['id'], red['receipt'], intentional_red=True, intent_event=intent)
        self.assertEqual(observed['classification'], 'intentional_red')
        with self.assertRaises(LedgerError): incidents.finalize(self.ledger, 'R', finding['id'])
        self.assertEqual(len(self.root_events('learning.incident')), 1)


class ClassACompatibilityTests(LearningWorld):
    baseline = BASELINE

    def test_real_prior_binary_and_v1_consumers_keep_their_semantics(self):
        self.prepare_repair()
        plain = Path(self.temp.name) / 'plain'
        import shutil
        shutil.copytree(self.ledger.state_root, plain)
        with contextlib.closing(sqlite3.connect(plain / 'ledger.sqlite3')) as conn:
            with conn:
                conn.execute("DELETE FROM events WHERE kind IN ('learning.incident','learning.lesson','context.entry')")
        old_before = ov.read(self.old, self.root, plain, 'R')
        old_after = ov.read(self.old, self.root, self.ledger.state_root, 'R')
        same = ov.compare(old_before, old_after)
        self.assertTrue(same['S'] and same['G'] and same['C'], str(same))
        self.assertFalse(old_after['read_blocked'])
        def consumers(ledger):
            with ledger.transaction() as conn:
                latest = skills.latest(ledger, conn)
            return learning.outcomes(ledger), task_intake.recommend(ledger, 'Unrelated v1 goal', 'audit', 'codex', 'fixture'), latest, [skills.good(v) for v in latest]
        self.assertEqual(consumers(Ledger(self.root, plain)), consumers(self.ledger))
        self.assertTrue(learning.lessons(self.ledger), 'the v1 lesson reader accepts the new payload')
