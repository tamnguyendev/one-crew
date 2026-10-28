"""2.3-A2 (docs/v23/HOP-DONG-2.3.vi.md §4, KB-01…KB-15 except KB-12, which runs on the installed wheel in test_v23_a2_installed):
knowledge is written when the evidence exists, at the evidence's own strength, and used again by NEW roots of the same project.

  * a worker's claim is an observation (root working memory) until a passing check of its node proves the stated property; then the
    engine publishes it for the project, citing the verification receipt, with the cause left "not established";
  * summaries keep `derived_from` and are never stronger than their weakest source; copies are not independent evidence;
  * an update based on an older version never overwrites the newer one silently: both are kept as contested;
  * withdrawal, supersession and archiving are lifecycle records written on an OPEN root; at the next retrieval they act through
    summaries and through wiki copies (by `ledger_id`/`derived_from`), and nothing is deleted;
  * nothing is written on a root that has ended (the guard of lessons._still_open), and nothing leaks across roots or projects.
Checkout tests on real git repositories and ledgers; the worker is a fixture (no model call).
"""
import copy
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from onecrew.common_executor import NativeExecutor
from onecrew.ledger import Ledger, LedgerError
from onecrew.v2 import context, knowledge, plan as plans
from tests.test_v2_l1 import plan_json
from tests.test_v23_a1_knowledge import KnowledgeFixture, PIN, fence
from tests.test_wf_engine import node


class A2Fixture(KnowledgeFixture):
    def setUp(self):
        super().setUp()
        self.calls, self.values = [], []
        self.adapter = NativeExecutor(self.ledger)
        factory = patch('onecrew.artifact_provider_core.make_worker', side_effect=self.factory)
        factory.start(); self.addCleanup(factory.stop)

    def factory(self, control, provider):
        case = self
        class Worker:
            def capability(self): return {'provider': provider, 'mode': 'fixture-no-tools'}
            def run(self, attempt, prompt, schema, profile):
                case.calls.append({'prompt': prompt, 'schema': schema})
                control.launched(attempt['id'], attempt['generation'], {'fixture': True})
                control.finish(attempt['id'], attempt['generation'], {'exit_code': 0, 'fixture': True})
            def result(self, attempt):
                value = case.values.pop(0)
                value = value(case.calls[-1]['prompt']) if callable(value) else value
                return copy.deepcopy(value), [{'source': 'fixture'}]
        return Worker()

    def root_b(self, name='P2'):
        import os
        plans.propose(self.ledger, name, plan_json(), 'codex', workflow=True, capabilities=self.engine_caps)
        actor = os.environ.pop('ONECREW_ACTOR', None)              # the fixture owner approves in its own temporary ledger
        try:
            plans.approve(self.ledger, name, 'owner', 'fixture approval of a new root')
        finally:
            if actor is not None: os.environ['ONECREW_ACTOR'] = actor
        return name

    def entries_for(self, plan, item=None):
        return {e['id']: e for e in knowledge.package(self.ledger, knowledge.consumer(self.ledger, plan, node=item or self.item()), cap_chars=8000)['entries']}

    def produce_and_verify(self, claims, content='right\n', result='pass'):
        self.revise([self.item('C', read=('a.txt', 'b.txt')), dict(node('I', ['C'], integration=True, write=()), executor=dict(PIN))])
        self.values.append({'summary': 'done', 'files': [{'path': 'a.txt', 'content': content}], 'backlog': [],
                            'knowledge': {'used': [], 'rejected': [], 'requests': [], 'new': claims}})
        produced = self.engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual(produced['state'], 'produced', produced)
        def checker(item, artifact):
            return {'artifact': artifact, 'checks': [{'id': c['id'], 'result': result, 'evidence': self.store.blob(b'fixture check ' + result.encode())}
                                                     for c in item['checks']]}
        self.verify('C', checker)
        return produced


