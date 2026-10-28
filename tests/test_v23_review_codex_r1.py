"""Independent adversarial review r1 of 581fbca (fix of Codex P2-01 / P2-02 on 38981bd) — probe tests.

Every test asserts the EXPECTED behaviour of the requirement (a failing test = a confirmed defect); the first assertion of a test is
usually a control showing that the setup works. Report: D:\\OneCrewRuns\\v23\\review-codex-r1.md. Temporary repositories and ledgers
only (the fixtures of test_v23_a1/a2); the worker is the A2 fixture worker (no model call).
"""
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from onecrew.v2 import context, knowledge, where, wiki
from tests.test_v23_a1_knowledge import fence
from tests import test_v23_a2_knowledge as a2
from tests.test_v23_a2_knowledge import A2Fixture
from tests.test_wf_engine import node


class Probe(A2Fixture):
    ledger_event = a2.RecordingTests.ledger_event
    run_cli = a2.CliTests.run_cli

    # ---- helpers --------------------------------------------------------------------------------------------------------------
    def must_meta(self, ident='required-rule', applies=('a.txt',)):
        return {'id': ident, 'kind': 'constraint', 'label': 'verified', 'must': True, 'applies_to': list(applies),
                'sources': [{'type': 'file', 'path': 'a.txt', 'revision': self.head}]}

    def must_text(self, ident='required-rule'):
        return '# Rules\n\n## a.txt value\n' + fence(self.must_meta(ident)) + 'a.txt must hold VALUE: right.\n'

    def write(self, path, data):
        path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode('utf-8'))

    def commit(self, message='wiki'):
        self.git('add', '-A'); self.git('commit', '-q', '-m', message)

    def package(self, item=None):
        return knowledge.package(self.ledger, knowledge.consumer(self.ledger, 'P1', node=item or self.item()), cap_chars=8000)

    def outcome(self, item=None):
        """('held', message) when the package stops the node before the model, else ('delivered', [mandatory ids])."""
        try:
            pkg = self.package(item)
        except knowledge.KnowledgeOverflow as error:
            return 'held', str(error)[:300]
        return 'delivered', [e['id'] for e in pkg['entries'] if e['must']]

    def step(self):
        self.revise([self.item('C'), dict(node('I', ['C'], integration=True, write=()), executor=dict(self.item()['executor']))])
        self.values.append({'summary': 'done', 'files': [{'path': 'a.txt', 'content': 'right\n'}], 'backlog': [],
                            'knowledge': {'used': [], 'rejected': [], 'requests': [], 'new': []}})
        return self.engine.step(self.ledger, 'P1', self.adapter)

    def prompt_must(self):
        body = json.loads(self.calls[-1]['prompt'].split('\n', 1)[1])
        return [e['id'] for e in (body.get('knowledge') or {}).get('entries', []) if e.get('must')]

    def ran_with_rule_or_held(self, produced, rule='required-rule'):
        if produced['state'] == 'produced':
            record = json.loads(self.store.read_blob(produced['receipt']))['knowledge']
            self.assertIn(rule, self.prompt_must(), 'the node ran without its mandatory rule; receipt knowledge record: '
                          + json.dumps({k: record.get(k) for k in ('delivered', 'problems', 'error', 'wiki')})[:600])
        else:
            self.assertEqual(produced['state'], 'held', produced)

    def decision(self, text, plan='P1', **extra):
        return knowledge.record(self.ledger, plan, kind='decision', text=text, applies_to=['a.txt'],
                                evidence={'status': 'verified', 'property': 'checked by M1', 'sources': [{'type': 'event', 'id': self.ledger_event()}]},
                                **extra)

    def pack(self, name='P1'):
        return {e['text']: e for e in context.for_pack(self.ledger, name)}

    # ---- P2-02: a mandatory constraint lost or a node held wrongly ---------------------------------------------------------------
    def test_r1_01_a_utf16_page_with_a_mandatory_section_never_lets_the_node_run_without_it(self):
        # Windows PowerShell 5.1 (`>`, Out-File, Set-Content -Encoding Unicode) writes UTF-16LE with a BOM
        self.write(self.wiki_dir / 'rules.md', self.must_text().encode('utf-16'))
        self.commit()
        self.ran_with_rule_or_held(self.step())

    def test_r1_02_a_config_json_with_a_utf8_bom_still_names_the_wiki_folders(self):
        self.write(self.root / 'kb' / 'rules.md', self.must_text()); self.commit()
        config = self.root / '.onecrew' / 'config.json'
        self.write(config, json.dumps({'wiki': {'paths': ['kb']}}))
        self.assertEqual(self.outcome(), ('delivered', ['required-rule']))                       # control: the configured folder is read
        self.write(config, b'\xef\xbb\xbf' + json.dumps({'wiki': {'paths': ['kb']}}).encode())    # Notepad / PowerShell 5.1 "UTF8"
        self.assertEqual(where.read_config(self.root).get('wiki'), {'paths': ['kb']})            # the rest of OneCrew reads it (utf-8-sig)
        state, value = self.outcome()
        self.assertTrue(state == 'held' or value == ['required-rule'], (state, value, wiki.configured_paths(self.root)))

    def test_r1_03_a_configured_wiki_folder_that_cannot_be_read_is_not_read_as_no_wiki(self):
        missing = Path(self.temp.name) / 'shared-wiki'                    # an external wiki folder: offline drive, share, typo
        self.write(self.root / '.onecrew' / 'config.json', json.dumps({'wiki': {'paths': [str(missing)]}}))
        pkg = self.package()
        said = json.dumps(pkg.get('problems')) + json.dumps(pkg.get('wiki'))
        self.assertTrue(pkg.get('wiki') or 'shared-wiki' in said, 'nothing in the package says the configured wiki was not read: '
                        + json.dumps({k: pkg.get(k) for k in ('problems', 'wiki')}))

    def test_r1_03b_an_invalid_config_json_does_not_silently_fall_back_to_docs_wiki(self):
        self.write(self.root / 'kb' / 'rules.md', self.must_text()); self.commit()
        self.write(self.root / '.onecrew' / 'config.json', '{"wiki": {"paths": ["kb"]},}\n')       # one trailing comma
        state, value = self.outcome()
        if state == 'delivered' and value != ['required-rule']:
            pkg = self.package()
            self.assertIn('config', json.dumps(pkg.get('problems')) + json.dumps(pkg.get('wiki')),
                          'the configured wiki (with a mandatory rule) is ignored without a word: ' + json.dumps(pkg.get('problems')))

    def test_r1_04_a_superseder_after_the_page_budget_still_supersedes_a_mandatory_rule(self):
        self.write(self.wiki_dir / 'a-rules.md', '## Old a.txt rule\n' + fence(self.must_meta('old-rule')) + 'a.txt must hold VALUE: old.\n')
        newer = {'id': 'new-rule', 'kind': 'decision', 'label': 'verified', 'supersedes': ['old-rule'], 'applies_to': ['a.txt'],
                 'sources': [{'type': 'file', 'path': 'a.txt', 'revision': self.head}]}
        self.write(self.wiki_dir / 'b-change.md', '## a.txt rule changed\n' + fence(newer) + 'VALUE: old is no longer required.\n')
        self.commit()
        self.assertEqual(self.outcome(), ('delivered', []))                                    # control: old-rule is superseded
        with patch.object(wiki, 'MAX_PAGES', 1):
            self.assertEqual(self.outcome(), ('delivered', []), 'a superseded rule comes back as a CURRENT mandatory constraint '
                             'because the page that supersedes it sorts after the page budget')

    def test_r1_05_the_package_says_so_when_optional_text_of_a_page_was_not_read(self):
        self.write(self.wiki_dir / 'a-first.md', '## Meeting room\nThe meeting room is on floor two.\n')
        self.write(self.wiki_dir / 'b-rules.md', self.must_text() + '\n## a.txt history\nThe a.txt VALUE was renamed; keep the old alias readable.\n')
        self.commit()
        self.assertIn('b-rules-a-txt-history', [e['id'] for e in self.package()['entries']])     # control: relevant, delivered
        with patch.object(wiki, 'MAX_PAGES', 1):
            pkg = self.package()
        ids = [e['id'] for e in pkg['entries']]
        self.assertIn('required-rule', ids); self.assertNotIn('b-rules-a-txt-history', ids)     # as designed: past the budget
        self.assertTrue((pkg.get('wiki') or {}).get('complete') is False or any('not read' in p['problem'] for p in pkg['problems']),
                        'the package presents itself as complete: ' + json.dumps({k: pkg.get(k) for k in ('problems', 'wiki')}))

    def test_r1_06_an_identical_copy_of_a_mandatory_page_does_not_hold_the_node(self):
        self.write(self.wiki_dir / 'rules.md', self.must_text())
        self.write(self.wiki_dir / 'archive' / 'rules.md', self.must_text())              # the same page kept twice
        self.commit()
        self.assertEqual(self.outcome(), ('delivered', ['required-rule']))

    def test_r1_06b_two_exported_copies_of_a_live_ledger_must_record_do_not_hold_the_node(self):
        written = knowledge.record(self.ledger, 'P1', kind='constraint', text='a.txt keeps one line', applies_to=['a.txt'], must=True,
                                   evidence={'status': 'verified', 'property': 'checked by M1', 'sources': [{'type': 'event', 'id': self.ledger_event()}]})
        self.assertEqual(self.outcome(), ('delivered', [written['id']]))                       # control: delivered from the ledger
        data = Path(knowledge.export(self.ledger, Path(self.temp.name) / 'export')['pages'][0]).read_bytes()
        self.write(self.wiki_dir / 'onecrew-export.md', data)                                 # `wiki export` committed (HUONG-DAN §6.2)
        self.write(self.wiki_dir / 'old' / 'onecrew-export-2026-10.md', data)                 # ... and last month's export kept
        self.commit()
        self.assertEqual(self.outcome(), ('delivered', [written['id']]))

    def test_r1_14_an_unexpected_failure_of_the_selection_does_not_run_the_node_without_its_mandatory_rule(self):
        self.write(self.wiki_dir / 'rules.md', self.must_text()); self.commit()
        with patch.object(knowledge, 'blob_of', side_effect=subprocess.TimeoutExpired(['git', 'hash-object'], 120)):   # git hangs 120 s
            produced = self.step()
        self.ran_with_rule_or_held(produced)

    def test_r1_16_a_utf8_bom_page_delivers_its_first_mandatory_section(self):
        self.write(self.wiki_dir / 'rules.md', b'\xef\xbb\xbf' + ('## a.txt value\n' + fence(self.must_meta()) + 'a.txt must hold VALUE: right.\n').encode())
        self.commit()
        self.assertEqual(self.outcome(), ('delivered', ['required-rule']))

    # ---- P2-01: the continue readers and the package ------------------------------------------------------------------------------
    def test_r1_07_the_pack_does_not_show_a_version_another_root_replaced_as_verified(self):
        first = self.decision('a.txt format: one line', key='fmt')
        self.root_b('P2')
        second = self.decision('a.txt format: two lines', plan='P2', key='fmt', base=first['version'])
        self.assertFalse(second.get('conflict'), second)
        self.assertEqual(self.entries_for('P1')[first['id']]['text'], 'a.txt format: two lines')   # control: the package has the newer one
        entry = self.pack('P1').get('a.txt format: one line')
        self.assertTrue(entry is None or entry['label'] == 'stale', entry)

    def test_r1_08_a_22_entry_whose_cited_line_and_symbol_are_unchanged_keeps_its_label(self):
        (self.root / 'c.py').write_text('def keep_me():\n    return 1\n'); self.commit('c.py')
        head = self.git('rev-parse', 'HEAD')
        context.add(self.ledger, 'P1', kind='decision', label='verified', text='Line 1 of a.txt is the header',
                    source={'type': 'file_line', 'path': 'a.txt', 'line': 1, 'revision': head})
        context.observe(self.ledger, 'P1', {'type': 'symbol_verified', 'symbol': 'keep_me', 'path': 'c.py', 'revision': head})
        (self.root / 'a.txt').write_text('one\nsecond line\n')
        (self.root / 'c.py').write_text('def keep_me():\n    return 1\n\n\ndef other():\n    return 2\n')
        self.commit('unrelated edits')
        labels22 = {e['text']: e['label'] for e in context.retrieve(self.ledger, plan='P1', scope='project')['entries']}
        self.assertEqual(labels22, {'Line 1 of a.txt is the header': 'verified', 'keep_me exists in c.py': 'verified'})   # 2.2 reader
        pack = self.pack()
        self.assertEqual({t: (pack[t]['label'], pack[t]['stale_reason']) for t in labels22},
                         {t: ('verified', None) for t in labels22})

    def test_r1_09_context_retrieve_judges_at_the_revision_it_was_asked_for(self):
        old = self.git('rev-parse', 'HEAD')
        context.add(self.ledger, 'P1', kind='decision', label='verified', text='a.txt line 1 is one',
                    source={'type': 'file_line', 'path': 'a.txt', 'line': 1, 'revision': old})
        (self.root / 'a.txt').write_text('changed\n'); self.commit('change line 1')
        code, out = self.run_cli('context', 'retrieve', '--plan', 'P1', '--revision', old)
        self.assertEqual(code, 0, out)
        result = json.loads(out)
        self.assertEqual(result['checked_at'], old)
        entry = {e['text']: e for e in result['entries']}['a.txt line 1 is one']
        self.assertEqual((entry['label'], entry['stale_reason']), ('verified', None), entry)

    def test_r1_10_context_retrieve_does_not_show_a_withdrawn_general_record_as_live(self):
        event = self.ledger_event()
        text = 'Versioned text formats need their version checked before parsing.'
        written = knowledge.record(self.ledger, 'P1', kind='lesson', text=text, scope='general', conditions=['when a text format carries a version'],
                                   evidence={'status': 'observed', 'sources': [{'type': 'event', 'id': event}]})
        knowledge.withdraw(self.ledger, 'P1', written['id'], reason='wrong advice', evidence={'sources': [{'type': 'event', 'id': event}]})
        self.assertEqual({r['id']: r['status'] for r in knowledge.records(self.ledger, history=True)}[written['id']], 'withdrawn')   # control
        code, out = self.run_cli('context', 'retrieve', '--plan', 'P1')
        self.assertEqual(code, 0, out)
        shown = {e['text']: e['label'] for e in json.loads(out)['entries']}
        self.assertNotIn(shown.get(text), ('observed', 'verified', 'hypothesis'), shown)

    def test_r1_11_when_the_judgement_fails_the_pack_still_hides_withdrawn_knowledge(self):
        event = self.ledger_event()
        gone = knowledge.record(self.ledger, 'P1', kind='finding', text='a.txt needs VALUE: gone', applies_to=['a.txt'],
                                evidence={'status': 'verified', 'property': 'checked once', 'sources': [{'type': 'event', 'id': event}]})
        knowledge.withdraw(self.ledger, 'P1', gone['id'], reason='wrong', evidence={'sources': [{'type': 'event', 'id': event}]})
        self.assertNotIn('a.txt needs VALUE: gone', self.pack())                                  # control
        with patch.object(knowledge, 'for_root', side_effect=RuntimeError('selection failed')):
            pack = self.pack()
        self.assertNotIn('a.txt needs VALUE: gone', pack, pack.get('a.txt needs VALUE: gone'))

    def test_r1_12_the_pack_is_judged_when_the_bare_plan_name_is_ambiguous(self):
        self.decision('P1 keeps a.txt as one line')
        self.assertEqual(self.pack()['P1 keeps a.txt as one line']['label'], 'verified')         # control
        self.root_b('Q1')
        with self.ledger.transaction(write=True) as conn:              # a 2.1 `plan:P1` root beside the `plan-ns:P1` root (EV-J layout)
            conn.execute("UPDATE tasks SET request_key='plan:P1' WHERE request_key='plan-ns:Q1'")
        entry = self.pack('plan-ns:P1')['P1 keeps a.txt as one line']
        self.assertEqual((entry['label'], entry['stale_reason']), ('verified', None), entry)

    def test_r1_13_context_retrieve_reads_the_wiki_once_per_command(self):
        self.write(self.wiki_dir / 'rules.md', self.must_text()); self.commit()
        for name in ('P2', 'P3'): self.root_b(name)
        for name in ('P1', 'P2', 'P3'): self.decision(f'{name} decision on a.txt', plan=name)
        with patch.object(wiki, 'pages', wraps=wiki.pages) as pages:
            code, out = self.run_cli('context', 'retrieve')
        self.assertEqual(code, 0, out)
        self.assertLessEqual(pages.call_count, 1, f'{pages.call_count} full readings of the wiki for one `context retrieve` (HUONG-DAN §7: once per command)')

    def test_r1_18_a_mandatory_rule_derived_from_a_page_after_the_budget_is_not_dropped_silently(self):
        rule = dict(self.must_meta('a-rule'), derived_from=['z-fact'])
        self.write(self.wiki_dir / 'a-rule.md', '## a.txt value\n' + fence(rule) + 'a.txt must hold VALUE: right (from z-fact).\n')
        fact = {'id': 'z-fact', 'kind': 'finding', 'label': 'verified', 'applies_to': ['a.txt'], 'sources': [{'type': 'file', 'path': 'a.txt', 'revision': self.head}]}
        self.write(self.wiki_dir / 'z-fact.md', '## a.txt VALUE finding\n' + fence(fact) + 'Measured: VALUE right.\n')
        self.commit()
        self.assertEqual(self.outcome(), ('delivered', ['a-rule']))                             # control: the whole wiki is read
        with patch.object(wiki, 'MAX_PAGES', 1):                                                # only the name order changes what is read
            state, value = self.outcome()
        self.assertTrue(state == 'held' or value == ['a-rule'], (state, value))

    def test_r1_18b_a_mandatory_rule_is_not_dropped_silently_because_its_optional_source_section_is_malformed(self):
        rule = dict(self.must_meta('a-rule'), derived_from=['base-fact'])
        fact = {'id': 'base-fact', 'kind': 'finding', 'label': 'verified', 'applies_to': ['a.txt'], 'colour': 'red',
                'sources': [{'type': 'file', 'path': 'a.txt', 'revision': self.head}]}
        self.write(self.wiki_dir / 'rules.md', '## a.txt VALUE finding\n' + fence(fact) + 'Measured: VALUE right.\n\n'
                   '## a.txt value\n' + fence(rule) + 'a.txt must hold VALUE: right.\n')
        self.commit()
        state, value = self.outcome()
        self.assertTrue(state == 'held' or value == ['a-rule'], (state, value))

    def test_r1_19_optional_pages_that_cannot_be_read_do_not_push_a_fitting_mandatory_rule_over_the_cap(self):
        from onecrew.ledger import canonical
        self.write(self.wiki_dir / 'rules.md', '# Rules\n\n## a.txt value\n' + fence(self.must_meta()) + 'a.txt must hold VALUE: right. ' + 'Detail. ' * 300 + '\n')
        self.commit()
        cons = knowledge.consumer(self.ledger, 'P1', node=self.item())
        cap = len(canonical(knowledge.package(self.ledger, cons, cap_chars=16000))) + 400       # the rule fits with 400 characters to spare
        self.assertEqual([e['id'] for e in knowledge.package(self.ledger, cons, cap_chars=cap)['entries'] if e['must']], ['required-rule'])
        for i in range(10):                                                                    # optional pages that cannot be read
            self.write(self.wiki_dir / f'optional-meeting-notes-from-the-weekly-team-call-number-{i:02d}.md', b'## Notes\nlatin-1 \xe9t\xe9\n')
        self.commit('broken optional pages')
        try:
            pkg = knowledge.package(self.ledger, cons, cap_chars=cap)
        except knowledge.KnowledgeOverflow as error:
            self.fail('optional pages that cannot be read hold the node: ' + str(error)[:300])
        self.assertEqual([e['id'] for e in pkg['entries'] if e['must']], ['required-rule'])

    def test_r1_20_a_mandatory_section_made_invalid_by_an_absolute_source_path_holds_the_node(self):
        meta = dict(self.must_meta(), sources=[{'type': 'file', 'path': str(self.root / 'a.txt')}])      # a Windows absolute path
        self.write(self.wiki_dir / 'rules.md', '# Rules\n\n## a.txt value\n' + fence(meta) + 'a.txt must hold VALUE: right.\n')
        self.commit()
        self.assertTrue(any('inside the repository' in p['problem'] for p in knowledge.pages_report(self.ledger)['problems']))   # invalid (wiki pages)
        self.assertEqual(self.outcome()[0], 'held', 'a mandatory rule for a.txt is dropped without holding the node')

    # ---- controls that hold on 581fbca (kept as evidence for the "checked and correct" list) -----------------------------------
    def test_r1_c1_a_held_node_does_not_stop_an_independent_node_of_the_same_root(self):
        self.write(self.wiki_dir / 'rules.md', '# Rules\n\n## a.txt value\n```onecrew\n{"id": "required-rule", "must": true, "applies_to": ["a.txt"], '
                   '"sources": [{"type": "file", "path": "a.txt"}], "colour": "red"}\n```\nVALUE: right\n')
        self.commit()
        self.revise([self.item('C'), self.item('D', read=('b.txt',), write=('b.txt',)),
                     dict(node('I', ['C', 'D'], integration=True, write=()), executor=dict(self.item()['executor']))])
        self.values.append({'summary': 'done', 'files': [{'path': 'b.txt', 'content': 'three\n'}], 'backlog': [],
                            'knowledge': {'used': [], 'rejected': [], 'requests': [], 'new': []}})
        first = self.engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual((first['node'], first['state']), ('C', 'held'), first)
        second = self.engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual((second['node'], second['state']), ('D', 'produced'), second)
        self.assertEqual(len(self.calls), 1)

    def test_r1_c2_a_22_event_entry_keeps_label_and_shape_and_continue_survives_a_failing_judgement(self):
        context.add(self.ledger, 'P1', kind='decision', label='verified', text='Keep a.txt short', source={'type': 'event', 'id': self.ledger_event()})
        raw = {e['text']: e for e in context.retrieve(self.ledger, plan='P1', scope='project')['entries']}['Keep a.txt short']
        packed = self.pack()['Keep a.txt short']
        self.assertEqual((set(packed), packed['label'], packed['stale_reason']), (set(raw), 'verified', None))
        with patch.object(knowledge, 'for_root', side_effect=RuntimeError('boom')):
            code, out = self.run_cli('continue', 'P1', '--json')
        self.assertEqual(code, 0, out)
        # review r2 R2-09: a 2.2 entry is judged on lifecycle only, which the fallback still reads: it keeps its label
        self.assertEqual({e['text']: e['label'] for e in json.loads(out)['context']}, {'Keep a.txt short': 'verified'})

    def test_r1_17_context_retrieve_shows_another_root_only_without_plan_as_documented(self):
        self.root_b('P2')
        knowledge.record(self.ledger, 'P2', kind='note', text='P2 private working note', visibility='root',
                         evidence={'status': 'observed', 'sources': [{'type': 'event', 'id': self.ledger_event()}]})
        code, out = self.run_cli('context', 'retrieve', '--plan', 'P1')
        self.assertNotIn('P2 private working note', [e['text'] for e in json.loads(out)['entries']])   # control: with --plan
        code, out = self.run_cli('context', 'retrieve')                                                  # --plan is optional
        self.assertEqual(code, 0, out)
        # F18 resolved in the guide (HUONG-DAN 6.3): without --plan `context retrieve` is the project-wide listing for the operator, as in
        # 2.2 and like `wiki history` (every root's entries, each judged by its own root); an agent continuing a root reads `continue` or
        # `--plan`, which show that root only.
        self.assertIn('P2 private working note', [e['text'] for e in json.loads(out)['entries']])

    def test_r1_15_an_unreadable_ledger_context_is_not_read_as_no_mandatory_record(self):
        from onecrew.ledger import LedgerError
        written = knowledge.record(self.ledger, 'P1', kind='constraint', text='a.txt keeps one line', applies_to=['a.txt'], must=True,
                                   evidence={'status': 'verified', 'property': 'checked by M1', 'sources': [{'type': 'event', 'id': self.ledger_event()}]})
        self.assertEqual(self.outcome(), ('delivered', [written['id']]))                       # control
        real = context.retrieve
        def failing(ledger, **kw):
            if kw.get('limit', 200) is None: raise LedgerError('context entries could not be read')
            return real(ledger, **kw)
        with patch.object(context, 'retrieve', side_effect=failing):
            state, value = self.outcome()
        self.assertTrue(state == 'held' or value == [written['id']], (state, value))
