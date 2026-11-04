"""Codex review of 2.3.0.dev2 (38981bd, 28/10): P2-01 and P2-02, the counterexamples first, with their controls.

P2-01 — the resume pack of `onecrew continue` (context.for_pack) and the knowledge package must agree on applicability, supersession,
withdrawal and certainty: an entry whose pinned file changed is not "verified" in the pack, a superseded root note is history, not
context, while an unchanged entry, a valid note and the permission boundary stay as they were.
P2-02 — a mandatory constraint never loses its force because of a reading limit, the order of page names or a page the reader cannot
parse: the reader looks through every page for mandatory sections, delivers them, and stops the node before the model when one cannot
be delivered (or the wiki cannot be looked through within its bound); optional pages that cannot be read never stop a node.
"""
import json
from unittest.mock import patch

from onecrew.v2 import context, knowledge, namespaces, resume_pack, wiki
from tests.test_v23_a1_knowledge import fence
from tests import test_v23_a2_knowledge as a2
from tests.test_v23_a2_knowledge import A2Fixture
from tests.test_wf_engine import node


class Continue(A2Fixture):
    ledger_event = a2.RecordingTests.ledger_event

    def pack(self):
        return {e['text']: e for e in resume_pack.build(self.ledger, 'P1', context=context.for_pack)['context']}

    def root_task(self, name='P1'):
        with self.ledger.transaction() as conn:
            return namespaces.resolve(self.ledger, conn, name)['id']

    def decision(self, text, plan='P1', **extra):
        return knowledge.record(self.ledger, plan, kind='decision', text=text, applies_to=['a.txt'],
                                evidence={'status': 'verified', 'property': 'checked by M1', 'sources': [{'type': 'event', 'id': self.ledger_event()}]}, **extra)

    def test_p201_an_entry_whose_pinned_file_changed_is_not_verified_in_the_resume_pack(self):
        written = self.decision('Use the old a.txt convention')
        self.assertEqual(self.pack()['Use the old a.txt convention']['label'], 'verified')                     # control: unchanged
        self.assertEqual(self.entries_for('P1')[written['id']]['use'], 'fact')
        (self.root / 'a.txt').write_text('a different content\n')
        delivered = self.entries_for('P1')[written['id']]
        self.assertEqual((delivered['use'], delivered['applicability']['state']), ('lead', 'recheck'))
        entry = self.pack()['Use the old a.txt convention']
        self.assertEqual(entry['label'], 'stale', entry)
        self.assertIn('a.txt', entry['stale_reason'] or '')

    def test_p201_a_superseded_root_note_leaves_the_pack_and_stays_in_the_history(self):
        old = knowledge.record(self.ledger, 'P1', kind='note', text='Old private rule', visibility='root',
                               evidence={'status': 'verified', 'property': 'agreed', 'sources': [{'type': 'event', 'id': self.ledger_event()}]})
        knowledge.record(self.ledger, 'P1', kind='note', text='New private rule', visibility='root', supersedes=[old['id']],
                         evidence={'status': 'verified', 'property': 'agreed', 'sources': [{'type': 'event', 'id': self.ledger_event()}]})
        pack = self.pack()
        self.assertIn('New private rule', pack); self.assertNotIn('Old private rule', pack)
        self.assertEqual(pack['New private rule']['label'], 'verified')                                      # the valid note is kept
        rows = {r['id']: r['status'] for r in knowledge.records(self.ledger, history=True, root=self.root_task())}
        self.assertEqual(rows[old['id']], 'superseded')                                                     # nothing deleted
        project_view = {r['id']: r['status'] for r in knowledge.records(self.ledger, history=True)}           # `wiki history`
        self.assertEqual(project_view[old['id']], 'superseded')

    def test_p201_the_pack_shows_no_other_root_and_no_entry_outside_the_root(self):
        self.root_b('P2')
        knowledge.record(self.ledger, 'P2', kind='note', text='P2 private working note', visibility='root',
                         evidence={'status': 'observed', 'sources': [{'type': 'event', 'id': self.ledger_event()}]})
        knowledge.record(self.ledger, 'P2', kind='finding', text='P2 published finding about b.txt', applies_to=['b.txt'],
                         evidence={'status': 'verified', 'property': 'seen', 'sources': [{'type': 'event', 'id': self.ledger_event()}]})
        self.decision('P1 own decision')
        texts = set(self.pack())
        self.assertIn('P1 own decision', texts)
        self.assertFalse({'P2 private working note', 'P2 published finding about b.txt'} & texts)