class RecordingTests(A2Fixture):
    def test_kb01_a_claim_proven_by_a_passing_check_is_published_for_the_project_before_the_root_ends(self):
        claim = {'kind': 'finding', 'text': 'a.txt must hold VALUE: right', 'applies_to': ['a.txt'], 'sources': ['b.txt'], 'check': 'check-C'}
        self.produce_and_verify([claim])
        self.assertEqual(plans.show(self.ledger, 'P1')['status'], 'approved')                         # the root is still open
        published = [e for e in knowledge.records(self.ledger) if e['text'] == claim['text'] and e['visibility'] == 'project']
        self.assertEqual(len(published), 1, knowledge.records(self.ledger))
        entry = published[0]
        self.assertEqual(entry['label'], 'verified')
        self.assertEqual(entry['evidence']['cause'], 'not_established')
        self.assertIn('check-C', entry['evidence']['property'])
        self.assertTrue(any(s['type'] == 'receipt' for s in entry['sources']))
        self.assertIn({'type': 'file', 'path': 'b.txt'}, [{k: s[k] for k in ('type', 'path')} for s in entry['sources'] if s.get('path')])
        b = self.entries_for(self.root_b(), self.item('D', read=('a.txt', 'b.txt')))
        self.assertEqual(b[entry['id']]['use'], 'fact')                                                # a NEW root of the project uses it

    def test_kb02_a_claim_without_a_proving_check_stays_an_observation_of_its_root(self):
        claim = {'kind': 'finding', 'text': 'a.txt seems to prefer VALUE: maybe', 'applies_to': ['a.txt']}
        self.produce_and_verify([claim])
        mine = [e for e in knowledge.records(self.ledger) if e['text'] == claim['text']]
        self.assertEqual([(e['label'], e['visibility']) for e in mine], [('observed', 'root')])
        self.assertNotIn(mine[0]['id'], self.entries_for(self.root_b()))
        self.assertEqual(self.entries_for('P1')[mine[0]['id']]['use'], 'lead')

    def test_kb02b_a_failed_check_publishes_nothing(self):
        claim = {'kind': 'finding', 'text': 'a.txt must hold VALUE: wrong', 'applies_to': ['a.txt'], 'check': 'check-C'}
        self.produce_and_verify([claim], content='wrong\n', result='fail')
        self.assertFalse([e for e in knowledge.records(self.ledger) if e['text'] == claim['text'] and e['visibility'] == 'project'])

    def test_kb03_general_knowledge_keeps_no_private_detail_and_project_never_becomes_general_by_itself(self):
        event = self.ledger_event()
        with self.assertRaises(LedgerError):
            knowledge.record(self.ledger, 'P1', kind='lesson', text='Files like a.txt in this repo need X', scope='general',
                             conditions=['when a text format is versioned'], evidence={'status': 'observed', 'sources': [{'type': 'event', 'id': event}]})
        written = knowledge.record(self.ledger, 'P1', kind='lesson', text='Versioned text formats need their version checked before parsing.',
                                   scope='general', conditions=['when a text format carries a version'],
                                   evidence={'status': 'observed', 'sources': [{'type': 'event', 'id': event}]})
        self.assertTrue(written['recorded'])
        project = knowledge.record(self.ledger, 'P1', kind='finding', text='a.txt carries version 2', applies_to=['a.txt'],
                                   evidence={'status': 'observed', 'sources': [{'type': 'event', 'id': event}]})
        scopes = {e['id']: e['scope'] for e in knowledge.records(self.ledger)}
        self.assertEqual(scopes[project['id']], 'project')

    def ledger_event(self):
        with self.ledger.transaction() as conn:
            return conn.execute("SELECT MAX(e.seq) FROM events e JOIN tasks t ON t.id=e.task_id WHERE t.project_id=?", (self.ledger.project_id,)).fetchone()[0]

    def test_kb15_nothing_is_written_on_an_ended_root_and_a_correction_goes_through_an_open_root(self):
        event = self.ledger_event()
        first = knowledge.record(self.ledger, 'P1', kind='decision', text='Keep a.txt as one line', applies_to=['a.txt'],
                                 evidence={'status': 'verified', 'property': 'decided in review', 'sources': [{'type': 'event', 'id': event}]})
        with self.ledger.transaction(write=True) as conn:
            root = plans.anchor_events(self.ledger, conn, 'P1')
            plans.emit(self.ledger, conn, root['task_id'], 'plan.closed', {'revision': root['approved']['revision'], 'reason': 'fixture end'})
        with self.assertRaises(LedgerError):
            knowledge.record(self.ledger, 'P1', kind='decision', text='late note', evidence={'status': 'observed', 'sources': [{'type': 'event', 'id': event}]})
        with self.assertRaises(LedgerError):
            knowledge.withdraw(self.ledger, 'P1', first['id'], reason='late', evidence={'sources': [{'type': 'event', 'id': event}]})
        self.root_b()
        knowledge.withdraw(self.ledger, 'P2', first['id'], reason='a.txt became two lines on purpose', evidence={'sources': [{'type': 'event', 'id': event}]})
        self.assertNotIn(first['id'], self.entries_for('P2'))


