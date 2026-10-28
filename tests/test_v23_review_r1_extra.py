"""2.3 review r1 (D:\\OneCrewRuns\\v23\\review-a1a2.md): the findings the reviewer's probes did not cover — #24 the open-root guard is
re-checked inside the write transaction; #25 a knowledge write failure of any kind never undoes the attempt or the verification; #26 a
lesson withdrawn through a knowledge record is withdrawn for the lesson readers too; #32 claims of a partial attempt are promoted when the
continuation's check passes; #33 an exported copy keeps `must` and its conditions; #5 a schema-valid but unacceptable declaration is
dropped, the artifact kept. Checkout tests, fixture worker, real ledgers."""
import json
from unittest.mock import patch

from onecrew.ledger import LedgerError
from onecrew.v2 import context, knowledge, lessons, plan as plans
from tests.test_v23_a1_knowledge import PIN, fence
from tests.test_v23_a2_knowledge import A2Fixture
from tests.test_wf_engine import node


class ExtraTests(A2Fixture):
    def event(self):
        with self.ledger.transaction() as conn:
            return conn.execute("SELECT MAX(e.seq) FROM events e JOIN tasks t ON t.id=e.task_id WHERE t.project_id=?", (self.ledger.project_id,)).fetchone()[0]

    def close_p1(self):
        with self.ledger.transaction(write=True) as conn:
            root = plans.anchor_events(self.ledger, conn, 'P1')
            plans.emit(self.ledger, conn, root['task_id'], 'plan.closed', {'revision': root['approved']['revision'], 'reason': 'fixture end'})

    def test_24_a_root_that_ended_after_the_first_check_is_refused_in_the_write_transaction(self):
        ev = self.event()
        real = knowledge._open_root
        def racing(ledger, plan):
            out = real(ledger, plan)            # the root was open when checked ...
            self.close_p1()                     # ... and ends before the write
            return out
        with patch.object(knowledge, '_open_root', racing):
            with self.assertRaises(LedgerError) as caught:
                knowledge.record(self.ledger, 'P1', kind='note', text='late note', evidence={'status': 'observed', 'sources': [{'type': 'event', 'id': ev}]})
        self.assertIn('ended', str(caught.exception))

    def test_25_a_failing_knowledge_write_keeps_the_candidate_and_the_verification(self):
        self.revise([self.item('C', read=('a.txt', 'b.txt')), dict(node('I', ['C'], integration=True, write=()), executor=dict(PIN))])
        self.values.append({'summary': 'done', 'files': [{'path': 'a.txt', 'content': 'right\n'}], 'backlog': [],
                            'knowledge': {'used': [], 'rejected': [], 'requests': [], 'new': [{'kind': 'finding', 'text': 'a.txt holds VALUE: right',
                                                                                             'sources': ['a.txt'], 'check': 'check-C'}]}})
        import sqlite3
        with patch.object(knowledge, 'record_claims', side_effect=sqlite3.OperationalError('database is locked')):
            produced = self.engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual(produced['state'], 'produced', produced)
        def checker(item, artifact):
            return {'artifact': artifact, 'checks': [{'id': c['id'], 'result': 'pass', 'evidence': self.store.blob(b'ok')} for c in item['checks']]}
        with patch.object(knowledge, 'after_verification', side_effect=sqlite3.OperationalError('database is locked')):
            verdict = self.verify('C', checker)
        self.assertEqual(verdict['result'], 'pass')

    def test_26_a_lesson_withdrawn_by_a_knowledge_record_is_gone_for_the_lesson_readers(self):
        ev = self.event()
        with self.ledger.transaction(write=True) as conn:            # a lesson as lessons.record writes it: learning.lesson, then its index entry
            root = plans.anchor_events(self.ledger, conn, 'P1')
            plans.emit(self.ledger, conn, root['task_id'], 'learning.lesson',
                       {'version': 1, 'lesson': 'abc123', 'scope': 'project', 'status': 'verified', 'text': 'a.txt lesson text',
                        'location': {'path': 'a.txt', 'line': 1, 'revision': self.head}, 'file_blob': self.git('rev-parse', 'HEAD:a.txt'),
                        'id': 'L1', 'task': root['task_id'], 'plan': 'P1'})
            lesson_event = conn.execute('SELECT MAX(seq) FROM events').fetchone()[0]
        context.add(self.ledger, 'P1', kind='note', label='verified', text='a.txt lesson text', key='lesson-abc123',
                    source={'type': 'event', 'id': lesson_event})
        listed = lambda: [e for e in lessons.retrieve(self.ledger, name='P1')['entries'] if e.get('lesson') == 'abc123']
        self.assertEqual(len(listed()), 1)
        knowledge.withdraw(self.ledger, 'P1', 'lesson-abc123', reason='wrong', evidence={'sources': [{'type': 'event', 'id': ev}]})
        self.assertEqual(listed(), [])                                  # lesson list, context retrieve, issue localize read through refine_context
        with self.assertRaises(LedgerError):
            lessons.propose_general(self.ledger, 'P1', 'abc123', text='General text about versioned formats.', conditions=['when formats are versioned'])

    def test_33_an_exported_copy_keeps_must_and_conditions(self):
        ev = self.event()
        knowledge.record(self.ledger, 'P1', kind='constraint', text='a.txt keeps one line', must=True, applies_to=['a.txt'],
                         conditions=[{'type': 'file_contains', 'path': 'requirements.txt', 'text': 'lib==1.0'}],
                         evidence={'status': 'verified', 'property': 'agreed', 'sources': [{'type': 'event', 'id': ev}]})
        out = knowledge.export(self.ledger, self.wiki_dir / 'export')
        text = open(out['pages'][0], encoding='utf-8').read()
        meta = json.loads(text.split('```onecrew\n', 1)[1].split('\n```', 1)[0])
        self.assertTrue(meta['must']); self.assertEqual(meta['conditions'][0]['type'], 'file_contains')

    def test_05_a_declaration_over_the_schema_limits_is_dropped_and_the_artifact_kept(self):
        self.revise([self.item('C', read=('a.txt', 'b.txt')), dict(node('I', ['C'], integration=True, write=()), executor=dict(PIN))])
        self.values.append({'summary': 'done', 'files': [{'path': 'a.txt', 'content': 'right\n'}], 'backlog': [],
                            'knowledge': {'used': ['x' * 500]}})
        produced = self.engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual(produced['state'], 'produced', produced)
        receipt = json.loads(self.store.read_blob(produced['receipt']))
        self.assertIn('dropped', receipt['knowledge_declaration_problem'])
        self.assertEqual(self.store.context(produced['artifact'])['a.txt'], 'right\n')

    def test_32_claims_of_a_partial_attempt_are_promoted_when_the_continuation_passes(self):
        self.revise([self.item('C', read=('a.txt', 'b.txt')), dict(node('I', ['C'], integration=True, write=()), executor=dict(PIN))])
        claim = {'kind': 'finding', 'text': 'a.txt needs the header line first', 'applies_to': ['a.txt'], 'sources': ['a.txt'], 'check': 'check-C'}
        self.values.append({'summary': 'part', 'files': [{'path': 'a.txt', 'content': 'header\n'}], 'backlog': [],
                            'continuation': {'remaining': 'body'}, 'knowledge': {'new': [claim]}})
        self.values.append({'summary': 'done', 'files': [{'path': 'a.txt', 'content': 'header\nbody\n'}], 'backlog': []})
        self.assertEqual(self.engine.step(self.ledger, 'P1', self.adapter)['state'], 'continuing')
        self.assertEqual(self.engine.step(self.ledger, 'P1', self.adapter)['state'], 'produced')
        def checker(item, artifact):
            return {'artifact': artifact, 'checks': [{'id': c['id'], 'result': 'pass', 'evidence': self.store.blob(b'ok')} for c in item['checks']]}
        self.verify('C', checker)
        published = [r for r in knowledge.records(self.ledger) if r['text'] == claim['text'] and r['visibility'] == 'project']
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0]['label'], 'verified')