class ContinueCli(A2Fixture):
    ledger_event = a2.RecordingTests.ledger_event
    run_cli = a2.CliTests.run_cli

    def test_p201_onecrew_continue_json_reports_the_changed_source(self):
        event = self.ledger_event()
        code, out = self.run_cli('wiki', 'record', '--plan', 'P1', '--kind', 'decision', '--text', 'Use the old a.txt convention', '--status', 'verified',
                                 '--property', 'check M1 passed', '--source', f'event:{event}', '--applies-to', 'a.txt')
        self.assertEqual(code, 0, out)
        code, out = self.run_cli('continue', 'P1', '--json')
        self.assertEqual({e['text']: e for e in json.loads(out)['context']}['Use the old a.txt convention']['label'], 'verified')   # control
        (self.root / 'a.txt').write_text('a different content\n')
        code, out = self.run_cli('continue', 'P1', '--json')
        self.assertEqual(code, 0, out)
        entry = {e['text']: e for e in json.loads(out)['context']}['Use the old a.txt convention']
        self.assertEqual(entry['label'], 'stale', entry)


class Mandatory(A2Fixture):
    def must_page(self, name='zzz.md', applies=('a.txt',), raw=None):
        meta = {'id': 'required-last', 'kind': 'constraint', 'label': 'verified', 'must': True, 'applies_to': list(applies),
                'sources': [{'type': 'file', 'path': 'a.txt', 'revision': self.head}]}
        text = raw if raw is not None else '# Rules\n\n## a.txt value\n' + fence(meta) + 'a.txt must hold VALUE: right.\n'
        (self.wiki_dir / name).write_bytes(text if isinstance(text, bytes) else text.encode('utf-8'))
        self.git('add', '.'); self.git('commit', '-q', '-m', 'wiki ' + name)

    def fillers(self, count):
        for i in range(count):
            (self.wiki_dir / f'a{i:05d}.md').write_text(f'## Note {i}\nMeeting room {i} is on floor two.\n', encoding='utf-8')

    def step(self):
        self.revise([self.item('C'), dict(node('I', ['C'], integration=True, write=()), executor=dict(self.item()['executor']))])
        self.values.append({'summary': 'done', 'files': [{'path': 'a.txt', 'content': 'right\n'}], 'backlog': [],
                            'knowledge': {'used': [], 'rejected': [], 'requests': [], 'new': []}})
        return self.engine.step(self.ledger, 'P1', self.adapter)

    def delivered_in_prompt(self):
        body = json.loads(self.calls[-1]['prompt'].split('\n', 1)[1])
        return [e['id'] for e in (body.get('knowledge') or {}).get('entries', [])]

    def test_p202_a_mandatory_section_after_the_page_budget_is_still_delivered(self):
        self.must_page()
        with patch.object(wiki, 'MAX_PAGES', 3):
            self.fillers(5)
            package = knowledge.package(self.ledger, knowledge.consumer(self.ledger, 'P1', node=self.item()), cap_chars=8000)
            produced = self.step()
        self.assertIn('required-last', [e['id'] for e in package['entries'] if e['must']], package)
        self.assertEqual(produced['state'], 'produced', produced)
        self.assertIn('required-last', self.delivered_in_prompt())

    def test_p202_the_codex_scale_two_thousand_pages_before_it(self):
        self.must_page()
        self.fillers(2000)
        package = knowledge.package(self.ledger, knowledge.consumer(self.ledger, 'P1', node=self.item()), cap_chars=8000)
        self.assertIn('required-last', [e['id'] for e in package['entries'] if e['must']], {k: package[k] for k in ('omitted', 'problems')})

    def held_before_model(self, raw):
        self.must_page(raw=raw)
        produced = self.step()
        self.assertEqual(produced['state'], 'held', produced)
        self.assertTrue(str(produced.get('reason', '')).startswith('Mandatory knowledge'), produced)
        self.assertEqual(self.calls, [])                                           # no model call

    def test_p202_a_mandatory_section_in_a_page_that_is_not_utf8_holds_the_node_before_the_model(self):
        self.held_before_model(b'# Rules\n\n## a.txt value\n```onecrew\n{"id": "required-last", "must": true, "kind": "constraint"}\n```\nVALUE: right \xff\xfe\n')

    def test_p202_a_mandatory_section_with_invalid_metadata_holds_the_node_before_the_model(self):
        self.held_before_model('# Rules\n\n## a.txt value\n```onecrew\n{"id": "required-last", "must": true, "kind": "constraint", "colour": "red"}\n```\nVALUE: right\n')

    def test_p202_a_page_too_large_to_read_that_declares_a_mandatory_section_holds_the_node(self):
        with patch.object(wiki, 'MAX_PAGE_BYTES', 400):
            self.must_page(raw='# Rules\n\n## a.txt value\n```onecrew\n{"id": "required-last", "must": true, "kind": "constraint"}\n```\n' + 'VALUE: right. ' * 60)
            produced = self.step()
        self.assertEqual(produced['state'], 'held', produced); self.assertEqual(self.calls, [])

    def test_p202_a_wiki_too_large_to_look_through_holds_the_node(self):
        self.must_page()
        with patch.object(wiki, 'MAX_PAGES', 2), patch.object(wiki, 'MAX_SCAN_BYTES', 300, create=True):
            self.fillers(20)
            produced = self.step()
        self.assertEqual(produced['state'], 'held', produced); self.assertEqual(self.calls, [])

    def test_p202_controls_optional_pages_that_cannot_be_read_never_hold_a_node(self):
        (self.wiki_dir / 'broken.md').write_bytes(b'## Notes\nnot utf-8 \xff\xfe here\n')
        (self.wiki_dir / 'bad-meta.md').write_text('## Note\n```onecrew\n{"id": "n1", "colour": "red"}\n```\nFree text.\n', encoding='utf-8')
        self.must_page(raw='# R\n\n## b value\n```onecrew\n{"id": "other", "must": true, "applies_to": ["b.txt"], "colour": "x"}\n```\nb.txt only.\n')
        produced = self.step()
        self.assertEqual(produced['state'], 'produced', produced)
        record = json.loads(self.store.read_blob(produced['receipt']))['knowledge']
        self.assertTrue(record['problems'], record)
        self.assertEqual((record['wiki']['complete'], record['wiki']['unreadable'], record['wiki']['not_read']), (False, 1, 0), record)

    def test_p202_mandatory_knowledge_over_the_room_holds_the_node_before_the_model(self):
        self.must_page(raw='# Rules\n\n## a.txt value\n' + fence({'id': 'required-last', 'kind': 'constraint', 'label': 'verified', 'must': True,
                       'applies_to': ['a.txt'], 'sources': [{'type': 'file', 'path': 'a.txt', 'revision': self.head}]}) + 'Detail. ' * 12000 + '\n')
        produced = self.step()
        self.assertEqual(produced['state'], 'held', produced)
        self.assertTrue(str(produced.get('reason', '')).startswith('Mandatory knowledge needs'), produced)
        self.assertEqual(self.calls, [])