class SummaryTests(A2Fixture):
    def two_sources(self):
        event = self.ledger_event()
        strong = knowledge.record(self.ledger, 'P1', kind='finding', text='a.txt parser needs VALUE: right', applies_to=['a.txt'],
                                  evidence={'status': 'verified', 'property': 'check passed', 'sources': [{'type': 'event', 'id': event}]})
        weak = knowledge.record(self.ledger, 'P1', kind='finding', text='a.txt parser maybe slow', applies_to=['a.txt'],
                                evidence={'status': 'hypothesis', 'sources': [{'type': 'event', 'id': event}]})
        return strong, weak

    ledger_event = RecordingTests.ledger_event

    def test_kb04_kb05_a_summary_is_never_stronger_than_its_sources_and_keeps_the_cause_open(self):
        strong, weak = self.two_sources()
        summary = knowledge.summarize(self.ledger, 'P1', [strong['id'], weak['id']], text='a.txt parser: needs right, maybe slow')
        twice = knowledge.summarize(self.ledger, 'P1', [summary['id']], text='a.txt parser notes')
        by_id = {e['id']: e for e in knowledge.records(self.ledger)}
        for ident in (summary['id'], twice['id']):
            self.assertEqual(by_id[ident]['label'], 'hypothesis')
            self.assertEqual(by_id[ident]['evidence']['cause'], 'not_established')
            self.assertEqual(by_id[ident]['evidence']['semantic_verification'], 'unverified')
        self.assertEqual(by_id[twice['id']]['derived_from'], [summary['id']])

    def test_kb06_copies_of_one_source_are_not_independent_evidence(self):
        event = self.ledger_event()
        knowledge.record(self.ledger, 'P1', kind='finding', text='a.txt hint copied', applies_to=['a.txt'],
                         evidence={'status': 'hypothesis', 'sources': [{'type': 'event', 'id': event}]})
        self.root_b()
        knowledge.record(self.ledger, 'P2', kind='finding', text='a.txt hint copied', applies_to=['a.txt'],       # the same claim, same source, again
                         evidence={'status': 'hypothesis', 'sources': [{'type': 'event', 'id': event}]})
        delivered = [e for e in knowledge.package(self.ledger, knowledge.consumer(self.ledger, 'P2', node=self.item()), cap_chars=8000)['entries']
                     if e['text'] == 'a.txt hint copied']
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0]['label'], 'hypothesis')
        self.assertEqual(delivered[0].get('copies'), 2)

    def test_kb07_an_update_from_an_older_version_is_kept_as_contested_not_lost(self):
        event = self.ledger_event()
        base = knowledge.record(self.ledger, 'P1', kind='decision', text='a.txt uses VALUE: one', key='a-format', applies_to=['a.txt'],
                                evidence={'status': 'verified', 'property': 'agreed', 'sources': [{'type': 'event', 'id': event}]})
        script = Path(self.temp.name) / 'writer.py'
        script.write_text('import sys, json\nsys.path.insert(0, %r)\nfrom pathlib import Path\nfrom onecrew.ledger import Ledger\nfrom onecrew.v2 import knowledge\n'
                          'ledger = Ledger(Path(sys.argv[1]), Path(sys.argv[2]))\n'
                          'out = knowledge.record(ledger, "P1", kind="decision", text=sys.argv[3], key="a-format", base=sys.argv[4], applies_to=["a.txt"],\n'
                          '    evidence={"status": "verified", "property": "agreed", "sources": [{"type": "event", "id": int(sys.argv[5])}]})\n'
                          'print(json.dumps(out))\n' % str(Path(__file__).resolve().parents[1]))
        outs = []
        for text in ('a.txt uses VALUE: two', 'a.txt uses VALUE: three'):           # two OS processes, both from the same base
            done = subprocess.run([sys.executable, str(script), str(self.root), str(self.ledger.state_root), text, base['version'], str(event)],
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr); outs.append(json.loads(done.stdout))
        self.assertFalse(outs[0].get('conflict')); self.assertTrue(outs[1].get('conflict'))
        texts = {e['text']: e for e in knowledge.records(self.ledger)}
        self.assertIn('a.txt uses VALUE: two', texts); self.assertIn('a.txt uses VALUE: three', texts)    # nothing lost
        delivered = {e['text']: e for e in knowledge.package(self.ledger, knowledge.consumer(self.ledger, 'P1', node=self.item()), cap_chars=8000)['entries']}
        self.assertEqual(delivered['a.txt uses VALUE: two']['use'], 'lead'); self.assertEqual(delivered['a.txt uses VALUE: three']['use'], 'lead')
        self.assertTrue(any('contested' in r for r in delivered['a.txt uses VALUE: three']['applicability']['reasons']))


