"""One managed lab flow uses the actual verifier, repair register and knowledge seam."""
import json
import sys
import time

from onecrew.common_verification import CandidateChecker
from onecrew.process_core import Supervisor, native_python
from onecrew.subscription import environment
from onecrew.v2 import engine, findings, knowledge, managed_executor, repair_tasks
from tests.test_review_b2_e2e import LoopFixture
from tests.test_v2_l1 import milestone


class ManagedRepairLessonTests(LoopFixture):
    paths = ('a.txt',)
    milestones = (milestone('M1', argv=[sys.executable, '-c',
        'from pathlib import Path; print("checking a.txt"); assert Path("a.txt").read_text()=="candidate\\n"']),)

    def prepare(self): pass

    def nodes(self):
        rows = super().nodes()
        for row in rows:
            row['executor'] = {'role': 'worker', 'provider': 'codex', 'model': 'fixture-model'}
            row['execution_cap_seconds'] = 120
        return rows

    def factory(self, control, provider):
        case = self
        class Worker:
            def capability(self): return {'provider': provider, 'mode': 'local-process-fixture-no-model'}
            def run(self, attempt, prompt, schema, profile):
                case.launches.append(attempt['id'])
                value = case.values.pop(0)
                directory = case.ledger.state_root / 'worker-io' / attempt['id']; directory.mkdir(parents=True)
                script = 'import pathlib,sys,time;time.sleep(.15);pathlib.Path("answer.json").write_text(sys.argv[1])'
                return Supervisor(control).run(attempt, [native_python(), '-c', script, json.dumps(value)], cwd=directory, timeout=10, env=environment())
            def result(self, attempt):
                return json.loads((case.ledger.state_root / 'worker-io' / attempt['id'] / 'answer.json').read_text()), []
        return Worker()

    def test_managed_fail_repair_recheck_then_next_task_receives_verified_scoped_lesson(self):
        began = time.monotonic()
        self.launches, self.values = [], []
        adapter = managed_executor.ManagedExecutor(self.ledger, worker_factory=self.factory)
        adapter.control.liveness_every = .05
        checker = CandidateChecker(self.ledger, 'P1')
        text = 'The declared a.txt output must be candidate followed by a newline.'
        claim = {'kind': 'lesson', 'text': text, 'applies_to': ['a.txt'], 'sources': ['a.txt'], 'check': 'M1'}
        def value(content):
            return {'summary': 'Local managed fixture', 'files': [{'path': 'a.txt', 'content': content}], 'backlog': [],
                    'knowledge': {'used': [], 'rejected': [], 'requests': [], 'new': [claim]}}
        self.values.append(value('wrong\n'))
        self.assertEqual(engine.step(self.ledger, 'P1', adapter)['state'], 'produced')
        red = engine.verify(self.ledger, 'P1', 'C', checker)
        self.assertEqual(red['result'], 'fail')
        self.assertEqual(red['recovery']['disposition'], 'repair')
        [finding] = findings.list_findings(self.ledger, 'P1', open_only=True)
        self.assertFalse([e for e in knowledge.records(self.ledger) if e['text'] == text and e['visibility'] == 'project'])
        failed = engine.state(self.ledger, 'P1')['nodes']['C']['verification_receipt']
        repair = repair_tasks.prepare(self.ledger, 'P1', 'C', 'C', reason='Repair the failed approved command', evidence=[failed])
        self.assertEqual(repair['source_receipt'], failed)
        self.values.append(value('candidate\n'))
        self.assertEqual(engine.step(self.ledger, 'P1', adapter)['state'], 'produced')
        green = engine.verify(self.ledger, 'P1', 'C', checker)
        self.assertEqual(green['result'], 'pass')
        self.assertEqual(green['findings']['closed'], [finding['id']])
        published = [e for e in knowledge.records(self.ledger) if e['text'] == text and e['visibility'] == 'project']
        self.assertEqual(len(published), 1)
        lesson = published[0]
        self.assertEqual((lesson['label'], lesson['evidence']['cause']), ('verified', 'not_established'))
        self.assertTrue(any(s['type'] == 'receipt' for s in lesson['sources']))
        verified_receipt = engine.state(self.ledger, 'P1')['nodes']['C']['verification_receipt']
        self.values.append({'summary': 'Next managed task', 'evidence': [verified_receipt],
                            'knowledge': {'used': [lesson['id']], 'rejected': [], 'requests': [], 'new': []}})
        produced = engine.step(self.ledger, 'P1', adapter)
        self.assertEqual((produced['state'], produced['node']), ('produced', 'I'), produced)
        body = json.loads(self.store.read_blob(produced['receipt']))
        self.assertIn(lesson['id'], body['knowledge']['delivered'])
        self.assertEqual(len(self.launches), 3)
        self.assertEqual(len(findings.list_findings(self.ledger, 'P1', open_only=True)), 0)
        self.assertEqual((self.root / 'a.txt').read_text(), 'one\n')
        self.assertLess(time.monotonic() - began, 120)