class LifecycleTests(A2Fixture):
    ledger_event = RecordingTests.ledger_event

    def test_kb08_kb10_withdrawn_knowledge_does_not_live_on_through_a_summary(self):
        event = self.ledger_event()
        lesson = knowledge.record(self.ledger, 'P1', kind='lesson', text='a.txt needs VALUE: right', applies_to=['a.txt'],
                                  evidence={'status': 'verified', 'property': 'check passed', 'sources': [{'type': 'event', 'id': event}]})
        other = knowledge.record(self.ledger, 'P1', kind='lesson', text='a.txt needs a trailing newline', applies_to=['a.txt'],
                                 evidence={'status': 'verified', 'property': 'check passed', 'sources': [{'type': 'event', 'id': event}]})
        summary = knowledge.summarize(self.ledger, 'P1', [lesson['id']], text='a.txt: write right')
        self.root_b()
        before = self.entries_for('P2')
        self.assertIn(summary['id'], before); self.assertIn(lesson['id'], before)
        knowledge.withdraw(self.ledger, 'P2', lesson['id'], reason='requirement changed', evidence={'sources': [{'type': 'event', 'id': event}]})
        after = self.entries_for('P2')
        self.assertNotIn(lesson['id'], after); self.assertNotIn(summary['id'], after)
        self.assertIn(other['id'], after)                                                                # KB-10 control
        self.assertTrue(any(e['id'] == lesson['id'] and e['status'] == 'withdrawn' for e in knowledge.records(self.ledger, history=True)))

    def test_kb09_a_wiki_copy_of_withdrawn_knowledge_is_not_delivered(self):
        event = self.ledger_event()
        lesson = knowledge.record(self.ledger, 'P1', kind='lesson', text='a.txt needs VALUE: right', applies_to=['a.txt'],
                                  evidence={'status': 'verified', 'property': 'check passed', 'sources': [{'type': 'event', 'id': event}]})
        written = knowledge.export(self.ledger, self.wiki_dir / 'exported')
        self.git('add', '.'); self.git('commit', '-qm', 'exported wiki copy')
        copied = [e for e in knowledge.package(self.ledger, self.consumer(), cap_chars=8000)['entries'] if e['origin']['type'] == 'wiki']
        self.assertTrue(written['pages'])
        self.assertFalse(copied, 'a copy of a ledger entry that is still live is delivered once, from the ledger')
        knowledge.withdraw(self.ledger, 'P1', lesson['id'], reason='wrong', evidence={'sources': [{'type': 'event', 'id': event}]})
        delivered = json.dumps(knowledge.package(self.ledger, self.consumer(), cap_chars=8000)['entries'])
        self.assertNotIn('VALUE: right', delivered)

    def test_kb11_archiving_hides_without_deleting(self):
        event = self.ledger_event()
        old = knowledge.record(self.ledger, 'P1', kind='finding', text='a.txt old observation', applies_to=['a.txt'],
                               evidence={'status': 'observed', 'sources': [{'type': 'event', 'id': event}]})
        with self.ledger.transaction() as conn:
            events_before = conn.execute('SELECT COUNT(*) FROM events').fetchone()[0]
        knowledge.archive(self.ledger, 'P1', old['id'], reason='no longer relevant')
        self.assertNotIn(old['id'], self.entries_for('P1'))
        with self.ledger.transaction() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM events').fetchone()[0], events_before + 1)    # one record added, none removed
        history = {e['id']: e for e in knowledge.records(self.ledger, history=True)}
        self.assertEqual(history[old['id']]['status'], 'archived')


class PermissionTests(A2Fixture):
    ledger_event = RecordingTests.ledger_event

    def test_kb14_other_roots_and_projects_see_only_what_they_may(self):
        event = self.ledger_event()
        private = knowledge.record(self.ledger, 'P1', kind='finding', text='P1 working note on a.txt', visibility='root', applies_to=['a.txt'],
                                   evidence={'status': 'observed', 'sources': [{'type': 'event', 'id': event}]})
        shared = knowledge.record(self.ledger, 'P1', kind='finding', text='b.txt format rule', applies_to=['b.txt'],
                                  evidence={'status': 'verified', 'property': 'checked', 'sources': [{'type': 'event', 'id': event},
                                                                                                    {'type': 'file', 'path': 'b.txt', 'revision': self.head}]})
        self.root_b()
        narrow = self.entries_for('P2', self.item('D', read=('a.txt',)))
        self.assertNotIn(private['id'], narrow); self.assertNotIn(shared['id'], narrow)
        wide = self.entries_for('P2', self.item('D', read=('a.txt', 'b.txt')))
        self.assertNotIn(private['id'], wide); self.assertIn(shared['id'], wide)
        other = Path(self.temp.name) / 'other'; other.mkdir()
        for args in (('init', '-q'), ('config', 'user.email', 't@localhost'), ('config', 'user.name', 'T')):
            subprocess.run(['git', '-C', str(other), *args], check=True)
        (other / 'b.txt').write_text('x\n'); subprocess.run(['git', '-C', str(other), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(other), 'commit', '-qm', 'o'], check=True)
        foreign = Ledger(other, self.ledger.state_root)
        plans.propose(foreign, 'Q1', plan_json(), 'codex')
        seen = knowledge.package(foreign, knowledge.consumer(foreign, 'Q1', node=self.item('E', read=('b.txt',))), cap_chars=8000)
        self.assertNotIn('b.txt format rule', json.dumps(seen))


class CliTests(A2Fixture):
    """`onecrew wiki record|history|summarize|withdraw|archive|export` through the v2 router."""
    ledger_event = RecordingTests.ledger_event

    def run_cli(self, *args):
        import contextlib, io
        from onecrew.v2 import cli
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(['--project', str(self.root), '--state-root', str(self.ledger.state_root), *args])
        return code, out.getvalue()

    def test_record_history_summarize_withdraw_archive_export(self):
        event = self.ledger_event()
        code, out = self.run_cli('wiki', 'record', '--plan', 'P1', '--kind', 'finding', '--text', 'a.txt needs VALUE: right', '--status', 'verified',
                                 '--property', 'check M1 passed', '--source', f'event:{event}', '--source', f'path:a.txt@{self.head}', '--applies-to', 'a.txt')
        self.assertEqual(code, 0, out); first = json.loads(out)
        code, out = self.run_cli('wiki', 'summarize', '--plan', 'P1', '--text', 'a.txt: right', first['id'])
        self.assertEqual(code, 0, out); summary = json.loads(out)
        code, out = self.run_cli('wiki', 'history')
        rows = {r['id']: r for r in json.loads(out)['records']}
        self.assertEqual(rows[summary['id']]['derived_from'], [first['id']])
        code, out = self.run_cli('wiki', 'withdraw', first['id'], '--plan', 'P1', '--reason', 'wrong word', '--source', f'event:{event}')
        self.assertEqual(code, 0, out)
        rows = {r['id']: r for r in json.loads(self.run_cli('wiki', 'history')[1])['records']}
        self.assertEqual(rows[first['id']]['status'], 'withdrawn'); self.assertEqual(rows[summary['id']]['status'], 'source_withdrawn')
        code, out = self.run_cli('wiki', 'record', '--plan', 'P1', '--kind', 'note', '--text', 'temporary a.txt note', '--status', 'observed',
                                 '--source', f'event:{event}', '--applies-to', 'a.txt')
        note = json.loads(out)
        self.assertEqual(self.run_cli('wiki', 'archive', note['id'], '--plan', 'P1', '--reason', 'done')[0], 0)
        rows = {r['id']: r for r in json.loads(self.run_cli('wiki', 'history')[1])['records']}
        self.assertEqual(rows[note['id']]['status'], 'archived')
        code, out = self.run_cli('wiki', 'export', '--out', str(Path(self.temp.name) / 'export'))
        self.assertEqual(code, 0, out); self.assertTrue(json.loads(out)['derived_view'])
        code, out = self.run_cli('wiki', 'record', '--plan', 'P1', '--kind', 'finding', '--text', 'x', '--status', 'verified', '--source', f'event:{event}')
        self.assertNotEqual(code, 0)                                  # verified without the property shown is refused


class NoResurrectionTests(A2Fixture):
    """Withdrawn knowledge does not come back through the other readers: the resume pack of `onecrew continue`, and a continuation's request."""
    ledger_event = RecordingTests.ledger_event

    def test_the_resume_pack_and_a_requested_id_do_not_bring_back_withdrawn_knowledge(self):
        from onecrew.v2 import resume_pack
        event = self.ledger_event()
        gone = knowledge.record(self.ledger, 'P1', kind='finding', text='a.txt needs VALUE: gone', applies_to=['a.txt'],
                                evidence={'status': 'verified', 'property': 'checked once', 'sources': [{'type': 'event', 'id': event}]})
        kept = knowledge.record(self.ledger, 'P1', kind='finding', text='a.txt keeps one line', applies_to=['a.txt'],
                                evidence={'status': 'verified', 'property': 'checked', 'sources': [{'type': 'event', 'id': event}]})
        knowledge.withdraw(self.ledger, 'P1', gone['id'], reason='wrong', evidence={'sources': [{'type': 'event', 'id': event}]})
        pack = resume_pack.build(self.ledger, 'P1', context=context.for_pack)
        texts = [e['text'] for e in pack['context']]
        self.assertNotIn('a.txt needs VALUE: gone', texts); self.assertIn('a.txt keeps one line', texts)
        self.assertFalse([t for t in texts if t.startswith('Withdraws ')])
        page = knowledge.package(self.ledger, self.consumer(), cap_chars=8000, requested=[gone['id'], kept['id']])
        self.assertEqual(page['requests_refused'], [{'id': gone['id'], 'reason': 'not_available'}])
